# -*- coding: utf-8 -*-
"""Phase 7-B.2 回归测试：消除重复 HTTP 请求。

核心验证：
    修改前：parser_ex 失败 → _original_parse_url → requests.get（重复 GET）
    修改后：parser_ex 失败 → extract_tiktok_data(html)（复用 HTML，无新 GET）

测试通过 mock 统计 HTTP GET call_count 和 Chrome call_count，
证明重复 GET 已消除。

Case 1: parser_ex 成功 → GET=1, Chrome=0
Case 2: parser_ex 不完整 → legacy parser 从同一 HTML 成功 → GET=1, Chrome=0
Case 3: parser_ex 不完整 + legacy 不完整 → Chrome 成功 → GET=1, Chrome=1
Case 4: 全部失败 → GET=1, Chrome=1, video_url=空, success=False
Case 5: HTTP 429 Retry → 不增加额外 requests
"""
import sys
import os
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tiktok_service_ex import parse_url_ex


# ─── 测试 HTML 样本 ──────────────────────────────────────

_HTML_FULL = (
    '<html><head>'
    '<meta property="og:title" content="Full Title">'
    '<meta property="og:image" content="https://example.com/cover.jpg">'
    '<meta property="og:video" content="https://example.com/video.mp4">'
    '</head><body>data</body></html>'
)

_HTML_EMPTY = "<html><body>TikTok 风控/验证页</body></html>"

_HTML_CHROME_RENDERED = (
    '<html><head>'
    '<meta property="og:title" content="Chrome Title">'
    '<meta property="og:image" content="https://example.com/chrome_cover.jpg">'
    '<meta property="og:video" content="https://example.com/chrome_video.mp4">'
    '</head><body>rendered</body></html>'
)


# ─── Case 1: parser_ex 成功 → GET=1, Chrome=0 ───────────

def test_case1_parser_ex_success_single_get():
    """Case 1: parser_ex 成功 → 仅 1 次 HTTP GET，0 次 Chrome。"""
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value=_HTML_FULL) as mock_fetch:
        with patch("core.tiktok_service_ex.extract_tiktok_data_ex",
                   return_value={
                       "author": "user", "title": "Title",
                       "image": "cover.jpg", "video_url": "video.mp4",
                       "duration": "30", "resolution": "1080x1920"
                   }):
            with patch("core.tiktok_service_ex.chrome_render_with_cookies") as mock_chrome:
                result = parse_url_ex(
                    "https://www.tiktok.com/@user/video/123"
                )

    # 验证结果
    assert result["video_url"] == "video.mp4"
    # 验证请求次数：fetch_tiktok_html 调用 1 次（内部 Retry 最多 4 次，但 1 次 session.get）
    assert mock_fetch.call_count == 1, "fetch_tiktok_html 应仅调用 1 次"
    # Chrome 不应触发
    mock_chrome.assert_not_called()


# ─── Case 2: parser_ex 不完整 → legacy parser 复用 HTML 成功 ───

def test_case2_legacy_reuses_html_no_duplicate_get():
    """Case 2（最重要）: parser_ex 不完整，legacy parser 从同一 HTML 成功。

    修改前：_original_parse_url 会再次 requests.get → GET=2
    修改后：extract_tiktok_data(html) 复用 HTML → GET=1
    """
    # parser_ex 返回空（风控页）
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value=_HTML_FULL) as mock_fetch:
        # parser_ex 返回不完整（video_url 为空）
        with patch("core.tiktok_service_ex.extract_tiktok_data_ex",
                   return_value={
                       "author": "", "title": "",
                       "image": "", "video_url": "",
                       "duration": "", "resolution": ""
                   }):
            # extract_tiktok_data（原 parser.py）从同一 HTML 提取到数据
            with patch("core.tiktok_service_ex.extract_tiktok_data",
                       return_value={
                           "author": "legacy_user", "title": "Legacy Title",
                           "image": "legacy_cover.jpg",
                           "video_url": "legacy_video.mp4",
                           "duration": "60", "resolution": "720x1280"
                       }) as mock_legacy_parser:
                with patch("core.tiktok_service_ex.chrome_render_with_cookies") as mock_chrome:
                    result = parse_url_ex(
                        "https://www.tiktok.com/@user/video/123"
                    )

    # legacy parser 从复用 HTML 提取到 video_url → 成功
    assert result["video_url"] == "legacy_video.mp4"
    assert result["title"] == "Legacy Title"
    # 验证：fetch_tiktok_html 仅 1 次（无重复 GET）
    assert mock_fetch.call_count == 1, "fetch_tiktok_html 应仅调用 1 次（消除重复 GET）"
    # legacy parser 被调用（复用 HTML）
    assert mock_legacy_parser.call_count == 1, "extract_tiktok_data 应被调用 1 次"
    # Chrome 不应触发（legacy parser 已补全）
    mock_chrome.assert_not_called()


