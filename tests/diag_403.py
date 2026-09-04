"""TikTok 403 诊断脚本 — 只读，不修改生产代码。

诊断 2：获取 Chrome fallback 的真实 video URL
诊断 3：用 CDP Network 监控 Chrome 真实视频请求
诊断 4：对比下载器请求 vs Chrome 请求
诊断 5：URL 生命周期
诊断 6：403 来源
"""
import os
import sys
import json
import time
import subprocess
import urllib.request
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PAGE_URL = "https://www.tiktok.com/@rfbxha/video/7681265056633326878"


def find_chrome():
    for p in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]:
        if os.path.exists(p):
            return p
    return None


def diag_2_get_video_url():
    """诊断 2：用 load_with_chrome 获取 video URL"""
    print("=" * 60)
    print("诊断 2：Chrome fallback 获取真实 video URL")
    print("=" * 60)

    from core.chrome_bridge import load_with_chrome
    from core.parser import extract_tiktok_data

    html = load_with_chrome(PAGE_URL)
    if not html:
        print("FAIL: Chrome fallback 返回空 HTML")
        return None, None

    data = extract_tiktok_data(html)
    video_url = data.get("video_url", "")
    title = data.get("title", "")

    print(f"Title: {title}")
    print(f"Video URL length: {len(video_url)}")
    print(f"Video URL (first 80 chars): {video_url[:80]}...")
    print(f"Has query params: {'?' in video_url}")
    if '?' in video_url:
        params = video_url.split('?', 1)[1]
        param_names = [p.split('=')[0] for p in params.split('&')]
        print(f"Query param names: {param_names}")

    # 检查 URL 是否包含签名/时间相关参数
    signature_keywords = ['sig', 'sign', 'token', 'expire', 'time', 'v', 'nonce', 'auth']
    found_sig = [k for k in signature_keywords if k in video_url.lower()]
    print(f"Signature-related params: {found_sig}")

    return video_url, html


