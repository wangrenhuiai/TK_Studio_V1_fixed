"""TikTok 短链 URL 解析器（Phase 5-B4.3）。

B4.2 基础上的增强：
- P1: 支持 vm./vt./www.tiktok.com/t//www.tiktok.com/tiktok/t/ 四种短链格式
- P2: HEAD 优先，HEAD 失败（异常或非 video URL）自动 GET fallback
- P3: urllib3 Retry（total=2, backoff=1, status_forcelist 429/5xx）
- P4: normalize_video_url() URL 标准化（剥离 query/fragment）
- P5: TTL + LRU 缓存（默认 300s / 256 条，线程安全）

暂缓（B4.3 不含）：
- P6: resolve_urls() ThreadPoolExecutor 并发
- P7: resolve_short_url_ex() 结构化返回
- P8: 完整测试套件

设计原则：
- 纯 stdlib + requests，不依赖 PySide6
- 不修改 parser / HomeFetcher / tiktok_service 等冻结模块
- 解析失败时返回原 URL（不抛异常，不阻塞 UI）
- 旧接口 resolve_short_url() 签名不变，B4.2 调用方零改动

支持的短链格式：
    https://www.tiktok.com/t/ZTUNyfkNF/
    https://www.tiktok.com/tiktok/t/ZTUNyfkNF/
    https://vm.tiktok.com/ZTUNyfkNF/
    https://vt.tiktok.com/ZTUNyfkNF/
"""
import re
import time
import threading
from collections import OrderedDict

import requests


# ─── 常量 ───────────────────────────────────────────────────

# TikTok 短链检测正则（4 种格式，P1）
# 分支顺序：更具体的 tiktok/t/ 放在 /t/ 之前，避免部分匹配
_SHORT_URL_PATTERN = re.compile(
    r'(?:tiktok\.com/tiktok/t/([A-Za-z0-9]+))'   # www.tiktok.com/tiktok/t/{token}
    r'|(?:tiktok\.com/t/([A-Za-z0-9]+))'          # www.tiktok.com/t/{token}
    r'|(?:vm\.tiktok\.com/([A-Za-z0-9]+))'        # vm.tiktok.com/{token}
    r'|(?:vt\.tiktok\.com/([A-Za-z0-9]+))',       # vt.tiktok.com/{token}  (P1 新增)
    re.I
)

# 标准视频 URL 正则（用于验证解析结果）
_VIDEO_URL_PATTERN = re.compile(r'tiktok\.com/@[\w.-]+/video/\d+', re.I)

# 请求头（与 tiktok_service.py 一致，避免 WAF 拦截）
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ─── 缓存（P5: TTL + LRU，线程安全）─────────────────────────

_CACHE_TTL = 300        # 秒
_CACHE_MAX = 256        # 最大条目
_cache = OrderedDict()  # token → (resolved_url, timestamp)
_cache_lock = threading.Lock()


# ─── 公开接口 ───────────────────────────────────────────────

def is_short_url(url):
    """检测 URL 是否为 TikTok 短链格式。

    支持 4 种格式（P1）：
        https://www.tiktok.com/t/ZTUNyfkNF/
        https://www.tiktok.com/tiktok/t/ZTUNyfkNF/
        https://vm.tiktok.com/ZTUNyfkNF/
        https://vt.tiktok.com/ZTUNyfkNF/

    Args:
        url: 待检测的 URL 字符串

    Returns:
        bool: True 表示是短链，False 表示不是
    """
    if not url or not isinstance(url, str):
        return False
    return bool(_SHORT_URL_PATTERN.search(url))


def normalize_video_url(url):
    """URL 标准化（P4）：剥离 query/fragment，保留 /video/{id}。

    将解析后的 URL 统一为：
        https://www.tiktok.com/@user/video/{id}

    无法匹配标准视频格式时原样返回。

    >>> normalize_video_url("https://www.tiktok.com/@u/video/1?a=b")
    'https://www.tiktok.com/@u/video/1'
    """
    if not url or not isinstance(url, str):
        return url
    m = _VIDEO_URL_PATTERN.search(url)
    if not m:
        return url
    # m.group(0) 形如 "tiktok.com/@user/video/123"
    return "https://www." + m.group(0)


def resolve_short_url(url, log_callback=None, timeout=10):
    """解析单个 TikTok 短链 URL（B4.2 兼容接口）。

    流程（P2/P3）：
        1. 非短链 → 原样返回
        2. 缓存命中 → 返回缓存值
        3. HEAD 跟随重定向
           - HEAD 成功且结果为标准视频 URL → 标准化 + 缓存 + 返回
           - HEAD 异常或结果非标准 → GET fallback
        4. GET 跟随重定向
           - GET 成功且结果为标准视频 URL → 标准化 + 缓存 + 返回
           - 否则 → 返回原 URL
        5. 所有网络路径均使用 urllib3 Retry（P3）

    解析失败时返回原 URL（不抛异常，不阻塞 UI）。

    Args:
        url: 待解析的 URL
        log_callback: 可选日志回调 ``Callable[[str], None]``
        timeout: HTTP 请求超时秒数（默认 10）

    Returns:
        str: 解析后的标准格式 URL，或原 URL（如果不是短链或解析失败）
    """
    if not url or not isinstance(url, str):
        return url

    if not is_short_url(url):
        return url

    # 提取短链 token 用于缓存
    match = _SHORT_URL_PATTERN.search(url)
    token = None
    if match:
        token = (match.group(1) or match.group(2)
                 or match.group(3) or match.group(4))

    # 检查缓存（P5）
    if token:
        cached = _cache_get(token)
        if cached is not None:
            _log(log_callback, f"短链 {token}（缓存命中）→ {cached}")
            return cached

    # 构建 session（含 Retry，P3）
    session = _build_session()

    # ── HEAD 尝试（P2）──
    final_url = _try_head(session, url, timeout, log_callback)

    # HEAD 结果为标准视频 URL → 成功
    if final_url and _VIDEO_URL_PATTERN.search(final_url):
        return _finalize_success(original_url=url, final_url=final_url,
                                 token=token, log_callback=log_callback)

    # ── GET fallback（P2：HEAD 异常或非标准 URL 时回退）──
    if final_url:
        _log(log_callback, f"HEAD 结果非标准 URL，尝试 GET：{final_url}")
    else:
        _log(log_callback, f"HEAD 失败，尝试 GET：{url}")

    final_url = _try_get(session, url, timeout, log_callback)

    # GET 结果校验
    if final_url and _VIDEO_URL_PATTERN.search(final_url):
        return _finalize_success(original_url=url, final_url=final_url,
                                 token=token, log_callback=log_callback)

    # 解析失败，返回原 URL
    _log(log_callback, f"短链解析结果非标准 URL：{final_url}，保留原 URL")
    return url


