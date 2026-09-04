"""单作品解析 Worker（Qt 线程层）。

ParseWorker(QThread) 负责：
- 接收待解析的 URL 列表
- 在后台线程依次调用 core.tiktok_service.parse_url 执行业务解析
- 调用 Database.add_work 写入作品库
- 通过 Qt Signal 向 GUI 报告 success / failed

此模块是 core 与 GUI 之间的桥接层，core/tiktok_service.py 不依赖 PySide6。
Worker 内部禁止任何 UI 操作，所有 UI 更新通过信号回到主线程。
"""
from PySide6.QtCore import QThread, Signal

from core.tiktok_service_ex import parse_url  # Phase 7-A: 增强解析链（Retry + JSON Layer + 原 fallback）


class ParseWorker(QThread):
    """TikTok 单作品后台解析器。

    逐个解析传入的 URL 列表，每个 URL 解析并入库后发出 success 信号，
    携带该作品的完整数据（含 work_id 与日志）。任一步骤抛出异常则发出
    failed 信号并终止后续解析。
    """
    success = Signal(dict)
    failed = Signal(str)

    def __init__(self, urls, db):
        super().__init__()
        # urls: 已校验的 TikTok 单作品 URL 列表（至少 1 个）
        self.urls = urls
        self.db = db

    def run(self):
        total = len(self.urls)
        for index, url in enumerate(self.urls, 1):
            logs = []
            try:
                data = parse_url(url, log_callback=lambda msg: logs.append(msg))

                video_id = data.get("video_id", "")
                author = data.get("author", "")
                title = data.get("title", "")
                cover_url = data.get("cover_url", "")
                video_url = data.get("video_url", "")
                duration = data.get("duration", "")
                resolution = data.get("resolution", "")

                work_id = self.db.add_work({
                    "video_id": video_id or url,
                    "author": author,
                    "title": title,
                    "url": url,
                    "video_url": video_url,
                    "cover_url": cover_url,
                    "duration": duration,
                    "resolution": resolution,
                })

                # 携带 work_id、日志与批次信息回主线程
                data["work_id"] = work_id
                data["logs"] = logs
                data["index"] = index
                data["total"] = total
                # Phase 7-A Final Acceptance: 显式成功标志，区分"URL 处理完成"与"解析成功"。
                # success signal 语义为"URL 处理完成（未抛异常）"，
                # 真正的成功判定以 video_url 是否有效为准（HTTP 200 ≠ 解析成功）。
                data["success"] = bool(video_url)
                self.success.emit(data)
            except Exception as e:
                self.failed.emit(str(e))
                return
