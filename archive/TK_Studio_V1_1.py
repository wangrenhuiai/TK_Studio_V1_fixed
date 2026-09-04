import sys
import os
import sqlite3
import threading
from datetime import datetime
from urllib.parse import urlparse
from PySide6.QtCore import Qt
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


class DownloadWorker(threading.Thread):
    def __init__(self, work_id, video_url, output_dir, db, callback):
        super().__init__(daemon=True)
        self.work_id = work_id
        self.video_url = video_url
        self.output_dir = output_dir
        self.db = db
        self.callback = callback

    def run(self):
        try:
            import requests
            if not self.video_url:
                raise RuntimeError("数据库中没有视频地址，请先重新解析作品。")

            os.makedirs(self.output_dir, exist_ok=True)

            with self.db.connect() as con:
                row = con.execute(
                    "SELECT video_id, author, title FROM works WHERE id=?",
                    (self.work_id,)
                ).fetchone()

            if not row:
                raise RuntimeError("找不到作品记录。")

            video_id, author, title = row
            safe = "".join(
                c for c in (title or video_id or "tiktok_video")
                if c not in '<>:"/\\|?*'
            ).strip()[:80]
            filename = f"{safe or video_id}.mp4"
            path = os.path.join(self.output_dir, filename)

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/151.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.tiktok.com/"
            }

            self.db.update_download(self.work_id, "下载中")
            self.callback(self.work_id, "下载中", 0, "")

            r = requests.get(
                self.video_url,
                headers=headers,
                stream=True,
                timeout=30
            )
            r.raise_for_status()

            total = int(r.headers.get("content-length", "0") or 0)
            done = 0

            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    percent = int(done * 100 / total) if total else 0
                    self.callback(self.work_id, "下载中", percent, "")

            self.db.update_download(self.work_id, "已下载", path)
            self.callback(self.work_id, "已下载", 100, path)

        except Exception as e:
            self.db.update_download(self.work_id, "下载失败")
            self.callback(self.work_id, "下载失败", 0, str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = Database()
        self.download_threads = []
        self.setWindowTitle("TK Studio V1 - TikTok作品管理工具")
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
        row.addWidget(start)
        row.addWidget(add)
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

        # 原代码缺少这一句，因此按钮虽然显示，但点击没有任何动作。
        start.clicked.connect(self.parse_single)
        add.clicked.connect(self.add_single_to_library)

    def parse_single(self):
        import re
        from html import unescape

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

        try:
            import requests
        except ImportError:
            self.single_log.append(
                "❌ 当前 Python 环境没有 requests。请在 CMD 执行："
                " py -m pip install requests"
            )
            return

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

        for index, url in enumerate(valid_urls, 1):
            self.single_log.append(f"\\n[{index}/{len(valid_urls)}] 开始解析：")
            self.single_log.append(url)

            m = re.search(r"/video/(\\d+)", url)
            video_id = m.group(1) if m else ""

            author = ""
            title = ""
            image = ""
            video_url = ""

            m = re.search(r"tiktok\\.com/@([^/?#]+)", url, re.I)
            if m:
                author = m.group(1)

            try:
                response = requests.get(
                    url,
                    headers=headers,
                    timeout=15,
                    allow_redirects=True
                )
                self.single_log.append(f"HTTP 状态：{response.status_code}")
                html = response.text

                m = re.search(
                    r'<meta[^>]+property=["\\\']og:title["\\\'][^>]+content=["\\\'](.*?)["\\\']',
                    html, re.I | re.S
                )
                if m:
                    title = unescape(m.group(1)).strip()

                m = re.search(
                    r'<meta[^>]+property=["\\\']og:image["\\\'][^>]+content=["\\\'](.*?)["\\\']',
                    html, re.I | re.S
                )
                if m:
                    image = unescape(m.group(1)).strip()

                # 首先尝试页面中的 og:video。
                m = re.search(
                    r'<meta[^>]+property=["\\\']og:video(?::secure_url)?["\\\'][^>]+content=["\\\'](.*?)["\\\']',
                    html, re.I | re.S
                )
                if m:
                    video_url = unescape(m.group(1)).strip()

                # 部分页面使用 JSON 字段 playAddr/playApi。
                if not video_url:
                    for key in ("playAddr", "playApi", "downloadAddr"):
                        m = re.search(
                            rf'["\\\']{key}["\\\']\\s*:\\s*["\\\'](.*?)["\\\']',
                            html, re.I | re.S
                        )
                        if m:
                            video_url = bytes(
                                m.group(1), "utf-8"
                            ).decode("unicode_escape", errors="ignore")
                            video_url = video_url.replace("\\/", "/")
                            break

                self.single_log.append("页面请求完成。")
            except Exception as e:
                self.single_log.append(f"⚠️ 页面请求失败：{e}")

            self.single_result.append(f"作品 {index}")
            self.single_result.append(f"作者：{author or '未获取'}")
            self.single_result.append(f"作品 ID：{video_id or '未获取'}")
            self.single_result.append(f"标题：{title or '暂未获取'}")
            self.single_result.append(f"封面：{image or '暂未获取'}")
            self.single_result.append(f"视频地址：{video_url or '暂未获取'}")
            self.single_result.append(f"URL：{url}")
            self.db.add_work({
                "video_id": video_id or url,
                "author": author,
                "title": title,
                "url": url,
                "video_url": video_url,
                "cover_url": image,
                "duration": "",
                "resolution": ""
            })
            self.single_result.append("✅ 已写入作品库。")
            self.single_result.append("-" * 70)

        self.single_log.append("\\n✅ 解析任务完成，作品已写入 SQLite。")
        self.refresh_work_list()

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
            "从作品列表选择作品后，可在这里下载最新一条作品。"
        ))

        self.download_progress = QProgressBar()
        self.download_progress.setValue(0)
        v.addWidget(self.download_progress)

        start = QPushButton("下载最新作品")
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

        # works columns:
        # id, video_id, author, title, url, video_url, ...
        video_url = work[5]
        if not video_url:
            QMessageBox.warning(
                self, "无法下载",
                "该作品目前没有获取到视频地址，请重新解析。"
            )
            return

        output_dir = self.download_path_edit.text().strip()
        if not output_dir:
            QMessageBox.warning(self, "提示", "请先选择下载目录。")
            return

        worker = DownloadWorker(
            work_id,
            video_url,
            output_dir,
            self.db,
            self.on_download_progress
        )
        self.download_threads.append(worker)
        worker.start()

    def on_download_progress(self, work_id, status, percent, message):
        # DownloadWorker is a Python thread; marshal UI updates back through
        # a zero-delay Qt callback.
        from PySide6.QtCore import QTimer

        def update():
            if hasattr(self, "download_progress"):
                self.download_progress.setValue(percent)

            if status == "已下载":
                self.refresh_work_list()
                QMessageBox.information(
                    self, "下载完成",
                    f"作品 {work_id} 已下载：\n{message}"
                )
            elif status == "下载失败":
                self.refresh_work_list()
                QMessageBox.warning(
                    self, "下载失败",
                    f"作品 {work_id} 下载失败：\n{message}"
                )
            else:
                self.refresh_work_list()

        QTimer.singleShot(0, update)

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
            "TK Studio V1\n\n"
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
