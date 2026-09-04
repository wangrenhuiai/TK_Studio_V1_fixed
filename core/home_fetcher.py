"""主页作品 URL 获取模块。

通过 Chrome DevTools Protocol (CDP) 访问 TikTok 用户主页，
滚动触发懒加载，从最终 DOM 中提取 /video/{id} URL 列表。

设计原则：
- 匿名访问，不依赖登录态
- 独立临时 profile，不影响用户 Chrome
- 只返回 URL 列表，不调用 parse_url / db.add_work
- 资源清理保证无僵尸 Chrome 进程
"""
import os
import re
import json
import time
import shutil
import subprocess
import urllib.request


# FIX-EXE.1：profile 目录使用用户可写数据根目录（EXE 时 %LOCALAPPDATA%\TK_Studio）。
from core.paths import get_app_data_root
_PROJECT_ROOT = get_app_data_root()

# 复用 chrome_bridge 的 Chrome 路径查找逻辑（只读引用，不修改 chrome_bridge）
def _find_chrome():
    """查找本机 Chrome 可执行文件路径。"""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    return next((x for x in candidates if os.path.exists(x)), None)


# 匹配 TikTok video URL 中的数字 ID
# 格式: https://www.tiktok.com/@username/video/1234567890
_VIDEO_ID_PATTERN = re.compile(r'/video/(\d+)')