# ─── Case 3: parser_ex + legacy 都失败 → Chrome 成功 ────

def test_case3_chrome_fallback_single_get():
    """Case 3: parser_ex + legacy 都失败 → Chrome 成功。

    修改前：GET=2（fetch + _original_parse_url）+ Chrome=1
    修改后：GET=1（fetch only）+ Chrome=1
    """
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value=_HTML_EMPTY) as mock_fetch:
        # parser_ex 返回空
        with patch("core.tiktok_service_ex.extract_tiktok_data_ex",
                   return_value={
                       "author": "", "title": "",
                       "image": "", "video_url": "",
                       "duration": "", "resolution": ""
                   }):
            # extract_tiktok_data 被调用 2 次：
            #   1st: legacy parser on _HTML_EMPTY → 空
            #   2nd: Chrome parser on _HTML_CHROME_RENDERED → Chrome 数据
            with patch("core.tiktok_service_ex.extract_tiktok_data",
                       side_effect=[
                           {"author": "", "title": "",
                            "image": "", "video_url": "",
                            "duration": "", "resolution": ""},
                           {"author": "chrome_user", "title": "Chrome Title",
                            "image": "chrome_cover.jpg",
                            "video_url": "chrome_video.mp4",
                            "duration": "60", "resolution": "720x1280"},
                       ]):
                # Chrome 渲染成功
                with patch("core.tiktok_service_ex.chrome_render_with_cookies",
                           return_value=(_HTML_CHROME_RENDERED, [])) as mock_chrome:
                    result = parse_url_ex(
                        "https://www.tiktok.com/@user/video/123"
                    )

    # Chrome fallback 成功
    assert result["video_url"] is not None and result["video_url"] != ""
    assert "chrome_video.mp4" in result["video_url"]
    # 验证：GET=1（仅 fetch_tiktok_html），无重复 GET
    assert mock_fetch.call_count == 1, "fetch_tiktok_html 应仅 1 次"
    # Chrome=1
    assert mock_chrome.call_count == 1, "Chrome 应调用 1 次"


# ─── Case 4: 全部失败 → GET=1, Chrome=1, 失败 ───────────

def test_case4_all_fail_no_duplicate_get():
    """Case 4: 全部失败 → GET=1, Chrome=1, video_url=空, success=False。"""
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value=_HTML_EMPTY) as mock_fetch:
        with patch("core.tiktok_service_ex.extract_tiktok_data_ex",
                   return_value={
                       "author": "", "title": "",
                       "image": "", "video_url": "",
                       "duration": "", "resolution": ""
                   }):
            # extract_tiktok_data: legacy 空 + Chrome 空（Chrome 返回空 HTML）
            with patch("core.tiktok_service_ex.extract_tiktok_data",
                       side_effect=[
                           {"author": "", "title": "",
                            "image": "", "video_url": "",
                            "duration": "", "resolution": ""},
                           {"author": "", "title": "",
                            "image": "", "video_url": "",
                            "duration": "", "resolution": ""},
                       ]):
                # Chrome 也失败（返回空）
                with patch("core.tiktok_service_ex.chrome_render_with_cookies",
                           return_value=("", [])) as mock_chrome:
                    result = parse_url_ex(
                        "https://www.tiktok.com/@user/video/123"
                    )

    # 最终失败
    assert result["video_url"] == ""
    success = bool(result["video_url"])
    assert success is False, "全部失败时必须判定为失败"
    # GET=1（无重复）
    assert mock_fetch.call_count == 1
    # Chrome=1
    assert mock_chrome.call_count == 1


# ─── Case 5: HTTP 429 Retry 不增加额外 requests ─────────

