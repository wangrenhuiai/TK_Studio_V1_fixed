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
import stat
import threading
import time

# ============================================================
# FIX-DL.1：最终文件名并发仲裁
#
# 批量下载（max_concurrent=3）下，同作者多视频的 TikTok 自动标题
# 高度重复（如 "COMMENTARY on TikTok"），同名任务并行会产生：
# - 同一 .part 被两个线程同时写（字节交错损坏）
# - 一个线程启动时的 _cleanup_part_file 删掉另一个线程正在写的 .part
# - os.replace 报「目标文件被占用」（Permission denied 类错误）
# - 同名 .mp4 静默互相覆盖（数据丢失）
#
# 因此最终文件名在下载开始前统一仲裁：
# 1) 进程内 in-flight 注册表（防并发同进程冲突）
# 2) DB 归属查询 works.local_path（防跨会话覆盖其他作品的文件）
# 3) 文件存在检查（防覆盖手工/旧版本残留文件）
# 干净名优先（保持单任务下载体验不变）；冲突时追加 " [video_id]"。
# ============================================================
_FINAL_NAME_LOCK = threading.Lock()
_FINAL_NAME_IN_FLIGHT = {}  # (normcase_abs_dir, filename) -> work_id


def _norm_key(output_dir, filename):
    return (
        os.path.normcase(os.path.abspath(output_dir)),
        os.path.normcase(filename),
    )


def _path_owned_by_other_work(db, work_id, full_path):
    """最终路径是否已被其他作品占用。

    run_download 成功后会把最终路径写入 works.local_path
    （db.update_download），以此作为跨会话归属依据。
    查询失败时保守返回 True（宁可不覆盖）。
    """
    try:
        with db.connect() as con:
            row = con.execute(
                "SELECT 1 FROM works WHERE id<>? AND local_path=? LIMIT 1",
                (work_id, full_path),
            ).fetchone()
        return bool(row)
    except Exception:
        return True


def _claim_final_path(db, work_id, output_dir, title, video_id):
    """仲裁最终 .mp4 文件名，返回 (path, claim_key)。

    干净名（标题.mp4）可用（无并发占用、无其他作品记录、文件不存在，
    或文件本就属于当前作品的重下场景）时直接使用；
    否则依次尝试 "标题 [video_id].mp4"、"标题 [video_id] (2).mp4"...
    claim_key 用于下载结束后释放注册表槽位（_release_final_path）。
    """
    base = safe_name(title, video_id)
    candidates = [base + ".mp4", f"{base} [{video_id}].mp4"]
    candidates += [f"{base} [{video_id}] ({i}).mp4" for i in range(2, 21)]

    claimed_key = None
    for filename in candidates:
        key = _norm_key(output_dir, filename)
        path = os.path.join(output_dir, filename)
        with _FINAL_NAME_LOCK:
            holder = _FINAL_NAME_IN_FLIGHT.get(key)
            if holder is not None and holder != work_id:
                continue  # 并发中被其他作品占用
            if (holder is None
                    and os.path.exists(path)
                    and _path_owned_by_other_work(db, work_id, path)):
                continue  # 已被其他作品下载过，避免静默覆盖
            _FINAL_NAME_IN_FLIGHT[key] = work_id
            claimed_key = key
            return path, claimed_key
    # 20 个候选都失败（极端情况）：退回干净名并让 os.replace 的
    # 占用检测兜底报错，不无限循环。
    path = os.path.join(output_dir, base + ".mp4")
    return path, None


def _release_final_path(claim_key):
    """释放最终文件名注册表槽位（下载结束/失败后调用）。"""
    if claim_key is None:
        return
    with _FINAL_NAME_LOCK:
        _FINAL_NAME_IN_FLIGHT.pop(claim_key, None)


def _force_remove(path):
    """删除文件；只读属性导致的 PermissionError 先清除只读位再删。

    部分同步/安全工具会给残留 .part 加只读属性，单纯退避重试无效。
    """
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return True
    except PermissionError:
        try:
            os.chmod(path, stat.S_IWRITE)
            os.remove(path)
            return True
        except OSError:
            return False
    except OSError:
        return False


def _open_part_resilient(part, mode, progress_cb=None, allow_recreate=False):
    """以目标模式打开 .part 验证可写性，成功后立即关闭，返回 True。

    .part 被其他进程独占锁定（常见为 Windows Defender 实时扫描窗口）时
    PermissionError 短退避重试；重试仍失败且 allow_recreate=True 时删除
    旧文件重建（放弃续传）。全部失败返回 False，由调用方决定报错或降级。
    """
    for delay in (0.0, 0.4, 0.8, 1.6):
        if delay:
            time.sleep(delay)
        try:
            with open(part, mode):
                pass
            return True
        except FileNotFoundError:
            # "ab" 模式下文件中途消失：按全新下载处理。
            return False
        except PermissionError:
            continue
        except OSError:
            return False
    if allow_recreate:
        for delay in (0.0, 0.4, 0.8):
            if delay:
                time.sleep(delay)
            try:
                # FIX-DL.1：只读属性等导致的删除失败用 _force_remove 处理
                _force_remove(part)
                with open(part, "wb"):
                    pass
                return True
            except OSError:
                continue
    return False


