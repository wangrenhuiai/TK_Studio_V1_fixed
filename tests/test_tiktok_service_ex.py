# -*- coding: utf-8 -*-
"""Phase 7-A + 7-B.2 测试：tiktok_service_ex 集成层。

验证：
1. parse_url_ex 签名兼容
2. Retry + parser_ex 链路
3. legacy parser 复用 HTML fallback（Phase 7-B.2：不再重复 GET）
4. Chrome fallback 保留
5. 字段补充逻辑（保守策略）
"""
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tiktok_service_ex import parse_url_ex, parse_url


# ─── 测试 fixture ──────────────────────────────────────────

_SAMPLE_HTML_WITH_JSON = """
<html>
<head>
<meta property="og:title" content="Test Video Title">
<meta property="og:image" content="https://example.com/cover.jpg">
</head>
<body>
<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">
{
  "__DEFAULT_SCOPE__": {
    "webapp.video-detail": {
      "itemInfo": {
        "itemStruct": {
          "author": {"uniqueId": "testuser"},
          "desc": "JSON Title",
          "video": {
            "cover": "https://example.com/json_cover.jpg",
            "playAddr": "https://example.com/video.mp4",
            "duration": 30000,
            "width": 1080,
            "height": 1920
          }
        }
      }
    }
  }
}
</script>
</body>
</html>
"""

_SAMPLE_HTML_EMPTY = "<html><body>No data</body></html>"

_EMPTY_PARSER_RESULT = {
    "author": "", "title": "",
    "image": "", "video_url": "",
    "duration": "", "resolution": ""
}


# ─── 测试 1：签名兼容 ─────────────────────────────────────

def test_parse_url_ex_callable():
    """parse_url_ex 可调用且签名兼容。"""
    assert callable(parse_url_ex)
    assert callable(parse_url)
    assert parse_url is parse_url_ex


def test_parse_url_ex_returns_dict():
    """parse_url_ex 返回 dict 且包含所有必需字段。"""
    with patch("core.tiktok_service_ex.fetch_tiktok_html", return_value=""):
        with patch("core.tiktok_service_ex.extract_tiktok_data",
                   return_value=_EMPTY_PARSER_RESULT):
            with patch("core.tiktok_service_ex.load_with_chrome", return_value=""):
                result = parse_url_ex("https://www.tiktok.com/@user/video/123")
                assert isinstance(result, dict)
                assert "video_id" in result
                assert "author" in result
                assert "title" in result
                assert "video_url" in result
                assert "cover_url" in result


# ─── 测试 2：Retry + parser_ex 链路 ────────────────────────

def test_retry_html_parsed_by_parser_ex():
    """Retry 获取的 HTML 由 parser_ex 解析。"""
    logs = []
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value=_SAMPLE_HTML_WITH_JSON):
        with patch("core.tiktok_service_ex.extract_tiktok_data") as mock_legacy:
            with patch("core.tiktok_service_ex.load_with_chrome") as mock_chrome:
                result = parse_url_ex(
                    "https://www.tiktok.com/@testuser/video/7681265056633326878",
                    log_callback=lambda msg: logs.append(msg)
                )
                # parser_ex 应从 JSON 提取字段
                assert result["author"] == "testuser"
                assert result["title"]  # 有标题
                assert result["video_url"]  # 有视频地址
                # legacy parser 不应被调用（字段完整）
                mock_legacy.assert_not_called()
                # Chrome 不应被调用（字段完整）
                mock_chrome.assert_not_called()
                # 日志应包含 parser_ex
                assert any("parser_ex" in log for log in logs)


def test_video_id_extraction():
    """video_id 从 URL 正确提取。"""
    with patch("core.tiktok_service_ex.fetch_tiktok_html", return_value=""):
        with patch("core.tiktok_service_ex.extract_tiktok_data",
                   return_value=_EMPTY_PARSER_RESULT):
            with patch("core.tiktok_service_ex.load_with_chrome", return_value=""):
                result = parse_url_ex(
                    "https://www.tiktok.com/@user/video/7681265056633326878"
                )
                assert result["video_id"] == "7681265056633326878"


def test_author_extraction_from_url():
    """author 从 URL @username 提取。"""
    with patch("core.tiktok_service_ex.fetch_tiktok_html", return_value=""):
        with patch("core.tiktok_service_ex.extract_tiktok_data",
                   return_value=_EMPTY_PARSER_RESULT):
            with patch("core.tiktok_service_ex.load_with_chrome", return_value=""):
                result = parse_url_ex(
                    "https://www.tiktok.com/@rfbxha/video/123"
                )
                assert result["author"] == "rfbxha"


# ─── 测试 3：legacy parser 复用 HTML fallback（Phase 7-B.2）──

