"""Phase FIX-DL.1 专项测试：下载模块权限问题加固。

覆盖：
1. 只读残留 .part 的强制删除
2. .part 被外部进程锁定：写打开退避后成功 / 持续锁定时友好报错
3. 并发同名下载（同标题不同 video_id）：文件名仲裁 + 无损坏
4. 跨会话同名保护：不覆盖其他作品已下载的文件
5. 下载完成后 .part 无残留
6. 同作品重下允许覆盖自身
"""
import ctypes
import hashlib
import http.server
import os
import shutil
import sys
import threading
import time

import pytest

from core.db import Database
from core.downloader import (
    _cleanup_part_file,
    _force_remove,
    _open_write_resilient,
    _claim_final_path,
    _release_final_path,
    run_download,
)

win32_only = pytest.mark.skipif(sys.platform != "win32",
                                reason="Windows 独占句柄模拟")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _exclusive_open(path):
    """Windows 独占打开文件（dwShareMode=0），模拟杀毒软件实时扫描。

    持有句柄期间，其他进程/线程对该文件的 open()/os.remove()/os.replace()
    均报 PermissionError（WinError 32 共享冲突），与真实 Defender 场景一致。
    返回句柄或 None。
    """
    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = -1
    h = ctypes.windll.kernel32.CreateFileW(
        str(path), GENERIC_READ | GENERIC_WRITE, 0, None,
        OPEN_EXISTING, 0, None)
    if h == INVALID_HANDLE_VALUE or h is None:
        return None
    return h


def _close_handle(h):
    if h is not None:
        ctypes.windll.kernel32.CloseHandle(h)

DATA_A = bytes(range(256)) * 8192          # 2 MiB，模式 A
DATA_B = bytes(range(255, -1, -1)) * 8192  # 2 MiB，模式 B


# ------------------------------------------------------------
# 工具
# ------------------------------------------------------------

def _make_work(db, video_id, title, video_url):
    work_id = db.add_work({
        "video_id": video_id,
        "author": "tester",
        "title": title,
        "url": f"https://www.tiktok.com/@tester/video/{video_id}",
        "video_url": video_url,
        "cover_url": "",
        "duration": "",
        "resolution": "",
    })
    return work_id


class _FileHandler(http.server.BaseHTTPRequestHandler):
    files = {}

    def do_GET(self):
        data = self.files.get(self.path)
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # 静默
        pass


@pytest.fixture(scope="module")
def http_server():
    handler = type("H", (_FileHandler,), {"files": {
        "/a.bin": DATA_A,
        "/b.bin": DATA_B,
    }})
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as srv:
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        port = srv.server_address[1]
        yield f"http://127.0.0.1:{port}"
        srv.shutdown()


# ------------------------------------------------------------
# 1. 只读残留 .part 强制删除
# ------------------------------------------------------------

def test_force_remove_readonly_part(tmp_path):
    part = tmp_path / "x.mp4.part"
    part.write_bytes(b"0" * 4096)
    os.chmod(part, 0o444)  # 只读
    assert _force_remove(str(part)) is True
    assert not part.exists()


def test_cleanup_part_file_readonly(tmp_path):
    part = tmp_path / "y.mp4.part"
    part.write_bytes(b"0" * 4096)
    os.chmod(part, 0o444)
    assert _cleanup_part_file(str(part)) is True
    assert not part.exists()


# ------------------------------------------------------------
# 2. .part 被外部锁定：写打开退避
# ------------------------------------------------------------

@win32_only
def test_open_write_resilient_lock_released(tmp_path):
    """独占锁 0.5s 后释放：退避重试应成功打开。"""
    part = tmp_path / "lock.mp4.part"
    part.write_bytes(b"z" * 1024)
    h = _exclusive_open(part)
    assert h is not None, "独占句柄创建失败"

    def release():
        time.sleep(0.5)
        _close_handle(h)

    threading.Thread(target=release, daemon=True).start()
    try:
        f = _open_write_resilient(str(part), "ab")
        assert f is not None
        f.close()
    finally:
        _close_handle(h)
        _cleanup_part_file(str(part))


