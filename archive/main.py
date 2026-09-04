import sys
import os
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

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
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
        search = QLineEdit()
        search.setPlaceholderText("搜索标题 / 作者 / 关键词...")
        bar.addWidget(search, 1)
        btn = QPushButton("搜索")
        bar.addWidget(btn)
        v.addLayout(bar)

        table = QTableWidget(0, 8)
        table.setHorizontalHeaderLabels(["序号", "作者", "提取方式", "作品标题", "时长", "分辨率", "下载状态", "操作"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for i in range(1, 6):
            row = table.rowCount()
            table.insertRow(row)
            vals = [str(i), "DemoUser", "单作品", f"示例作品 {i}", f"{i+8}s", "1080p", "未下载", "操作"]
            for c, val in enumerate(vals):
                table.setItem(row, c, QTableWidgetItem(val))
        v.addWidget(table, 1)

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

                self.single_log.append("页面请求完成。")
            except Exception as e:
                self.single_log.append(f"⚠️ 页面请求失败：{e}")

            self.single_result.append(f"作品 {index}")
            self.single_result.append(f"作者：{author or '未获取'}")
            self.single_result.append(f"作品 ID：{video_id or '未获取'}")
            self.single_result.append(f"标题：{title or '暂未获取'}")
            self.single_result.append(f"封面：{image or '暂未获取'}")
            self.single_result.append(f"URL：{url}")
            self.single_result.append("-" * 70)

        self.single_log.append("\\n✅ 解析任务完成。")

    def add_single_to_library(self):
        text = self.single_url_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请先输入作品 URL。")
            return

        QMessageBox.information(
            self,
            "作品库",
            "已读取作品 URL。\\n\\n"
            "作品库数据库功能将在下一版接入。"
        )

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
        card = QFrame(); card.setObjectName("card")
        cv = QVBoxLayout(card)
        path = QLineEdit(os.path.expanduser("~/Downloads/TK_Studio"))
        cv.addWidget(QLabel("下载目录"))
        cv.addWidget(path)
        b = QPushButton("选择目录")
        cv.addWidget(b)
        b.clicked.connect(lambda: self.choose_dir(path))
        cv.addWidget(QLabel("下载类型"))
        for text in ["下载视频", "下载封面", "下载背景音乐", "下载字幕"]:
            cb = QPushButton(text); cb.setCheckable(True); cb.setChecked(text == "下载视频")
            cv.addWidget(cb)
        v.addWidget(card)
        p = QProgressBar(); p.setValue(0); v.addWidget(p)
        start = QPushButton("开始下载测试任务"); start.setObjectName("green")
        v.addWidget(start)
        start.clicked.connect(lambda: p.setValue(100))
        v.addStretch()

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
