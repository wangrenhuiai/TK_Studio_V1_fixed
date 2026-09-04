# -*- coding: utf-8 -*-
"""Phase 5-C1 parser_ex 单元测试。

覆盖方案 A（结构化 JSON 解析层）：
- SIGI_STATE / __UNIVERSAL_DATA__ / __NEXT_DATA__ 三种 JSON blob 提取
- JSON 字段路径解析（ItemModule / webapp.video-detail / props.pageProps）
- 正则兜底（无 JSON blob 时回退原 parser）
- 合并策略（JSON 优先，正则补充缺失）
- 字段一致性（与原 extract_tiktok_data 输出结构一致）

全部使用构造的 HTML 样本，不依赖真实 TikTok 网络。
"""
import sys
import os
import unittest
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.parser_ex import (
    extract_tiktok_data_ex,
    _extract_structured_json,
    _parse_from_structured,
    _find_item_module,
    _find_universal_item,
    _find_next_data_item,
    _fill_from_item,
    _merge,
)
from core.parser import extract_tiktok_data


def _make_item(author="testuser", desc="test title", cover="https://example.com/cover.jpg",
               play_addr="https://example.com/video.mp4", duration=12345,
               width=1080, height=1920):
    """构造 TikTok 视频 item dict。"""
    return {
        "author": {"uniqueId": author, "nickname": "Test User"},
        "desc": desc,
        "video": {
            "cover": cover,
            "originCover": cover,
            "playAddr": play_addr,
            "downloadAddr": "",
            "duration": duration,
            "width": width,
            "height": height,
        }
    }


def _make_sigi_html(item=None, meta_title="", meta_image="", meta_video=""):
    """构造含 SIGI_STATE 的 HTML。"""
    if item is None:
        item = _make_item()
    sigi = {"ItemModule": {"7681265056633326878": item}}
    sigi_json = json.dumps(sigi)
    html = f'<html><head>'
    if meta_title:
        html += f'<meta property="og:title" content="{meta_title}"/>'
    if meta_image:
        html += f'<meta property="og:image" content="{meta_image}"/>'
    if meta_video:
        html += f'<meta property="og:video" content="{meta_video}"/>'
    html += f'<script id="SIGI_STATE" type="application/json">{sigi_json}</script>'
    html += '</head><body></body></html>'
    return html


def _make_universal_html(item=None):
    """构造含 __UNIVERSAL_DATA_FOR_REHYDRATION__ 的 HTML。"""
    if item is None:
        item = _make_item()
    data = {
        "__DEFAULT_SCOPE__": {
            "webapp.video-detail": {
                "itemInfo": {"itemStruct": item}
            }
        }
    }
    data_json = json.dumps(data)
    return f'<html><head><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{data_json}</script></head></html>'


def _make_next_data_html(item=None):
    """构造含 __NEXT_DATA__ 的 HTML。"""
    if item is None:
        item = _make_item()
    data = {
        "props": {
            "pageProps": {
                "itemInfo": {"itemStruct": item}
            }
        }
    }
    data_json = json.dumps(data)
    return f'<html><head><script id="__NEXT_DATA__" type="application/json">{data_json}</script></head></html>'


def _make_meta_only_html(title="", image="", video=""):
    """构造仅含 meta 标签的 HTML（无 JSON blob）。"""
    html = '<html><head>'
    if title:
        html += f'<meta property="og:title" content="{title}"/>'
    if image:
        html += f'<meta property="og:image" content="{image}"/>'
    if video:
        html += f'<meta property="og:video" content="{video}"/>'
    html += '</head><body></body></html>'
    return html


