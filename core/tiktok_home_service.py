"""TikTok 主页服务层（Phase 5-B1.2）。

在 ``TikTokHomeFetcher``（B1.1 探测层）之上提供统一服务入口：

- 输入归一化：接受纯用户名 ``"tiktok"`` 或完整主页 URL
  ``"https://www.tiktok.com/@tiktok"``
- 统一返回结构：``{"success", "count", "videos", "error"}``
- 异常全部捕获，绝不向上抛出

职责边界（B1.2 服务层只读探测）：
- 封装 ``TikTokHomeFetcher``，自身不直接操作 Chrome / CDP
- 不访问数据库（不 import ``core.db``）
- 不调用 parser（不 import ``core.parser``）
- 不修改 ``TK_Studio_V1_6_4.py`` / ``downloader`` / ``db`` / ``parser``
- 不登录、不注入 Cookie、不存储
"""
import re

from core.tiktok_home_fetcher import TikTokHomeFetcher


# TikTok 用户名合法字符集：字母 / 数字 / 下划线 / 短横线 / 点
_USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9._-]+$')


class TikTokHomeService:
    """TikTok 主页作品 URL 只读探测服务。

    对外只暴露 :meth:`fetch_home`，统一返回结构化字典，捕获全部异常，
    调用方无需 try/except。
    """

    def __init__(self):
        # HomeFetcher 实例无内部状态（fetch 全部使用局部变量），
        # 可安全复用，避免每次调用重建。
        self._fetcher = TikTokHomeFetcher()

    def fetch_home(self, username_or_url, log_callback=None,
                   profile_dir=None):
        """获取 TikTok 用户主页的作品 URL 列表。

        Args:
            username_or_url: 纯用户名（如 ``"tiktok"``）或完整主页 URL
                （如 ``"https://www.tiktok.com/@tiktok"``）
            log_callback: 可选日志回调函数 ``Callable[[str], None]``
            profile_dir: 可选 Chrome user-data-dir 路径（默认 None 走匿名
                profile；认证模式由调用方传入）。透传给
                ``TikTokHomeFetcher.fetch``。

        Returns:
            dict: 始终返回以下结构，绝不抛异常::

                {
                    "success": bool,
                    "count": int,           # 成功时为视频数；失败时为 0
                    "videos": list[str],    # 成功时为 URL 列表；失败时为 []
                    "error": str | None,    # 失败原因；成功时为 None
                }
        """
        # 1. 输入归一化
        try:
            url = self._normalize_input(username_or_url)
        except ValueError as exc:
            return self._failure(f"输入无效: {exc}")

        # 2. 调用探测层
        try:
            videos = self._fetcher.fetch(
                url, log_callback=log_callback, profile_dir=profile_dir,
            )
        except Exception as exc:
            return self._failure(f"探测失败: {exc}")

        # 3. 防御性清洗：确保是字符串列表
        if not isinstance(videos, list):
            return self._failure(f"探测层返回非列表类型: {type(videos).__name__}")
        videos = [v for v in videos if isinstance(v, str)]

        return {
            "success": True,
            "count": len(videos),
            "videos": videos,
            "error": None,
        }

    @staticmethod
    def _normalize_input(username_or_url):
        """把用户名或 URL 归一化为完整主页 URL。

        - ``"tiktok"``                          -> ``https://www.tiktok.com/@tiktok``
        - ``"https://www.tiktok.com/@tiktok"``  -> 原样
        - ``"https://www.tiktok.com/@xxx"``     -> 原样

        Raises:
            ValueError: 输入为空 / 用户名含非法字符 / 不是 TikTok 主页 URL
        """
        if not username_or_url or not isinstance(username_or_url, str):
            raise ValueError("输入不能为空")

        value = username_or_url.strip()

        # 已是完整 TikTok 主页 URL
        if "tiktok.com/@" in value:
            return value

        # 纯用户名（不含 / 与空格）：校验合法字符后拼 URL
        if "/" not in value and " " not in value:
            if not _USERNAME_PATTERN.match(value):
                raise ValueError(f"用户名含非法字符: {value!r}")
            return f"https://www.tiktok.com/@{value}"

        # 其它形态（含 / 但非 tiktok 主页 URL，或含空格等）
        raise ValueError(f"不是有效的 TikTok 用户名或主页 URL: {value!r}")

    @staticmethod
    def _failure(message):
        """构造统一失败返回。"""
        return {
            "success": False,
            "count": 0,
            "videos": [],
            "error": message,
        }


__all__ = ["TikTokHomeService"]
