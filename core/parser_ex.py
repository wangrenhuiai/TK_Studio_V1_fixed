"""TikTok 结构化 JSON 解析层（Phase 5-C1 方案 A）。

在 ``core/parser.py``（冻结）正则解析之上，新增结构化 JSON 解析能力，
提升 TikTok 页面结构变化时的解析鲁棒性。

设计原则：
- 不修改冻结的 ``core/parser.py``
- 优先从 TikTok 内嵌 JSON blob 提取结构化数据
- 正则兜底（回退到原 ``extract_tiktok_data``）
- 用结构化结果补充正则缺失字段
- 输出字段与原 parser 完全一致

TikTok 页面 JSON blob 来源（按优先级）：
1. ``<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">``
   — 新版页面主数据源
2. ``<script id="SIGI_STATE" type="application/json">``
   — 旧版页面主数据源
3. ``window.__NEXT_DATA__`` JSON
   — Next.js 框架数据

JSON 字段路径（TikTok 视频 ItemModule）：
    ItemModule.<video_id>.author.uniqueId      → author
    ItemModule.<video_id>.desc                 → title
    ItemModule.<video_id>.video.cover          → image
    ItemModule.<video_id>.video.playAddr       → video_url
    ItemModule.<video_id>.video.duration       → duration
    ItemModule.<video_id>.video.width/height   → resolution
"""
import json
import re

from core.parser import extract_tiktok_data


# ─── JSON blob 提取正则 ────────────────────────────────────

# TikTok 页面内嵌 JSON 的 script 标签（按优先级排序）
_JSON_BLOB_PATTERNS = [
    # 新版：__UNIVERSAL_DATA_FOR_REHYDRATION__
    re.compile(
        r'<script\s+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*type="application/json"[^>]*>(.*?)</script>',
        re.I | re.S
    ),
    # 旧版：SIGI_STATE
    re.compile(
        r'<script\s+id="SIGI_STATE"[^>]*type="application/json"[^>]*>(.*?)</script>',
        re.I | re.S
    ),
    # Next.js：__NEXT_DATA__
    re.compile(
        r'<script\s+id="__NEXT_DATA__"[^>]*type="application/json"[^>]*>(.*?)</script>',
        re.I | re.S
    ),
]


def extract_tiktok_data_ex(html):
    """增强解析：正则优先，JSON 补充缺失字段。

    流程：
        1. 执行原 ``extract_tiktok_data``（正则解析，始终执行）
        2. 尝试从 JSON blob 提取结构化数据
        3. 正则结果优先，JSON 只补充正则缺失的字段

    Args:
        html: TikTok 视频/主页页面 HTML

    Returns:
        dict: 与 ``extract_tiktok_data`` 相同的字段结构：
            author, title, image, video_url, duration, resolution
    """
    # 1. 原正则解析（始终执行，作为基础结果）
    base = extract_tiktok_data(html)

    # 2. 尝试结构化 JSON
    json_data = _extract_structured_json(html)

    # 3. 如果无 JSON blob，直接返回正则结果
    if not json_data:
        return base

    # 4. 从 JSON 提取结构化字段
    structured = _parse_from_structured(json_data)

    # 5. 合并：正则优先，JSON 只补充缺失字段
    return _merge(base, structured)


def _extract_structured_json(html):
    """从 HTML 提取 TikTok 内嵌 JSON blob。

    Returns:
        dict: 解析后的 JSON dict，或 None（未找到/解析失败）
    """
    for pattern in _JSON_BLOB_PATTERNS:
        match = pattern.search(html)
        if match:
            raw = match.group(1).strip()
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                # JSON 解析失败，尝试下一个 blob
                continue
    return None


def _parse_from_structured(data):
    """从 TikTok JSON blob 提取视频字段。

    支持 SIGI_STATE / __UNIVERSAL_DATA__ / __NEXT_DATA__ 三种结构。

    Returns:
        dict: author, title, image, video_url, duration, resolution
    """
    result = {
        "author": "",
        "title": "",
        "image": "",
        "video_url": "",
        "duration": "",
        "resolution": "",
    }

    if not data or not isinstance(data, dict):
        return result

    # 尝试不同的 JSON 结构路径
    # 1. SIGI_STATE: { ItemModule: { <video_id>: {...} } }
    item = _find_item_module(data)
    if item:
        _fill_from_item(result, item)
        return result

    # 2. __UNIVERSAL_DATA__: { __DEFAULT_SCOPE__: { "webapp.video-detail": { itemInfo: { itemStruct: {...} } } } }
    item = _find_universal_item(data)
    if item:
        _fill_from_item(result, item)
        return result

    # 3. __NEXT_DATA__: { props: { pageProps: { itemInfo: { itemStruct: {...} } } } }
    item = _find_next_data_item(data)
    if item:
        _fill_from_item(result, item)
        return result

    return result


