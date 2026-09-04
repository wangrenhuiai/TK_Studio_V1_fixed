import sys
import os
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QStackedWidget, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QProgressBar, QFileDialog, QTextEdit, QFrame, QCheckBox
)

from core.db import Database, get_latest_work_id
from core.chrome_bridge import chrome_render_with_cookies
from core.tiktok_service import parse_url
from workers.task_manager import TaskManager
from workers.parse_worker import ParseWorker
from workers.login_worker import LoginWorker
from workers.home_fetch_worker import HomeFetchWorker
from workers.resolve_worker import ResolveWorker
from core.tiktok_login import LoginState, TikTokLogin
from core.profile_snapshot import snapshot_login_to_auth, delete_auth_profile
from core.url_resolver import resolve_short_url, is_short_url

# 下载并发上限：达到后直接提示，不排队（Phase 3.2 策略）。
MAX_CONCURRENT_DOWNLOADS = 3

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

class _LoginCheckWorker(QThread):
    """一次性异步登录态检查 Worker（M5，headless 短生命周期）。

    程序启动时异步检查 chrome_login_profile 是否已有登录态，
    避免 headless Chrome 检查（~10s）阻塞 Qt 主线程。
    复用 TikTokLogin.check_existing_login()，不重复实现检测逻辑。
    """
    check_done = Signal(bool)

    def __init__(self):
        super().__init__()
        self._login = TikTokLogin()
        self._aborted = False

    def stop(self):
        """请求中止检查（终止 headless Chrome），用于程序退出时快速回收。"""
        self._aborted = True
        try:
            self._login.abort_check()
        except Exception:
            pass

    def run(self):
        try:
            logged_in = self._login.check_existing_login()
        except Exception:
            logged_in = False
        # 已中止（程序退出）时不再发射信号，避免向已销毁窗口投递。
        if not self._aborted:
            self.check_done.emit(logged_in)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = Database()
        # 启动恢复：将上次异常退出残留的“下载中”统一重置为“下载失败”，
        # 避免用户误以为任务仍在运行。不改表结构、不新增状态。
        try:
            self.db.reset_downloading_to_failed()
        except Exception:
            pass
        # B1：下载任务管理器（等待队列 + 并发上限 + Worker 生命周期/取消/自动补位）。
        self.task_manager = TaskManager(self.db, MAX_CONCURRENT_DOWNLOADS)
        self.task_manager.progress.connect(self._on_dl_progress)
        self.task_manager.finished_ok.connect(self._on_dl_finished)
        self.task_manager.failed.connect(self._on_dl_failed)
        self.task_manager.state_changed.connect(self._sync_download_ui)
        # 单作品解析 Worker：同一时刻只允许一个解析任务。
        self._parse_worker = None
        # 本次解析的 URL 列表，用于竞态校验（旧结果不得覆盖当前输入）。
        self._parse_token = None
        # C1 方案 B: 短链解析后台 Worker（同一时刻只允许一个）。
        self._resolve_worker = None
        # 短链解析阶段暂存的原始 URL 列表，解析完成后用于后续 tiktok.com / /video/ 校验。
        self._pending_urls = None
        # TikTok 登录 Worker：同一时刻只允许一个登录会话。
        self._login_worker = None
        # B3.4: 登录成功标志，由 _on_login_success 置位，_on_login_worker_finished
        # 读取并触发 profile snapshot 后清零。不在 _on_login_success 直接 snapshot，
        # 因此时 LoginWorker.shutdown() 可能尚未完成（Chrome 未释放 profile 锁）。
        self._login_succeeded = False
        # TikTok 登录态检查 Worker（M5）：启动时一次性 headless 检查。
        self._login_check_worker = None
        # 主页抓取 Worker（B2.2-B）：同一时刻只允许一个主页抓取任务。
        self._home_worker = None
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

        # M5: UI 就绪后异步检查持久化登录态（headless，不阻塞主线程）。
        self.start_login_state_check()

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

        table = QTableWidget(0, 9)
        table.setHorizontalHeaderLabels([
            "序号", "作者", "提取方式", "作品标题",
            "时长", "分辨率", "下载状态", "作品ID", "操作"
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

            op_widget = QWidget()
            op_layout = QHBoxLayout(op_widget)
            op_layout.setContentsMargins(4, 2, 4, 2)
            op_layout.setSpacing(4)

            is_downloading = self.task_manager.is_busy(work_id)

            dl_btn = QPushButton("取消" if is_downloading else "下载")
            dl_btn.setFixedWidth(54)
            # 下载/取消按钮始终可用；删除按钮在下载中禁用。
            dl_btn.setEnabled(True)
            dl_btn.clicked.connect(
                lambda checked, wid=work_id: self._download_or_cancel_work(wid)
            )
            op_layout.addWidget(dl_btn)

            del_btn = QPushButton("删除")
            del_btn.setFixedWidth(54)
            # 下载中的作品删除按钮禁用，避免 DB 记录与 Worker/本地文件不一致。
            del_btn.setEnabled(not is_downloading)
            del_btn.clicked.connect(
                lambda checked, wid=work_id: self.delete_row_work(wid)
            )
            op_layout.addWidget(del_btn)

            self.work_table.setCellWidget(r, 8, op_widget)

    def download_row_work(self, work_id):
        self.current_work_id = work_id
        self.download_current_work()

    def _download_or_cancel_work(self, work_id):
        """列表按钮统一入口：排队中/下载中则取消，否则启动下载。"""
        if self.task_manager.is_busy(work_id):
            self.cancel_download(work_id)
        else:
            self.download_row_work(work_id)

    def cancel_download(self, work_id):
        """请求取消指定作品的下载/排队任务（委托 TaskManager）。

        下载中：由下载循环在检查点主动退出（不杀线程）；
        排队中：直接出队并标记取消。UI 不再直接持有 Worker。
        """
        self.task_manager.cancel(work_id)

    def delete_row_work(self, work_id):
        # 排队中/下载中的作品禁止删除，避免 DB 记录与 Worker/本地文件不一致。
        if self.task_manager.is_busy(work_id):
            QMessageBox.information(
                self,
                "提示",
                "该作品正在下载，请等待下载完成后再删除。"
            )
            return
        work = self.db.get_work(work_id)
        if not work:
            QMessageBox.warning(self, "提示", "作品不存在。")
            return
        title = work[3] or "无标题"
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除作品「{title}」吗？\n\n"
            "将删除数据库中的作品记录。\n"
            "已下载的本地视频文件不会被删除。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        try:
            deleted = self.db.delete_work(work_id)
        except Exception as e:
            QMessageBox.critical(self, "删除失败", f"删除作品时出错：\n{e}")
            return
        if deleted:
            self.refresh_work_list()
        else:
            QMessageBox.warning(self, "提示", "作品未找到或已被删除。")

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

        # B3.2：profile 模式选择。默认不勾选 = 匿名抓取（profile_dir=None，
        # 走 chrome_home_fetcher_profile，B3.1 基线行为不变）；
        # 勾选 = 复用登录态（profile_dir=chrome_home_auth_profile）。
        self.home_auth_checkbox = QCheckBox(
            "复用登录态（需先在「浏览器/登录 TK」页扫码登录）"
        )
        cv.addWidget(self.home_auth_checkbox)

        v.addWidget(card)
        log = self.add_log(v)

        self.home_edit = edit
        self.home_log = log
        self.home_start_btn = start
        # B2.2-B：接线主页抓取按钮（后台线程，不阻塞 UI）。
        start.clicked.connect(self.start_home_fetch)

    def start_home_fetch(self):
        """主页抓取按钮入口：启动后台抓取（B2.2-B，不阻塞 UI）。

        输入支持完整主页 URL 或纯用户名，逐行解析；HomeWorker(B2.1) 在
        后台线程执行，结果通过信号回主线程。

        B3.2：根据 ``home_auth_checkbox`` 选择 profile 模式：
        - 未勾选（默认）：匿名抓取，profile_dir=None（走
          chrome_home_fetcher_profile，B3.1 基线行为不变）
        - 勾选：复用登录态，profile_dir=chrome_home_auth_profile
          （需先扫码登录建立该 profile，B3.3 将实现 login_success
          快照填充；当前若 profile 不存在则由 HomeFetcher 自动 makedirs
          创建空目录，等同匿名，不会崩溃）
        """
        text = self.home_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请先输入 TikTok 主页地址或用户名。")
            return

        # 防重入：已有 HomeFetchWorker 运行时直接返回。
        if self._home_worker is not None:
            return

        urls = [x.strip() for x in text.splitlines() if x.strip()]
        if not urls:
            QMessageBox.warning(self, "提示", "没有有效的主页地址。")
            return

        # B3.2：根据复选框决定 profile_dir。
        if self.home_auth_checkbox.isChecked():
            profile_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "chrome_home_auth_profile",
            )
        else:
            profile_dir = None  # 匿名（默认，B3.1 基线）

        self.home_log.clear()
        if profile_dir is not None:
            self.home_log.append("ℹ️ 复用登录态模式：chrome_home_auth_profile")
        self.home_start_btn.setEnabled(False)
        self.home_start_btn.setText("抓取中...")

        worker = HomeFetchWorker(urls, source="tiktok", profile_dir=profile_dir)
        self._home_worker = worker
        worker.home_success.connect(self._on_home_success)
        worker.home_failed.connect(self._on_home_failed)
        worker.log.connect(self._on_home_log)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._on_home_finished)
        worker.start()

    def _on_home_success(self, result):
        """主页抓取成功回调（主线程）。展示该主页的视频 URL 列表。"""
        username = result.get("username", "")
        count = result.get("count", 0)
        urls = result.get("urls", [])
        self.home_log.append(
            f"✅ @{username or '?'} 抓取到 {count} 条视频："
        )
        for u in urls:
            self.home_log.append(f"  {u}")

    def _on_home_failed(self, error):
        """主页抓取失败回调（主线程）。"""
        self.home_log.append(f"❌ 抓取失败：{error}")

    def _on_home_log(self, msg):
        """主页抓取日志回调（主线程）。"""
        self.home_log.append(str(msg))

    def _on_home_finished(self):
        """HomeFetchWorker 结束回调（主线程）。清理状态并恢复按钮。

        try/finally 保证追加日志抛异常时也能释放引用并恢复按钮，避免
        按钮卡死、Worker 引用泄漏导致后续抓取被永久拒绝。
        """
        try:
            self.home_log.append("✅ 主页抓取任务完成。")
        finally:
            self._home_worker = None
            self.home_start_btn.setEnabled(True)
            self.home_start_btn.setText("开始提取主页")

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
        self.single_parse_btn = start
        add = QPushButton("加入作品库")
        download = QPushButton("下载当前作品")
        download.setObjectName("pink")
        self.single_download_btn = download
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

        # 原代码缺少这一句，因此按钮虽然显示，但点击没有任何动作。
        start.clicked.connect(self.parse_single)
        add.clicked.connect(self.add_single_to_library)
        download.clicked.connect(self._single_download_or_cancel)

    def parse_single(self):
        text = self.single_url_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请先粘贴 TikTok 单作品 URL。")
            return

        # 防止重复解析：已有 ParseWorker 或 ResolveWorker 运行时直接返回。
        if self._parse_worker is not None:
            return
        if self._resolve_worker is not None:
            return

        urls = [x.strip() for x in text.splitlines() if x.strip()]
        self.single_log.clear()
        self.single_result.clear()

        # C1 方案 B: 短链解析移入后台线程，避免批量短链卡 UI。
        # 先快速检查是否有短链；全非短链则跳过 ResolveWorker 直接校验。
        has_short = any(is_short_url(u) for u in urls)
        if not has_short:
            # 无短链，直接走校验 + ParseWorker（与原流程一致）。
            self._validate_and_parse(urls)
            return

        # 有短链：启动 ResolveWorker 后台解析。
        self.single_parse_btn.setEnabled(False)
        self.single_parse_btn.setText("解析中...")  # C3: 与 home_start_btn 文本反馈一致
        self._pending_urls = list(urls)
        worker = ResolveWorker(urls)
        self._resolve_worker = worker
        worker.log.connect(self.single_log.append)
        worker.resolved.connect(self._on_url_resolved)
        worker.finished_ok.connect(self._on_resolve_finished)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._on_resolve_worker_finished)
        worker.start()
        # 立即返回主线程，不阻塞 UI。

    def _on_url_resolved(self, item):
        """ResolveWorker 逐条解析回调（主线程）。展示短链转换结果。"""
        original = item.get("original", "")
        resolved = item.get("resolved", "")
        changed = item.get("changed", False)
        if changed and "/video/" in resolved.lower():
            self.single_log.append("🔗 TikTok短链解析:")
            self.single_log.append("原始:")
            self.single_log.append(original)
            self.single_log.append("解析:")
            self.single_log.append(resolved)
        elif item.get("success") is False and original != resolved:
            # 短链但解析未变化 → 视为失败
            self.single_log.append("⚠️ TikTok短链解析失败，保留原URL")

    def _on_resolve_finished(self, results):
        """ResolveWorker 全部完成回调（主线程）。汇总后走校验 + ParseWorker。"""
        if self._pending_urls is None:
            return
        # 用解析结果替换原 URL（仅成功转换为 /video/ 的）
        resolved_urls = []
        for item in results:
            original = item.get("original", "")
            resolved = item.get("resolved", "")
            changed = item.get("changed", False)
            if changed and "/video/" in resolved.lower():
                resolved_urls.append(resolved)
            else:
                resolved_urls.append(original)
        self._pending_urls = None
        self._validate_and_parse(resolved_urls)

    def _on_resolve_worker_finished(self):
        """ResolveWorker 线程结束清理（主线程）。释放引用。"""
        self._resolve_worker = None

    def _validate_and_parse(self, urls):
        """URL 校验（tiktok.com / /video/）+ 启动 ParseWorker。

        从 parse_single 和 _on_resolve_finished 调用，统一后续流程。
        """
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
            self.single_parse_btn.setEnabled(True)
            self.single_parse_btn.setText("开始解析")  # C3: 无效 URL 时恢复按钮文本
            return

        # 记录本次解析 token，用于竞态校验。
        self._parse_token = list(valid_urls)

        # 禁用解析按钮，避免重复点击。
        self.single_parse_btn.setEnabled(False)
        self.single_parse_btn.setText("解析中...")  # C3: 进入 ParseWorker 时保持文本

        # 把阻塞性解析流程移到后台线程。
        worker = ParseWorker(valid_urls, self.db)
        self._parse_worker = worker
        worker.success.connect(self._on_parse_success)
        worker.failed.connect(self._on_parse_failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._on_parse_finished)
        worker.start()
        # 立即返回主线程，不阻塞 UI。

    def _on_parse_success(self, data):
        """解析成功回调（主线程）。处理单个 URL 的解析结果与 UI 更新。"""
        # 竞态校验：结果不属于当前解析任务则丢弃。
        if self._parse_token is None or data.get("url") not in self._parse_token:
            return

        url = data["url"]
        index = data.get("index", 1)
        total = data.get("total", 1)

        # 回放解析期间收集的日志
        self.single_log.append(f"\n[{index}/{total}] 开始解析：")
        self.single_log.append(url)
        for msg in data.get("logs", []):
            self.single_log.append(msg)

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

        # work_id 已由 Worker 入库时返回
        self.current_work_id = data.get("work_id")

        if video_url:
            self.single_result.append("✅ 已解析视频地址并写入作品库。")
        else:
            self.single_result.append(
                "⚠️ 已写入作品库，但暂未获取视频地址，当前不能直接下载。"
            )

        self.single_result.append("-" * 70)

    def _on_parse_failed(self, error):
        """解析失败回调（主线程）。"""
        self.single_log.append(f"\n❌ 解析失败：{error}")
        QMessageBox.warning(self, "解析失败", f"解析过程中出现错误：\n{error}")
        # 清空 token，使 _on_parse_finished 不再追加"解析完成"日志。
        self._parse_token = None

    def _on_parse_finished(self):
        """ParseWorker 结束回调（主线程）。清理状态并恢复 UI。

        try/finally 保证任一异常下状态都能恢复，避免按钮卡死、
        Worker 引用泄漏导致后续 parse_single 被永久拒绝。
        """
        try:
            # 正常完成时追加完成日志；失败时已在 _on_parse_failed 提示。
            if self._parse_token is not None:
                self.single_log.append("\n✅ 解析任务完成。")
            # 无论成功/失败，刷新作品列表与下载按钮状态（可能已有部分作品入库）。
            self._sync_download_ui()
        finally:
            # 状态清理必须无条件执行：_sync_download_ui 抛异常时
            # 也要释放 _parse_worker 引用并恢复按钮，否则用户无法再次解析。
            self._parse_token = None
            self._parse_worker = None
            self.single_parse_btn.setEnabled(True)
            self.single_parse_btn.setText("开始解析")  # C3: 完成时恢复按钮文本

    def _single_download_or_cancel(self):
        """单作品页按钮入口：排队中/下载中则取消当前作品，否则启动下载。"""
        if self.current_work_id and self.task_manager.is_busy(self.current_work_id):
            self.cancel_download(self.current_work_id)
        else:
            self.download_current_work()

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

        self.single_log.append("\n开始下载当前作品……")
        self._start_download_worker(work_id, source="single")

    def _sync_download_ui(self):
        """同步下载相关 UI 状态。

        TaskManager 是唯一真实任务状态来源（排队中/下载中均视为忙碌）。
        - 刷新作品列表（按钮文本/enabled 由 refresh_work_list 根据 is_busy 决定）
        - 同步单作品页按钮：当前作品排队/下载中时显示"取消下载"，否则"下载当前作品"
        """
        self.refresh_work_list()
        if hasattr(self, "single_download_btn") and self.current_work_id is not None:
            downloading = self.task_manager.is_busy(self.current_work_id)
            self.single_download_btn.setText("取消下载" if downloading else "下载当前作品")
            self.single_download_btn.setEnabled(True)

    def _start_download_worker(self, work_id, source="single"):
        """统一下载入口：校验后委托 TaskManager 入队（B1）。

        单作品下载（source="single"）和作品列表/最新下载（source="latest"）
        共用此方法。互斥、排队（超过并发上限自动进入等待并自动补位）、
        Worker 创建/回收/取消全部由 TaskManager 负责。
        """
        # 互斥：同一作品排队中或下载中不重复入队。
        if self.task_manager.is_busy(work_id):
            QMessageBox.information(
                self, "提示", "该作品正在下载或排队中，请稍候。"
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

        # 超过并发上限的任务进入等待队列，任务完成后由 TaskManager 自动补位。
        self.task_manager.enqueue(work_id, video_url, output_dir, source=source)
        # 立即同步 UI：按钮切换为取消态。
        self._sync_download_ui()

    def _on_dl_progress(self, work_id, percent, status, message, source):
        if source == "single":
            self.single_log.append(
                f"下载状态：{status} {percent}%"
                + (f"  {message}" if message else "")
            )
        else:
            self.download_progress.setValue(percent)

    def _on_dl_finished(self, work_id, path, source):
        self._sync_download_ui()
        if source == "single":
            self.single_log.append(f"✅ 下载完成：{path}")
        else:
            self.download_progress.setValue(100)
        QMessageBox.information(
            self, "下载完成",
            f"视频已经保存到：\n{path}"
        )

    def _on_dl_failed(self, work_id, error, source):
        self._sync_download_ui()
        # 区分用户主动取消与普通失败：取消不弹"下载失败"警告。
        if error == "用户取消下载":
            if source == "single":
                self.single_log.append("⏹ 下载已取消")
            return
        if source == "single":
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
        # 复用统一入口，不复制任务管理逻辑。
        self._start_download_worker(work_id, source="latest")


    def choose_dir(self, edit):
        d = QFileDialog.getExistingDirectory(self, "选择下载目录")
        if d: edit.setText(d)

    def build_browser(self):
        w, v = self.page("浏览器 / 登录 TK")

        # --- TikTok 登录区 ---
        login_title = QLabel("TikTok 登录")
        login_title.setObjectName("title")
        v.addWidget(login_title)

        # 登录状态标签
        self.login_status_label = QLabel("状态：未登录")
        v.addWidget(self.login_status_label)

        # 按钮行：扫码登录 / 登出 / 打开官网
        btn_row = QHBoxLayout()
        self.login_btn = QPushButton("扫码登录")
        self.login_btn.setObjectName("green")
        self.login_btn.clicked.connect(self.on_login_clicked)
        btn_row.addWidget(self.login_btn)

        logout_btn = QPushButton("登出")
        logout_btn.clicked.connect(self.on_logout_clicked)
        btn_row.addWidget(logout_btn)

        open_tiktok_btn = QPushButton("打开 TikTok 官网")
        open_tiktok_btn.clicked.connect(
            lambda: __import__("webbrowser").open("https://www.tiktok.com/")
        )
        btn_row.addWidget(open_tiktok_btn)
        btn_row.addStretch()
        v.addLayout(btn_row)

        # 登录日志区
        v.addWidget(QLabel("登录日志："))
        self.login_log = QTextEdit()
        self.login_log.setReadOnly(True)
        self.login_log.setMaximumHeight(220)
        v.addWidget(self.login_log)

        v.addStretch()

    # ------------------------------------------------------------------
    # TikTok 登录管理
    # ------------------------------------------------------------------

    def start_login_state_check(self):
        """M5: 启动时异步检查持久化登录态（headless，不阻塞 UI）。

        检查期间状态标签显示「检测登录态...」；完成后回填
        「已登录 / 未登录」。检查占用专用 Profile，期间禁止扫码登录。
        """
        self.login_status_label.setText("状态：检测登录态...")
        self._login_check_worker = _LoginCheckWorker()
        self._login_check_worker.check_done.connect(self._on_login_check_done)
        self._login_check_worker.finished.connect(self._login_check_worker.deleteLater)
        self._login_check_worker.start()

    def _on_login_check_done(self, logged_in):
        """登录态检查完成回调（主线程）。

        若用户已抢先启动登录会话，则不覆盖其状态显示。
        """
        self._login_check_worker = None
        if self._login_worker is not None and self._login_worker.isRunning():
            return
        self.login_status_label.setText(
            "状态：已登录" if logged_in else "状态：未登录"
        )
        self._append_login_log(
            "登录态检测完成：" + ("已登录（复用持久化 Profile）" if logged_in else "未登录")
        )

    def on_login_clicked(self):
        """扫码登录 / 取消登录按钮。"""
        # M5: 登录态检查占用专用 Profile 时禁止启动，避免 Chrome profile 锁冲突。
        if self._login_check_worker is not None and self._login_check_worker.isRunning():
            QMessageBox.information(
                self, "提示", "正在检测登录状态，请稍候几秒后再点击扫码登录。"
            )
            return
        # M4: 引用未清理（旧 Worker finished 槽尚未送达）时忽略点击，
        # 防止旧 queued 槽把新 Worker 引用清空导致 closeEvent 失察/二次启动。
        if self._login_worker is not None:
            if self._login_worker.isRunning():
                # 正在登录 → 取消
                self._login_worker.cancel()
                self.login_btn.setEnabled(False)
                self.login_btn.setText("正在取消...")
            return
        # 启动登录
        self.login_log.clear()
        self._append_login_log("正在启动浏览器...")
        self.login_btn.setText("取消登录")
        self.login_status_label.setText("状态：正在登录...")

        self._login_worker = LoginWorker()
        self._login_worker.log.connect(self._append_login_log)
        self._login_worker.status_changed.connect(self._on_login_status_changed)
        self._login_worker.login_success.connect(self._on_login_success)
        self._login_worker.login_failed.connect(self._on_login_failed)
        # Worker 结束后清理引用并恢复按钮
        self._login_worker.finished.connect(self._on_login_worker_finished)
        self._login_worker.finished.connect(self._login_worker.deleteLater)
        self._login_worker.start()

    def on_logout_clicked(self):
        """登出：清除持久化 Profile。"""
        # M2: 登录会话运行中禁止登出，避免 rmtree 与运行中 Chrome 竞争 Profile
        # 导致假登出（Chrome 退出时把内存 sessionid 重新落盘）和 Profile 半损坏。
        if self._login_worker is not None and self._login_worker.isRunning():
            QMessageBox.information(
                self, "提示", "扫码登录正在进行中，请先取消登录再登出。"
            )
            return
        reply = QMessageBox.question(
            self, "确认登出",
            "将清除本地 TikTok 登录态（Chrome Profile），确定登出吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self._append_login_log("正在登出...")
        tiktok = TikTokLogin()
        ok = tiktok.logout(log_callback=lambda msg: self._append_login_log(msg))
        if ok:
            self.login_status_label.setText("状态：未登录")
            self._append_login_log("登出完成")
            # B3.4: 同步清理 auth profile 快照，避免残留过期登录态。
            delete_auth_profile(log_callback=self._append_login_log)
        else:
            self._append_login_log("登出失败")

    def _on_login_status_changed(self, state):
        """LoginWorker 状态变化回调（主线程）。"""
        state_text = {
            LoginState.UNKNOWN: "未知",
            LoginState.LOGIN_PAGE: "登录页加载中",
            LoginState.QR_WAITING: "请使用手机 TikTok 扫码...",
            LoginState.QR_SCANNED: "已扫码，等待手机确认...",
            LoginState.LOGIN_SUCCESS: "已登录",
            LoginState.LOGIN_FAILED: "登录失败",
            LoginState.TIMEOUT: "登录超时",
            LoginState.NOT_LOGGED_IN: "未登录",
        }.get(state, str(state))
        self.login_status_label.setText(f"状态：{state_text}")

    def _on_login_success(self):
        """登录成功回调（主线程）。"""
        self.login_status_label.setText("状态：已登录")
        self._append_login_log("登录成功！")
        # B3.4: 置位成功标志，snapshot 在 _on_login_worker_finished 执行
        # （此时 shutdown 可能未完成，Chrome 尚未释放 profile 锁）。
        self._login_succeeded = True

    def _on_login_failed(self, reason):
        """登录失败/超时/取消回调（主线程）。"""
        if "取消" in reason:
            self.login_status_label.setText("状态：未登录")
        self._append_login_log(f"登录失败：{reason}")
        # B3.4: 失败/取消时清零标志，避免 finished 误触发 snapshot。
        self._login_succeeded = False

    def _on_login_worker_finished(self):
        """Worker 结束后恢复按钮状态（主线程）。"""
        self.login_btn.setEnabled(True)
        self.login_btn.setText("扫码登录")
        self._login_worker = None
        # B3.4: shutdown() 已完成（Chrome 释放 profile 锁），可安全快照。
        if self._login_succeeded:
            result = snapshot_login_to_auth(
                log_callback=self._append_login_log
            )
            if result["success"]:
                self._append_login_log("登录态已同步至主页抓取 profile")
            else:
                self._append_login_log(
                    f"登录态同步失败：{result['error']}（主页将用匿名模式）"
                )
        self._login_succeeded = False

    def _append_login_log(self, msg):
        """追加一条登录日志。"""
        self.login_log.append(str(msg))

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

    def closeEvent(self, event):
        """窗口关闭处理。

        策略：
        - 无活动任务：直接关闭
        - 有解析任务：询问用户；取消则不关闭；确认则直接退出
          （解析无 DB 副作用需标记，进程退出终止 QThread，与 Phase 3.13 一致）
        - 有下载任务：询问用户；取消则不关闭；确认则先通知各 Worker 取消，
          再将进行中的任务标记为「下载失败」并立即关闭（不等待 Worker，
          进程退出会终止 QThread）。
        - 有登录任务：询问用户；取消则不关闭；确认则通知 LoginWorker 取消
          并有界等待（上限 8s）其执行 shutdown/Browser.close 优雅关闭
          Chrome（Profile 保留）；超时则随进程退出终止 QThread。
        - 有主页抓取任务：询问用户；取消则不关闭；确认则直接退出
          （依赖进程退出终止 QThread，与解析任务一致；HomeFetcher 启动的
          Chrome 子进程可能残留，留待后续 Phase 处理）。
        """
        # 先检查解析 Worker：与下载任务对称处理。
        parse_running = (
            self._parse_worker is not None
            and self._parse_worker.isRunning()
        )
        download_running = self.task_manager.running_count()
        download_waiting = self.task_manager.waiting_count()
        download_count = download_running + download_waiting
        login_running = (
            self._login_worker is not None
            and self._login_worker.isRunning()
        )
        # M5: 启动期 headless 登录态检查运行中（无需打扰用户，静默回收）。
        check_running = (
            self._login_check_worker is not None
            and self._login_check_worker.isRunning()
        )
        # B2.2-B: 主页抓取 Worker 运行中（依赖进程退出终止 QThread，与解析一致）。
        home_running = (
            self._home_worker is not None
            and self._home_worker.isRunning()
        )
        # C1 方案 B: 短链解析 Worker 运行中（依赖进程退出终止 QThread，与解析一致）。
        resolve_running = (
            self._resolve_worker is not None
            and self._resolve_worker.isRunning()
        )

        if not parse_running and not download_count and not login_running and not home_running and not resolve_running:
            if not check_running:
                event.accept()
                return
            # 仅 headless 登录态检查运行中：静默回收后直接退出（无副作用，不打扰用户）。
            try:
                self._login_check_worker.stop()
                self._login_check_worker.wait(3000)
            except Exception:
                pass
            event.accept()
            return

        # 拼提示文案：解析、下载与登录分别说明。
        msgs = []
        if parse_running:
            msgs.append("当前有解析任务正在进行中。\n退出将中断解析。")
        if download_count:
            detail = f"{download_running} 个下载中"
            if download_waiting:
                detail += f"、{download_waiting} 个排队中"
            msgs.append(
                f"当前有 {download_count} 个下载任务（{detail}）。\n"
                "退出将中断这些下载：下载中的标记为「下载失败」，排队中的标记为取消。"
            )
        if login_running:
            msgs.append("当前有 TikTok 登录会话正在进行中。\n退出将关闭浏览器（登录态保留）。")
        if home_running:
            msgs.append("当前有主页抓取任务正在进行中。\n退出将中断抓取。")
        if resolve_running:
            msgs.append("当前有短链解析任务正在进行中。\n退出将中断解析。")
        reply = QMessageBox.question(
            self, "确认退出",
            "\n\n".join(msgs) + "\n\n确定要退出吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            event.ignore()
            return

        # 下载任务统一委托 TaskManager 回收：排队任务标记取消；下载中任务
        # 同步把 works 标记为「下载失败」后请求 Worker 协作取消（不等待线程，
        # 进程退出终止 QThread，与 Phase 3.13 语义一致）。
        # ParseWorker 无 DB 副作用需标记，依赖进程退出终止。
        self.task_manager.shutdown()
        # M5: 静默回收启动期 headless 登录态检查的 Chrome（有界等待）。
        if check_running:
            try:
                self._login_check_worker.stop()
                self._login_check_worker.wait(3000)
            except Exception:
                pass

        # M3: 通知 LoginWorker 取消后有界等待，给 Worker 机会执行
        # TikTokLogin.shutdown() → Browser.close（优雅落盘 Profile）。
        # 典型耗时 ~5s（3s 轮询 sleep + ~2s 优雅关闭），上限 8s，不无限等待。
        if login_running:
            try:
                self._login_worker.cancel()
                self._login_worker.wait(8000)
            except Exception:
                pass
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