def _prepare_part_file(part, progress_cb=None):
    """下载前确保 .part 可写，返回可用于续传的字节数（-1 表示无法写入）。

    - 超小残片（<1KB）无续传价值：直接删除，防止发起坏的 Range 请求，
      同时清理历史失败残留。
    - 续传文件被独占锁定：短退避重试；可删除重建时降级为全新下载
      （以重建后的实际大小为准，保证 Range 头与文件状态一致）。
    - 文件持续被占用或目录不可写：返回 -1，调用方报人话错误，
      .part 保留待用户稍后重试。
    """
    existing = 0
    try:
        existing = os.path.getsize(part) if os.path.exists(part) else 0
    except OSError:
        existing = 0

    if 0 < existing < 1024:
        # FIX-DL.1：只读残片也一并清理
        _force_remove(part)
        existing = 0

    if not existing:
        if _open_part_resilient(part, "wb", progress_cb):
            return 0
        return -1

    if _open_part_resilient(part, "ab", progress_cb, allow_recreate=True):
        # allow_recreate 可能已删除旧文件并重建为空文件：
        # 以重建后的实际大小为准，避免 Range 头与文件内容错位。
        try:
            return os.path.getsize(part)
        except OSError:
            return 0
    return -1


def _cleanup_part_file(part):
    """清理残留 .part 临时文件（最佳努力）。

    - 文件不存在：视为已清理，返回 True
    - 被占用（Windows Defender 实时扫描锁定）：短退避重试删除
    - 只读属性残留：FIX-DL.1，_force_remove 清除只读位后删除
    - 重试仍失败：返回 False，保留文件（后续 _prepare_part_file 兜底）
    """
    for delay in (0.0, 0.5, 1.0, 2.0):
        if delay:
            time.sleep(delay)
        if _force_remove(part):
            return True
        # 只读位已由 _force_remove 处理；仍失败说明被独占锁定，继续退避
    return False


def _part_path_for(db, work_id, output_dir):
    """根据作品记录推导 .part 路径（失败清理时兜底重建路径用）。"""
    try:
        row = _get_work(db, work_id)
        if row:
            video_id, author, title, page_url, _ = row
            return os.path.join(
                output_dir, safe_name(title, video_id) + ".mp4.part"
            )
    except Exception:
        pass
    return None


def _open_write_resilient(part, mode):
    """FIX-DL.1：以写入模式打开 .part，PermissionError 短退避重试。

    - _prepare_part_file 预检通过后、真正写打开前，文件仍可能被
      Windows Defender 等瞬间锁定：退避重试覆盖该窗口。
    - FileNotFoundError：文件在预检后被安全软件隔离删除，转为可重试的
      友好错误（下一次 attempt 会重新准备 .part）。
    - 退避耗尽仍 PermissionError：抛「临时文件无法写入」，由
      run_download 快速短路（本地环境问题，重试无意义）。
    """
    f = None
    for delay in (0.0, 0.4, 0.8, 1.6):
        if delay:
            time.sleep(delay)
        try:
            f = open(part, mode)
            return f
        except FileNotFoundError:
            raise RuntimeError(
                "临时文件被安全软件删除或隔离（如 Windows Defender 实时防护），"
                "正在自动重试下载"
            )
        except PermissionError:
            continue
        except OSError as e:
            raise RuntimeError(f"临时文件无法写入：{e}")
    raise RuntimeError(
        "临时文件无法写入（被其他程序占用，如杀毒软件正在扫描）。"
        "请稍后重试或更换下载目录"
    )


