"""下载 Worker（Qt 线程层）。

DownloadWorker(QThread) 负责：
- 接收任务参数
- 调用 core.downloader.run_download 执行业务逻辑
- 通过 Qt Signal 向 GUI 报告 progress / finished_ok / failed

此模块是 core 与 GUI 之间的桥接层，core/downloader.py 不依赖 PySide6。
接口与原 TK_Studio_V1_6_4.py 中的 DownloadWorker 完全一致。
"""
from PySide6.QtCore import QThread, Signal

from core.downloader import run_download


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

    def run(self):
        self.video_url = run_download(
            self.work_id,
            self.video_url,
            self.output_dir,
            self.db,
            progress_cb=lambda p, s, m: self.progress.emit(p, s, m),
            finished_cb=lambda path: self.finished_ok.emit(path),
            failed_cb=lambda err: self.failed.emit(err),
        )
