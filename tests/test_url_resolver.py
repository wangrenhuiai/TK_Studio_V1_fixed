# -*- coding: utf-8 -*-
"""Phase 5-B4.3 url_resolver 单元测试（基础版）。

覆盖已实施项：P1（4 种短链格式）/ P2（HEAD+GET fallback）/ P4（normalize）/ P5（缓存）。
全部使用 mock，不依赖真实 TikTok 网络。

P6（并发）/ P7（ex 接口）/ P8（完整套件）暂缓，本文件后续阶段扩展。
"""
import sys
import os
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from core.url_resolver import (
    is_short_url,
    resolve_short_url,
    resolve_urls,
    normalize_video_url,
    clear_cache,
)


class TestIsShortUrl(unittest.TestCase):
    """P1: 短链格式识别（4 种）。"""

    def test_vm_tiktok_com(self):
        """1. vm.tiktok.com 短链识别。"""
        self.assertTrue(is_short_url("https://vm.tiktok.com/abc123/"))
        self.assertTrue(is_short_url("https://vm.tiktok.com/ZTUNyfkNF/"))

    def test_vt_tiktok_com(self):
        """2. vt.tiktok.com 短链识别。"""
        self.assertTrue(is_short_url("https://vt.tiktok.com/abc123/"))
        self.assertTrue(is_short_url("https://vt.tiktok.com/ZTUNyfkNF/"))

    def test_www_tiktok_t(self):
        """www.tiktok.com/t/ 短链识别。"""
        self.assertTrue(is_short_url("https://www.tiktok.com/t/abc123/"))

    def test_www_tiktok_tiktok_t(self):
        """www.tiktok.com/tiktok/t/ 短链识别。"""
        self.assertTrue(is_short_url("https://www.tiktok.com/tiktok/t/abc123/"))

    def test_normal_video_url_not_short(self):
        """3. 普通 video URL 不变化。"""
        url = "https://www.tiktok.com/@test/video/123456789"
        self.assertFalse(is_short_url(url))

    def test_illegal_not_short(self):
        """4. 非法 URL 不崩溃。"""
        for u in ["", None, "abc", 123, "https://example.com/page"]:
            self.assertFalse(is_short_url(u))


class TestResolveShortUrl(unittest.TestCase):
    """P2: resolve_short_url HEAD + GET fallback。"""

    def setUp(self):
        clear_cache()

    def test_normal_url_unchanged(self):
        """普通 video URL 不变化。"""
        url = "https://www.tiktok.com/@test/video/123456789"
        result = resolve_short_url(url)
        self.assertEqual(result, url)

    def test_illegal_url_no_crash(self):
        """非法 URL 不崩溃。"""
        for u in ["", None, "abc", 123]:
            result = resolve_short_url(u)
            self.assertEqual(result, u)

    @patch("core.url_resolver._build_session")
    def test_head_redirect_success(self, mock_build):
        """5. mock HEAD redirect 成功。"""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.url = "https://www.tiktok.com/@user/video/123"
        mock_session.head.return_value = mock_resp
        mock_build.return_value = mock_session

        result = resolve_short_url("https://vm.tiktok.com/abc123/")
        self.assertIn("/video/", result)
        mock_session.head.assert_called_once()
        mock_session.get.assert_not_called()

    @patch("core.url_resolver._build_session")
    def test_get_fallback_on_non_video_head(self, mock_build):
        """6a. GET fallback: HEAD 返回非 video URL → GET。"""
        mock_session = MagicMock()
        head_resp = MagicMock()
        head_resp.url = "https://www.tiktok.com/some/other/page"
        mock_session.head.return_value = head_resp
        get_resp = MagicMock()
        get_resp.url = "https://www.tiktok.com/@user/video/456"
        mock_session.get.return_value = get_resp
        mock_build.return_value = mock_session

        result = resolve_short_url("https://vm.tiktok.com/abc456/")
        self.assertIn("/video/", result)
        mock_session.get.assert_called_once()

    @patch("core.url_resolver._build_session")
    def test_get_fallback_on_head_exception(self, mock_build):
        """6b. GET fallback: HEAD 抛异常 → GET。"""
        mock_session = MagicMock()
        mock_session.head.side_effect = requests.ConnectionError("refused")
        get_resp = MagicMock()
        get_resp.url = "https://www.tiktok.com/@user/video/789"
        mock_session.get.return_value = get_resp
        mock_build.return_value = mock_session

        result = resolve_short_url("https://vt.tiktok.com/abc789/")
        self.assertIn("/video/", result)
        mock_session.get.assert_called_once()

    @patch("core.url_resolver._build_session")
    def test_timeout_returns_original(self, mock_build):
        """timeout 返回原 URL。"""
        mock_session = MagicMock()
        mock_session.head.side_effect = requests.Timeout("slow")
        mock_session.get.side_effect = requests.Timeout("slow")
        mock_build.return_value = mock_session

        url = "https://vm.tiktok.com/timeout1/"
        result = resolve_short_url(url)
        self.assertEqual(result, url)

    @patch("core.url_resolver._build_session")
    def test_non_video_returns_original(self, mock_build):
        """HEAD + GET 均非 video URL → 返回原 URL。"""
        mock_session = MagicMock()
        head_resp = MagicMock()
        head_resp.url = "https://www.tiktok.com/some/page"
        get_resp = MagicMock()
        get_resp.url = "https://www.tiktok.com/another/page"
        mock_session.head.return_value = head_resp
        mock_session.get.return_value = get_resp
        mock_build.return_value = mock_session

        url = "https://vm.tiktok.com/nonvideo/"
        result = resolve_short_url(url)
        self.assertEqual(result, url)