class TestExtractStructuredJson(unittest.TestCase):
    """JSON blob 提取。"""

    def test_sigi_state(self):
        html = _make_sigi_html()
        data = _extract_structured_json(html)
        self.assertIsNotNone(data)
        self.assertIn("ItemModule", data)

    def test_universal_data(self):
        html = _make_universal_html()
        data = _extract_structured_json(html)
        self.assertIsNotNone(data)
        self.assertIn("__DEFAULT_SCOPE__", data)

    def test_next_data(self):
        html = _make_next_data_html()
        data = _extract_structured_json(html)
        self.assertIsNotNone(data)
        self.assertIn("props", data)

    def test_no_json_blob(self):
        html = _make_meta_only_html("title", "img", "vid")
        data = _extract_structured_json(html)
        self.assertIsNone(data)

    def test_invalid_json(self):
        html = '<script id="SIGI_STATE" type="application/json">{invalid json}</script>'
        data = _extract_structured_json(html)
        self.assertIsNone(data)

    def test_priority_universal_over_sigi(self):
        """UNIVERSAL_DATA 优先于 SIGI_STATE。"""
        item1 = _make_item(author="sigi_user")
        item2 = _make_item(author="universal_user")
        sigi = json.dumps({"ItemModule": {"123": item1}})
        universal = json.dumps({"__DEFAULT_SCOPE__": {"webapp.video-detail": {"itemInfo": {"itemStruct": item2}}}})
        html = (f'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{universal}</script>'
                f'<script id="SIGI_STATE" type="application/json">{sigi}</script>')
        data = _extract_structured_json(html)
        self.assertIn("__DEFAULT_SCOPE__", data)


class TestParseFromStructured(unittest.TestCase):
    """结构化 JSON 字段解析。"""

    def test_sigi_item_module(self):
        item = _make_item(author="sigi_author", desc="sigi title")
        data = {"ItemModule": {"123": item}}
        result = _parse_from_structured(data)
        self.assertEqual(result["author"], "sigi_author")
        self.assertEqual(result["title"], "sigi title")
        self.assertIn("cover.jpg", result["image"])
        self.assertIn("video.mp4", result["video_url"])
        self.assertEqual(result["duration"], "12345")
        self.assertEqual(result["resolution"], "1080x1920")

    def test_universal_item(self):
        item = _make_item(author="uni_author")
        data = {"__DEFAULT_SCOPE__": {"webapp.video-detail": {"itemInfo": {"itemStruct": item}}}}
        result = _parse_from_structured(data)
        self.assertEqual(result["author"], "uni_author")

    def test_next_data_item(self):
        item = _make_item(author="next_author")
        data = {"props": {"pageProps": {"itemInfo": {"itemStruct": item}}}}
        result = _parse_from_structured(data)
        self.assertEqual(result["author"], "next_author")

    def test_empty_data(self):
        result = _parse_from_structured({})
        self.assertEqual(result["author"], "")
        self.assertEqual(result["title"], "")

    def test_none_data(self):
        result = _parse_from_structured(None)
        self.assertEqual(result["author"], "")

    def test_no_item_module(self):
        result = _parse_from_structured({"OtherModule": {}})
        self.assertEqual(result["author"], "")


class TestFillFromItem(unittest.TestCase):
    """_fill_from_item 字段填充。"""

    def test_full_item(self):
        item = _make_item()
        result = {"author": "", "title": "", "image": "", "video_url": "", "duration": "", "resolution": ""}
        _fill_from_item(result, item)
        self.assertEqual(result["author"], "testuser")
        self.assertEqual(result["title"], "test title")
        self.assertEqual(result["duration"], "12345")
        self.assertEqual(result["resolution"], "1080x1920")

    def test_missing_video(self):
        item = {"author": {"uniqueId": "user"}, "desc": "title"}
        result = {"author": "", "title": "", "image": "", "video_url": "", "duration": "", "resolution": ""}
        _fill_from_item(result, item)
        self.assertEqual(result["author"], "user")
        self.assertEqual(result["title"], "title")
        self.assertEqual(result["video_url"], "")

    def test_author_as_string(self):
        item = {"author": "plain_string_author", "desc": ""}
        result = {"author": "", "title": "", "image": "", "video_url": "", "duration": "", "resolution": ""}
        _fill_from_item(result, item)
        self.assertEqual(result["author"], "plain_string_author")

    def test_duration_as_float(self):
        item = {"video": {"duration": 12.5, "width": 720, "height": 1280}}
        result = {"author": "", "title": "", "image": "", "video_url": "", "duration": "", "resolution": ""}
        _fill_from_item(result, item)
        self.assertEqual(result["duration"], "12.5")
        self.assertEqual(result["resolution"], "720x1280")