def resolve_urls(urls, log_callback=None, timeout=10):
    """批量解析 URL 列表中的短链。

    对每个 URL 检测是否为短链，如果是则解析为标准视频 URL。
    非短链 URL 原样保留。

    注意：B4.3 暂缓 P6 并发优化，当前为串行实现。

    Args:
        urls: URL 字符串列表
        log_callback: 可选日志回调
        timeout: 每个短链的 HTTP 超时秒数

    Returns:
        list[dict]: 每个元素包含：
            - original: 原 URL
            - resolved: 解析后的 URL（如果解析失败则为原 URL）
            - changed: bool，是否发生了变化
            - success: bool，是否解析成功（仅短链有意义的字段）
    """
    results = []
    for url in urls:
        if not url or not isinstance(url, str):
            results.append({
                "original": url,
                "resolved": url,
                "changed": False,
                "success": False,
            })
            continue

        was_short = is_short_url(url)
        resolved = resolve_short_url(url, log_callback, timeout)
        changed = (resolved != url)

        results.append({
            "original": url,
            "resolved": resolved,
            "changed": changed,
            "success": was_short and changed,
        })
    return results


def clear_cache():
    """清空短链解析缓存。"""
    with _cache_lock:
        _cache.clear()


# ─── 内部函数 ───────────────────────────────────────────────

def _build_session():
    """构建带 urllib3 Retry 的 requests.Session（P3）。

    Retry 配置与 downloader.py 对齐：
        total=2, connect=2, read=2, status=2
        backoff_factor=1
        status_forcelist=(429, 500, 502, 503, 504)
    """
    from requests.adapters import HTTPAdapter
    try:
        from urllib3.util.retry import Retry
    except ImportError:
        from urllib3.util import Retry

    s = requests.Session()
    retry = Retry(
        total=2, connect=2, read=2, status=2,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update(_HEADERS)
    return s


def _try_head(session, url, timeout, log_callback):
    """HEAD 请求跟随重定向，返回 final_url 或 None。"""
    try:
        _log(log_callback, f"正在解析短链（HEAD）：{url}")
        resp = session.head(url, allow_redirects=True, timeout=timeout)
        return resp.url
    except Exception as e:
        _log(log_callback, f"HEAD 失败（{e}），将回退 GET")
        return None


def _try_get(session, url, timeout, log_callback):
    """GET 请求跟随重定向（stream，不下载 body），返回 final_url 或 None。"""
    try:
        resp = session.get(url, allow_redirects=True, timeout=timeout,
                           stream=True)
        try:
            return resp.url
        finally:
            resp.close()
    except requests.Timeout:
        _log(log_callback, f"短链解析超时（{timeout}s），保留原 URL")
        return None
    except requests.ConnectionError:
        _log(log_callback, "短链解析连接失败，保留原 URL")
        return None
    except Exception as e:
        _log(log_callback, f"短链解析失败：{e}，保留原 URL")
        return None


def _finalize_success(original_url, final_url, token, log_callback):
    """解析成功：标准化（P4）+ 缓存（P5）+ 日志 + 返回。"""
    normalized = normalize_video_url(final_url)
    if token:
        _cache_put(token, normalized)
    _log(log_callback, f"短链解析成功 → {normalized}")
    return normalized


def _cache_get(token):
    """从缓存获取（TTL + LRU），线程安全（P5）。

    Returns:
        缓存的 URL 字符串，或 None（未命中/已过期）
    """
    with _cache_lock:
        if token not in _cache:
            return None
        resolved, ts = _cache[token]
        if time.time() - ts > _CACHE_TTL:
            del _cache[token]
            return None
        _cache.move_to_end(token)  # LRU: 移到末尾
        return resolved


def _cache_put(token, resolved):
    """写入缓存（LRU 淘汰），线程安全（P5）。"""
    with _cache_lock:
        _cache[token] = (resolved, time.time())
        _cache.move_to_end(token)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)  # LRU: 淘汰最久未用


def _log(callback, message):
    """安全调用日志回调。"""
    if callback:
        try:
            callback(message)
        except Exception:
            pass


__all__ = [
    "is_short_url",
    "resolve_short_url",
    "resolve_urls",
    "normalize_video_url",
    "clear_cache",
]
