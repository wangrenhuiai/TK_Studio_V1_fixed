"""Chrome / CDP 渲染模块。

保持与 TK_Studio_V1_6_4.py 中 _find_chrome / load_with_chrome /
chrome_render_with_cookies 完全一致的行为：
- Chrome 路径搜索
- chrome_headless_profile / chrome_cdp_profile（位于项目根目录）
- 9222~9231 端口探测
- Page.navigate / Network.enable / Network.getAllCookies / Runtime.evaluate
- Chrome 进程关闭流程
"""
import os
import json
import time
import random
import subprocess
import urllib.request

# 项目根目录（core/chrome_bridge.py 的上一级），profile 目录放在此处。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_chrome():
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    return next((x for x in candidates if os.path.exists(x)), None)


def load_with_chrome(url, log_callback=None):
    """用本机 Chrome 的 headless --dump-dom 获取 JS 渲染后的 DOM。"""
    chrome = _find_chrome()
    if not chrome:
        return ""

    if log_callback:
        log_callback("使用本机 Chrome 渲染页面……")

    profile_dir = os.path.join(_PROJECT_ROOT, "chrome_headless_profile")
    os.makedirs(profile_dir, exist_ok=True)

    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        f"--user-data-dir={profile_dir}",
        "--dump-dom",
        url
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="ignore", timeout=45
        )
        if result.returncode != 0 and log_callback:
            log_callback(f"Chrome 返回码：{result.returncode}")
        return result.stdout or ""
    except subprocess.TimeoutExpired:
        if log_callback:
            log_callback("⚠️ Chrome 渲染超时。")
        return ""
    except Exception as e:
        if log_callback:
            log_callback(f"⚠️ Chrome 渲染失败：{e}")
        return ""


def chrome_render_with_cookies(url, log_callback=None):
    """通过 Chrome DevTools Protocol 获取渲染后的 DOM 和浏览器 Cookie。
    不读取 Chrome 的 Cookies SQLite 文件，因此不会触发
    --cookies-from-browser 的数据库权限问题。
    """
    chrome = _find_chrome()
    if not chrome:
        return "", {}

    # 使用独立临时 profile，避免锁定用户正在使用的 Chrome。
    base = os.path.join(_PROJECT_ROOT, "chrome_cdp_profile")
    os.makedirs(base, exist_ok=True)

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
        return "", {}

    if log_callback:
        log_callback("正在用独立 Chrome 会话刷新视频地址并读取会话 Cookie……")

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--autoplay-policy=no-user-gesture-required",
        "--remote-allow-origins=*",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={base}",
        "about:blank",
    ]

    proc = None
    ws = None
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=creationflags
        )

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
            raise RuntimeError("Chrome DevTools 调试端口启动失败。")

        import websocket
        ws = websocket.create_connection(endpoint, timeout=5)
        seq = 0

        def cdp(method, params=None):
            nonlocal seq
            seq += 1
            ident = seq
            ws.send(json.dumps({
                "id": ident, "method": method, "params": params or {}
            }))
            deadline = time.time() + 12
            while time.time() < deadline:
                raw = ws.recv()
                msg = json.loads(raw)
                if msg.get("id") == ident:
                    if "error" in msg:
                        raise RuntimeError(str(msg["error"]))
                    return msg.get("result", {})
            raise RuntimeError(f"Chrome CDP 超时：{method}")

        cdp("Page.enable")
        cdp("Network.enable")
        cdp("Page.navigate", {"url": url})
        time.sleep(7)

        # 再给 TikTok 一点时间执行页面脚本。
        for _ in range(3):
            time.sleep(2)

        cookies_result = cdp("Network.getAllCookies")
        cookies = {}
        for item in cookies_result.get("cookies", []):
            name = item.get("name")
            value = item.get("value")
            domain = (item.get("domain") or "").lower()
            if name:
                # 同名 Cookie 以更具体的域名优先。
                key = (domain, name)
                cookies[key] = value

        # 获取最终 DOM。
        dom = cdp("Page.getResourceTree")
        _ = dom  # 保留调用以确保页面已完成资源树初始化。
        eval_result = cdp("Runtime.evaluate", {
            "expression": "document.documentElement.outerHTML",
            "returnByValue": True
        })
        html = (eval_result.get("result") or {}).get("value", "")

        # requests 使用 CookieJar 时按域名加入 Cookie。
        cookiejar = []
        for (domain, name), value in cookies.items():
            cookiejar.append({
                "domain": domain,
                "name": name,
                "value": value
            })

        return html, cookiejar

    except Exception as e:
        if log_callback:
            log_callback(f"⚠️ Chrome CDP 获取 Cookie 失败：{e}")
        return "", []
    finally:
        try:
            if ws:
                ws.close()
        except Exception:
            pass
        try:
            if proc:
                proc.terminate()
                proc.wait(timeout=3)
        except Exception:
            try:
                if proc:
                    proc.kill()
            except Exception:
                pass