def _find_item_module(data):
    """SIGI_STATE 结构：查找 ItemModule 中的第一个视频项。"""
    item_module = data.get("ItemModule")
    if not item_module or not isinstance(item_module, dict):
        return None
    # 取第一个视频项（ItemModule 以 video_id 为 key）
    for video_id, item in item_module.items():
        if isinstance(item, dict):
            return item
    return None


def _find_universal_item(data):
    """__UNIVERSAL_DATA__ 结构：查找 webapp.video-detail.itemInfo.itemStruct。"""
    scope = data.get("__DEFAULT_SCOPE__")
    if not scope or not isinstance(scope, dict):
        return None
    video_detail = scope.get("webapp.video-detail")
    if not video_detail or not isinstance(video_detail, dict):
        return None
    item_info = video_detail.get("itemInfo")
    if not item_info or not isinstance(item_info, dict):
        return None
    item_struct = item_info.get("itemStruct")
    if isinstance(item_struct, dict):
        return item_struct
    return None


def _find_next_data_item(data):
    """__NEXT_DATA__ 结构：查找 props.pageProps.itemInfo.itemStruct。"""
    props = data.get("props")
    if not props or not isinstance(props, dict):
        return None
    page_props = props.get("pageProps")
    if not page_props or not isinstance(page_props, dict):
        return None
    item_info = page_props.get("itemInfo")
    if not item_info or not isinstance(item_info, dict):
        return None
    item_struct = item_info.get("itemStruct")
    if isinstance(item_struct, dict):
        return item_struct
    return None


def _fill_from_item(result, item):
    """从单个视频 item dict 填充 result 字段。

    TikTok 视频 item 结构：
        {
            "author": {"uniqueId": "...", "nickname": "..."},
            "desc": "...",
            "video": {
                "cover": "...",
                "originCover": "...",
                "dynamicCover": "...",
                "playAddr": "...",
                "downloadAddr": "...",
                "duration": 12345,
                "width": 1080,
                "height": 1920
            }
        }
    """
    # author
    author = item.get("author")
    if isinstance(author, dict):
        result["author"] = (
            author.get("uniqueId")
            or author.get("unique_id")
            or author.get("nickname")
            or ""
        )
    elif isinstance(author, str):
        result["author"] = author

    # title (desc)
    result["title"] = item.get("desc") or item.get("description") or ""

    # video fields
    video = item.get("video")
    if isinstance(video, dict):
        result["image"] = (
            video.get("cover")
            or video.get("originCover")
            or video.get("dynamicCover")
            or ""
        )
        result["video_url"] = (
            video.get("playAddr")
            or video.get("playApi")
            or video.get("downloadAddr")
            or ""
        )
        # duration（TikTok JSON 中通常是整数毫秒）
        duration = video.get("duration")
        if duration is not None:
            result["duration"] = str(duration)
        # resolution
        width = video.get("width")
        height = video.get("height")
        if width and height:
            result["resolution"] = f"{width}x{height}"


def _merge(base, structured):
    """合并正则结果与结构化结果。

    规则：正则优先，JSON 只补充正则缺失字段。
    """
    merged = dict(base)  # 以正则结果为基础
    for key in ("author", "title", "image", "video_url", "duration", "resolution"):
        # 如果正则结果为空，用结构化结果补充
        if not merged.get(key) and structured.get(key):
            merged[key] = structured[key]
        # 如果结构化结果非空且与正则不同，优先用正则（保守策略）
        elif structured.get(key) and merged.get(key) != structured.get(key):
            # 正则有值就用正则，避免破坏现有行为
            pass
    return merged


# 别名：解决 C1 验收命名差异，提供 extract_json_data 入口
extract_json_data = extract_tiktok_data_ex

__all__ = ["extract_tiktok_data_ex", "extract_json_data"]
