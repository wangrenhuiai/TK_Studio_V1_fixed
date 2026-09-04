import sys
import os
import sqlite3
import threading
import subprocess
import json
from datetime import datetime
from urllib.parse import urlparse, unquote
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QStackedWidget, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QProgressBar, QFileDialog, QTextEdit, QFrame
)

APP_STYLE = """
QMainWindow { background: #f4f7fb; }
QLabel { color: #202938; }
#sidebar { background: #1677ff; }
#brand { color: white; font-size: 22px; font-weight: 700; padding: 18px 10px; }
QListWidget { background: #1677ff; color: white; border: none; font-size: 16px; }
QListWidget::item { padding: 14px 12px; border-radius: 6px; margin: 2px 6px; }
QListWidget::item:selected { background: #ff5be7; }
#title { font-size: 22px; font-weight: 700; }
QPushButton { background: #1677ff; color: white; border: none; border-radius: 5px; padding: 9px 16px; font-weight: 600; }
QPushButton:hover { background: #0d63d8; }
QPushButton#green { background: #10b981; }
QPushButton#pink { background: #ec25d6; }
QLineEdit, QTextEdit { background: white; border: 1px solid #cfd7e3; border-radius: 5px; padding: 8px; }
QTableWidget { background: white; border: 1px solid #d7dee8; gridline-color: #e5eaf0; }
QHeaderView::section { background: #e9f1ff; padding: 8px; border: none; font-weight: 600; }
QProgressBar { background: #e8edf3; border: none; border-radius: 5px; text-align: center; }
QProgressBar::chunk { background: #1677ff; border-radius: 5px; }
#card { background: white; border: 1px solid #e0e6ef; border-radius: 8px; padding: 12px; }
"""

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tk_studio.db")


