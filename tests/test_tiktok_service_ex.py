"""Phase 7-A 测试：tiktok_service_ex 集成层。

验证：
1. parse_url_ex 签名兼容
2. Retry + parser_ex 链路
3. fallback 到原 parse_url
4. 字段补充逻辑（保守策略）
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


# ─── 测试 1：签名兼容 ─────────────────────────────────────

def test_parse_url_ex_callable():
    """parse_url_ex 可调用且签名兼容。"""
    assert callable(parse_url_ex)
    assert callable(parse_url)
    assert parse_url is parse_url_ex


def test_parse_url_ex_returns_dict():
    """parse_url_ex 返回 dict 且包含所有必需字段。"""
    with patch("core.tiktok_service_ex.fetch_tiktok_html", return_value=""):
        with patch("core.tiktok_service_ex._original_parse_url", return_value={
            "video_id": "123", "author": "user", "title": "t",
            "url": "https://www.tiktok.com/@user/video/123",
            "video_url": "url", "cover_url": "cover", "duration": "10", "resolution": "1080x1920"
        }):
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
    with patch("core.tiktok_service_ex.fetch_tiktok_html", return_value=_SAMPLE_HTML_WITH_JSON):
        with patch("core.tiktok_service_ex._original_parse_url") as mock_fallback:
            result = parse_url_ex(
                "https://www.tiktok.com/@testuser/video/7681265056633326878",
                log_callback=lambda msg: logs.append(msg)
            )
            # parser_ex 应从 JSON 提取字段
            assert result["author"] == "testuser"
            assert result["title"]  # 有标题
            assert result["video_url"]  # 有视频地址
            # fallback 不应被调用（字段完整）
            mock_fallback.assert_not_called()
            # 日志应包含 parser_ex
            assert any("parser_ex" in log for log in logs)


def test_video_id_extraction():
    """video_id 从 URL 正确提取。"""
    with patch("core.tiktok_service_ex.fetch_tiktok_html", return_value=""):
        with patch("core.tiktok_service_ex._original_parse_url", return_value={
            "video_id": "", "author": "", "title": "", "url": "",
            "video_url": "", "cover_url": "", "duration": "", "resolution": ""
        }):
            result = parse_url_ex("https://www.tiktok.com/@user/video/7681265056633326878")
            assert result["video_id"] == "7681265056633326878"


def test_author_extraction_from_url():
    """author 从 URL @username 提取。"""
    with patch("core.tiktok_service_ex.fetch_tiktok_html", return_value=""):
        with patch("core.tiktok_service_ex._original_parse_url", return_value={
            "video_id": "", "author": "", "title": "", "url": "",
            "video_url": "", "cover_url": "", "duration": "", "resolution": ""
        }):
            result = parse_url_ex("https://www.tiktok.com/@rfbxha/video/123")
            assert result["author"] == "rfbxha"


# ─── 测试 3：fallback 到原 parse_url ───────────────────────

def test_fallback_when_title_missing():
    """parser_ex 无 title 时调用原 fallback。"""
    logs = []
    fallback_result = {
        "video_id": "123", "author": "fb_user", "title": "Fallback Title",
        "url": "https://www.tiktok.com/@user/video/123",
        "video_url": "fb_video_url", "cover_url": "fb_cover",
        "duration": "10", "resolution": "1080x1920"
    }
    with patch("core.tiktok_service_ex.fetch_tiktok_html", return_value=_SAMPLE_HTML_EMPTY):
        with patch("core.tiktok_service_ex._original_parse_url", return_value=fallback_result) as mock_fb:
            result = parse_url_ex(
                "https://www.tiktok.com/@user/video/123",
                log_callback=lambda msg: logs.append(msg)
            )
            mock_fb.assert_called_once()
            assert result["title"] == "Fallback Title"
            assert result["video_url"] == "fb_video_url"
            assert "fallback" in " ".join(logs).lower()


def test_fallback_when_video_url_missing():
    """parser_ex 无 video_url 时调用原 fallback。"""
    html_no_video = '<html><meta property="og:title" content="Has Title"><meta property="og:image" content="cover.jpg"></html>'
    with patch("core.tiktok_service_ex.fetch_tiktok_html", return_value=html_no_video):
        with patch("core.tiktok_service_ex._original_parse_url", return_value={
            "video_id": "", "author": "", "title": "", "url": "",
            "video_url": "fb_url", "cover_url": "", "duration": "", "resolution": ""
        }) as mock_fb:
            result = parse_url_ex("https://www.tiktok.com/@user/video/123")
            mock_fb.assert_called_once()
            assert result["video_url"] == "fb_url"


# ─── 测试 4：保守补充策略 ──────────────────────────────────

def test_conservative_merge_does_not_overwrite():
    """fallback 不覆盖 parser_ex 已有值。"""
    html_with_title = '<html><meta property="og:title" content="Original Title"><meta property="og:image" content="original_cover.jpg"></html>'
    # parser_ex 提取到 title + cover，但无 video_url
    # fallback 返回不同 title，不应覆盖
    with patch("core.tiktok_service_ex.fetch_tiktok_html", return_value=html_with_title):
        with patch("core.tiktok_service_ex._original_parse_url", return_value={
            "video_id": "123", "author": "fb_user", "title": "FB Title",
            "url": "", "video_url": "fb_video", "cover_url": "fb_cover",
            "duration": "", "resolution": ""
        }):
            result = parse_url_ex("https://www.tiktok.com/@user/video/123")
            # title 应保持 parser_ex 的值
            assert result["title"] == "Original Title"
            # video_url 应从 fallback 补充
            assert result["video_url"] == "fb_video"


def test_fallback_exception_does_not_crash():
    """原 fallback 抛异常时不崩溃。"""
    logs = []
    with patch("core.tiktok_service_ex.fetch_tiktok_html", return_value=_SAMPLE_HTML_EMPTY):
        with patch("core.tiktok_service_ex._original_parse_url", side_effect=RuntimeError("Chrome error")):
            result = parse_url_ex(
                "https://www.tiktok.com/@user/video/123",
                log_callback=lambda msg: logs.append(msg)
            )
            # 不崩溃，返回部分结果
            assert isinstance(result, dict)
            assert "fallback 失败" in " ".join(logs)


# ─── 测试 5：空 HTML 处理 ──────────────────────────────────

def test_empty_html_triggers_fallback():
    """fetch_tiktok_html 返回空时触发 fallback。"""
    logs = []
    with patch("core.tiktok_service_ex.fetch_tiktok_html", return_value=""):
        with patch("core.tiktok_service_ex._original_parse_url", return_value={
            "video_id": "123", "author": "u", "title": "t", "url": "",
            "video_url": "v", "cover_url": "c", "duration": "", "resolution": ""
        }) as mock_fb:
            result = parse_url_ex("https://www.tiktok.com/@user/video/123", log_callback=lambda msg: logs.append(msg))
            mock_fb.assert_called_once()
            assert "回退" in " ".join(logs)


def test_invalid_url_no_crash():
    """非法 URL 不崩溃。"""
    with patch("core.tiktok_service_ex.fetch_tiktok_html", return_value=""):
        with patch("core.tiktok_service_ex._original_parse_url", return_value={
            "video_id": "", "author": "", "title": "", "url": "",
            "video_url": "", "cover_url": "", "duration": "", "resolution": ""
        }):
            result = parse_url_ex("not_a_url")
            assert isinstance(result, dict)
