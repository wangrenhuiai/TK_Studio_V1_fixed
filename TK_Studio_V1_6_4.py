import sys
import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QStackedWidget, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QProgressBar, QFileDialog, QTextEdit, QFrame
)

from core.db import Database, get_latest_work_id
from core.chrome_bridge import chrome_render_with_cookies
from core.tiktok_service import parse_url
from workers.download_worker import DownloadWorker

APP_STYLE = """
/* ===== Base ===== */
QMainWindow { background: #f8fafc; }
QWidget { color: #0f172a; font-size: 14px; }
QLabel { color: #0f172a; }

/* ===== Sidebar ===== */
#sidebar { background: #1e293b; }
#brand { color: #f8fafc; font-size: 20px; font-weight: 700; padding: 20px 10px 14px 10px; letter-spacing: 0.5px; }
QListWidget { background: #1e293b; color: #cbd5e1; border: none; font-size: 14px; outline: none; }
QListWidget::item { padding: 12px 14px; border-radius: 8px; margin: 2px 8px; color: #cbd5e1; }
QListWidget::item:hover { background: #334155; color: #f8fafc; }
QListWidget::item:selected { background: #2563eb; color: #ffffff; }
QListWidget::item:selected:hover { background: #1d4ed8; }

/* ===== Title ===== */
#title { font-size: 20px; font-weight: 700; color: #0f172a; }

/* ===== Buttons ===== */
QPushButton {
    background: #ffffff; color: #2563eb;
    border: 1px solid #cbd5e1; border-radius: 8px;
    padding: 8px 16px; font-weight: 600;
}
QPushButton:hover { background: #eff6ff; border-color: #2563eb; }
QPushButton:pressed { background: #dbeafe; }
QPushButton:disabled { color: #94a3b8; border-color: #e2e8f0; background: #f1f5f9; }
QPushButton#green {
    background: #2563eb; color: #ffffff; border: 1px solid #2563eb;
}
QPushButton#green:hover { background: #1d4ed8; border-color: #1d4ed8; }
QPushButton#green:pressed { background: #1e40af; }
QPushButton#green:disabled { background: #93c5fd; border-color: #93c5fd; color: #ffffff; }
QPushButton#pink {
    background: #16a34a; color: #ffffff; border: 1px solid #16a34a;
}
QPushButton#pink:hover { background: #15803d; border-color: #15803d; }
QPushButton#pink:pressed { background: #166534; }
QPushButton#pink:disabled { background: #86efac; border-color: #86efac; color: #ffffff; }

/* ===== Inputs ===== */
QLineEdit, QTextEdit {
    background: #ffffff; color: #0f172a;
    border: 1px solid #e2e8f0; border-radius: 8px;
    padding: 8px 10px; selection-background-color: #dbeafe;
}
QLineEdit:focus, QTextEdit:focus { border: 1px solid #2563eb; }
QLineEdit:disabled, QTextEdit:disabled { background: #f8fafc; color: #94a3b8; }

/* ===== Card ===== */
#card {
    background: #ffffff; border: 1px solid #e2e8f0;
    border-radius: 10px; padding: 16px;
}

/* ===== Table ===== */
QTableWidget {
    background: #ffffff; alternate-background-color: #f8fafc;
    border: 1px solid #e2e8f0; border-radius: 8px;
    gridline-color: #eef2f7; selection-background-color: #dbeafe;
    selection-color: #0f172a; outline: none;
}
QTableWidget::item { padding: 6px 8px; }
QTableWidget::item:hover { background: #f1f5f9; }
QHeaderView::section {
    background: #f1f5f9; color: #334155;
    padding: 10px 8px; border: none;
    border-bottom: 1px solid #e2e8f0; font-weight: 600;
}
QTableCornerButton::section { background: #f1f5f9; border: none; }

/* ===== ProgressBar ===== */
QProgressBar {
    background: #e2e8f0; border: none; border-radius: 3px;
    text-align: center; height: 6px; color: #64748b; font-size: 11px;
}
QProgressBar::chunk { background: #2563eb; border-radius: 3px; }

/* ===== ScrollBar ===== */
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #cbd5e1; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #94a3b8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 0; }
QScrollBar::handle:horizontal { background: #cbd5e1; border-radius: 4px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: #94a3b8; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = Database()
        self.download_threads = []
        self.setWindowTitle("TK Studio V1.6.4 - TikTok作品管理工具")
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

        for index, url in enumerate(valid_urls, 1):
            self.single_log.append(f"\n[{index}/{len(valid_urls)}] 开始解析：")
            self.single_log.append(url)

            data = parse_url(url, log_callback=lambda msg: self.single_log.append(msg))
            video_id = data["video_id"]
            author = data["author"]
            title = data["title"]
            image = data["cover_url"]
            video_url = data["video_url"]
            duration = data["duration"]
            resolution = data["resolution"]

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
