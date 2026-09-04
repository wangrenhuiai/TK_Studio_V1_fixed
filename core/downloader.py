"""TikTok 视频下载业务逻辑模块。

从 DownloadWorker 中剥离出的纯下载逻辑，不依赖 PySide6。
通过 progress_cb / finished_cb / failed_cb 回调向外部报告状态，
由 workers.download_worker.DownloadWorker 负责转发为 Qt Signal。

行为与 TK_Studio_V1_6_4.py 中的 DownloadWorker 完全一致：
- safe filename
- Chrome-like headers
- Range + .part 断点续传
- HTTP status / Content-Type 检查
- 206 append / 200 restart
- os.replace
- urllib3 Retry
- 403/404/410 → Chrome 刷新 video_url → 重试
- Cookie 注入
- 下载状态更新到 SQLite
"""
import os


def safe_name(title, video_id):
    safe = "".join(c for c in (title or video_id or "tiktok_video")
                   if c not in '<>:"/\\|?*').strip()
    return (safe or video_id or "tiktok_video")[:100]


def build_headers(page_url, range_header=None):
    h = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
        "Referer": page_url or "https://www.tiktok.com/",
        "Origin": "https://www.tiktok.com",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
    }
    if range_header:
        h["Range"] = range_header
    return h


def refresh_video_url(page_url, progress_cb=None):
    """通过 Chrome CDP 刷新视频地址。返回 (video_url, cookie_items)。"""
    if not page_url:
        return "", []
    if progress_cb:
        progress_cb(0, "刷新视频地址", "正在用独立 Chrome 重新获取页面和会话 Cookie")
    from core.chrome_bridge import chrome_render_with_cookies
    from core.parser import extract_tiktok_data

    rendered, cookie_items = chrome_render_with_cookies(page_url)
    if not rendered:
        return "", cookie_items
    data = extract_tiktok_data(rendered)
    return data.get("video_url", ""), cookie_items


def download_once(url, page_url, path, session, cookie_items=None,
                  progress_cb=None, cancel_check=None):
    """单次下载（含断点续传）。progress_cb(percent, status, message)。

    cancel_check: 可选回调，返回 True 表示用户请求取消，
    会在写入前抛 RuntimeError("用户取消下载")。
    """
    # Start a fresh file for the first request. If a partial .part exists,
    # resume it with Range; this is useful when the connection drops.
    part = path + ".part"
    existing = os.path.getsize(part) if os.path.exists(part) else 0
    range_header = f"bytes={existing}-" if existing else None
    headers = build_headers(page_url, range_header)

    if cookie_items:
        # 使用 Chrome CDP 获取的会话 Cookie，不读取 Cookies SQLite。
        session.cookies.clear()
        cookie_pairs = []
        for item in cookie_items:
            try:
                name = item.get("name", "")
                value = item.get("value", "")
                if name:
                    cookie_pairs.append(f"{name}={value}")
                    session.cookies.set(name, value, domain=item.get("domain") or None, path="/")
            except Exception:
                pass
        if cookie_pairs:
            headers["Cookie"] = "; ".join(cookie_pairs)

    # TikTok CDN 对 Range/浏览器请求特征更敏感
    headers["Sec-Fetch-Dest"] = "video"
    headers["Sec-Fetch-Mode"] = "cors"
    headers["Sec-Fetch-Site"] = "cross-site"

    r = session.get(url, headers=headers, stream=True,
                    timeout=(20, 90), allow_redirects=True)
    status = r.status_code
    content_type = (r.headers.get("content-type") or "").lower()

    if status in (401, 403, 404, 410):
        r.close()
        raise RuntimeError(f"HTTP {status}：视频地址可能已过期或当前请求被拒绝")
    if status >= 400:
        r.close()
        raise RuntimeError(f"HTTP {status}")
    if "text/html" in content_type:
        r.close()
        raise RuntimeError("服务器返回网页而不是视频文件，视频地址可能已过期")

    # If server ignored Range, restart the partial file rather than
    # appending the whole response to it.
    append = existing > 0 and status == 206
    if not append:
        existing = 0

    total = 0
    if status == 206:
        cr = r.headers.get("content-range", "")
        try:
            total = int(cr.rsplit("/", 1)[1])
        except Exception:
            total = 0
    if not total:
        try:
            total = int(r.headers.get("content-length", "0") or 0) + existing
        except Exception:
            total = 0

    done = existing
    mode = "ab" if append else "wb"
    with open(part, mode) as f:
        for chunk in r.iter_content(chunk_size=1024 * 512):
            # 取消检查：在写入前检查，避免继续写入已取消的任务。
            if cancel_check and cancel_check():
                r.close()
                raise RuntimeError("用户取消下载")
            if not chunk:
                continue
            f.write(chunk)
            done += len(chunk)
            percent = min(99, int(done * 100 / total)) if total else 0
            if progress_cb:
                progress_cb(percent, "下载中", f"{done / 1024 / 1024:.1f} MB")
    r.close()

    if not os.path.exists(part) or os.path.getsize(part) < 1024:
        raise RuntimeError("下载文件为空或文件异常")
    os.replace(part, path)