def _replace_with_retry(part, path):
    """.part → .mp4 改名；目标被占用（杀毒扫描/播放器占用）时短退避重试。

    重试窗口覆盖常见的实时扫描锁定（通常 <1s）。全部失败抛出人话错误，
    由 run_download 失败清理逻辑统一处理残留临时文件。
    """
    last = None
    for delay in (0.0, 0.5, 1.0, 2.0):
        if delay:
            time.sleep(delay)
        try:
            os.replace(part, path)
            return
        except FileNotFoundError:
            raise
        except OSError as e:
            last = e
    raise RuntimeError(
        "视频保存失败：目标文件被其他程序占用（如正在播放或杀毒软件扫描中）。"
        f"请稍后重试。({last})"
    )


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
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
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
    # 先确保 .part 可写（清理残片/处理被锁定文件），再据此决定 Range 头，
    # 保证 Range 与实际文件状态一致。
    part = path + ".part"
    existing = _prepare_part_file(part, progress_cb)
    if existing < 0:
        raise RuntimeError(
            "临时文件无法写入（被其他程序占用，如杀毒软件正在扫描，"
            "或下载目录只读）。请关闭相关程序或更换下载目录后重试"
        )
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
    # FIX-DL.1：写打开带退避（预检后仍可能被杀毒扫描瞬间锁定），
    # 写入中 OSError 转友好错误（AV 隔离删除 .part 等）。
    f = _open_write_resilient(part, mode)
    try:
        for chunk in r.iter_content(chunk_size=1024 * 512):
            # 取消检查：在写入前检查，避免继续写入已取消的任务。
            if cancel_check and cancel_check():
                r.close()
                raise RuntimeError("用户取消下载")
            if not chunk:
                continue
            try:
                f.write(chunk)
            except FileNotFoundError:
                raise RuntimeError(
                    "临时文件在写入中被安全软件删除或隔离，正在自动重试下载"
                )
            except PermissionError as e:
                raise RuntimeError(f"临时文件写入被拒绝：{e}")
            done += len(chunk)
            percent = min(99, int(done * 100 / total)) if total else 0
            if progress_cb:
                progress_cb(percent, "下载中", f"{done / 1024 / 1024:.1f} MB")
    finally:
        try:
            f.close()
        except OSError:
            pass
    r.close()

    if not os.path.exists(part) or os.path.getsize(part) < 1024:
        raise RuntimeError("下载文件为空或文件异常")
    _replace_with_retry(part, path)


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
    # FIX-DL.1：本次下载实际使用的 .part 路径与最终名注册表槽位
    # （异常发生在赋值前时保持 None，失败清理与释放逻辑做判空兜底）
    part = None
    claim_key = None
    try:
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        if not video_url:
            raise RuntimeError("没有视频地址，请重新解析作品。")

        os.makedirs(output_dir, exist_ok=True)
        # 目录可写预检：尽早把"目录只读/被安全软件限制"转成明确提示，
        # 避免下载数 MB 后才在写盘时失败。并发下载用线程 id 区分探针文件。
        probe = os.path.join(
            output_dir,
            f"__tk_writetest_{os.getpid()}_{threading.get_ident()}.tmp",
        )
        try:
            with open(probe, "wb") as pf:
                pf.write(b"0")
        except OSError as e:
            raise RuntimeError(
                "下载目录不可写（可能为只读目录或被安全软件限制），"
                "请在下载设置中更换保存目录后重试"
            ) from e
        try:
            os.remove(probe)
        except OSError:
            # 删除失败不影响可写判定（如扫描器短暂锁定）；
            # 探针残片含 pid/tid，下次下载同名覆盖，无累积。
            pass
        row = _get_work(db, work_id)
        if not row:
            raise RuntimeError("找不到作品记录。")

        video_id, author, title, page_url, stored_video_url = row
        # FIX-DL.1：最终文件名仲裁。并发/跨会话/残留同名冲突时自动改用
        # "标题 [video_id].mp4"，防止同名 .part 混写损坏与 .mp4 互相覆盖。
        path, claim_key = _claim_final_path(
            db, work_id, output_dir, title, video_id)
        part = path + ".part"

        # 下载前清理历史残留 .part。
        # 新方案下 .part 跟随最终文件名（并发唯一，不再混写/互删）；
        # 旧版残留的 "标题.mp4.part"（与当前 part 不同名时）一并清理。
        _cleanup_part_file(part)
        legacy_part = os.path.join(
            output_dir, safe_name(title, video_id) + ".mp4.part")
        if os.path.normcase(legacy_part) != os.path.normcase(part):
            _cleanup_part_file(legacy_part)

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
        cookie_items = []

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
                # 临时文件被持续占用/目录不可写：本地环境问题，重试无意义。
                if str(e).startswith("临时文件无法写入"):
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
                # 普通重试退避：给杀毒扫描/网络抖动留出恢复窗口，
                # 避免毫秒级连发重试全部落入同一个锁定/故障状态。
                time.sleep(1.0)

        raise RuntimeError(f"下载失败：{last_error}")

    except Exception as e:
        try:
            db.update_download(work_id, "下载失败")
        except Exception:
            pass
        # 下载失败后自动清理残留临时文件，
        # 避免被锁定的 .part 残留引发后续 Permission denied。
        # 用户主动取消除外：保留 .part 供下次续传。
        # FIX-DL.1：优先使用本次下载实际使用的 .part 路径；
        # 异常发生在路径计算前时回退到 DB 记录重建（旧路径兼容）。
        if str(e) != "用户取消下载":
            try:
                stale_part = part or _part_path_for(db, work_id, output_dir)
                if stale_part:
                    _cleanup_part_file(stale_part)
            except Exception:
                pass
        if failed_cb:
            failed_cb(str(e))
        return video_url
    finally:
        # FIX-DL.1：释放最终文件名注册表槽位（成功/失败/取消都释放）
        _release_final_path(claim_key)