class Database:
    def __init__(self, path=DB_FILE):
        self.path = path
        self.init_db()

    def connect(self):
        return sqlite3.connect(self.path)

    def init_db(self):
        with self.connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS works (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT UNIQUE,
                    author TEXT,
                    title TEXT,
                    url TEXT,
                    video_url TEXT,
                    cover_url TEXT,
                    duration TEXT,
                    resolution TEXT,
                    download_status TEXT DEFAULT '未下载',
                    local_path TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            con.commit()

    def add_work(self, data):
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as con:
            con.execute("""
                INSERT INTO works
                (video_id, author, title, url, video_url, cover_url,
                 duration, resolution, download_status, local_path,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, '未下载', '', ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    author=excluded.author,
                    title=excluded.title,
                    url=excluded.url,
                    video_url=excluded.video_url,
                    cover_url=excluded.cover_url,
                    duration=excluded.duration,
                    resolution=excluded.resolution,
                    updated_at=excluded.updated_at
            """, (
                data.get("video_id", ""),
                data.get("author", ""),
                data.get("title", ""),
                data.get("url", ""),
                data.get("video_url", ""),
                data.get("cover_url", ""),
                data.get("duration", ""),
                data.get("resolution", ""),
                now, now
            ))
            con.commit()
            row = con.execute(
                "SELECT id FROM works WHERE video_id=?",
                (data.get("video_id", ""),)
            ).fetchone()
            return row[0] if row else None

    def list_works(self, keyword=""):
        with self.connect() as con:
            if keyword:
                rows = con.execute("""
                    SELECT id, author, title, url, duration, resolution,
                           download_status, video_id
                    FROM works
                    WHERE author LIKE ? OR title LIKE ? OR video_id LIKE ?
                    ORDER BY id DESC
                """, (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%")).fetchall()
            else:
                rows = con.execute("""
                    SELECT id, author, title, url, duration, resolution,
                           download_status, video_id
                    FROM works ORDER BY id DESC
                """).fetchall()
        return rows

    def get_work(self, work_id):
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM works WHERE id=?", (work_id,)
            ).fetchone()

    def update_download(self, work_id, status, local_path=""):
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as con:
            con.execute("""
                UPDATE works
                SET download_status=?, local_path=?, updated_at=?
                WHERE id=?
            """, (status, local_path, now, work_id))
            con.commit()


class DownloadWorker(QThread):
    """TikTok video downloader.

    Uses the parsed video URL first, with Chrome-like headers, retries and
    Range resume. If the signed URL has expired, it refreshes the TikTok page
    in the bundled headless Chrome profile and retries with the fresh URL.
    """
    progress = Signal(int, str, str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, work_id, video_url, output_dir, db):
        super().__init__()
        self.work_id = work_id
        self.video_url = video_url
        self.output_dir = output_dir
        self.db = db

    @staticmethod
    def _safe_name(title, video_id):
        safe = "".join(c for c in (title or video_id or "tiktok_video")
                       if c not in '<>:"/\\|?*').strip()
        return (safe or video_id or "tiktok_video")[:100]

    def _get_work(self):
        with self.db.connect() as con:
            return con.execute(
                "SELECT video_id, author, title, url, video_url FROM works WHERE id=?",
                (self.work_id,)
            ).fetchone()

    def _headers(self, page_url, range_header=None):
        h = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            ),
            "Referer": page_url or "https://www.tiktok.com/",
            "Origin": "https://www.tiktok.com",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "identity",
            "Connection": "keep-alive",
        }
        if range_header:
            h["Range"] = range_header
        return h

    def _fresh_video_url(self, page_url):
        if not page_url:
            return ""
        self.progress.emit(0, "刷新视频地址", "正在用 Chrome 重新获取页面")
        rendered = load_with_chrome(page_url)
        if not rendered:
            return ""
        data = extract_tiktok_data(rendered)
        return data.get("video_url", "")

    def _download_once(self, url, page_url, path, session):
        # Start a fresh file for the first request. If a partial .part exists,
        # resume it with Range; this is useful when the connection drops.
        part = path + ".part"
        existing = os.path.getsize(part) if os.path.exists(part) else 0
        range_header = f"bytes={existing}-" if existing else None
        headers = self._headers(page_url, range_header)

        r = session.get(url, headers=headers, stream=True,
                        timeout=(20, 90), allow_redirects=True)
        status = r.status_code
        content_type = (r.headers.get("content-type") or "").lower()

        if status in (401, 403, 404, 410):
            r.close()
            raise RuntimeError(f"HTTP {status}：视频地址可能已过期或当前请求被拒绝")
        if status >= 400:
            r.close()
            raise RuntimeError(f"HTTP {status}")
        if "text/html" in content_type:
            r.close()
            raise RuntimeError("服务器返回网页而不是视频文件，视频地址可能已过期")

        # If server ignored Range, restart the partial file rather than
        # appending the whole response to it.
        append = existing > 0 and status == 206
        if not append:
            existing = 0

        total = 0
        if status == 206:
            cr = r.headers.get("content-range", "")
            try:
                total = int(cr.rsplit("/", 1)[1])
            except Exception:
                total = 0
        if not total:
            try:
                total = int(r.headers.get("content-length", "0") or 0) + existing
            except Exception:
                total = 0

        done = existing
        mode = "ab" if append else "wb"
        with open(part, mode) as f:
            for chunk in r.iter_content(chunk_size=1024 * 512):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                percent = min(99, int(done * 100 / total)) if total else 0
                self.progress.emit(percent, "下载中", f"{done / 1024 / 1024:.1f} MB")
        r.close()

        if not os.path.exists(part) or os.path.getsize(part) < 1024:
            raise RuntimeError("下载文件为空或文件异常")
        os.replace(part, path)

    def run(self):
        try:
            import requests
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry

            if not self.video_url:
                raise RuntimeError("没有视频地址，请重新解析作品。")

            os.makedirs(self.output_dir, exist_ok=True)
            row = self._get_work()
            if not row:
                raise RuntimeError("找不到作品记录。")

            video_id, author, title, page_url, stored_video_url = row
            filename = self._safe_name(title, video_id) + ".mp4"
            path = os.path.join(self.output_dir, filename)
            part = path + ".part"

            session = requests.Session()
            retry = Retry(
                total=2, connect=2, read=2, status=2,
                backoff_factor=1,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset(["GET"]),
                raise_on_status=False,
            )
            session.mount("http://", HTTPAdapter(max_retries=retry))
            session.mount("https://", HTTPAdapter(max_retries=retry))

            self.db.update_download(self.work_id, "下载中")
            self.progress.emit(0, "准备下载", "")

            last_error = None
            urls = [self.video_url]
            refreshed = False

            for attempt in range(1, 4):
                url = urls[-1]
                self.progress.emit(0, "连接中", f"第 {attempt}/3 次")
                try:
                    self._download_once(url, page_url, path, session)
                    self.db.update_download(self.work_id, "已下载", path)
                    self.progress.emit(100, "已下载", path)
                    self.finished_ok.emit(path)
                    return
                except Exception as e:
                    last_error = e
                    # A signed TikTok media URL can expire. Refresh the page
                    # once and retry with the newly extracted URL.
                    if (not refreshed and page_url and
                            any(x in str(e) for x in ("403", "404", "410", "过期"))):
                        refreshed = True
                        fresh = self._fresh_video_url(page_url)
                        if fresh and fresh != url:
                            urls.append(fresh)
                            self.video_url = fresh
                            self.db.add_work({
                                "video_id": video_id,
                                "author": author,
                                "title": title,
                                "url": page_url,
                                "video_url": fresh,
                                "cover_url": "",
                                "duration": "",
                                "resolution": "",
                            })
                            self.progress.emit(0, "已刷新地址", "重新尝试下载")
                            continue
                    self.progress.emit(0, "重试", str(e))

            raise RuntimeError(f"下载失败：{last_error}")

        except Exception as e:
            try:
                self.db.update_download(self.work_id, "下载失败")
            except Exception:
                pass
            self.failed.emit(str(e))


