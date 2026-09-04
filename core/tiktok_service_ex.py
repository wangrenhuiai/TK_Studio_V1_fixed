"""TikTok 解析服务增强层（Phase 7-A + 7-B.2 + 7-F）。

在冻结的 ``core/tiktok_service.py`` 之上，新增结构化解析链路：

    parse_url_ex(url)
        ↓
    tiktok_request.fetch_tiktok_html(url)   ← C2 Retry(total=3)
        ↓
    parser_ex.extract_tiktok_data_ex(html)  ← C1 JSON + 正则
        ↓
    （字段缺失时）parser.extract_tiktok_data(html)  ← 复用已有 HTML，不重复 GET
        ↓
    （仍缺失时）chrome_bridge.chrome_render_with_cookies(url)  ← Phase 7-F: CDP fallback
        ↓
    结构化作品数据 + cookie_items（写入内存缓存供 download 使用）

Phase 7-B.2 改动：
- 消除 parser_ex 失败后 _original_parse_url 对同一 URL 的重复 requests.get
- 直接用 extract_tiktok_data(html) 复用已获取的 HTML
- Chrome fallback 逻辑内联，保持与 tiktok_service.parse_url 一致的行为

Phase 7-F 改动：
- Chrome fallback 从 load_with_chrome(--dump-dom) 改为 chrome_render_with_cookies(CDP)
- CDP 使用 chrome_login_profile（已登录态），同时获取 video_url + cookies
- 解析成功后将 cookie_items 写入 cookie_cache（纯内存），供 download 首次请求注入
- 不打印 / 不日志输出 cookie value

设计原则：
- 不修改冻结的 ``core/tiktok_service.py`` / ``core/parser.py``
- 保持 ``parse_url(url, log_callback)`` 签名完全兼容
- 解析优先级：parser_ex JSON → 原 parser.py（复用 HTML） → Chrome CDP fallback
- 已获取的 HTML 不允许为 legacy parser 再次 GET（Phase 7-B.2 约束保持）
- CDP fallback 不是 requests.get，不违反"一次初始 HTTP GET"约束
"""
import re

from core.tiktok_request import fetch_tiktok_html
from core.parser_ex import extract_tiktok_data_ex
from core.parser import extract_tiktok_data
from core.chrome_bridge import chrome_render_with_cookies
from core import cookie_cache


def parse_url_ex(url, log_callback=None):
    """增强解析：Retry + JSON Layer + 原 fallback。

    Args:
        url: TikTok 视频 URL（已通过短链解析）
        log_callback: 日志回调函数

    Returns:
        dict: 与 ``tiktok_service.parse_url`` 完全相同的字段结构：
            video_id, author, title, url, video_url, cover_url, duration, resolution
    """
    # 1. 提取 video_id / author（与原 parse_url 一致）
    result = {
        "video_id": "",
        "author": "",
        "title": "",
        "url": url,
        "video_url": "",
        "cover_url": "",
        "duration": "",
        "resolution": "",
    }

    m = re.search(r"/video/(\d+)", url)
    result["video_id"] = m.group(1) if m else ""

    m = re.search(r"tiktok\.com/@([^/?#]+)", url, re.I)
    if m:
        result["author"] = m.group(1)

    # 2. 用 C2 Retry Session 获取 HTML
    html = fetch_tiktok_html(url, log_callback=log_callback)

    if html:
        # 3. 用 C1 parser_ex 解析（JSON + 正则）
        data = extract_tiktok_data_ex(html)
        result["author"] = data["author"] or result["author"]
        result["title"] = data["title"]
        result["cover_url"] = data["image"]
        result["video_url"] = data["video_url"]
        result["duration"] = data["duration"]
        result["resolution"] = data["resolution"]

        if log_callback:
            log_callback(
                f"parser_ex解析：标题={'有' if result['title'] else '无'}，"
                f"封面={'有' if result['cover_url'] else '无'}，"
                f"视频地址={'有' if result['video_url'] else '无'}"
            )

        # 4. Phase 7-B.2: 复用已有 HTML，用原 parser.py 补充缺失字段（不重复 GET）
        if not result["title"] or not result["cover_url"] or not result["video_url"]:
            if log_callback:
                log_callback("字段缺失，复用已有 HTML 用原 parser 补充……")

            legacy_data = extract_tiktok_data(html)
            # 保守合并：只补充缺失字段，不覆盖已有值
            if not result["author"] and legacy_data["author"]:
                result["author"] = legacy_data["author"]
            if not result["title"] and legacy_data["title"]:
                result["title"] = legacy_data["title"]
            if not result["cover_url"] and legacy_data["image"]:
                result["cover_url"] = legacy_data["image"]
            if not result["video_url"] and legacy_data["video_url"]:
                result["video_url"] = legacy_data["video_url"]
            if not result["duration"] and legacy_data["duration"]:
                result["duration"] = legacy_data["duration"]
            if not result["resolution"] and legacy_data["resolution"]:
                result["resolution"] = legacy_data["resolution"]

            if log_callback:
                log_callback(
                    f"原 parser 复用 HTML：标题={'有' if result['title'] else '无'}，"
                    f"封面={'有' if result['cover_url'] else '无'}，"
                    f"视频地址={'有' if result['video_url'] else '无'}"
                )
    else:
        if log_callback:
            log_callback("⚠️ Retry 请求未获取 HTML")

    # Phase 7-F：cookie_items 初始化为空；CDP fallback 填充后写入 cookie_cache。
    cookie_items = []

    # 5. Chrome CDP fallback（Phase 7-F：改用 CDP 获取 video_url + cookies）
    #    保留：video_url 仍为空时触发。
    #    CDP 使用 chrome_login_profile（已登录态），不是 requests.get，不违反 7-B.2 约束。
    if not result["title"] or not result["cover_url"] or not result["video_url"]:
        if log_callback:
            log_callback("字段仍缺失，启用 Chrome CDP fallback……")

        rendered, cookie_items = chrome_render_with_cookies(
            url, log_callback=log_callback
        )
        if rendered:
            chrome_data = extract_tiktok_data(rendered)
            # 保守合并：只补充缺失字段，不覆盖已有值（与原 fallback 一致）
            if not result["author"] and chrome_data["author"]:
                result["author"] = chrome_data["author"]
            if not result["title"] and chrome_data["title"]:
                result["title"] = chrome_data["title"]
            if not result["cover_url"] and chrome_data["image"]:
                result["cover_url"] = chrome_data["image"]
            if not result["video_url"] and chrome_data["video_url"]:
                result["video_url"] = chrome_data["video_url"]
            if not result["duration"] and chrome_data["duration"]:
                result["duration"] = chrome_data["duration"]
            if not result["resolution"] and chrome_data["resolution"]:
                result["resolution"] = chrome_data["resolution"]

            if log_callback:
                log_callback(
                    f"Chrome解析：标题={'有' if result['title'] else '无'}，"
                    f"封面={'有' if result['cover_url'] else '无'}，"
                    f"视频地址={'有' if result['video_url'] else '无'}"
                )

    # Phase 7-F：解析成功且有 video_url 时，将 cookies 写入内存缓存
    # 供 download 首次请求注入（不打印 / 不日志 / 不写文件）
    if result["video_url"] and result["video_id"] and cookie_items:
        cookie_cache.set_cookie(result["video_id"], cookie_items)

    return result


# 兼容别名：ParseWorker import parse_url 时可无缝替换
parse_url = parse_url_ex

__all__ = ["parse_url_ex", "parse_url"]
