"""Phase 7-F：cookie_cache 内存缓存单元测试。

覆盖：
- set_cookie / get_cookie 基本读写
- TTL 过期自动清理
- clear_cookie 单条清除
- clear_all 全量清除
- 线程安全（多线程并发 set/get 不崩溃）
- 空值 / None 不写入
"""
import time
import threading

from core import cookie_cache


def test_set_get_basic():
    """set_cookie 后 get_cookie 应返回相同 cookies。"""
    cookie_cache.clear_all()
    cookies = [{"name": "sid", "value": "abc", "domain": ".tiktok.com"}]
    cookie_cache.set_cookie("123", cookies)
    result = cookie_cache.get_cookie("123")
    assert result == cookies


def test_get_miss_returns_empty():
    """不存在的 video_id 返回空列表（非 None）。"""
    cookie_cache.clear_all()
    result = cookie_cache.get_cookie("nonexistent")
    assert result == []


def test_ttl_expiry():
    """TTL 过期后 get_cookie 返回空列表。"""
    cookie_cache.clear_all()
    cookies = [{"name": "sid", "value": "abc"}]
    cookie_cache.set_cookie("456", cookies, ttl=1)
    # 立即可取
    assert cookie_cache.get_cookie("456") == cookies
    # 等 1.2s 过期
    time.sleep(1.2)
    assert cookie_cache.get_cookie("456") == []


def test_clear_cookie_single():
    """clear_cookie 清除单条。"""
    cookie_cache.clear_all()
    cookie_cache.set_cookie("a", [{"name": "x", "value": "1"}])
    cookie_cache.set_cookie("b", [{"name": "y", "value": "2"}])
    cookie_cache.clear_cookie("a")
    assert cookie_cache.get_cookie("a") == []
    assert cookie_cache.get_cookie("b") == [{"name": "y", "value": "2"}]


def test_clear_all():
    """clear_all 清除全部。"""
    cookie_cache.set_cookie("x", [{"name": "x", "value": "1"}])
    cookie_cache.set_cookie("y", [{"name": "y", "value": "2"}])
    cookie_cache.clear_all()
    assert cookie_cache.get_cookie("x") == []
    assert cookie_cache.get_cookie("y") == []


def test_empty_cookies_not_stored():
    """空 cookies / 空 video_id 不写入缓存。"""
    cookie_cache.clear_all()
    cookie_cache.set_cookie("123", [])
    assert cookie_cache.get_cookie("123") == []
    cookie_cache.set_cookie("", [{"name": "x", "value": "1"}])
    assert cookie_cache.get_cookie("") == []


def test_thread_safety():
    """多线程并发 set/get 不崩溃，最终结果一致。"""
    cookie_cache.clear_all()
    cookies = [{"name": "sid", "value": "v"}]
    errors = []

    def writer():
        try:
            for i in range(50):
                cookie_cache.set_cookie(f"vid{i}", cookies)
        except Exception as e:
            errors.append(e)

    def reader():
        try:
            for i in range(50):
                cookie_cache.get_cookie(f"vid{i}")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer) for _ in range(3)]
    threads += [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    # 最后一条应可读
    cookie_cache.set_cookie("final", cookies)
    assert cookie_cache.get_cookie("final") == cookies


def test_get_returns_copy_not_reference():
    """get_cookie 返回副本，修改不影响缓存内部。"""
    cookie_cache.clear_all()
    original = [{"name": "sid", "value": "abc"}]
    cookie_cache.set_cookie("789", original)
    got = cookie_cache.get_cookie("789")
    got.append({"name": "extra", "value": "x"})
    # 再次 get 应不受影响
    again = cookie_cache.get_cookie("789")
    assert len(again) == 1
    assert again[0]["name"] == "sid"
