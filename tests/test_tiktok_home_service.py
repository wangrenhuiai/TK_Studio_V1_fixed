"""TikTok Home Service 测试（Phase 5-B1.2）。

用法::

    python tests/test_tiktok_home_service.py [用户名或URL]

不指定参数时默认使用 ``tiktok``。

输出字段：
    TikTok Home Service Test
    username/url:
    success:
    count:
    videos:
    first url:
"""
import os
import sys

# 脚本直接运行时 sys.path[0] 是 tests/，需把项目根目录加入搜索路径
# 才能正确 import core 包（与 core/home_worker.py 的 import 风格一致）。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.tiktok_home_service import TikTokHomeService


def main():
    target = sys.argv[1].strip() if len(sys.argv) > 1 else "tiktok"

    print("TikTok Home Service Test")
    print("=" * 60)
    print(f"username/url: {target}")
    print("-" * 60)

    service = TikTokHomeService()

    # 日志回调：实时输出 CDP / 滚动 / 提取进度
    def log(msg):
        print(f"  [log] {msg}")

    result = service.fetch_home(target, log_callback=log)

    print("-" * 60)
    print(f"success: {result['success']}")
    print(f"count:   {result['count']}")
    print(f"videos:  {result['videos']}")
    if result['videos']:
        print(f"first url: {result['videos'][0]}")
    else:
        print("first url: (none)")
    if result['error']:
        print(f"error:   {result['error']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
