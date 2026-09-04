"""TikTok 主页作品 URL 只读探测模块（Phase 5-B1.1）。

对外别名入口：将已冻结的 B 阶段基线 ``core/home_fetcher.py::HomeFetcher``
以 ``TikTokHomeFetcher`` 名义重新导出，供 ``tests/tiktok_home_dom_probe.py``
及后续 B2 模块统一复用。

为什么不直接在 home_fetcher.py 上改类名？
- home_fetcher.py 已被项目记为 B 阶段 NEW BASELINE（含 B2 就绪增强：
  滚动参数 max_scrolls/initial_wait/scroll_wait、独立 profile_directory），
  直接改动会破坏已冻结基线与 HomeWorker 的引用。
- 本模块仅做“命名对外暴露”，不重复实现 CDP 逻辑，避免双份代码漂移。

设计原则（继承自 HomeFetcher，行为完全一致）：
- 通过 Chrome DevTools Protocol (CDP) 匿名访问 TikTok 用户主页
- 使用项目目录下独立 Chrome profile（累积 WAF cookie，不污染用户 Chrome）
- 自动滚动触发懒加载
- 从最终 DOM 提取 /video/{video_id} URL 列表

限制（B1.1 只读探测边界）：
- 不登录
- 不修改数据库（不调用 db）
- 不调用 parser
- 不影响生产代码（TK_Studio_V1_6_4.py / downloader / parser 均不修改）
"""
from core.home_fetcher import HomeFetcher


class TikTokHomeFetcher(HomeFetcher):
    """B1.1 对外暴露的 TikTok 主页作品 URL 探测器。

    继承自已冻结的 B 阶段基线 ``HomeFetcher``，未新增/覆盖任何方法，
    仅以用户要求的类名 ``TikTokHomeFetcher`` 提供导入入口。

    ``fetch()`` 行为与 ``HomeFetcher.fetch()`` 完全一致::

        fetch(url, log_callback=None,
              max_scrolls=3, initial_wait=15, scroll_wait=8) -> list[str]

    返回去重后保持首次出现顺序的 video URL 列表；URL 无效或 Chrome/CDP
    失败时分别抛出 ``ValueError`` / ``RuntimeError``。
    """


__all__ = ["TikTokHomeFetcher"]