def test_case5_429_retry_no_extra_requests():
    """Case 5: fetch_tiktok_html 失败（Retry 耗尽）→ 不增加额外 requests。

    修改前：fetch 失败 → _original_parse_url 再 requests.get 1 次
    修改后：fetch 失败 → 直接 Chrome fallback，无额外 requests.get
    """
    # fetch_tiktok_html 返回空（Retry 耗尽或网络失败）
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value="") as mock_fetch:
        with patch("core.tiktok_service_ex.chrome_render_with_cookies",
                   return_value=(_HTML_CHROME_RENDERED, [])) as mock_chrome:
            result = parse_url_ex(
                "https://www.tiktok.com/@user/video/123"
            )

    # Chrome fallback 成功
    assert result["video_url"] != ""
    # fetch 仅 1 次
    assert mock_fetch.call_count == 1
    # Chrome=1（fetch 失败直接走 Chrome，不经过 parser_ex/legacy）
    assert mock_chrome.call_count == 1


# ─── Case 6: 保守合并 — 空值不覆盖有效值 ─────────────────

def test_conservative_merge_no_overwrite():
    """保守合并：parser_ex 有值时 legacy parser 不覆盖。"""
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value=_HTML_FULL):
        # parser_ex 提取到 video_url
        with patch("core.tiktok_service_ex.extract_tiktok_data_ex",
                   return_value={
                       "author": "ex_user", "title": "Ex Title",
                       "image": "ex_cover.jpg",
                       "video_url": "ex_video.mp4",
                       "duration": "30", "resolution": "1080x1920"
                   }):
            with patch("core.tiktok_service_ex.chrome_render_with_cookies") as mock_chrome:
                result = parse_url_ex(
                    "https://www.tiktok.com/@user/video/123"
                )

    # parser_ex 值应保留（不被覆盖）
    assert result["video_url"] == "ex_video.mp4"
    assert result["title"] == "Ex Title"
    # Chrome 不应触发（parser_ex 已完整）
    mock_chrome.assert_not_called()


# ─── Case 7: Chrome fallback 保守合并 ───────────────────

def test_chrome_conservative_merge():
    """Chrome fallback 保守合并：不覆盖已有值。"""
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value=_HTML_FULL):
        # parser_ex 有 title 但无 video_url
        with patch("core.tiktok_service_ex.extract_tiktok_data_ex",
                   return_value={
                       "author": "ex_user", "title": "Ex Title",
                       "image": "ex_cover.jpg",
                       "video_url": "",  # ← 缺失
                       "duration": "30", "resolution": "1080x1920"
                   }):
            # extract_tiktok_data: legacy 空 + Chrome 有数据
            with patch("core.tiktok_service_ex.extract_tiktok_data",
                       side_effect=[
                           # 1st: legacy parser → 空
                           {"author": "", "title": "",
                            "image": "", "video_url": "",
                            "duration": "", "resolution": ""},
                           # 2nd: Chrome parser → Chrome 数据（不同 title）
                           {"author": "chrome_user", "title": "Chrome Title",
                            "image": "chrome_cover.jpg",
                            "video_url": "chrome_video.mp4",
                            "duration": "60", "resolution": "720x1280"},
                       ]):
                with patch("core.tiktok_service_ex.chrome_render_with_cookies",
                           return_value=(_HTML_CHROME_RENDERED, [])):
                    result = parse_url_ex(
                        "https://www.tiktok.com/@user/video/123"
                    )

    # Chrome 补充 video_url
    assert "chrome_video.mp4" in result["video_url"]
    # parser_ex 的 title 应保留（Chrome 不覆盖已有值）
    assert result["title"] == "Ex Title"


# ─── Case 8: 无 _original_parse_url 调用 ─────────────────

def test_no_original_parse_url_called():
    """验证 parse_url_ex 不再调用 tiktok_service.parse_url（消除重复 GET 根因）。"""
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value=_HTML_EMPTY):
        with patch("core.tiktok_service_ex.extract_tiktok_data_ex",
                   return_value={
                       "author": "", "title": "",
                       "image": "", "video_url": "",
                       "duration": "", "resolution": ""
                   }):
            with patch("core.tiktok_service_ex.extract_tiktok_data",
                       side_effect=[
                           {"author": "", "title": "",
                            "image": "", "video_url": "",
                            "duration": "", "resolution": ""},
                           {"author": "", "title": "",
                            "image": "", "video_url": "",
                            "duration": "", "resolution": ""},
                       ]):
                with patch("core.tiktok_service_ex.chrome_render_with_cookies",
                           return_value=("", [])):
                    # mock tiktok_service.parse_url 确保不被调用
                    with patch("core.tiktok_service.parse_url") as mock_orig:
                        result = parse_url_ex(
                            "https://www.tiktok.com/@user/video/123"
                        )

    # _original_parse_url 不应被调用
    mock_orig.assert_not_called()
    assert result["video_url"] == ""
