"""Phase 7-F：Parse → Download 的内存 Cookie 缓存。

将 parse 阶段从 CDP 获取的 cookie_items 暂存于进程内存，
供 download 阶段首次请求直接注入，避免 attempt 1 无 cookies → 403。

设计约束（Phase 7-F 安全要求）：
- 纯内存，不持久化（进程退出即丢失）
- 线程安全（threading.Lock）
- TTL 过期自动清理（默认 600s）
- 禁止打印 / 日志 / 写文件 / 写 DB

接口：
- set_cookie(video_id, cookies)
- get_cookie(video_id)  → list（空列表表示无缓存/已过期）
- clear_cookie(video_id)
- clear_all()
"""
import threading
import time


# 默认 TTL（秒）：与 TikTok signed URL 有效期对齐，过期后由 refresh 补充。
_DEFAULT_TTL = 600

_lock = threading.Lock()
_cache = {}  # {video_id: {"cookies": list, "ts": float}}


def set_cookie(video_id, cookies, ttl=_DEFAULT_TTL):
    """存入 parse 阶段获取的 cookie_items（仅内存）。

    Args:
        video_id: TikTok 视频 ID（字符串）
        cookies: cookie_items 列表（dict: name/value/domain）
        ttl: 缓存存活秒数，默认 600s
    """
    if not video_id or not cookies:
        return
    with _lock:
        _cache[video_id] = {
            "cookies": list(cookies),
            "ts": time.time(),
            "ttl": ttl,
        }


def get_cookie(video_id):
    """取出 download 阶段需要的 cookie_items。

    过期或不存在时返回空列表 []，调用方走现有 refresh fallback。
    """
    with _lock:
        entry = _cache.get(video_id)
        if not entry:
            return []
        if time.time() - entry["ts"] > entry.get("ttl", _DEFAULT_TTL):
            # 过期，清理
            _cache.pop(video_id, None)
            return []
        return list(entry["cookies"])


def clear_cookie(video_id):
    """清除单个作品的 cookie 缓存。"""
    with _lock:
        _cache.pop(video_id, None)


def clear_all():
    """清除全部 cookie 缓存（登出时调用）。"""
    with _lock:
        _cache.clear()


__all__ = ["set_cookie", "get_cookie", "clear_cookie", "clear_all"]
