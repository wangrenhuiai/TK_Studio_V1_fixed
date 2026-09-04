"""HTTP Retry Session 工厂（Phase 5-C2 方案 B）。

提供带 urllib3 Retry 的 requests.Session，用于 TikTok 页面请求。
不修改冻结的 ``core/tiktok_service.py``，由 ``core/tiktok_request.py`` 调用。

配置与 ``core/downloader.py`` L192-200 对齐（保持一致性）：
    Retry(total=3, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504))
    默认 timeout=20
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# Retry 配置（与 downloader.py 对齐，total=3）
_RETRY_TOTAL = 3
_RETRY_BACKOFF = 1
_RETRY_STATUS_FORCELIST = (429, 500, 502, 503, 504)

# 默认超时（与 tiktok_service.py L57 timeout=20 对齐）
DEFAULT_TIMEOUT = 20

# TikTok 请求 UA（与 tiktok_service.py _HEADERS 对齐）
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
}


def create_retry_session(
    total=_RETRY_TOTAL,
    backoff_factor=_RETRY_BACKOFF,
    status_forcelist=_RETRY_STATUS_FORCELIST,
    timeout=DEFAULT_TIMEOUT,
):
    """创建带 Retry 的 requests.Session。

    Args:
        total: Retry 总次数（默认 3）
        backoff_factor: 退避因子（默认 1，即 0s, 1s, 2s）
        status_forcelist: 触发重试的 HTTP 状态码
        timeout: 默认超时秒数（默认 20）

    Returns:
        requests.Session: 配置好 Retry 的 Session 对象
    """
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    retry = Retry(
        total=total,
        connect=total,
        read=total,
        status=total,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # 把 timeout 挂到 session 上，供调用方读取（requests 不原生支持 session 级 timeout）
    session._default_timeout = timeout

    return session


__all__ = [
    "create_retry_session",
    "DEFAULT_TIMEOUT",
    "DEFAULT_HEADERS",
    "DEFAULT_USER_AGENT",
]