class TestNormalizeVideoUrl(unittest.TestCase):
    """P4: normalize_video_url。"""

    def test_strips_query(self):
        """9. normalize_video_url 剥离 query。"""
        url = "https://www.tiktok.com/@user/video/123?_r=1&_t=abc"
        result = normalize_video_url(url)
        self.assertEqual(result, "https://www.tiktok.com/@user/video/123")

    def test_strips_fragment(self):
        url = "https://www.tiktok.com/@user/video/123#section"
        result = normalize_video_url(url)
        self.assertEqual(result, "https://www.tiktok.com/@user/video/123")

    def test_no_query_unchanged(self):
        url = "https://www.tiktok.com/@user/video/123"
        self.assertEqual(normalize_video_url(url), url)

    def test_non_video_url_unchanged(self):
        url = "https://example.com/page"
        self.assertEqual(normalize_video_url(url), url)


class TestCache(unittest.TestCase):
    """P5: 缓存 TTL + LRU。"""

    def setUp(self):
        clear_cache()

    @patch("core.url_resolver._build_session")
    def test_cache_hit(self, mock_build):
        """7. cache 命中（第二次不构建 session）。"""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.url = "https://www.tiktok.com/@user/video/123"
        mock_session.head.return_value = mock_resp
        mock_build.return_value = mock_session

        url = "https://vm.tiktok.com/cacheTest/"
        r1 = resolve_short_url(url)
        self.assertIn("/video/", r1)

        r2 = resolve_short_url(url)
        self.assertEqual(r1, r2)
        # 第二次应命中缓存，不构建 session
        self.assertEqual(mock_build.call_count, 1)

    def test_cache_ttl_expiry(self):
        """缓存 TTL 过期后重新请求。"""
        from core.url_resolver import _cache_put, _cache_get
        import core.url_resolver as mod

        _cache_put("test_token", "https://www.tiktok.com/@u/video/1")
        # 未过期：命中
        self.assertIsNotNone(_cache_get("test_token"))

        # 模拟过期：写入一个过期的时间戳
        with mod._cache_lock:
            mod._cache["test_token"] = ("https://www.tiktok.com/@u/video/1",
                                        time.time() - mod._CACHE_TTL - 1)
        # 过期：未命中
        self.assertIsNone(_cache_get("test_token"))

    def test_cache_lru_eviction(self):
        """缓存 LRU 淘汰。"""
        from core.url_resolver import _cache_put, _cache_get
        import core.url_resolver as mod

        # 写入 _CACHE_MAX + 1 条，触发 LRU 淘汰
        for i in range(mod._CACHE_MAX + 1):
            _cache_put(f"token_{i}", f"https://www.tiktok.com/@u/video/{i}")

        # 第一条应被淘汰（LRU）
        self.assertIsNone(_cache_get("token_0"))
        # 最后一条应存在
        self.assertIsNotNone(_cache_get(f"token_{mod._CACHE_MAX}"))

    def test_clear_cache(self):
        from core.url_resolver import _cache_put, _cache_get
        _cache_put("abc", "https://www.tiktok.com/@u/video/1")
        self.assertIsNotNone(_cache_get("abc"))
        clear_cache()
        self.assertIsNone(_cache_get("abc"))


class TestResolveUrls(unittest.TestCase):
    """批量解析（串行，P6 暂缓）。"""

    def setUp(self):
        clear_cache()

    def test_empty_list(self):
        """8a. 空列表返回空。"""
        self.assertEqual(resolve_urls([]), [])

    @patch("core.url_resolver._build_session")
    def test_batch_resolve(self, mock_build):
        """8b. batch resolve 混合输入。"""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.url = "https://www.tiktok.com/@user/video/123"
        mock_session.head.return_value = mock_resp
        mock_build.return_value = mock_session

        urls = [
            "https://www.tiktok.com/@test/video/999",  # 非短链
            "https://vm.tiktok.com/short1/",            # 短链
            "https://vt.tiktok.com/short2/",            # 短链
            "https://www.tiktok.com/t/short3/",         # 短链
            "https://www.tiktok.com/tiktok/t/short4/",  # 短链
        ]
        results = resolve_urls(urls)

        self.assertEqual(len(results), 5)

        # 非短链不变
        self.assertFalse(results[0]["changed"])
        self.assertFalse(results[0]["success"])
        self.assertEqual(results[0]["resolved"], urls[0])

        # 短链全部解析成功
        for i in range(1, 5):
            self.assertTrue(results[i]["changed"])
            self.assertTrue(results[i]["success"])
            self.assertIn("/video/", results[i]["resolved"])

        # 返回格式兼容
        for r in results:
            self.assertIn("original", r)
            self.assertIn("resolved", r)
            self.assertIn("changed", r)
            self.assertIn("success", r)

    @patch("core.url_resolver._build_session")
    def test_batch_all_timeout(self, mock_build):
        """8c. 批量全部超时不崩溃。"""
        mock_session = MagicMock()
        mock_session.head.side_effect = requests.Timeout("slow")
        mock_session.get.side_effect = requests.Timeout("slow")
        mock_build.return_value = mock_session

        results = resolve_urls([
            "https://vm.tiktok.com/a/",
            "https://vt.tiktok.com/b/",
        ])
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertFalse(r["success"])
            self.assertFalse(r["changed"])


if __name__ == "__main__":
    unittest.main()