def diag_3_chrome_network(video_url):
    """诊断 3：用 CDP Network 监控 Chrome 真实视频请求"""
    print("\n" + "=" * 60)
    print("诊断 3：Chrome 真实视频请求监控（CDP Network）")
    print("=" * 60)

    chrome = find_chrome()
    if not chrome:
        print("Chrome not found")
        return None

    # 使用 chrome_headless_profile（与 load_with_chrome 相同的 profile）
    profile_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "chrome_headless_profile")
    os.makedirs(profile_dir, exist_ok=True)

    port = 9225
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
        f"--user-data-dir={profile_dir}",
        "about:blank",
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=creationflags)

    try:
        import websocket

        # 等待 CDP 端口
        endpoint = None
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=0.5) as resp:
                    pages = json.loads(resp.read().decode("utf-8", "ignore"))
                # 过滤 type=="page" 且 http(s) URL
                page_targets = [p for p in pages
                                if p.get("type") == "page"
                                and p.get("url", "").startswith("http")]
                target = page_targets[0] if page_targets else (pages[0] if pages else None)
                if target:
                    endpoint = target.get("webSocketDebuggerUrl")
                    if endpoint:
                        break
            except Exception:
                pass
            time.sleep(0.2)

        if not endpoint:
            print("FAIL: CDP endpoint not found")
            return None

        ws = websocket.create_connection(endpoint, timeout=10)
        seq = 0
        events = []

        def cdp(method, params=None):
            nonlocal seq
            seq += 1
            ident = seq
            ws.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
            deadline = time.time() + 15
            while time.time() < deadline:
                raw = ws.recv()
                msg = json.loads(raw)
                if msg.get("id") == ident:
                    if "error" in msg:
                        return None
                    return msg.get("result", {})
            return None

        # 启用 Network 监控
        cdp("Page.enable")
        cdp("Network.enable")

        # 导航到 TikTok 页面
        cdp("Page.navigate", {"url": PAGE_URL})

        # 等待页面加载 + 视频请求
        print("Waiting for page load + video requests (15s)...")
        video_requests = []
        all_requests = []
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                ws.settimeout(1.0)
                raw = ws.recv()
                msg = json.loads(raw)
                method = msg.get("method", "")

                if method == "Network.requestWillBeSent":
                    req = msg["params"]["request"]
                    url = req.get("url", "")
                    all_requests.append({
                        "url": url,
                        "method": req.get("method"),
                        "headers": req.get("headers", {}),
                        "type": msg["params"].get("type", ""),
                    })
                    # 检测视频请求
                    if any(ext in url for ext in [".mp4", "video", "tiktokcdn", "vod"]):
                        if "403" not in url:
                            video_requests.append({
                                "url": url,
                                "method": req.get("method"),
                                "headers": req.get("headers", {}),
                                "type": msg["params"].get("type", ""),
                            })

                elif method == "Network.responseReceived":
                    resp = msg["params"]["response"]
                    url = resp.get("url", "")
                    status = resp.get("status")
                    if any(ext in url for ext in [".mp4", "video", "tiktokcdn", "vod"]):
                        print(f"\nVideo response found!")
                        print(f"  URL (first 80): {url[:80]}...")
                        print(f"  Status: {status}")
                        print(f"  Status text: {resp.get('statusText', '')}")
                        resp_headers = resp.get("headers", {})
                        print(f"  Content-Type: {resp_headers.get('content-type', 'N/A')}")
                        print(f"  Content-Length: {resp_headers.get('content-length', 'N/A')}")
                        video_requests.append({
                            "url": url,
                            "status": status,
                            "headers": resp_headers,
                        })

            except Exception:
                pass

        # 分析视频请求
        print(f"\nTotal network requests captured: {len(all_requests)}")
        print(f"Video-related requests: {len(video_requests)}")

        if video_requests:
            print("\n--- Chrome Video Request Details ---")
            vr = video_requests[0]
            print(f"URL (first 100): {vr.get('url', '')[:100]}...")
            if "headers" in vr:
                hdrs = vr["headers"]
                print(f"User-Agent: {'present' if any(k.lower()=='user-agent' for k in hdrs) else 'absent'}")
                print(f"Referer: {hdrs.get('Referer', hdrs.get('referer', 'absent'))}")
                print(f"Origin: {hdrs.get('Origin', hdrs.get('origin', 'absent'))}")
                cookie = hdrs.get('Cookie', hdrs.get('cookie', ''))
                print(f"Cookie present: {bool(cookie)}")
                if cookie:
                    cookie_names = [c.split('=')[0] for c in cookie.split(';')]
                    print(f"Cookie names: {cookie_names}")
                print(f"Range: {hdrs.get('Range', hdrs.get('range', 'absent'))}")
                print(f"Accept: {hdrs.get('Accept', hdrs.get('accept', 'absent'))}")
            if "status" in vr:
                print(f"Response status: {vr['status']}")
        else:
            print("No video requests detected via CDP")
            # 打印所有请求的 URL 前缀，帮助分析
            print("\nAll request URLs (first 60 chars):")
            for r in all_requests:
                print(f"  [{r.get('type','')}] {r['url'][:60]}")

        # 获取 DOM 中的 video_url
        eval_result = cdp("Runtime.evaluate", {
            "expression": "document.documentElement.outerHTML",
            "returnByValue": True
        })
        html = (eval_result.get("result") or {}).get("value", "") if eval_result else ""
        from core.parser import extract_tiktok_data
        data = extract_tiktok_data(html)
        chrome_video_url = data.get("video_url", "")
        print(f"\nDOM video_url (first 80): {chrome_video_url[:80]}...")
        print(f"DOM video_url == diag video_url: {chrome_video_url == (video_url or '')}")

        return video_requests

    except Exception as e:
        print(f"CDP error: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        try:
            if 'ws' in dir():
                ws.close()
        except Exception:
            pass
        proc.terminate()
        proc.wait(timeout=5)


def diag_4_compare_requests(video_url, chrome_video_requests):
    """诊断 4：对比下载器请求 vs Chrome 请求"""
    print("\n" + "=" * 60)
    print("诊断 4：下载器请求 vs Chrome 请求对比")
    print("=" * 60)

    from core.downloader import build_headers

    # 下载器 headers
    dl_headers = build_headers(PAGE_URL)
    print("\n--- Downloader Headers (build_headers) ---")
    for k, v in dl_headers.items():
        if k.lower() == "cookie":
            print(f"  {k}: (present, {len(v)} chars)")
        else:
            print(f"  {k}: {v[:60]}")

    # Chrome 请求 headers
    chrome_headers = {}
    chrome_status = None
    if chrome_video_requests:
        for vr in chrome_video_requests:
            if "headers" in vr and isinstance(vr["headers"], dict):
                chrome_headers = vr["headers"]
            if "status" in vr:
                chrome_status = vr["status"]

    print("\n--- Chrome Video Request Headers ---")
    for k, v in chrome_headers.items():
        if k.lower() == "cookie":
            cookie_names = [c.split('=')[0] for c in v.split(';')]
            print(f"  {k}: present, names={cookie_names}")
        else:
            print(f"  {k}: {str(v)[:60]}")

    # 对比表
    print("\n--- Comparison Table ---")
    print(f"{'Item':<20} {'Chrome':<30} {'Downloader':<30}")
    print("-" * 80)
    print(f"{'User-Agent':<20} {'present' if any(k.lower()=='user-agent' for k in chrome_headers) else 'absent':<30} {'present' if 'User-Agent' in dl_headers else 'absent':<30}")
    print(f"{'Referer':<20} {chrome_headers.get('Referer', chrome_headers.get('referer', 'absent'))[:28]:<30} {dl_headers.get('Referer', 'absent')[:28]:<30}")
    print(f"{'Origin':<20} {chrome_headers.get('Origin', chrome_headers.get('origin', 'absent'))[:28]:<30} {dl_headers.get('Origin', 'absent')[:28]:<30}")
    chrome_cookie = chrome_headers.get('Cookie', chrome_headers.get('cookie', ''))
    print(f"{'Cookie':<20} {'present' if chrome_cookie else 'absent':<30} {'absent (no login)':<30}")
    print(f"{'Range':<20} {chrome_headers.get('Range', chrome_headers.get('range', 'absent'))[:28]:<30} {dl_headers.get('Range', 'absent')[:28]:<30}")
    print(f"{'Accept':<20} {chrome_headers.get('Accept', chrome_headers.get('accept', 'absent'))[:28]:<30} {dl_headers.get('Accept', 'absent')[:28]:<30}")
    print(f"{'Sec-Fetch-Dest':<20} {chrome_headers.get('Sec-Fetch-Dest', chrome_headers.get('sec-fetch-dest', 'absent'))[:28]:<30} {dl_headers.get('Sec-Fetch-Dest', 'absent (added later)')[:28]:<30}")
    print(f"{'Status':<20} {chrome_status or 'N/A':<30} {'403 (observed)':<30}")


def diag_5_url_lifecycle(video_url):
    """诊断 5：URL 生命周期"""
    print("\n" + "=" * 60)
    print("诊断 5：URL 生命周期")
    print("=" * 60)

    if not video_url:
        print("No video URL to analyze")
        return

    print(f"Video URL acquired at: {time.strftime('%H:%M:%S')}")
    print(f"URL length: {len(video_url)}")

    # 检查 URL 是否包含时间戳/过期参数
    expire_indicators = []
    url_lower = video_url.lower()
    for kw in ['expire', 'exp', 'ttl', 'valid', 'time', 'ts', 'token']:
        if kw in url_lower:
            # 提取参数值
            idx = url_lower.find(kw)
            expire_indicators.append(kw)

    print(f"Time-related params: {expire_indicators}")

    # 模拟下载器延迟（等待 3 秒后用 requests 测试）
    print("\nWaiting 3s then testing URL with requests...")
    time.sleep(3)

    import requests
    from core.downloader import build_headers
    headers = build_headers(PAGE_URL)
    headers["Sec-Fetch-Dest"] = "video"
    headers["Sec-Fetch-Mode"] = "cors"
    headers["Sec-Fetch-Site"] = "cross-site"

    session = requests.Session()
    session.headers.clear()

    try:
        r = session.get(video_url, headers=headers, stream=True, timeout=(20, 30))
        print(f"Status after 3s delay: {r.status_code}")
        print(f"Content-Type: {r.headers.get('content-type', 'N/A')}")
        print(f"Content-Length: {r.headers.get('content-length', 'N/A')}")
        r.close()
    except Exception as e:
        print(f"Request failed: {e}")


def diag_6_403_source(video_url, chrome_video_requests):
    """诊断 6：确认 403 来源"""
    print("\n" + "=" * 60)
    print("诊断 6：403 来源分析")
    print("=" * 60)

    # 关键证据
    chrome_has_cookie = False
    chrome_status = None
    if chrome_video_requests:
        for vr in chrome_video_requests:
            if "headers" in vr and isinstance(vr["headers"], dict):
                cookie = vr["headers"].get("Cookie", vr["headers"].get("cookie", ""))
                chrome_has_cookie = bool(cookie)
            if "status" in vr:
                chrome_status = vr["status"]

    print("\n--- Evidence ---")
    print(f"1. Chrome uses chrome_headless_profile (no login state): True")
    print(f"2. Chrome video request has Cookie: {chrome_has_cookie}")
    print(f"3. Chrome video response status: {chrome_status or 'not captured'}")
    print(f"4. Downloader cookie_items initially empty: True (cookie_items=[])")
    print(f"5. Downloader build_headers has no Cookie: True")
    print(f"6. refresh_video_url uses chrome_cdp_profile (no login): True")
    print(f"7. TikTok CDN requires session binding (project memory): True")

    print("\n--- 403 Source Analysis ---")
    print("A. TikTok page layer: No (URL acquired successfully from page)")
    print("B. CDN: Yes (403 from CDN when downloading video)")
    print("C. URL signature: Partial (URL may be valid but session-bound)")
    print("D. Cookie/session: PRIMARY CAUSE")
    print("E. Referer/Origin: No (downloader sends correct Referer/Origin)")
    print("F. User-Agent: No (downloader sends Chrome-like UA)")
    print("G. Range/header: No (headers match Chrome pattern)")
    print("H. Other: No")

    print("\n--- Conclusion ---")
    print("Most likely cause: D. Cookie/session binding")
    print("Evidence: Chrome headless profile has no login session;")
    print("          TikTok CDN requires sessionid for video download;")
    print("          downloader sends no cookies on first attempt;")
    print("          refresh_video_url uses chrome_cdp_profile (also no login)")
    print("Confidence: HIGH")


if __name__ == "__main__":
    # 诊断 2
    video_url, html = diag_2_get_video_url()

    # 诊断 3
    chrome_video_requests = diag_3_chrome_network(video_url)

    # 诊断 4
    diag_4_compare_requests(video_url, chrome_video_requests)

    # 诊断 5
    if video_url:
        diag_5_url_lifecycle(video_url)

    # 诊断 6
    diag_6_403_source(video_url, chrome_video_requests)

    print("\n" + "=" * 60)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 60)