class TestMerge(unittest.TestCase):
    """合并策略。"""

    def test_json_supplements_missing_regex(self):
        """JSON 补充正则缺失字段。"""
        base = {"author": "", "title": "regex_title", "image": "", "video_url": "regex_url",
                "duration": "", "resolution": ""}
        structured = {"author": "json_author", "title": "json_title", "image": "json_img",
                      "video_url": "json_url", "duration": "100", "resolution": "1080x1920"}
        merged = _merge(base, structured)
        # 正则有值的保留，正则空的用 JSON 补充
        self.assertEqual(merged["author"], "json_author")  # 正则为空 → JSON 补充
        self.assertEqual(merged["title"], "regex_title")   # 正则有值 → 保留
        self.assertEqual(merged["image"], "json_img")      # 正则为空 → JSON 补充
        self.assertEqual(merged["video_url"], "regex_url") # 正则有值 → 保留
        self.assertEqual(merged["duration"], "100")        # 正则为空 → JSON 补充
        self.assertEqual(merged["resolution"], "1080x1920")  # 正则为空 → JSON 补充

    def test_both_empty(self):
        base = {"author": "", "title": "", "image": "", "video_url": "", "duration": "", "resolution": ""}
        structured = {"author": "", "title": "", "image": "", "video_url": "", "duration": "", "resolution": ""}
        merged = _merge(base, structured)
        self.assertEqual(merged["author"], "")


class TestExtractTiktokDataEx(unittest.TestCase):
    """端到端：extract_tiktok_data_ex。"""

    def test_sigi_html(self):
        """SIGI_STATE HTML 解析。"""
        html = _make_sigi_html()
        result = extract_tiktok_data_ex(html)
        self.assertEqual(result["author"], "testuser")
        self.assertEqual(result["title"], "test title")
        self.assertIn("cover.jpg", result["image"])
        self.assertIn("video.mp4", result["video_url"])
        self.assertEqual(result["duration"], "12345")
        self.assertEqual(result["resolution"], "1080x1920")

    def test_universal_html(self):
        """__UNIVERSAL_DATA__ HTML 解析。"""
        html = _make_universal_html()
        result = extract_tiktok_data_ex(html)
        self.assertEqual(result["author"], "testuser")
        self.assertIn("video.mp4", result["video_url"])

    def test_next_data_html(self):
        """__NEXT_DATA__ HTML 解析。"""
        html = _make_next_data_html()
        result = extract_tiktok_data_ex(html)
        self.assertEqual(result["author"], "testuser")

    def test_meta_only_fallback(self):
        """无 JSON blob 时回退正则。"""
        html = _make_meta_only_html("meta title", "https://img/cover.jpg", "https://vid/video.mp4")
        result = extract_tiktok_data_ex(html)
        self.assertEqual(result["title"], "meta title")
        self.assertIn("cover.jpg", result["image"])
        self.assertIn("video.mp4", result["video_url"])

    def test_empty_html(self):
        """空 HTML 不崩溃。"""
        result = extract_tiktok_data_ex("")
        self.assertEqual(result["author"], "")
        self.assertEqual(result["title"], "")

    def test_invalid_json_fallback_to_regex(self):
        """JSON 解析失败时回退正则。"""
        html = ('<meta property="og:title" content="fallback title"/>'
                '<script id="SIGI_STATE" type="application/json">{invalid}</script>')
        result = extract_tiktok_data_ex(html)
        self.assertEqual(result["title"], "fallback title")

    def test_field_consistency_with_original(self):
        """输出字段结构与原 parser 一致。"""
        html = _make_sigi_html()
        result_ex = extract_tiktok_data_ex(html)
        result_orig = extract_tiktok_data(_make_meta_only_html())
        # 字段集一致
        self.assertEqual(set(result_ex.keys()), set(result_orig.keys()))
        self.assertEqual(set(result_orig.keys()),
                         {"author", "title", "image", "video_url", "duration", "resolution"})

    def test_json_supplements_missing_meta(self):
        """meta 缺失字段时 JSON 补充。"""
        # meta 只有 title，无 image/video → JSON 补充
        html = _make_sigi_html(meta_title="meta title")
        result = extract_tiktok_data_ex(html)
        self.assertEqual(result["title"], "meta title")  # meta 优先
        self.assertIn("cover.jpg", result["image"])       # JSON 补充
        self.assertIn("video.mp4", result["video_url"])   # JSON 补充


if __name__ == "__main__":
    unittest.main()
