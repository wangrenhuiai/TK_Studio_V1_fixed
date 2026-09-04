"""TikTok 解析服务增强层（Phase 7-A）。

在冻结的 ``core/tiktok_service.py`` 之上，新增结构化解析链路：

    parse_url_ex(url)
        ↓
    tiktok_request.fetch_tiktok_html(url)   ← C2 Retry(total=3)
        ↓
    parser_ex.extract_tiktok_data_ex(html)  ← C1 JSON + 正则
        ↓
    （字段缺失时）tiktok_service.parse_url(url)  ← 原 fallback（含 Chrome）
        ↓
    结构化作品数据

设计原则：
- 不修改冻结的 ``core/tiktok_service.py`` / ``core/parser.py``
- 保持 ``parse_url(url, log_callback)`` 签名完全兼容
- 解析优先级：parser_ex JSON → 原 parser.py → Chrome fallback
- 原 ``tiktok_service.parse_url`` 作为最终 fallback，保证不退化
"""
import re

from core.tiktok_request import fetch_tiktok_html
from core.parser_ex import extract_tiktok_data_ex
from core.tiktok_service import parse_url as _original_parse_url


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
    else:
        if log_callback:
            log_callback("⚠️ Retry 请求未获取 HTML，回退到原解析链")

    # 4. 如果 parser_ex 结果不完整，调用原 parse_url（含 Chrome fallback）
    if not result["title"] or not result["cover_url"] or not result["video_url"]:
        if log_callback:
            log_callback("字段缺失，启用原解析链 fallback……")

        try:
            fallback = _original_parse_url(url, log_callback=log_callback)
            # 只补充缺失字段（保守策略，不覆盖已有值）
            for key in ("author", "title", "cover_url", "video_url", "duration", "resolution", "video_id"):
                if not result.get(key) and fallback.get(key):
                    result[key] = fallback[key]
        except Exception as e:
            if log_callback:
                log_callback(f"⚠️ 原 fallback 失败：{e}")

    return result


# 兼容别名：ParseWorker import parse_url 时可无缝替换
parse_url = parse_url_ex

__all__ = ["parse_url_ex", "parse_url"]
