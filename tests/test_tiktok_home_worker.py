"""TikTok Home Worker 测试（Phase 5-B1.4）。

运行::

    python tests/test_tiktok_home_worker.py

测试策略：**不真实访问 TikTok**，使用 ``unittest.mock`` 注入 mock Service，
验证 Worker 的编排逻辑（Service → Adapter 链路）与异常安全。

测试项：
1. Import：``from core.tiktok_home_worker import TikTokHomeWorker``
2. Success Run：mock Service 返回成功 + 1 个视频 → 校验 source/success/count
3. Failure Run：mock Service 返回失败 → 校验 success=False
4. Exception Safety：mock Service 抛异常 → Worker 不崩溃，返回失败 dict

输出格式::

    TikTok Home Worker Test
    ==============================

    Import:
    OK

    Success Run:
    OK

    Failure Run:
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

from core.tiktok_home_worker import TikTokHomeWorker


def main():
    print("TikTok Home Worker Test")
    print("=" * 30)
    print()

    results = []
    # patch 目标：worker 模块内绑定的 Service 类名
    service_patch_target = "core.tiktok_home_worker.TikTokHomeService"

    # 1. Import
    print("Import:")
    ok = False
    try:
        assert TikTokHomeWorker is not None
        inst = TikTokHomeWorker()
        ok = hasattr(inst, "run") and callable(inst.run)
        ok = ok and hasattr(inst, "service") and hasattr(inst, "adapter")
    except Exception:
        ok = False
    print("OK" if ok else "FAIL")
    results.append(ok)
    print()

    # 2. Success Run — mock Service 返回成功 + 1 个视频
    print("Success Run:")
    ok = False
    try:
        with mock.patch(service_patch_target):
            inst = TikTokHomeWorker()
            # 配置 mock service 实例的 fetch_home 返回成功结构
            inst.service.fetch_home.return_value = {
                "success": True,
                "videos": ["https://www.tiktok.com/@a/video/111"],
            }
            out = inst.run("a")
            ok = (
                isinstance(out, dict)
                and out.get("source") == "tiktok"
                and out.get("success") is True
                and out.get("count") == 1
                and len(out.get("urls", [])) == 1
                and out.get("username") == "a"
                and out.get("error") is None
            )
    except Exception:
        ok = False
    print("OK" if ok else "FAIL")
    results.append(ok)
    print()

    # 3. Failure Run — mock Service 返回失败
    print("Failure Run:")
    ok = False
    try:
        with mock.patch(service_patch_target):
            inst = TikTokHomeWorker()
            inst.service.fetch_home.return_value = {
                "success": False,
                "videos": [],
                "error": "xxx",
            }
            out = inst.run("a")
            ok = (
                isinstance(out, dict)
                and out.get("success") is False
                and out.get("error") is not None
                and out.get("count") == 0
                and out.get("urls") == []
                and out.get("source") == "tiktok"
            )
    except Exception:
        ok = False
    print("OK" if ok else "FAIL")
    results.append(ok)
    print()

    # 4. Exception Safety — mock Service 抛异常
    print("Exception Safety:")
    ok = False
    try:
        with mock.patch(service_patch_target):
            inst = TikTokHomeWorker()
            inst.service.fetch_home.side_effect = RuntimeError("boom")
            out = inst.run("a")
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
