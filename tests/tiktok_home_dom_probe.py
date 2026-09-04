"""TikTok 主页作品 URL 只读探测最小运行测试（Phase 5-B1.1）。

用法::

    python tests/tiktok_home_dom_probe.py [用户名]

不指定用户名时默认使用 ``tiktok`` 官方账号。

输出：
- 滚动 / 提取进度日志
- 发现视频数量
- video URL 列表
"""
import os
import sys

# 脚本直接运行时 sys.path[0] 是 tests/，需要把项目根目录加入搜索路径
# 才能正确 import core 包（与 core/home_worker.py 的 import 风格一致）。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.tiktok_home_fetcher import TikTokHomeFetcher


def main():
    # 解析用户名（可选 CLI 参数）
    if len(sys.argv) > 1:
        username = sys.argv[1].strip()
    else:
        username = "tiktok"

    url = f"https://www.tiktok.com/@{username}"
    print(f"目标主页：{url}")
    print("-" * 60)

    fetcher = TikTokHomeFetcher()

    # 日志回调：实时输出 CDP / 滚动 / 提取进度
    def log(msg):
        print(f"  [log] {msg}")

    try:
        videos = fetcher.fetch(
            url,
            log_callback=log,
            max_scrolls=3,
            initial_wait=15,
            scroll_wait=8,
        )
    except Exception as exc:
        print(f"⚠️ 探测失败：{exc}")
        sys.exit(1)

    print("=" * 60)
    print("发现视频数量:", len(videos))
    print("-" * 60)
    for v in videos:
        print(v)
    print("=" * 60)


if __name__ == "__main__":
    main()
