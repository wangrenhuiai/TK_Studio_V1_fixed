"""主页抓取 QThread 包装层（Phase 5-B2.2-B）。

把同步的 ``HomeWorker``(B2.1) 移到 worker 线程执行，避免阻塞 UI。
完全镜像 ``ParseWorker`` 模式：MainWindow 直接持有 + 信号回主线程。

调用链::

    HomeFetchWorker.run()  (worker 线程)
        |
        v
    HomeWorker(B2.1).run(source, username_or_url, log_callback)   ← 未修改
        |
        v
    TikTokHomeWorker(B1.4) -> Service(B1.2) -> Adapter(B1.3)
        -> TikTokHomeFetcher(B1.1) -> HomeFetcher(B 基线)

职责边界（B2.2-B QThread 包装层）：
- 仅负责线程化 + 信号转换，不实现业务逻辑
- 业务逻辑委托 ``HomeWorker``(B2.1)
- 不 import ``core.db`` / ``core.parser`` / ``core.downloader``
- 不登录、不注入 Cookie、不存储、不写文件
- ``HomeWorker.run`` 永不抛异常（返回结构化 dict），本类把结果转为 Qt 信号
"""
from PySide6.QtCore import QThread, Signal

from core.home_worker import HomeWorker


class HomeFetchWorker(QThread):
    """主页抓取后台线程。

    逐个处理传入的主页 URL/用户名列表，每条抓取完成后发出信号。
    ``HomeWorker.run()`` 永不抛异常（返回结构化 dict），本类把成功/失败
    转为 Qt 信号回主线程；单条失败不中断后续抓取（逐条独立 emit）。
    """

    # 抓取成功：携带 HomeWorker 返回的完整 result dict
    # {source, username, success, count, urls, error}
    home_success = Signal(dict)

    # 抓取失败：携带 error 字符串
    home_failed = Signal(str)

    # 日志：携带日志消息
    log = Signal(str)

    def __init__(self, urls, source="tiktok", profile_dir=None):
        super().__init__()
        # urls: 已校验的主页 URL/用户名列表（至少 1 个）
        self.urls = urls
        self.source = source
        # Chrome user-data-dir（默认 None 走匿名 profile；认证模式由上游
        # UI 传入 chrome_home_auth_profile 等持久化目录复用登录态）。
        self.profile_dir = profile_dir

    def run(self):
        # HomeWorker 无内部状态，可复用同一个实例逐条处理。
        home = HomeWorker()
        total = len(self.urls)

        def log_cb(msg):
            # QThread 内 emit 信号走 queued 连接到主线程，线程安全。
            self.log.emit(str(msg))

        for index, url in enumerate(self.urls, 1):
            self.log.emit(f"[{index}/{total}] 开始抓取：{url}")
            try:
                result = home.run(
                    self.source, url, log_callback=log_cb,
                    profile_dir=self.profile_dir,
                )
            except Exception as exc:
                # 防御性：HomeWorker.run 本不应抛异常，此处兜底，不中断后续。
                self.home_failed.emit(str(exc))
                continue

            if result.get("success"):
                self.home_success.emit(result)
            else:
                self.home_failed.emit(
                    result.get("error") or "未知错误"
                )


__all__ = ["HomeFetchWorker"]