def get_latest_work_id(db):
    rows = db.list_works()
    return rows[0][0] if rows else None

def _clean_tiktok_value(value):
    if not value:
        return ""
    value = unquote(value)
    value = value.replace("\\u002F", "/").replace("\\/", "/")
    value = value.replace("&amp;", "&")
    try:
        value = bytes(value, "utf-8").decode("unicode_escape")
    except Exception:
        pass
    return value.strip()


def extract_tiktok_data(html):
    """从普通 HTML、meta 标签和 TikTok 页面内嵌 JSON 尽可能提取信息。"""
    import re
    from html import unescape

    result = {
        "author": "",
        "title": "",
        "image": "",
        "video_url": "",
        "duration": "",
        "resolution": ""
    }

    # meta 标签属性顺序并不固定，所以不再要求 property 必须出现在 content 前面。
    meta_pattern = re.compile(r"<meta\b[^>]*>", re.I | re.S)
    attr_pattern = re.compile(
        r'([:\w-]+)\s*=\s*["\'](.*?)["\']',
        re.I | re.S
    )

    for tag in meta_pattern.findall(html):
        attrs = {}
        for k, v in attr_pattern.findall(tag):
            attrs[k.lower()] = unescape(v)

        prop = attrs.get("property", "").lower()
        name = attrs.get("name", "").lower()
        content = attrs.get("content", "").strip()

        if prop in ("og:title", "twitter:title") or name == "twitter:title":
            if not result["title"]:
                result["title"] = content

        elif prop in ("og:image", "og:image:url", "twitter:image") or name == "twitter:image":
            if not result["image"]:
                result["image"] = content

        elif prop.startswith("og:video") or name in ("twitter:player:stream", "twitter:player"):
            if not result["video_url"]:
                result["video_url"] = content

    # TikTok 内嵌 JSON 常见字段。
    keys = {
        "author": ["uniqueId", "unique_id", "authorName"],
        "title": ["desc", "description"],
        "image": ["cover", "originCover", "dynamicCover"],
        "video_url": ["playAddr", "playApi", "downloadAddr"],
    }

    def find_json_string(key):
        patterns = [
            rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"',
            rf"'{re.escape(key)}'\s*:\s*'((?:\\.|[^'\\])*)'",
        ]
        for pat in patterns:
            m = re.search(pat, html, re.I | re.S)
            if m:
                return _clean_tiktok_value(m.group(1))
        return ""

    for key in keys["author"]:
        if not result["author"]:
            result["author"] = find_json_string(key)

    for key in keys["title"]:
        if not result["title"]:
            result["title"] = find_json_string(key)

    for key in keys["image"]:
        if not result["image"]:
            result["image"] = find_json_string(key)

    for key in keys["video_url"]:
        if not result["video_url"]:
            result["video_url"] = find_json_string(key)

    # 从 JSON 中补充 duration / width / height。
    for key in ("duration",):
        if not result["duration"]:
            m = re.search(rf'"{key}"\s*:\s*(\d+(?:\.\d+)?)', html, re.I)
            if m:
                result["duration"] = m.group(1)

    if not result["resolution"]:
        wm = re.search(r'"width"\s*:\s*(\d+)', html, re.I)
        hm = re.search(r'"height"\s*:\s*(\d+)', html, re.I)
        if wm and hm:
            result["resolution"] = f"{wm.group(1)}x{hm.group(1)}"

    return {k: _clean_tiktok_value(v) for k, v in result.items()}


