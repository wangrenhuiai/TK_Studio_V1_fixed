"""Phase 8-D 真实视频下载验证脚本。

使用修改后的 build_headers() 测试真实 TikTok 视频下载。
"""
import os
import sys
import time
import hashlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PAGE_URL = "https://www.tiktok.com/@rfbxha/video/7681265056633326878"


def main():
    from core.chrome_bridge import load_with_chrome
    from core.parser import extract_tiktok_data
    from core.downloader import build_headers
    import requests

    # Step 1: 获取 video_url（Chrome fallback）
    print("=" * 60)
    print("Step 1: Chrome fallback 获取 video_url")
    print("=" * 60)
    html = load_with_chrome(PAGE_URL)
    if not html:
        print("FAIL: Chrome fallback 返回空 HTML")
        return

    data = extract_tiktok_data(html)
    video_url = data.get("video_url", "")
    title = data.get("title", "")
    print(f"Title: {title[:60]}...")
    print(f"Video URL length: {len(video_url)}")
    print(f"Video URL (first 80): {video_url[:80]}...")

    if not video_url:
        print("FAIL: No video_url extracted")
        return

    # Step 2: 用修改后的 build_headers 请求下载
    print("\n" + "=" * 60)
    print("Step 2: 下载器请求（修改后 build_headers）")
    print("=" * 60)

    headers = build_headers(PAGE_URL)
    print("Headers:")
    for k, v in headers.items():
        print(f"  {k}: {v[:60]}")

    session = requests.Session()
    session.headers.clear()

    print(f"\nRequesting video URL...")
    try:
        r = session.get(video_url, headers=headers, stream=True,
                        timeout=(20, 60), allow_redirects=True)
        print(f"HTTP Status: {r.status_code}")
        print(f"Content-Type: {r.headers.get('content-type', 'N/A')}")
        print(f"Content-Length: {r.headers.get('content-length', 'N/A')}")

        if r.status_code in (200, 206):
            content_type = r.headers.get("content-type", "")
            if "video" in content_type.lower():
                # 下载前 1MB 验证
                print("\nDownloading first 1MB to verify...")
                chunk_hash = hashlib.sha256()
                total = 0
                for chunk in r.iter_content(chunk_size=8192):
                    chunk_hash.update(chunk)
                    total += len(chunk)
                    if total >= 1024 * 1024:  # 1MB
                        break
                r.close()
                print(f"Downloaded: {total} bytes")
                print(f"SHA-256 (first 1MB): {chunk_hash.hexdigest()[:32]}...")
                print(f"\n*** DOWNLOAD: PASS ***")
                print(f"Before: HTTP 403")
                print(f"After: HTTP {r.status_code}")
                print(f"Content-Type: {content_type}")
            else:
                print(f"FAIL: Content-Type is not video: {content_type}")
                r.close()
        else:
            print(f"FAIL: HTTP {r.status_code}")
            # 打印响应体前 200 字符
            body = r.text[:200] if r.text else "(empty)"
            print(f"Response body: {body}")
            r.close()
            print(f"\nBefore: HTTP 403")
            print(f"After: HTTP {r.status_code}")
            print(f"Download: FAIL")

    except Exception as e:
        print(f"Request failed: {e}")
        print(f"Download: FAIL")


if __name__ == "__main__":
    main()
