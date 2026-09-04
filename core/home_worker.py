"""统一主页 Worker 层（Phase 5-B2.1）。

按 ``source`` 路由到对应来源的 source worker，对上游完全屏蔽来源差异，
统一返回内部结构。当前仅支持 TikTok；未知 source 返回失败结构。

调用链::

    HomeWorker.run(source, username_or_url, log_callback)
        |
        |  source == "tiktok"
        v
    TikTokHomeWorker.run(username_or_url, log_callback)   ← B1.4
        |
        v
    返回 {source, username, success, count, urls, error}

设计说明：
- 本模块取代了早期 B2-pending 的 QThread 版 HomeWorker（直接包 HomeFetcher，
  已备份至 data/probes/phase5_b2/home_worker.qthread_draft.py.bak）。
  新版改为复用 B1.x 完整链路（Fetcher→Service→Adapter→TikTokHomeWorker），
  通过 source 路由统一编排，符合 B2.1 职责。

职责边界（B2.1 统一 Worker 层）：
- 只负责 source 路由 + 编排 source workers
- 不直接操作 Chrome / CDP / websocket
- 不访问数据库（不 import ``core.db``）
- 不调用 parser（不 import ``core.parser``）
- 不 import ``downloader``
- 不登录、不注入 Cookie、不存储、不写文件、不做 UI 接线
- 永远不向上抛异常
"""
from core.tiktok_home_worker import TikTokHomeWorker


class HomeWorker:
    """统一主页探测 Worker：按 source 路由到具体 source worker。

    无状态编排器。任何异常都被捕获并转为失败结构返回，
    调用方无需 try/except。
    """

    def __init__(self):
        # 各来源的 source worker（当前仅 TikTok；新增来源时在此扩展）
        self.tiktok_worker = TikTokHomeWorker()

    def run(self, source, username_or_url, log_callback=None,
            profile_dir=None):
        """按 source 路由并执行主页探测。

        Args:
            source: 来源标识，当前仅支持 ``"tiktok"``
            username_or_url: 纯用户名或完整主页 URL
            log_callback: 可选日志回调函数 ``Callable[[str], None]``
            profile_dir: 可选 Chrome user-data-dir（默认 None 走匿名 profile；
                认证模式由调用方传入）。透传给对应 source worker。

        Returns:
            dict: 统一内部格式，**永不抛异常**::

                {
                    "source": str,        # 透传请求的 source（未知 source 也原样回填）
                    "username": str,
                    "success": bool,
                    "count": int,
                    "urls": list[str],
                    "error": str | None,
                }

            未知 source 或任何异常时返回失败结构::

                {
                    "source": "<请求的 source>",
                    "username": "",
                    "success": False,
                    "count": 0,
                    "urls": [],
                    "error": "<原因>",
                }
        """
        try:
            if source == "tiktok":
                return self.tiktok_worker.run(
                    username_or_url,
                    log_callback,
                    profile_dir=profile_dir,
                )
            # 未知 source：不调用任何 source worker
            return self._failure(source, f"不支持的 source: {source!r}")
        except Exception as exc:
            return self._failure(source, str(exc))

    @staticmethod
    def _failure(source, message):
        """构造统一失败返回（不抛异常）。"""
        return {
            "source": source if source is not None else "",
            "username": "",
            "success": False,
            "count": 0,
            "urls": [],
            "error": message,
        }


__all__ = ["HomeWorker"]
