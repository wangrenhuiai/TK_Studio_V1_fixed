"""短链解析后台 Worker（Phase 5-C1 方案 B）。

把 ``resolve_short_url`` 从 ``parse_single`` 主线程同步调用移到后台 QThread，
避免批量短链输入时 UI 阻塞（B4.3 加 Retry 后最坏 60s/短链，N 个串行 = N×60s）。

完全镜像 ``ParseWorker`` 模式：MainWindow 直接持有 + 信号回主线程。

调用链::

    ResolveWorker.run()  (worker 线程)
        |
        v
    core.url_resolver.resolve_short_url(url, log_callback)   ← B4.3 已实现
        |
        v
    resolved_signal(url, resolved)  →  主线程逐条回调
        |
        v
    finished_signal(results)        →  主线程汇总后走 parse_single 后续校验

职责边界：
- 仅负责线程化 + 信号转换，不实现业务逻辑
- 业务逻辑委托 ``core.url_resolver``
- 不 import ``core.db`` / ``core.parser`` / ``core.downloader``
- 不写库、不调用 ParseWorker
- ``resolve_short_url`` 永不抛异常（失败返回原 URL），本类仍做 try/except 兜底
"""
from PySide6.QtCore import QThread, Signal

from core.url_resolver import is_short_url, resolve_short_url


class ResolveWorker(QThread):
    """TikTok 短链后台解析器。

    逐个解析传入的 URL 列表中的短链，每个 URL 解析后发出 ``resolved`` 信号，
    携带 (original, resolved) 元数据。全部完成后发出 ``finished_ok`` 信号，
    携带结构化结果列表（与 ``resolve_urls`` 返回格式兼容）。

    非短链 URL 原样透传（resolved == original）。
    """

    # 逐条解析完成：携带 dict {original, resolved, changed, success}
    resolved = Signal(dict)

    # 全部完成：携带 list[dict]
    finished_ok = Signal(list)

    # 日志：携带日志消息
    log = Signal(str)

    def __init__(self, urls):
        super().__init__()
        # urls: 待解析的 URL 列表（含短链与非短链，至少 1 个）
        self.urls = urls

    def run(self):
        results = []
        total = len(self.urls)

        for index, url in enumerate(self.urls, 1):
            if not url or not isinstance(url, str):
                item = {
                    "original": url,
                    "resolved": url,
                    "changed": False,
                    "success": False,
                }
                results.append(item)
                self.resolved.emit(item)
                continue

            was_short = is_short_url(url)
            if was_short:
                self.log.emit(f"[{index}/{total}] 正在解析短链：{url}")
            else:
                self.log.emit(f"[{index}/{total}] 非短链，跳过：{url}")

            try:
                resolved = resolve_short_url(
                    url, log_callback=lambda m: self.log.emit(str(m))
                )
            except Exception as e:
                # resolve_short_url 内部已兜底，此处防御性保护不中断后续。
                self.log.emit(f"⚠️ 短链解析异常：{e}，保留原 URL")
                resolved = url

            changed = (resolved != url)
            item = {
                "original": url,
                "resolved": resolved,
                "changed": changed,
                "success": was_short and changed,
            }
            results.append(item)
            self.resolved.emit(item)

        self.finished_ok.emit(results)


__all__ = ["ResolveWorker"]
