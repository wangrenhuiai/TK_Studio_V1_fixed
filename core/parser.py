"""TikTok 页面数据解析模块。

从 HTML 的 meta 标签和页面内嵌 JSON 中提取作品信息。
保持与 TK_Studio_V1_6_4.py 中 extract_tiktok_data / _clean_tiktok_value
完全一致的解析行为。
"""
import re
from html import unescape
from urllib.parse import unquote


def _clean_tiktok_value(value):
    if not value:
        return ""
    value = unquote(value)
    value = value.replace("\\u002F", "/").replace("\\/", "/")
    value = value.replace("&amp;", "&")
    # 安全处理剩余的 \uXXXX 转义序列。
    # 旧实现 bytes(value, "utf-8").decode("unicode_escape") 会把 UTF-8 多字节
    # 字符（如中文、emoji）拆成单字节再解码，导致乱码。
    # 改用正则只替换 \uXXXX 转义序列，不影响已解码的 Unicode 字符。
    value = re.sub(
        r'\\u([0-9a-fA-F]{4})',
        lambda m: chr(int(m.group(1), 16)),
        value
    )
    return value.strip()


def extract_tiktok_data(html):
    """从普通 HTML、meta 标签和 TikTok 页面内嵌 JSON 尽可能提取信息。"""

    result = {
        "author": "",
        "title": "",
        "image": "",
        "video_url": "",
        "duration": "",
        "resolution": ""
    }

    # meta 标签属性顺序并不固定，所以不再要求 property 必须出现在 content 前面。
    meta_pattern = re.compile(r"<meta\b[^>]*>", re.I | re.S)
    attr_pattern = re.compile(
        r'([:\w-]+)\s*=\s*["\'](.*?)["\']',
        re.I | re.S
    )

    for tag in meta_pattern.findall(html):
        attrs = {}
        for k, v in attr_pattern.findall(tag):
            attrs[k.lower()] = unescape(v)

        prop = attrs.get("property", "").lower()
        name = attrs.get("name", "").lower()
        content = attrs.get("content", "").strip()

        if prop in ("og:title", "twitter:title") or name == "twitter:title":
            if not result["title"]:
                result["title"] = content

        elif prop in ("og:image", "og:image:url", "twitter:image") or name == "twitter:image":
            if not result["image"]:
                result["image"] = content

        elif prop.startswith("og:video") or name in ("twitter:player:stream", "twitter:player"):
            if not result["video_url"]:
                result["video_url"] = content

    # TikTok 内嵌 JSON 常见字段。
    keys = {
        "author": ["uniqueId", "unique_id", "authorName"],
        "title": ["desc", "description"],
        "image": ["cover", "originCover", "dynamicCover"],
        "video_url": ["playAddr", "playApi", "downloadAddr"],
    }

    def find_json_string(key):
        patterns = [
            rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"',
            rf"'{re.escape(key)}'\s*:\s*'((?:\\.|[^'\\])*)'",
        ]
        for pat in patterns:
            m = re.search(pat, html, re.I | re.S)
            if m:
                return _clean_tiktok_value(m.group(1))
        return ""

    for key in keys["author"]:
        if not result["author"]:
            result["author"] = find_json_string(key)

    for key in keys["title"]:
        if not result["title"]:
            result["title"] = find_json_string(key)

    for key in keys["image"]:
        if not result["image"]:
            result["image"] = find_json_string(key)

    for key in keys["video_url"]:
        if not result["video_url"]:
            result["video_url"] = find_json_string(key)

    # 从 JSON 中补充 duration / width / height。
    for key in ("duration",):
        if not result["duration"]:
            m = re.search(rf'"{key}"\s*:\s*(\d+(?:\.\d+)?)', html, re.I)
            if m:
                result["duration"] = m.group(1)

    if not result["resolution"]:
        wm = re.search(r'"width"\s*:\s*(\d+)', html, re.I)
        hm = re.search(r'"height"\s*:\s*(\d+)', html, re.I)
        if wm and hm:
            result["resolution"] = f"{wm.group(1)}x{hm.group(1)}"

    return {k: _clean_tiktok_value(v) for k, v in result.items()}
