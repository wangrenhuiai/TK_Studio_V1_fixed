"""Phase 8-D 验证：用 CDP 捕获真实 video URL，然后用修改后的 build_headers 测试下载。"""
import os, sys, json, time, subprocess, urllib.request, hashlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PAGE_URL = "https://www.tiktok.com/@rfbxha/video/7681265056633326878"

def find_chrome():
    for p in [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]:
        if os.path.exists(p): return p
    return None

def main():
    chrome = find_chrome()
    if not chrome:
        print("Chrome not found"); return

    # 使用 chrome_headless_profile（与生产 load_with_chrome 相同）
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    profile = os.path.join(root, "chrome_headless_profile")
    os.makedirs(profile, exist_ok=True)
    port = 9227
    cmd = [chrome, "--headless=new", "--disable-gpu", "--disable-extensions",
           "--no-first-run", "--no-default-browser-check",
           "--disable-background-networking", "--autoplay-policy=no-user-gesture-required",
           "--remote-allow-origins=*", f"--remote-debugging-port={port}",
           f"--user-data-dir={profile}", "about:blank"]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        import websocket
        endpoint = None
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=0.5) as resp:
                    pages = json.loads(resp.read().decode("utf-8", "ignore"))
                page_targets = [p for p in pages if p.get("type")=="page" and p.get("url","").startswith("http")]
                target = page_targets[0] if page_targets else (pages[0] if pages else None)
                if target and target.get("webSocketDebuggerUrl"):
                    endpoint = target["webSocketDebuggerUrl"]; break
            except: pass
            time.sleep(0.2)
        if not endpoint: print("FAIL: CDP endpoint not found"); return

        ws = websocket.create_connection(endpoint, timeout=10)
        seq = [0]
        video_urls = []

        def cdp(method, params=None):
            seq[0] += 1; ident = seq[0]
            ws.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
            deadline = time.time() + 15
            while time.time() < deadline:
                raw = ws.recv(); msg = json.loads(raw)
                if msg.get("id") == ident:
                    return msg.get("result", {})
            return {}

        cdp("Page.enable"); cdp("Network.enable")
        cdp("Page.navigate", {"url": PAGE_URL})
        print("Waiting for page load + video requests (20s)...")
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                ws.settimeout(1.0); raw = ws.recv(); msg = json.loads(raw)
                method = msg.get("method", "")
                if method == "Network.responseReceived":
                    resp = msg["params"]["response"]
                    url = resp.get("url", "")
                    status = resp.get("status", 0)
                    ct = resp.get("headers", {}).get("content-type", "")
                    # 捕获 v16-webapp-prime 的 video/mp4 响应
                    if "v16-webapp" in url and "video/mp4" in ct.lower() and status == 200:
                        cl = resp.get("headers", {}).get("content-length", "?")
                        print(f"  Video found: status={status}, type={ct}, len={cl}")
                        print(f"  URL (first 80): {url[:80]}...")
                        video_urls.append(url)
            except: pass

        ws.close()
        print(f"\nCaptured {len(video_urls)} video URLs from Chrome network")

        if not video_urls:
            print("FAIL: No video URL captured from Chrome network")
            return

        # 用最新捕获的 video URL 测试下载
        video_url = video_urls[-1]
        print(f"\nUsing video URL for download test...")

        from core.downloader import build_headers
        import requests

        headers = build_headers(PAGE_URL)
        print("Modified build_headers:")
        for k, v in headers.items():
            print(f"  {k}: {v[:60]}")

        session = requests.Session()
        session.headers.clear()
        print(f"\nRequesting video URL with modified headers...")
        r = session.get(video_url, headers=headers, stream=True, timeout=(20, 60))
        print(f"HTTP Status: {r.status_code}")
        print(f"Content-Type: {r.headers.get('content-type', 'N/A')}")
        print(f"Content-Length: {r.headers.get('content-length', 'N/A')}")

        if r.status_code in (200, 206):
            ct = r.headers.get("content-type", "")
            if "video" in ct.lower():
                chunk_hash = hashlib.sha256(); total = 0
                for chunk in r.iter_content(chunk_size=8192):
                    chunk_hash.update(chunk); total += len(chunk)
                    if total >= 1024 * 1024: break
                r.close()
                print(f"Downloaded: {total} bytes (first 1MB)")
                print(f"SHA-256 (first 1MB): {chunk_hash.hexdigest()[:32]}...")
                print(f"\n*** RESULT ***")
                print(f"Before: HTTP 403")
                print(f"After: HTTP {r.status_code}")
                print(f"Content-Type: {ct}")
                print(f"Download: PASS")
            else:
                print(f"FAIL: Content-Type not video: {ct}")
                r.close()
        else:
            body = r.text[:200] if r.text else "(empty)"
            print(f"FAIL: HTTP {r.status_code}")
            print(f"Response body: {body}")
            r.close()
            print(f"\n*** RESULT ***")
            print(f"Before: HTTP 403")
            print(f"After: HTTP {r.status_code}")
            print(f"Download: FAIL")

    except Exception as e:
        print(f"Error: {e}")
        import traceback; traceback.print_exc()
    finally:
        proc.terminate(); proc.wait(timeout=5)

if __name__ == "__main__":
    main()
