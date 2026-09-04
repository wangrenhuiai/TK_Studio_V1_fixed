# -*- coding: utf-8 -*-
"""Phase 7-F 回归测试：统一 Chrome Profile + 登录态 Cookie 链路。

验证要点：
1. chrome_render_with_cookies 使用 chrome_login_profile（而非 chrome_cdp_profile）
2. parse_url_ex 的 Chrome fallback 调用 chrome_render_with_cookies（CDP）
3. parse 成功后 cookie_items 写入 cookie_cache
4. downloader.run_download 首次请求前从 cookie_cache 取 cookies
5. Phase 7-B.2 约束保持：fetch_tiktok_html = 1（无重复 GET）
"""
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tiktok_service_ex import parse_url_ex
from core import cookie_cache


# ─── 测试 HTML 样本 ──────────────────────────────────────

_HTML_EMPTY = "<html><body>TikTok 风控/验证页</body></html>"

_HTML_CHROME_RENDERED = (
    '<html><head>'
    '<meta property="og:title" content="Chrome Title">'
    '<meta property="og:image" content="https://example.com/chrome_cover.jpg">'
    '<meta property="og:video" content="https://example.com/chrome_video.mp4">'
    '</head><body>rendered</body></html>'
)

_COOKIES = [
    {"name": "sessionid", "value": "secret_value", "domain": ".tiktok.com"},
    {"name": "sid_tt", "value": "another_secret", "domain": ".tiktok.com"},
]


# ─── 1. chrome_render_with_cookies 使用 chrome_login_profile ──

def test_chrome_uses_login_profile():
    """chrome_render_with_cookies 的 profile 路径应为 chrome_login_profile。"""
    import core.chrome_bridge as cb
    source = open(cb.__file__, encoding="utf-8").read()
    assert "chrome_login_profile" in source, "chrome_bridge 应使用 chrome_login_profile"
    # chrome_cdp_profile 不应再出现在 chrome_render_with_cookies 的 profile 赋值行
    # （load_with_chrome 仍用 chrome_headless_profile，不算违规）
    assert 'chrome_cdp_profile' not in source, \
        "chrome_cdp_profile 已废弃，应全部改为 chrome_login_profile"


# ─── 2. parse_url_ex Chrome fallback 使用 CDP ────────────

def test_parse_uses_cdp_fallback():
    """parse_url_ex 字段缺失时调用 chrome_render_with_cookies（CDP）。"""
    cookie_cache.clear_all()
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
                           # legacy parser → 空
                           {"author": "", "title": "",
                            "image": "", "video_url": "",
                            "duration": "", "resolution": ""},
                           # Chrome parser → 有数据
                           {"author": "chrome_user", "title": "Chrome Title",
                            "image": "chrome_cover.jpg",
                            "video_url": "chrome_video.mp4",
                            "duration": "60", "resolution": "720x1280"},
                       ]):
                with patch("core.tiktok_service_ex.chrome_render_with_cookies",
                           return_value=(_HTML_CHROME_RENDERED, _COOKIES)) as mock_cdp:
                    result = parse_url_ex(
                        "https://www.tiktok.com/@user/video/7681265056633326878"
                    )

    # CDP 被调用 1 次
    assert mock_cdp.call_count == 1, "chrome_render_with_cookies 应调用 1 次"
    # video_url 从 Chrome 获取
    assert "chrome_video.mp4" in result["video_url"]


# ─── 3. parse 成功后 cookies 写入 cookie_cache ─────────

def test_parse_writes_cookies_to_cache():
    """parse 成功后 cookie_items 应写入 cookie_cache（纯内存）。"""
    cookie_cache.clear_all()
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
                           {"author": "chrome_user", "title": "Chrome Title",
                            "image": "chrome_cover.jpg",
                            "video_url": "chrome_video.mp4",
                            "duration": "60", "resolution": "720x1280"},
                       ]):
                with patch("core.tiktok_service_ex.chrome_render_with_cookies",
                           return_value=(_HTML_CHROME_RENDERED, _COOKIES)):
                    result = parse_url_ex(
                        "https://www.tiktok.com/@user/video/7681265056633326878"
                    )

    # cookie_cache 应有 video_id → cookies
    cached = cookie_cache.get_cookie("7681265056633326878")
    assert cached == _COOKIES, "cookie_cache 应存储 parse 阶段获取的 cookies"