@win32_only
def test_open_write_resilient_lock_exhausted(tmp_path):
    """持续独占锁定：退避耗尽后报「临时文件无法写入」（快速短路前缀）。"""
    part = tmp_path / "lock2.mp4.part"
    part.write_bytes(b"z" * 1024)
    h = _exclusive_open(part)
    assert h is not None, "独占句柄创建失败"
    try:
        with pytest.raises(RuntimeError) as ei:
            _open_write_resilient(str(part), "ab")
        assert "临时文件无法写入" in str(ei.value)
    finally:
        _close_handle(h)
        _cleanup_part_file(str(part))


@win32_only
def test_prepare_part_file_locked_then_recover(http_server, tmp_path):
    """run_download 级别：.part 被独占锁定 1s 后释放，下载应自动恢复完成。"""
    out = tmp_path / "dl4"
    db = Database(str(tmp_path / "t4.db"))
    out.mkdir()
    url = http_server + "/a.bin"
    wid = _make_work(db, "6666666666666666666", "locky video", url)

    # 预置一个会被续传的 .part 并独占锁定 1s（模拟 Defender 扫描窗口）
    part = out / "locky video.mp4.part"
    part.write_bytes(b"\x00" * 4096)
    h = _exclusive_open(part)

    def release():
        time.sleep(1.0)
        _close_handle(h)

    threading.Thread(target=release, daemon=True).start()
    try:
        ev = {}
        run_download(wid, url, str(out), db,
                     finished_cb=lambda p: ev.setdefault("ok", p),
                     failed_cb=lambda e: ev.setdefault("fail", e))
        assert "ok" in ev and not ev.get("fail"), ev
        # 预置 4KB 残片被锁定：锁释放后清理/重建，最终内容必须完整正确
        with open(out / "locky video.mp4", "rb") as f:
            assert _sha(f.read()) == _sha(DATA_A)
        assert not part.exists(), "下载完成后 .part 应消失"
    finally:
        _close_handle(h)


# ------------------------------------------------------------
# 3. 并发同名下载：文件名仲裁 + 无损坏
# ------------------------------------------------------------

def _run_download_async(db, work_id, url, out, results, idx):
    events = {"ok": [], "fail": []}
    run_download(
        work_id, url, out, db,
        finished_cb=lambda p: events["ok"].append(p),
        failed_cb=lambda e: events["fail"].append(e),
    )
    results[idx] = events


