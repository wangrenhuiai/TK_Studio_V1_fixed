"""统一 Home Worker 测试（Phase 5-B2.1）。

运行::

    python tests/test_home_worker.py

测试策略：**不真实访问 TikTok**，使用 ``unittest.mock`` 注入 mock source worker，
验证 HomeWorker 的 source 路由与异常安全。

测试项：
1. Import：``from core.home_worker import HomeWorker``
2. TikTok Route：source="tiktok" → mock tiktok_worker.run 返回成功 → 校验路由正确
3. Unknown Source：source="xyz" → 返回失败 dict（source 回填、tiktok_worker 未被调用）
4. Exception Safety：mock tiktok_worker.run 抛异常 → HomeWorker 不崩溃，返回失败 dict

输出格式::

    Home Worker Test
    ==============================

    Import:
    OK

    TikTok Route:
    OK

    Unknown Source:
    OK

    Exception Safety:
    OK

    ==============================

    PASS
"""
import os
import sys
from unittest import mock

# 脚本直接运行时 sys.path[0] 是 tests/，需把项目根目录加入搜索路径
# 才能正确 import core 包。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.home_worker import HomeWorker


def main():
    print("Home Worker Test")
    print("=" * 30)
    print()

    results = []
    # patch 目标：home_worker 模块内绑定的 TikTokHomeWorker 类名
    tiktok_patch = "core.home_worker.TikTokHomeWorker"

    # 1. Import
    print("Import:")
    ok = False
    try:
        assert HomeWorker is not None
        inst = HomeWorker()
        ok = (
            hasattr(inst, "run") and callable(inst.run)
            and hasattr(inst, "tiktok_worker")
        )
    except Exception:
        ok = False
    print("OK" if ok else "FAIL")
    results.append(ok)
    print()

    # 2. TikTok Route — source="tiktok" 路由到 tiktok_worker
    print("TikTok Route:")
    ok = False
    try:
        with mock.patch(tiktok_patch):
            inst = HomeWorker()
            inst.tiktok_worker.run.return_value = {
                "source": "tiktok",
                "username": "a",
                "success": True,
                "count": 1,
                "urls": ["https://www.tiktok.com/@a/video/111"],
                "error": None,
            }
            out = inst.run("tiktok", "a")
            # 校验：tiktok_worker.run 被调用一次，且首参为 username
            routed_ok = (
                inst.tiktok_worker.run.called
                and inst.tiktok_worker.run.call_args[0][0] == "a"
            )
            ok = (
                isinstance(out, dict)
                and out.get("source") == "tiktok"
                and out.get("success") is True
                and out.get("count") == 1
                and len(out.get("urls", [])) == 1
                and routed_ok
            )
    except Exception:
        ok = False
    print("OK" if ok else "FAIL")
    results.append(ok)
    print()

    # 3. Unknown Source — source="xyz" 返回失败，不调用 tiktok_worker
    print("Unknown Source:")
    ok = False
    try:
        with mock.patch(tiktok_patch):
            inst = HomeWorker()
            out = inst.run("xyz", "a")
            ok = (
                isinstance(out, dict)
                and out.get("source") == "xyz"
                and out.get("success") is False
                and out.get("count") == 0
                and out.get("urls") == []
                and out.get("error") is not None
                and not inst.tiktok_worker.run.called  # 未路由到 tiktok
            )
    except Exception:
        ok = False
    print("OK" if ok else "FAIL")
    results.append(ok)
    print()

    # 4. Exception Safety — mock tiktok_worker.run 抛异常
    print("Exception Safety:")
    ok = False
    try:
        with mock.patch(tiktok_patch):
            inst = HomeWorker()
            inst.tiktok_worker.run.side_effect = RuntimeError("boom")
            out = inst.run("tiktok", "a")
            ok = (
                isinstance(out, dict)
                and out.get("success") is False
                and out.get("error") is not None
                and out.get("urls") == []
                and out.get("count") == 0
                and out.get("source") == "tiktok"
            )
    except Exception:
        ok = False
    print("OK" if ok else "FAIL")
    results.append(ok)
    print()

    print("=" * 30)
    print()
    all_pass = all(results)
    print("PASS" if all_pass else "FAIL")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