# ─── 4. parse 无 video_url 时不写 cookie_cache ──────────

def test_parse_no_video_url_no_cache():
    """parse 失败（无 video_url）时不写 cookie_cache。"""
    cookie_cache.clear_all()
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value=_HTML_EMPTY):
        with patch("core.tiktok_service_ex.extract_tiktok_data_ex",
                   return_value={
                       "author": "", "title": "",
                       "image": "", "video_url": "",
                       "duration": "", "resolution": ""
                   }):
            with patch("core.tiktok_service_ex.extract_tiktok_data",
                       return_value={
                           "author": "", "title": "",
                           "image": "", "video_url": "",
                           "duration": "", "resolution": ""
                       }):
                with patch("core.tiktok_service_ex.chrome_render_with_cookies",
                           return_value=("", [])):
                    result = parse_url_ex(
                        "https://www.tiktok.com/@user/video/7681265056633326878"
                    )

    # 无 video_url → 不写缓存
    assert result["video_url"] == ""
    assert cookie_cache.get_cookie("7681265056633326878") == []


# ─── 5. Phase 7-B.2 约束：fetch_tiktok_html = 1 ──────────

def test_single_get_constraint_maintained():
    """Phase 7-B.2: 一次解析仅一次初始 HTTP GET（CDP 不算 GET）。"""
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value=_HTML_EMPTY) as mock_fetch:
        with patch("core.tiktok_service_ex.extract_tiktok_data_ex",
                   return_value={
                       "author": "", "title": "",
                       "image": "", "video_url": "",
                       "duration": "", "resolution": ""
                   }):
            with patch("core.tiktok_service_ex.extract_tiktok_data",
                       return_value={
                           "author": "", "title": "",
                           "image": "", "video_url": "",
                           "duration": "", "resolution": ""
                       }):
                with patch("core.tiktok_service_ex.chrome_render_with_cookies",
                           return_value=("", [])):
                    parse_url_ex(
                        "https://www.tiktok.com/@user/video/123"
                    )

    assert mock_fetch.call_count == 1, "fetch_tiktok_html 应仅调用 1 次"


# ─── 6. downloader 从 cookie_cache 取 cookies ──────────

def test_downloader_reads_cookie_cache():
    """downloader.run_download 首次请求前从 cookie_cache 取 cookies。"""
    cookie_cache.clear_all()
    cookie_cache.set_cookie("999", _COOKIES)

    # mock DB
    mock_db = MagicMock()
    mock_db.connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (
        "999",       # video_id
        "author",    # author
        "title",     # title
        "https://www.tiktok.com/@user/video/999",  # page_url
        "https://example.com/video.mp4",  # stored_video_url
    )

    # mock requests session
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers.get.return_value = "video/mp4"
    mock_response.iter_content.return_value = [b"x" * 2048]

    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    with patch("builtins.open", MagicMock()):
        with patch("os.path.exists", return_value=False):
            with patch("os.path.getsize", return_value=0):
                with patch("os.replace"):
                    with patch("os.makedirs"):
                        from core.downloader import run_download
                        # Capture cookie_items passed to download_once
                        with patch("core.downloader.download_once") as mock_dl:
                            mock_dl.return_value = None  # success
                            run_download(
                                work_id=1,
                                video_url="https://example.com/video.mp4",
                                output_dir="/tmp/test",
                                db=mock_db,
                            )

    # download_once 应被调用，cookie_items 来自 cookie_cache（= _COOKIES）
    assert mock_dl.call_count >= 1
    call_kwargs = mock_dl.call_args
    # 第 5 个位置参数是 cookie_items
    cookie_items_arg = call_kwargs.args[4] if len(call_kwargs.args) > 4 else call_kwargs.kwargs.get("cookie_items")
    assert cookie_items_arg == _COOKIES, \
        "downloader 首次请求应从 cookie_cache 取 cookies"

    cookie_cache.clear_all()