def _get_work(db, work_id):
    """保持与原 DownloadWorker._get_work 一致的查询（直接 SQL，不改行为）。"""
    with db.connect() as con:
        return con.execute(
            "SELECT video_id, author, title, url, video_url FROM works WHERE id=?",
            (work_id,)
        ).fetchone()


def run_download(work_id, video_url, output_dir, db,
                 progress_cb=None, finished_cb=None, failed_cb=None,
                 cancel_check=None):
    """下载主循环。对应原 DownloadWorker.run()。

    progress_cb(percent, status, message)
    finished_cb(path)
    failed_cb(error)
    cancel_check: 可选回调，返回 True 表示用户请求取消。
    """
    try:
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        if not video_url:
            raise RuntimeError("没有视频地址，请重新解析作品。")

        os.makedirs(output_dir, exist_ok=True)
        row = _get_work(db, work_id)
        if not row:
            raise RuntimeError("找不到作品记录。")

        video_id, author, title, page_url, stored_video_url = row
        filename = safe_name(title, video_id) + ".mp4"
        path = os.path.join(output_dir, filename)
        part = path + ".part"

        session = requests.Session()
        retry = Retry(
            total=2, connect=2, read=2, status=2,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        session.mount("http://", HTTPAdapter(max_retries=retry))
        session.mount("https://", HTTPAdapter(max_retries=retry))

        db.update_download(work_id, "下载中")
        if progress_cb:
            progress_cb(0, "准备下载", "")

        # 先使用现有地址尝试；如果服务器拒绝，再通过 Chrome CDP
        # 获取新的签名地址和 Cookie。这样完全绕开 Chrome Cookies
        # SQLite 文件的锁定/权限问题。
        last_error = None
        urls = [video_url]
        refreshed = False
        # Phase 7-F：首次请求前尝试从 cookie_cache 取 parse 阶段获取的 cookies，
        # 使 attempt 1 即带登录态 cookies，避免无 cookies → 403 → refresh → 403 循环。
        # cookie_cache 为纯内存，未命中返回 []，走现有 refresh fallback。
        from core import cookie_cache
        cookie_items = cookie_cache.get_cookie(video_id) if video_id else []

        for attempt in range(1, 4):
            # 每次 attempt 开始前检查取消：已取消则不再发起新请求。
            if cancel_check and cancel_check():
                raise RuntimeError("用户取消下载")
            url = urls[-1]
            if progress_cb:
                progress_cb(0, "连接中", f"第 {attempt}/3 次")
            try:
                download_once(url, page_url, path, session, cookie_items,
                              progress_cb, cancel_check)
                db.update_download(work_id, "已下载", path)
                if progress_cb:
                    progress_cb(100, "已下载", path)
                if finished_cb:
                    finished_cb(path)
                return video_url
            except Exception as e:
                last_error = e
                # 用户取消：立即抛出，不进入 refresh，也不重试。
                if str(e) == "用户取消下载":
                    raise
                # A signed TikTok media URL can expire. Refresh the page
                # once and retry with the newly extracted URL.
                if (not refreshed and page_url and
                        any(x in str(e) for x in ("403", "404", "410", "过期"))):
                    refreshed = True
                    fresh, cookie_items = refresh_video_url(page_url, progress_cb)
                    # refresh 可能耗时较长，返回后再次检查取消，
                    # 避免用户已取消却继续下一次下载。
                    if cancel_check and cancel_check():
                        raise RuntimeError("用户取消下载")
                    if fresh:
                        urls.append(fresh)
                        video_url = fresh
                        db.add_work({
                            "video_id": video_id,
                            "author": author,
                            "title": title,
                            "url": page_url,
                            "video_url": fresh,
                            "cover_url": "",
                            "duration": "",
                            "resolution": "",
                        })
                        if progress_cb:
                            progress_cb(
                                0, "已刷新地址",
                                "已取得 Chrome 会话，重新尝试下载"
                            )
                        continue
                if progress_cb:
                    progress_cb(0, "重试", str(e))

        raise RuntimeError(f"下载失败：{last_error}")

    except Exception as e:
        try:
            db.update_download(work_id, "下载失败")
        except Exception:
            pass
        if failed_cb:
            failed_cb(str(e))
        return video_url
