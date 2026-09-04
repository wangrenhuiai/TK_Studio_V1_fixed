# -*- coding: utf-8 -*-
"""Phase 5-C2 http_client + tiktok_request 测试。

覆盖 C2-B：
- Retry 配置存在（total=3, backoff=1, status_forcelist 429/5xx）
- 429 重试
- 5xx 重试
- fetch_tiktok_html 基本行为
- 网络失败返回空字符串
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.http_client import (
    create_retry_session,
    DEFAULT_TIMEOUT,
    DEFAULT_HEADERS,
    DEFAULT_USER_AGENT,
)
from core.tiktok_request import fetch_tiktok_html


class TestRetryConfig(unittest.TestCase):
    """Retry 配置存在。"""

    def test_create_retry_session_returns_session(self):
        session = create_retry_session()
        self.assertIsNotNone(session)
        session.close()

    def test_retry_total_is_3(self):
        session = create_retry_session()
        adapter = session.get_adapter("https://example.com")
        retry = adapter.max_retries
        self.assertEqual(retry.total, 3)
        session.close()

    def test_retry_backoff_is_1(self):
        session = create_retry_session()
        adapter = session.get_adapter("https://example.com")
        retry = adapter.max_retries
        self.assertEqual(retry.backoff_factor, 1)
        session.close()

    def test_retry_status_forcelist(self):
        session = create_retry_session()
        adapter = session.get_adapter("https://example.com")
        retry = adapter.max_retries
        forcelist = retry.status_forcelist
        self.assertIn(429, forcelist)
        self.assertIn(500, forcelist)
        self.assertIn(502, forcelist)
        self.assertIn(503, forcelist)
        self.assertIn(504, forcelist)
        session.close()

    def test_default_timeout_is_20(self):
        self.assertEqual(DEFAULT_TIMEOUT, 20)

    def test_session_has_default_headers(self):
        session = create_retry_session()
        self.assertEqual(session.headers["User-Agent"], DEFAULT_USER_AGENT)
        self.assertIn("Accept", session.headers)
        session.close()

    def test_session_mounted_http_and_https(self):
        session = create_retry_session()
        http_adapter = session.get_adapter("http://example.com")
        https_adapter = session.get_adapter("https://example.com")
        self.assertIsNotNone(http_adapter)
        self.assertIsNotNone(https_adapter)
        session.close()

    def test_custom_total(self):
        session = create_retry_session(total=5)
        adapter = session.get_adapter("https://example.com")
        retry = adapter.max_retries
        self.assertEqual(retry.total, 5)
        session.close()


class TestFetchTiktokHtml(unittest.TestCase):
    """fetch_tiktok_html 行为。"""

    @patch("core.tiktok_request.create_retry_session")
    def test_success_returns_html(self, mock_create):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html>TikTok content</html>"
        mock_session.get.return_value = mock_response
        mock_create.return_value = mock_session

        result = fetch_tiktok_html("https://www.tiktok.com/@user/video/123")
        self.assertEqual(result, "<html>TikTok content</html>")
        mock_session.get.assert_called_once()
        mock_session.close.assert_called_once()

    @patch("core.tiktok_request.create_retry_session")
    def test_non_200_returns_empty(self, mock_create):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_session.get.return_value = mock_response
        mock_create.return_value = mock_session

        result = fetch_tiktok_html("https://www.tiktok.com/@user/video/123")
        self.assertEqual(result, "")

    @patch("core.tiktok_request.create_retry_session")
    def test_network_error_returns_empty(self, mock_create):
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("Connection error")
        mock_create.return_value = mock_session

        result = fetch_tiktok_html("https://www.tiktok.com/@user/video/123")
        self.assertEqual(result, "")

    @patch("core.tiktok_request.create_retry_session")
    def test_log_callback_called(self, mock_create):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html></html>"
        mock_session.get.return_value = mock_response
        mock_create.return_value = mock_session

        logs = []
        fetch_tiktok_html("https://example.com", log_callback=logs.append)
        self.assertTrue(any("HTTP 状态" in msg for msg in logs))

    @patch("core.tiktok_request.create_retry_session")
    def test_custom_timeout(self, mock_create):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html></html>"
        mock_session.get.return_value = mock_response
        mock_create.return_value = mock_session

        fetch_tiktok_html("https://example.com", timeout=30)
        call_args = mock_session.get.call_args
        self.assertEqual(call_args.kwargs["timeout"], 30)

    @patch("core.tiktok_request.create_retry_session")
    def test_session_closed_on_success(self, mock_create):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html></html>"
        mock_session.get.return_value = mock_response
        mock_create.return_value = mock_session

        fetch_tiktok_html("https://example.com")
        mock_session.close.assert_called_once()

    @patch("core.tiktok_request.create_retry_session")
    def test_session_closed_on_error(self, mock_create):
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("error")
        mock_create.return_value = mock_session

        fetch_tiktok_html("https://example.com")
        mock_session.close.assert_called_once()


class TestRetryBehavior(unittest.TestCase):
    """Retry 行为验证（通过 urllib3 Retry 配置间接验证）。"""

    def test_429_in_forcelist(self):
        """429 触发重试。"""
        session = create_retry_session()
        adapter = session.get_adapter("https://example.com")
        retry = adapter.max_retries
        self.assertIn(429, retry.status_forcelist)
        session.close()

    def test_500_in_forcelist(self):
        """500 触发重试。"""
        session = create_retry_session()
        adapter = session.get_adapter("https://example.com")
        retry = adapter.max_retries
        self.assertIn(500, retry.status_forcelist)
        session.close()

    def test_502_in_forcelist(self):
        """502 触发重试。"""
        session = create_retry_session()
        adapter = session.get_adapter("https://example.com")
        retry = adapter.max_retries
        self.assertIn(502, retry.status_forcelist)
        session.close()

    def test_503_in_forcelist(self):
        """503 触发重试。"""
        session = create_retry_session()
        adapter = session.get_adapter("https://example.com")
        retry = adapter.max_retries
        self.assertIn(503, retry.status_forcelist)
        session.close()

    def test_504_in_forcelist(self):
        """504 触发重试。"""
        session = create_retry_session()
        adapter = session.get_adapter("https://example.com")
        retry = adapter.max_retries
        self.assertIn(504, retry.status_forcelist)
        session.close()

    def test_retry_connect_read_status_all_set(self):
        """connect/read/status retry 均配置。"""
        session = create_retry_session()
        adapter = session.get_adapter("https://example.com")
        retry = adapter.max_retries
        self.assertEqual(retry.connect, 3)
        self.assertEqual(retry.read, 3)
        self.assertEqual(retry.status, 3)
        session.close()


if __name__ == "__main__":
    unittest.main()