def test_concurrent_same_title_downloads(http_server, tmp_path):
    """同标题不同 video_id 并行下载：互不干扰、文件名去重、内容不损坏。"""
    out = tmp_path / "dl"
    db = Database(str(tmp_path / "t.db"))
    out.mkdir()

    url_a = http_server + "/a.bin"
    url_b = http_server + "/b.bin"
    wid_a = _make_work(db, "1111111111111111111", "COMMENTARY on TikTok", url_a)
    wid_b = _make_work(db, "2222222222222222222", "COMMENTARY on TikTok", url_b)

    results = {}
    threads = [
        threading.Thread(target=_run_download_async,
                         args=(db, wid_a, url_a, str(out), results, 0)),
        threading.Thread(target=_run_download_async,
                         args=(db, wid_b, url_b, str(out), results, 1)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not results[0]["fail"], results[0]["fail"]
    assert not results[1]["fail"], results[1]["fail"]

    names = sorted(os.listdir(out))
    # 一个干净名 + 一个带 video_id 的去重名；且无 .part 残留
    mp4s = [n for n in names if n.endswith(".mp4")]
    parts = [n for n in names if n.endswith(".part")]
    assert len(mp4s) == 2
    assert parts == []
    assert "COMMENTARY on TikTok.mp4" in mp4s
    # 去重名携带的 video_id 取决于线程调度顺序（谁先占名谁用干净名），
    # 因此断言须对称：另一个文件应携带任一 video_id 后缀。
    other = [n for n in mp4s if n != "COMMENTARY on TikTok.mp4"][0]
    assert "[1111111111111111111]" in other or "[2222222222222222222]" in other

    # 内容完整性：无字节交错损坏（哈希比较，避免 pytest 对大字节串 diff）。
    # 干净名文件的归属由线程调度决定，按 other 的 video_id 反推。
    vid_b_suffix = "[2222222222222222222]"
    with open(out / "COMMENTARY on TikTok.mp4", "rb") as f:
        clean_hash = _sha(f.read())
    with open(out / other, "rb") as f:
        other_hash = _sha(f.read())
    if vid_b_suffix in other:
        # other = work_b → 干净名 = work_a
        assert clean_hash == _sha(DATA_A)
        assert other_hash == _sha(DATA_B)
    else:
        # other = work_a → 干净名 = work_b
        assert clean_hash == _sha(DATA_B)
        assert other_hash == _sha(DATA_A)


def test_claim_release_registry():
    """注册表占用检测与释放。"""
    key1 = key2 = None
    try:
        path1, key1 = _claim_final_path(None, 1, "Z:/nonexistent_dir",
                                        "same title", "aaa")
        path2, key2 = _claim_final_path(None, 2, "Z:/nonexistent_dir",
                                        "same title", "bbb")
        # 同目录同标题：第二个必须去重（目录不存在时 exists=False，
        # 但注册表占用生效；DB 参数传 None 会触发 _path_owned_by_other_work
        # 的异常兜底 → 保守视为占用 → 第二个候选去重）
        assert path1 != path2
    finally:
        _release_final_path(key1)
        _release_final_path(key2)


# ------------------------------------------------------------
# 4. 跨会话同名保护（已有同名 mp4 不覆盖）
# ------------------------------------------------------------

def test_cross_session_no_overwrite(http_server, tmp_path):
    """其他作品已下载过同名文件：新任务不得覆盖，改用去重名。"""
    out = tmp_path / "dl2"
    db = Database(str(tmp_path / "t2.db"))
    out.mkdir()

    url_a = http_server + "/a.bin"
    url_b = http_server + "/b.bin"
    wid_a = _make_work(db, "3333333333333333333", "same title", url_a)
    wid_b = _make_work(db, "4444444444444444444", "same title", url_b)

    # 会话 1：作品 A 完成下载（干净名）
    ev1 = {}
    run_download(wid_a, url_a, str(out), db,
                 finished_cb=lambda p: ev1.setdefault("ok", p),
                 failed_cb=lambda e: ev1.setdefault("fail", e))
    assert "ok" in ev1 and not ev1.get("fail")
    clean = out / "same title.mp4"
    assert clean.exists()

    # 会话 2：作品 B（同名不同视频）不得覆盖 A 的文件
    ev2 = {}
    run_download(wid_b, url_b, str(out), db,
                 finished_cb=lambda p: ev2.setdefault("ok", p),
                 failed_cb=lambda e: ev2.setdefault("fail", e))
    assert "ok" in ev2 and not ev2.get("fail")

    assert clean.exists()
    with open(clean, "rb") as f:
        assert _sha(f.read()) == _sha(DATA_A)  # A 的内容未被覆盖
    dedup = out / "same title [4444444444444444444].mp4"
    assert dedup.exists()
    with open(dedup, "rb") as f:
        assert _sha(f.read()) == _sha(DATA_B)


# ------------------------------------------------------------
# 5. 重下同一作品允许覆盖自身
# ------------------------------------------------------------

def test_same_work_redownload_overwrites_own(http_server, tmp_path):
    out = tmp_path / "dl3"
    db = Database(str(tmp_path / "t3.db"))
    out.mkdir()
    url = http_server + "/a.bin"
    wid = _make_work(db, "5555555555555555555", "my video", url)

    ev1 = {}
    run_download(wid, url, str(out), db,
                 finished_cb=lambda p: ev1.setdefault("ok", p))
    assert "ok" in ev1

    # 同一作品重新排队下载：应覆盖自己的旧文件，而不是去重
    ev2 = {}
    run_download(wid, url, str(out), db,
                 finished_cb=lambda p: ev2.setdefault("ok", p))
    assert "ok" in ev2 and not ev2.get("fail")
    assert (out / "my video.mp4").exists()
    assert not any("[" in n for n in os.listdir(out))
