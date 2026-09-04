"""TikTok 页面请求层（Phase 5-C2 方案 B）。

提供带 Retry 的 TikTok HTML 获取能力，作为冻结模块
``core/tiktok_service.py`` 的增强替代。

调用链::

    fetch_tiktok_html(url)
        |
        v
    http_client.create_retry_session()   ← Retry(total=3, backoff=1)
        |
        v
    session.get(url, timeout=20)
        |
        v
    response.text  →  供 parser_ex 解析

职责边界：
- 仅负责 HTTP 请求 + Retry，不解析 HTML
- 不修改冻结的 ``core/tiktok_service.py``
- 不依赖 PySide6 / GUI / SQLite
- 网络失败返回空字符串（不抛异常到调用方）
"""
from core.http_client import create_retry_session, DEFAULT_TIMEOUT


def fetch_tiktok_html(url, timeout=None, log_callback=None):
    """获取 TikTok 页面 HTML（带 Retry）。

    Args:
        url: TikTok 视频 URL
        timeout: 超时秒数（默认 None → 使用 http_client.DEFAULT_TIMEOUT=20）
        log_callback: 日志回调函数

    Returns:
        str: 页面 HTML 文本，网络失败返回 ""
    """
    session = create_retry_session()
    actual_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

    try:
        response = session.get(
            url,
            timeout=actual_timeout,
            allow_redirects=True,
        )
        if log_callback:
            log_callback(f"HTTP 状态：{response.status_code}")
        if response.status_code == 200:
            return response.text
        else:
            if log_callback:
                log_callback(
                    f"⚠️ HTTP {response.status_code}，未获取页面内容"
                )
            return ""
    except Exception as e:
        if log_callback:
            log_callback(f"⚠️ 请求失败：{e}")
        return ""
    finally:
        session.close()


__all__ = ["fetch_tiktok_html"]