class HomeFetcher:
    """通过 Chrome CDP 获取 TikTok 用户主页的作品 URL 列表。

    匿名访问 + 滚动触发懒加载 + DOM 提取 /video/{id}。
    """

    def fetch(self, url, log_callback=None,
              max_scrolls=3, initial_wait=15, scroll_wait=8,
              profile_dir=None):
        """获取主页作品 URL 列表。

        Args:
            url: TikTok 用户主页 URL（如 https://www.tiktok.com/@tiktok）
            log_callback: 可选的日志回调函数
            max_scrolls: 最大滚动次数（默认 3）
            initial_wait: 初始页面等待秒数（默认 15）
            scroll_wait: 每次滚动后等待秒数（默认 4）
            profile_dir: 可选 Chrome user-data-dir 路径（默认 None
                使用 chrome_home_fetcher_profile 匿名 profile；认证
                模式由调用方传入 chrome_home_auth_profile 等持久化目录）。
                注意：此参数指 Chrome --user-data-dir，与 _start_chrome_cdp
                的 profile_directory="Default"（子 profile 名）不同。

        Returns:
            list[str]: 去重后的 video URL 列表，保持首次出现顺序

        Raises:
            RuntimeError: Chrome 找不到 / CDP 连接失败 / 页面加载失败
            ValueError: URL 无效
        """
        self._log(log_callback, f"开始获取主页作品 URL：{url}")

        # 1. URL 校验
        if not url or not isinstance(url, str):
            raise ValueError("URL 不能为空")
        if "tiktok.com/@" not in url and "tiktok.com/" not in url:
            raise ValueError(f"不是有效的 TikTok URL：{url}")

        chrome_path = _find_chrome()
        if not chrome_path:
            raise RuntimeError("未找到 Chrome 可执行文件")

        # 2. Chrome user-data-dir：默认匿名 profile（累积 WAF cookie），
        #    认证模式由调用方传入 profile_dir 复用登录态。
        if profile_dir is None:
            profile_dir = os.path.join(_PROJECT_ROOT, "chrome_home_fetcher_profile")
        os.makedirs(profile_dir, exist_ok=True)
        self._log(log_callback, f"使用 profile：{profile_dir}")

        proc = None
        ws = None
        try:
            proc, ws, cdp = self._start_chrome_cdp(chrome_path, profile_dir, "Default")

            # 3. 页面加载
            self._log(log_callback, f"加载页面，等待 {initial_wait}s...")
            cdp("Page.enable")
            cdp("Network.enable")
            cdp("Page.navigate", {"url": url})
            time.sleep(initial_wait)

            # 4. 初始 DOM 提取
            html = self._get_dom(cdp)
            video_urls = self._extract_video_urls(html, url)
            initial_count = len(video_urls)
            self._log(log_callback, f"初始 video URLs: {initial_count}")

            # 5. 滚动循环
            all_urls = list(video_urls)
            for i in range(1, max_scrolls + 1):
                # 滚动到底部
                cdp("Runtime.evaluate", {
                    "expression": (
                        "window.scrollTo(0, document.body.scrollHeight);"
                    ),
                    "returnByValue": True
                })
                time.sleep(scroll_wait)

                # 获取新 DOM
                html = self._get_dom(cdp)
                new_urls = self._extract_video_urls(html, url)
                prev_count = len(all_urls)
                all_urls = list(dict.fromkeys(all_urls + new_urls))
                added = len(all_urls) - prev_count
                self._log(log_callback, f"Scroll {i}: +{added} video URLs (total: {len(all_urls)})")

            # 6. 最终去重
            final_urls = list(dict.fromkeys(all_urls))
            self._log(log_callback, f"最终唯一 video URLs: {len(final_urls)}")
            return final_urls

        finally:
            # 7. 资源清理（不删除固定 profile，保留 WAF cookie 供下次使用）
            self._cleanup(proc, ws, log_callback)

    def _start_chrome_cdp(self, chrome_path, profile_dir, profile_directory="Default"):
        """启动 Chrome CDP 会话，返回 (proc, ws, cdp_func)。"""
        # 查找可用端口
        port = None
        for candidate in range(9222, 9232):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{candidate}/json/version", timeout=0.3
                ):
                    continue
            except Exception:
                port = candidate
                break

        if port is None:
            raise RuntimeError("无可用 CDP 端口（9222-9231 均被占用）")

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        cmd = [
            chrome_path,
            "--headless=new",
            "--disable-gpu",
            "--disable-extensions",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--autoplay-policy=no-user-gesture-required",
            "--remote-allow-origins=*",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            f"--profile-directory={profile_directory}",
            "about:blank",
        ]

        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=creationflags
        )

        # 等待 CDP endpoint 就绪
        endpoint = None
        for _ in range(50):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/json", timeout=0.5
                ) as resp:
                    pages = json.loads(resp.read().decode("utf-8", "ignore"))
                if pages:
                    endpoint = pages[0].get("webSocketDebuggerUrl")
                    if endpoint:
                        break
            except Exception:
                pass
            time.sleep(0.2)

        if not endpoint:
            raise RuntimeError("Chrome CDP endpoint 启动失败")

        import websocket
        ws = websocket.create_connection(endpoint, timeout=15)
        seq = [0]

        def cdp(method, params=None):
            """发送 CDP 命令并等待响应。"""
            seq[0] += 1
            ident = seq[0]
            ws.send(json.dumps({
                "id": ident, "method": method, "params": params or {}
            }))
            deadline = time.time() + 30
            while time.time() < deadline:
                raw = ws.recv()
                msg = json.loads(raw)
                if msg.get("id") == ident:
                    if "error" in msg:
                        raise RuntimeError(f"CDP 错误 {method}: {msg['error']}")
                    return msg.get("result", {})
                # 忽略事件消息
            raise RuntimeError(f"CDP 超时：{method}")

        return proc, ws, cdp

    def _get_dom(self, cdp):
        """通过 Runtime.evaluate 获取当前 DOM。"""
        eval_result = cdp("Runtime.evaluate", {
            "expression": "document.documentElement.outerHTML",
            "returnByValue": True
        })
        return (eval_result.get("result") or {}).get("value", "")

    def _extract_video_urls(self, html, base_url):
        """从 HTML 中提取 TikTok video URL。

        只接受 /video/{numeric_id} 格式的 URL，排除 /music/ /tag/ 等。
        """
        if not html:
            return []

        # 提取所有 /video/{id} 匹配
        matches = _VIDEO_ID_PATTERN.findall(html)
        video_ids = list(dict.fromkeys(matches))  # 保序去重

        # 构建完整 URL
        # 从 base_url 提取 @username 部分
        # 例如 https://www.tiktok.com/@tiktok → @tiktok
        username_match = re.search(r'@([\w.-]+)', base_url)
        username = username_match.group(1) if username_match else "unknown"

        urls = [
            f"https://www.tiktok.com/@{username}/video/{vid}"
            for vid in video_ids
        ]
        return urls

    def _cleanup(self, proc, ws, log_callback=None):
        """清理 CDP 会话（不删除固定 profile，保留 WAF cookie）。"""
        # 1. 关闭 WebSocket
        try:
            if ws:
                ws.close()
        except Exception:
            pass

        # 2. 终止 Chrome 进程
        try:
            if proc:
                proc.terminate()
                proc.wait(timeout=3)
        except Exception:
            try:
                if proc:
                    proc.kill()
                    proc.wait(timeout=2)
            except Exception:
                pass

    def _log(self, callback, message):
        """安全调用日志回调。"""
        if callback:
            try:
                callback(message)
            except Exception:
                pass
