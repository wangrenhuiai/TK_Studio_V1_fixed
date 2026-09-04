"""TikTok 主页 Worker 层（Phase 5-B1.4）。

后台任务编排层：按调用链 ``Service → Adapter`` 串联，
对上游完全屏蔽 TikTok 探测细节，统一返回内部结构。

调用链::

    TikTokHomeWorker.run(username_or_url, log_callback)
        |
        v
    TikTokHomeService.fetch_home()   # 返回 {success, count, videos, error}
        |
        v
    TikTokHomeAdapter.adapt()         # 转换为统一内部格式
        |
        v
    返回 {source, username, success, count, urls, error}

职责边界（B1.4 Worker 层）：
- 只负责 Service + Adapter 编排
- 不直接操作 Chrome / CDP / websocket
- 不访问数据库（不 import ``core.db``）
- 不调用 parser（不 import ``core.parser``）
- 不 import ``downloader``
- 不登录、不注入 Cookie、不存储、不写文件、不做 UI 接线
- 永远不向上抛异常
"""
from core.tiktok_home_service import TikTokHomeService
from core.tiktok_home_adapter import TikTokHomeAdapter


class TikTokHomeWorker:
    """TikTok 主页后台任务编排 Worker。

    无状态编排器：组合 ``TikTokHomeService`` + ``TikTokHomeAdapter``，
    统一返回内部结构。任何异常都被捕获并转为失败结构返回。
    """

    def __init__(self):
        # Service / Adapter 实例均无内部状态，可安全复用
        self.service = TikTokHomeService()
        self.adapter = TikTokHomeAdapter()

    def run(self, username_or_url, log_callback=None, profile_dir=None):
        """执行主页探测编排：Service → Adapter。

        Args:
            username_or_url: 纯用户名（如 ``"tiktok"``）或完整主页 URL
                （如 ``"https://www.tiktok.com/@tiktok"``）
            log_callback: 可选日志回调函数 ``Callable[[str], None]``
            profile_dir: 可选 Chrome user-data-dir（默认 None 走匿名 profile；
                认证模式由调用方传入）。透传给 ``TikTokHomeService.fetch_home``。

        Returns:
            dict: 统一内部格式，**永不抛异常**::

                {
                    "source": "tiktok",
                    "username": str,     # Adapter 从 URL 自动提取
                    "success": bool,
                    "count": int,        # len(urls)
                    "urls": list[str],
                    "error": str | None,
                }

            任何异常都会被捕获，返回::

                {
                    "source": "tiktok",
                    "username": "",
                    "success": False,
                    "count": 0,
                    "urls": [],
                    "error": "<异常信息>",
                }
        """
        try:
            service_result = self.service.fetch_home(
                username_or_url,
                log_callback,
                profile_dir=profile_dir,
            )
            return self.adapter.adapt(service_result)
        except Exception as exc:
            return {
                "source": "tiktok",
                "username": "",
                "success": False,
                "count": 0,
                "urls": [],
                "error": str(exc),
            }


__all__ = ["TikTokHomeWorker"]
