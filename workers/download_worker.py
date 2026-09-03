"""下载 Worker。

负责：
1. 在线程中执行 core.downloader.run_download()
2. 将下载进度转发为 Qt Signal
3. 提供协作式取消
"""

from PySide6.QtCore import QThread, Signal

from core.downloader import run_download


class DownloadWorker(QThread):
    """单个作品下载线程。

    TaskManager 负责：
    - 队列
    - 并发限制
    - Worker 生命周期
    - 取消/关闭

    DownloadWorker 只负责执行一次下载。
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

        self._cancel_requested = False

    def cancel(self):
        """请求取消。

        不强杀线程，由 downloader 在请求/写入检查点主动退出。
        """
        self._cancel_requested = True

    def is_cancel_requested(self):
        return self._cancel_requested

    def _progress(self, percent, status, message):
        self.progress.emit(
            int(percent),
            str(status or ""),
            str(message or ""),
        )

    def _finished(self, path):
        self.finished_ok.emit(str(path))

    def _failed(self, error):
        self.failed.emit(str(error))

    def run(self):
        try:
            run_download(
                self.work_id,
                self.video_url,
                self.output_dir,
                self.db,
                progress_cb=self._progress,
                finished_cb=self._finished,
                failed_cb=self._failed,
                cancel_check=self.is_cancel_requested,
            )
        except Exception as e:
            # run_download 本身已经负责 failed_cb；
            # 这里只兜底处理线程层异常，避免异常直接逃出 QThread。
            self.failed.emit(str(e))