def load_with_chrome(url, log_callback=None):
    """用本机 Chrome 的 headless --dump-dom 获取 JS 渲染后的 DOM。
    不要求安装 Selenium/Playwright。
    """
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    chrome = next((x for x in candidates if os.path.exists(x)), None)
    if not chrome:
        return ""

    if log_callback:
        log_callback("requests 没拿到作品数据，尝试使用本机 Chrome 渲染页面……")

    profile_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "chrome_headless_profile"
    )
    os.makedirs(profile_dir, exist_ok=True)

    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile_dir}",
        "--dump-dom",
        url
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=45
        )
        if result.returncode != 0 and log_callback:
            log_callback(f"Chrome 返回码：{result.returncode}")
        return result.stdout or ""
    except subprocess.TimeoutExpired:
        if log_callback:
            log_callback("⚠️ Chrome 渲染超时。")
        return ""
    except Exception as e:
        if log_callback:
            log_callback(f"⚠️ Chrome 渲染失败：{e}")
        return ""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = Database()
        self.download_threads = []
        self.setWindowTitle("TK Studio V1.4 - TikTok作品管理工具")
        self.resize(1180, 760)
        self.setMinimumSize(980, 650)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(180)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(8, 8, 8, 8)

        brand = QLabel("TK Studio")
        brand.setObjectName("brand")
        brand.setAlignment(Qt.AlignCenter)
        side.addWidget(brand)

        self.nav = QListWidget()
        pages = ["作品列表", "主页提取", "单作品提取", "关键词提取",
                 "我的主页", "下载设置", "浏览器 / 登录TK", "软件设置", "使用教程"]
        self.nav.addItems(pages)
        side.addWidget(self.nav)
        layout.addWidget(sidebar)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.build_work_list()
        self.build_home()
        self.build_single()
        self.build_keyword()
        self.build_myhome()
        self.build_download()
        self.build_browser()
        self.build_settings()
        self.build_help()

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

    def page(self, title):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(20, 18, 20, 18)
        h = QHBoxLayout()
        lab = QLabel(title)
        lab.setObjectName("title")
        h.addWidget(lab)
        h.addStretch()
        v.addLayout(h)
        self.stack.addWidget(w)
        return w, v

    def build_work_list(self):
        w, v = self.page("作品列表")
        bar = QHBoxLayout()
        self.work_search = QLineEdit()
        self.work_search.setPlaceholderText("搜索标题 / 作者 / 作品ID...")
        bar.addWidget(self.work_search, 1)

        btn = QPushButton("搜索")
        bar.addWidget(btn)

        refresh = QPushButton("刷新")
        bar.addWidget(refresh)
        v.addLayout(bar)

        table = QTableWidget(0, 8)
        table.setHorizontalHeaderLabels([
            "序号", "作者", "提取方式", "作品标题",
            "时长", "分辨率", "下载状态", "作品ID"
        ])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(table, 1)

        self.work_table = table
        btn.clicked.connect(self.refresh_work_list)
        refresh.clicked.connect(self.refresh_work_list)

        self.refresh_work_list()

    def refresh_work_list(self):
        if not hasattr(self, "work_table"):
            return

        keyword = self.work_search.text().strip() if hasattr(self, "work_search") else ""
        rows = self.db.list_works(keyword)
        self.work_table.setRowCount(0)

        for i, row in enumerate(rows, 1):
            work_id, author, title, url, duration, resolution, status, video_id = row
            r = self.work_table.rowCount()
            self.work_table.insertRow(r)

            vals = [
                str(i), author or "未知", "单作品",
                title or "无标题", duration or "-",
                resolution or "-", status or "未下载",
                video_id or "-"
            ]

            for c, val in enumerate(vals):
                self.work_table.setItem(r, c, QTableWidgetItem(str(val)))

    def build_home(self):
        w, v = self.page("主页提取")
        card = QFrame(); card.setObjectName("card")
        cv = QVBoxLayout(card)
        cv.addWidget(QLabel("输入 TikTok 主页地址（支持一行一个）"))
        edit = QTextEdit()
        edit.setPlaceholderText("https://www.tiktok.com/@username")
        edit.setFixedHeight(130)
        cv.addWidget(edit)
        row = QHBoxLayout()
        row.addWidget(QLabel("提取类型："))
        row.addWidget(QPushButton("视频"))
        row.addWidget(QPushButton("图文"))
        row.addStretch()
        start = QPushButton("开始提取主页"); start.setObjectName("green")
        row.addWidget(start)
        cv.addLayout(row)
        v.addWidget(card)
        self.add_log(v)

    def build_single(self):
        w, v = self.page("单作品提取")
        card = QFrame()
        card.setObjectName("card")
        cv = QVBoxLayout(card)

        cv.addWidget(QLabel("输入作品 URL，支持批量（一行一个）"))

        edit = QTextEdit()
        edit.setPlaceholderText(
            "https://www.tiktok.com/@user/video/1234567890\\n"
            "一行一个 URL"
        )
        edit.setFixedHeight(180)
        cv.addWidget(edit)

        row = QHBoxLayout()
        start = QPushButton("开始解析")
        start.setObjectName("green")
        add = QPushButton("加入作品库")
        download = QPushButton("下载当前作品")
        download.setObjectName("pink")
        row.addWidget(start)
        row.addWidget(add)
        row.addWidget(download)
        row.addStretch()
        cv.addLayout(row)

        v.addWidget(card)

        result_card = QFrame()
        result_card.setObjectName("card")
        rv = QVBoxLayout(result_card)
        rv.addWidget(QLabel("作品信息"))

        result = QTextEdit()
        result.setReadOnly(True)
        result.setPlaceholderText("解析成功后，这里显示作品信息")
        result.setMinimumHeight(180)
        rv.addWidget(result)
        v.addWidget(result_card)

        log = self.add_log(v)

        self.single_url_edit = edit
        self.single_result = result
        self.single_log = log
        self.current_work_id = None
        self.current_download_worker = None

        # 原代码缺少这一句，因此按钮虽然显示，但点击没有任何动作。
        start.clicked.connect(self.parse_single)
        add.clicked.connect(self.add_single_to_library)
        download.clicked.connect(self.download_current_work)

    def parse_single(self):
        import re
        import requests

        text = self.single_url_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请先粘贴 TikTok 单作品 URL。")
            return

        urls = [x.strip() for x in text.splitlines() if x.strip()]
        self.single_log.clear()
        self.single_result.clear()

        valid_urls = []
        for url in urls:
            if "tiktok.com" not in url.lower():
                self.single_log.append(f"❌ 不是 TikTok URL：{url}")
                continue
            if "/video/" not in url.lower():
                self.single_log.append(f"⚠️ 暂未识别为标准单作品 URL：{url}")
                continue
            valid_urls.append(url)

        if not valid_urls:
            self.single_log.append("没有找到可以解析的 TikTok 单作品 URL。")
            return

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        for index, url in enumerate(valid_urls, 1):
            self.single_log.append(f"\n[{index}/{len(valid_urls)}] 开始解析：")
            self.single_log.append(url)

            m = re.search(r"/video/(\d+)", url)
            video_id = m.group(1) if m else ""

            author = ""
            title = ""
            image = ""
            video_url = ""
            duration = ""
            resolution = ""

            m = re.search(r"tiktok\.com/@([^/?#]+)", url, re.I)
            if m:
                author = m.group(1)

            html = ""
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    timeout=20,
                    allow_redirects=True
                )
                self.single_log.append(f"HTTP 状态：{response.status_code}")
                html = response.text

                data = extract_tiktok_data(html)
                author = data["author"] or author
                title = data["title"]
                image = data["image"]
                video_url = data["video_url"]
                duration = data["duration"]
                resolution = data["resolution"]

                self.single_log.append(
                    f"requests解析：标题={'有' if title else '无'}，"
                    f"封面={'有' if image else '无'}，"
                    f"视频地址={'有' if video_url else '无'}"
                )

            except Exception as e:
                self.single_log.append(f"⚠️ requests 请求失败：{e}")

            # requests 拿不到数据时，用本机 Chrome 渲染后的 DOM 再解析。
            if not title or not image or not video_url:
                rendered = load_with_chrome(
                    url,
                    lambda msg: self.single_log.append(msg)
                )
                if rendered:
                    data = extract_tiktok_data(rendered)
                    author = data["author"] or author
                    title = data["title"] or title
                    image = data["image"] or image
                    video_url = data["video_url"] or video_url
                    duration = data["duration"] or duration
                    resolution = data["resolution"] or resolution

                    self.single_log.append(
                        f"Chrome解析：标题={'有' if title else '无'}，"
                        f"封面={'有' if image else '无'}，"
                        f"视频地址={'有' if video_url else '无'}"
                    )

            self.single_result.append(f"作品 {index}")
            self.single_result.append(f"作者：{author or '未获取'}")
            self.single_result.append(f"作品 ID：{video_id or '未获取'}")
            self.single_result.append(f"标题：{title or '暂未获取'}")
            self.single_result.append(f"封面：{image or '暂未获取'}")
            self.single_result.append(f"视频地址：{video_url or '暂未获取'}")
            self.single_result.append(f"时长：{duration or '暂未获取'}")
            self.single_result.append(f"分辨率：{resolution or '暂未获取'}")
            self.single_result.append(f"URL：{url}")

            self.current_work_id = self.db.add_work({
                "video_id": video_id or url,
                "author": author,
                "title": title,
                "url": url,
                "video_url": video_url,
                "cover_url": image,
                "duration": duration,
                "resolution": resolution
            })

            if video_url:
                self.single_result.append("✅ 已解析视频地址并写入作品库。")
            else:
                self.single_result.append(
                    "⚠️ 已写入作品库，但暂未获取视频地址，当前不能直接下载。"
                )

            self.single_result.append("-" * 70)

        self.single_log.append("\n✅ 解析任务完成。")
        self.refresh_work_list()

    def download_current_work(self):
        work_id = self.current_work_id

        if not work_id:
            work_id = get_latest_work_id(self.db)

        if not work_id:
            QMessageBox.warning(
                self, "提示",
                "还没有解析作品，请先点击“开始解析”。"
            )
            return

        work = self.db.get_work(work_id)
        if not work:
            QMessageBox.warning(self, "提示", "找不到当前作品。")
            return

        video_url = work[5]
        if not video_url:
            QMessageBox.warning(
                self, "无法下载",
                "当前作品没有视频地址。\n请重新解析后再下载。"
            )
            return

        output_dir = self.download_path_edit.text().strip()
        if not output_dir:
            output_dir = os.path.expanduser("~/Downloads/TK_Studio")
            self.download_path_edit.setText(output_dir)

        self.single_log.append("\n开始下载当前作品……")

        self.current_download_worker = DownloadWorker(
            work_id,
            video_url,
            output_dir,
            self.db
        )
        self.current_download_worker.progress.connect(
            self.on_single_download_progress
        )
        self.current_download_worker.finished_ok.connect(
            self.on_single_download_finished
        )
        self.current_download_worker.failed.connect(
            self.on_single_download_failed
        )
        self.current_download_worker.start()

    def on_single_download_progress(self, percent, status, message):
        self.single_log.append(
            f"下载状态：{status} {percent}%"
            + (f"  {message}" if message else "")
        )

    def on_single_download_finished(self, path):
        self.refresh_work_list()
        self.single_log.append(f"✅ 下载完成：{path}")
        QMessageBox.information(
            self, "下载完成",
            f"视频已经保存到：\n{path}"
        )

    def on_single_download_failed(self, error):
        self.refresh_work_list()
        self.single_log.append(f"❌ 下载失败：{error}")
        QMessageBox.warning(
            self, "下载失败",
            f"视频下载失败：\n{error}"
        )

    def add_single_to_library(self):
        text = self.single_url_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请先输入作品 URL。")
            return

        self.parse_single()

    def build_keyword(self):
        w, v = self.page("关键词提取")
        row = QHBoxLayout()
        inp = QLineEdit(); inp.setPlaceholderText("例如：celebrity news / football / fashion")
        row.addWidget(inp, 1)
        btn = QPushButton("搜索关键词"); btn.setObjectName("green")
        row.addWidget(btn)
        v.addLayout(row)
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(["关键词", "作者", "标题", "播放量", "点赞", "状态"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(table, 1)
        btn.clicked.connect(lambda: self.add_keyword_demo(table, inp.text().strip()))

    def add_keyword_demo(self, table, keyword):
        if not keyword:
            QMessageBox.warning(self, "提示", "请输入关键词")
            return
        table.setRowCount(0)
        for i in range(1, 6):
            r = table.rowCount(); table.insertRow(r)
            vals = [keyword, f"Creator{i}", f"{keyword} 示例视频 {i}", f"{i*12}.5K", f"{i*1.2}K", "待下载"]
            for c, x in enumerate(vals):
                table.setItem(r, c, QTableWidgetItem(str(x)))

    def build_myhome(self):
        w, v = self.page("我的主页")
        info = QLabel("这里用于管理你自己的主页、关注列表、收藏/喜欢作品等任务。")
        info.setObjectName("card")
        v.addWidget(info)
        row = QHBoxLayout()
        for text in ["我的关注主页", "我的主页作品", "我的收藏", "我的喜欢"]:
            b = QPushButton(text); row.addWidget(b)
        v.addLayout(row); v.addStretch()

    def build_download(self):
        w, v = self.page("下载设置")

        card = QFrame()
        card.setObjectName("card")
        cv = QVBoxLayout(card)

        cv.addWidget(QLabel("下载目录"))
        path = QLineEdit(os.path.expanduser("~/Downloads/TK_Studio"))
        cv.addWidget(path)

        choose = QPushButton("选择目录")
        cv.addWidget(choose)
        choose.clicked.connect(lambda: self.choose_dir(path))

        v.addWidget(card)

        self.download_path_edit = path

        v.addWidget(QLabel(
            "这里设置保存目录；解析页面也可以直接下载当前作品。"
        ))

        self.download_progress = QProgressBar()
        self.download_progress.setValue(0)
        v.addWidget(self.download_progress)

        start = QPushButton("下载作品库最新作品")
        start.setObjectName("green")
        v.addWidget(start)
        start.clicked.connect(self.download_latest_work)

        v.addStretch()

    def download_latest_work(self):
        rows = self.db.list_works()
        if not rows:
            QMessageBox.warning(self, "提示", "作品库为空，请先解析 TikTok 作品。")
            return

        work_id = rows[0][0]
        work = self.db.get_work(work_id)
        if not work:
            return

        video_url = work[5]
        if not video_url:
            QMessageBox.warning(
                self, "无法下载",
                "该作品目前没有获取到视频地址，请先重新解析。"
            )
            return

        output_dir = self.download_path_edit.text().strip()
        if not output_dir:
            output_dir = os.path.expanduser("~/Downloads/TK_Studio")
            self.download_path_edit.setText(output_dir)

        self.current_download_worker = DownloadWorker(
            work_id, video_url, output_dir, self.db
        )
        self.current_download_worker.progress.connect(
            lambda p, s, m: self.download_progress.setValue(p)
        )
        self.current_download_worker.finished_ok.connect(
            lambda path: self._latest_download_ok(path)
        )
        self.current_download_worker.failed.connect(
            lambda err: self._latest_download_failed(err)
        )
        self.current_download_worker.start()

    def _latest_download_ok(self, path):
        self.refresh_work_list()
        self.download_progress.setValue(100)
        QMessageBox.information(self, "下载完成", f"已保存：\n{path}")

    def _latest_download_failed(self, error):
        self.refresh_work_list()
        QMessageBox.warning(self, "下载失败", error)


    def choose_dir(self, edit):
        d = QFileDialog.getExistingDirectory(self, "选择下载目录")
        if d: edit.setText(d)

    def build_browser(self):
        w, v = self.page("浏览器 / 登录 TK")
        v.addWidget(QLabel("第一版先提供浏览器入口；后续可以接入 Qt WebEngine / 独立浏览器。"))
        b = QPushButton("打开 TikTok 官网")
        v.addWidget(b)
        b.clicked.connect(lambda: __import__("webbrowser").open("https://www.tiktok.com/"))
        v.addStretch()

    def build_settings(self):
        w, v = self.page("软件设置")
        for text in ["启动时检查更新", "自动保存任务", "下载完成后打开目录", "失败任务自动重试"]:
            b = QPushButton(text); b.setCheckable(True); b.setChecked(True)
            v.addWidget(b)
        v.addStretch()

    def build_help(self):
        w, v = self.page("使用教程")
        t = QTextEdit()
        t.setReadOnly(True)
        t.setPlainText(
            "TK Studio V1.4\n\n"
            "1. 主页提取：输入主页 URL。\n"
            "2. 单作品提取：输入视频 URL。\n"
            "3. 关键词提取：输入关键词并搜索。\n"
            "4. 下载设置：设置本地保存目录。\n\n"
            "当前版本主要完成桌面 GUI 和任务管理框架。\n"
            "TikTok 数据采集、解析和下载引擎将在后续版本接入。"
        )
        v.addWidget(t)

    def add_log(self, v):
        log = QTextEdit()
        log.setReadOnly(True)
        log.setPlaceholderText("任务日志...")
        v.addWidget(log, 1)
        return log

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
