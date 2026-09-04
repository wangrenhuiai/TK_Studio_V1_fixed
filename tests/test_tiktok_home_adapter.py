"""TikTok Home Adapter 测试（Phase 5-B1.3）。

运行::

    python tests/test_tiktok_home_adapter.py

测试项：
1. Import：``from core.tiktok_home_adapter import TikTokHomeAdapter``
2. Success Adapt：成功输入转换后 source/count/urls 正确
3. Failure Adapt：失败输入转换后 success=False 且 error 存在
4. Exception Safety：None / 非法输入不崩溃

输出格式::

    TikTok Home Adapter Test
    ==============================

    Import:
    OK

    Success Adapt:
    OK

    Failure Adapt:
    OK

    Exception Safety:
    OK

    ==============================

    PASS
"""
import os
import sys

# 脚本直接运行时 sys.path[0] 是 tests/，需把项目根目录加入搜索路径
# 才能正确 import core 包。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.tiktok_home_adapter import TikTokHomeAdapter


def main():
    print("TikTok Home Adapter Test")
    print("=" * 30)
    print()

    adapter = TikTokHomeAdapter()
    results = []  # 每项 True/False

    # 1. Import
    print("Import:")
    ok = False
    try:
        # 顶部已 import 成功，这里再确认类对象可用
        assert TikTokHomeAdapter is not None
        inst = TikTokHomeAdapter()
        ok = hasattr(inst, "adapt") and callable(inst.adapt)
    except Exception:
        ok = False
    print("OK" if ok else "FAIL")
    results.append(ok)
    print()

    # 2. Success Adapt
    print("Success Adapt:")
    ok = False
    try:
        out = adapter.adapt({
            "success": True,
            "count": 2,
            "videos": ["url1", "url2"],
            "error": None,
        }, username="a")
        ok = (
            isinstance(out, dict)
            and out.get("source") == "tiktok"
            and out.get("count") == 2
            and len(out.get("urls", [])) == 2
            and out.get("success") is True
            and out.get("error") is None
            and out.get("username") == "a"
        )
    except Exception:
        ok = False
    print("OK" if ok else "FAIL")
    results.append(ok)
    print()

    # 3. Failure Adapt
    print("Failure Adapt:")
    ok = False
    try:
        out = adapter.adapt({
            "success": False,
            "count": 0,
            "videos": [],
            "error": "xxx",
        }, username="a")
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

    # 4. Exception Safety（None / 非法输入）
    print("Exception Safety:")
    ok = False
    try:
        # None
        out1 = adapter.adapt(None)
        # 列表类型（非 dict）
        out2 = adapter.adapt(["not", "a", "dict"])
        # 嵌套异常对象（不应崩溃）
        out3 = adapter.adapt({"videos": [1, 2, None, "url1"]}, username=None)
        ok = (
            isinstance(out1, dict) and out1.get("success") is False
            and out1.get("error") is not None
            and isinstance(out2, dict) and out2.get("success") is False
            and isinstance(out3, dict)
            and out3.get("urls") == ["url1"]
            and out3.get("count") == 1
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
