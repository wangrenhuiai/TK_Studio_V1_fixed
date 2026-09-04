"""TikTok 主页数据适配层（Phase 5-B1.3）。

将 :class:`TikTokHomeService` 返回的服务结构转换为统一内部格式，
便于后续 UI / Worker / Storage 层无差别消费，屏蔽上游字段差异。

输入（``TikTokHomeService.fetch_home()`` 返回）::

    {"success": bool, "count": int, "videos": list[str], "error": str | None}

输出（统一内部格式）::

    {
        "source":   "tiktok",          # 固定来源标识
        "username": str,               # 显式传入或从 URL 自动提取
        "success":  bool,              # 透传
        "count":    int,                # 由 urls 实际长度派生，不信任输入 count
        "urls":     list[str],         # 清洗后的视频 URL 列表
        "error":    str | None,        # 透传
    }

设计要点：
- ``count`` 由 ``len(urls)`` 派生（输入 count 可能与 videos 长度不一致，
  以实际数据为准）。
- ``username`` 为 None 时从首个视频 URL 的 ``@用户名`` 自动提取，
  无法提取则置空字符串。
- 纯数据转换，无 I/O；异常全部捕获，永远返回结构。

职责边界（B1.3 适配层）：
- 不操作 Chrome / CDP / websocket
- 不访问数据库（不 import ``core.db``）
- 不调用 parser（不 import ``core.parser``）
- 不修改 ``TK_Studio_V1_6_4.py`` / ``downloader`` / ``db`` / ``parser``
  / ``workers/task_manager.py`` / ``tiktok_home_fetcher.py`` / ``tiktok_home_service.py``
- 不登录、不注入 Cookie、不存储
"""
import re

# 从视频 URL 提取用户名：https://www.tiktok.com/@用户名/video/{id}
_USERNAME_FROM_URL_PATTERN = re.compile(r'tiktok\.com/@([\w.-]+)/video')


class TikTokHomeAdapter:
    """TikTok 主页服务结果 → 统一内部格式的数据适配器。

    无状态、纯函数式转换；任何异常都被捕获并转为失败结构返回。
    """

    SOURCE = "tiktok"

    def adapt(self, service_result, username=None):
        """把 service 返回转换为统一内部格式。

        Args:
            service_result: ``TikTokHomeService.fetch_home()`` 返回的 dict。
                允许为 None / 非 dict / 缺字段，适配器都会安全处理。
            username: 可选用户名；为 None 或空时从视频 URL 自动提取。

        Returns:
            dict: 统一内部格式，**永不抛异常**::

                {
                    "source": "tiktok",
                    "username": str,
                    "success": bool,
                    "count": int,           # len(urls)
                    "urls": list[str],
                    "error": str | None,
                }
        """
        try:
            # 1. 输入防御：必须为 dict
            if not isinstance(service_result, dict):
                return self._failure(username, "service_result 不是 dict")

            success = bool(service_result.get("success", False))
            error = service_result.get("error")
            if error is not None and not isinstance(error, str):
                error = str(error)

            # 2. 清洗 urls（来自 videos 字段，仅保留字符串元素）
            videos = service_result.get("videos")
            if not isinstance(videos, list):
                videos = []
            urls = [u for u in videos if isinstance(u, str)]

            # 3. 用户名：显式传入优先；否则从首个可解析的视频 URL 提取
            user = username
            if (user is None or not str(user).strip()) and urls:
                for u in urls:
                    m = _USERNAME_FROM_URL_PATTERN.search(u)
                    if m:
                        user = m.group(1)
                        break

            # 4. count 由实际 urls 长度派生（不信任输入 count 字段）
            count = len(urls)

            return {
                "source": self.SOURCE,
                "username": user if user is not None else "",
                "success": success,
                "count": count,
                "urls": urls,
                "error": error if error is not None else None,
            }
        except Exception as exc:
            return self._failure(username, f"适配异常: {exc}")

    @staticmethod
    def _failure(username, message):
        """构造统一失败返回（不抛异常）。"""
        return {
            "source": "tiktok",
            "username": username if username is not None else "",
            "success": False,
            "count": 0,
            "urls": [],
            "error": message,
        }


__all__ = ["TikTokHomeAdapter"]