def test_fallback_when_title_missing():
    """parser_ex 无 title 时 legacy parser 复用 HTML 补充。"""
    logs = []
    legacy_result = {
        "author": "fb_user", "title": "Fallback Title",
        "image": "fb_cover.jpg", "video_url": "fb_video_url",
        "duration": "10", "resolution": "1080x1920"
    }
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value=_SAMPLE_HTML_EMPTY):
        # parser_ex 返回空（无法提取）
        with patch("core.tiktok_service_ex.extract_tiktok_data_ex",
                   return_value=_EMPTY_PARSER_RESULT):
            # legacy parser 从同一 HTML 提取到数据
            with patch("core.tiktok_service_ex.extract_tiktok_data",
                       return_value=legacy_result) as mock_legacy:
                with patch("core.tiktok_service_ex.load_with_chrome") as mock_chrome:
                    result = parse_url_ex(
                        "https://www.tiktok.com/@user/video/123",
                        log_callback=lambda msg: logs.append(msg)
                    )
                    mock_legacy.assert_called_once()
                    assert result["title"] == "Fallback Title"
                    assert result["video_url"] == "fb_video_url"
                    # Chrome 不应触发（legacy parser 已补全）
                    mock_chrome.assert_not_called()
                    assert "复用" in " ".join(logs) or "parser" in " ".join(logs)


def test_fallback_when_video_url_missing():
    """parser_ex 无 video_url 时 legacy parser 复用 HTML 补充。"""
    html_no_video = (
        '<html><meta property="og:title" content="Has Title">'
        '<meta property="og:image" content="cover.jpg"></html>'
    )
    with patch("core.tiktok_service_ex.fetch_tiktok_html", return_value=html_no_video):
        # parser_ex 提取到 title 但无 video_url
        with patch("core.tiktok_service_ex.extract_tiktok_data_ex",
                   return_value={
                       "author": "", "title": "Has Title",
                       "image": "cover.jpg", "video_url": "",
                       "duration": "", "resolution": ""
                   }):
            # legacy parser 从同一 HTML 提取到 video_url
            with patch("core.tiktok_service_ex.extract_tiktok_data",
                       return_value={
                           "author": "", "title": "",
                           "image": "", "video_url": "fb_url",
                           "duration": "", "resolution": ""
                       }):
                with patch("core.tiktok_service_ex.load_with_chrome") as mock_chrome:
                    result = parse_url_ex("https://www.tiktok.com/@user/video/123")
                    assert result["video_url"] == "fb_url"
                    # Chrome 不应触发（legacy parser 已补全）
                    mock_chrome.assert_not_called()


# ─── 测试 4：保守补充策略 ──────────────────────────────────

def test_conservative_merge_does_not_overwrite():
    """legacy parser + Chrome fallback 不覆盖 parser_ex 已有值。"""
    html_with_title = (
        '<html><meta property="og:title" content="Original Title">'
        '<meta property="og:image" content="original_cover.jpg"></html>'
    )
    # parser_ex 提取到 title + cover，但无 video_url
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value=html_with_title):
        with patch("core.tiktok_service_ex.extract_tiktok_data_ex",
                   return_value={
                       "author": "", "title": "Original Title",
                       "image": "original_cover.jpg", "video_url": "",
                       "duration": "", "resolution": ""
                   }):
            # legacy parser 返回不同 title（不应覆盖）
            with patch("core.tiktok_service_ex.extract_tiktok_data",
                       return_value={
                           "author": "fb_user", "title": "FB Title",
                           "image": "fb_cover", "video_url": "fb_video",
                           "duration": "", "resolution": ""
                       }):
                result = parse_url_ex("https://www.tiktok.com/@user/video/123")
                # title 应保持 parser_ex 的值
                assert result["title"] == "Original Title"
                # video_url 应从 legacy parser 补充
                assert result["video_url"] == "fb_video"


def test_chrome_failure_does_not_crash():
    """Chrome fallback 失败（返回空）时不崩溃。"""
    logs = []
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value=_SAMPLE_HTML_EMPTY):
        with patch("core.tiktok_service_ex.extract_tiktok_data_ex",
                   return_value=_EMPTY_PARSER_RESULT):
            with patch("core.tiktok_service_ex.extract_tiktok_data",
                       return_value=_EMPTY_PARSER_RESULT):
                # Chrome 返回空（失败）
                with patch("core.tiktok_service_ex.load_with_chrome",
                           return_value=""):
                    result = parse_url_ex(
                        "https://www.tiktok.com/@user/video/123",
                        log_callback=lambda msg: logs.append(msg)
                    )
                    # 不崩溃，返回部分结果
                    assert isinstance(result, dict)
                    assert result["video_url"] == ""


# ─── 测试 5：空 HTML 处理 ──────────────────────────────────

def test_empty_html_triggers_chrome_fallback():
    """fetch_tiktok_html 返回空时直接触发 Chrome fallback（无重复 GET）。"""
    logs = []
    chrome_html = (
        '<html><meta property="og:title" content="Chrome Title">'
        '<meta property="og:video" content="chrome_video.mp4"></html>'
    )
    with patch("core.tiktok_service_ex.fetch_tiktok_html", return_value=""):
        with patch("core.tiktok_service_ex.load_with_chrome",
                   return_value=chrome_html) as mock_chrome:
            result = parse_url_ex(
                "https://www.tiktok.com/@user/video/123",
                log_callback=lambda msg: logs.append(msg)
            )
            mock_chrome.assert_called_once()
            assert "未获取" in " ".join(logs)
            assert result["video_url"] != ""


def test_invalid_url_no_crash():
    """非法 URL 不崩溃。"""
    with patch("core.tiktok_service_ex.fetch_tiktok_html", return_value=""):
        with patch("core.tiktok_service_ex.extract_tiktok_data",
                   return_value=_EMPTY_PARSER_RESULT):
            with patch("core.tiktok_service_ex.load_with_chrome", return_value=""):
                result = parse_url_ex("not_a_url")
                assert isinstance(result, dict)
