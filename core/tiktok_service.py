"""TikTok 单作品解析服务。

仅负责 TikTok 页面解析业务逻辑：URL 校验、video_id/author 提取、
requests 请求、parser 解析、Chrome fallback。不依赖 PySide6 / GUI / SQLite。
"""
import re

import requests

from core.parser import extract_tiktok_data
from core.chrome_bridge import load_with_chrome


_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def parse_url(url, log_callback=None):
    """解析单个 TikTok 作品 URL，返回结构化作品数据。

    返回字段：
        video_id, author, title, url, video_url, cover_url, duration, resolution
    """
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

    # 提取 video_id
    m = re.search(r"/video/(\d+)", url)
    result["video_id"] = m.group(1) if m else ""

    # 从 URL 提取 author
    m = re.search(r"tiktok\.com/@([^/?#]+)", url, re.I)
    if m:
        result["author"] = m.group(1)

    # requests 请求页面
    html = ""
    try:
        response = requests.get(
            url,
            headers=_HEADERS,
            timeout=20,
            allow_redirects=True,
        )
        if log_callback:
            log_callback(f"HTTP 状态：{response.status_code}")
        html = response.text

        data = extract_tiktok_data(html)
        result["author"] = data["author"] or result["author"]
        result["title"] = data["title"]
        result["cover_url"] = data["image"]
        result["video_url"] = data["video_url"]
        result["duration"] = data["duration"]
        result["resolution"] = data["resolution"]

        if log_callback:
            log_callback(
                f"requests解析：标题={'有' if result['title'] else '无'}，"
                f"封面={'有' if result['cover_url'] else '无'}，"
                f"视频地址={'有' if result['video_url'] else '无'}"
            )
    except Exception as e:
        if log_callback:
            log_callback(f"⚠️ requests 请求失败：{e}")

    # requests 拿不到数据时，用本机 Chrome 渲染后的 DOM 再解析
    if not result["title"] or not result["cover_url"] or not result["video_url"]:
        rendered = load_with_chrome(url, log_callback)
        if rendered:
            data = extract_tiktok_data(rendered)
            result["author"] = data["author"] or result["author"]
            result["title"] = data["title"] or result["title"]
            result["cover_url"] = data["image"] or result["cover_url"]
            result["video_url"] = data["video_url"] or result["video_url"]
            result["duration"] = data["duration"] or result["duration"]
            result["resolution"] = data["resolution"] or result["resolution"]

            if log_callback:
                log_callback(
                    f"Chrome解析：标题={'有' if result['title'] else '无'}，"
                    f"封面={'有' if result['cover_url'] else '无'}，"
                    f"视频地址={'有' if result['video_url'] else '无'}"
                )

    return result
