"""FIX-DB.1 测试：SQLite 多线程并发写稳定性。

覆盖：
1. WAL 模式已启用
2. busy_timeout 已设置
3. 多线程并发写入不报 "database is locked"
4. 并发写入数据完整性
"""
import os
import threading
import time

import pytest

from core.db import Database


def test_wal_mode_enabled(tmp_path):
    """WAL 模式应已启用。"""
    db = Database(str(tmp_path / "t.db"))
    with db.connect() as con:
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal", f"journal_mode={mode}, 期望 wal"


def test_busy_timeout_set(tmp_path):
    """busy_timeout 应为 5000ms。"""
    db = Database(str(tmp_path / "t.db"))
    with db.connect() as con:
        bt = con.execute("PRAGMA busy_timeout").fetchone()[0]
    assert bt == 5000, f"busy_timeout={bt}, 期望 5000"


def test_concurrent_writes_no_lock(tmp_path):
    """4 线程并发写入 50 条记录，不应出现 "database is locked"。

    每个线程获取独立连接（模拟多 worker），并发执行 INSERT + COMMIT。
    """
    db = Database(str(tmp_path / "t.db"))
    # 确保 download_tasks 表存在
    with db.connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS works (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT UNIQUE,
                author TEXT, title TEXT, url TEXT,
                video_url TEXT, cover_url TEXT,
                duration TEXT, resolution TEXT,
                download_status TEXT DEFAULT '未下载',
                local_path TEXT,
                created_at TEXT, updated_at TEXT
            )
        """)
        con.commit()

    errors = []
    total = 48
    per_thread = total // 4  # 48 / 4 = 12

    def writer(thread_idx):
        try:
            for i in range(per_thread):
                vid = f"t{thread_idx}_{i:04d}"
                with db.connect() as con:
                    con.execute(
                        "INSERT OR REPLACE INTO works "
                        "(video_id, author, title, url, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (vid, f"thread{thread_idx}", f"title_{i}", "", ""),
                    )
                    con.commit()
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"并发写入出错: {errors}"

    # 验证记录数
    with db.connect() as con:
        count = con.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    assert count == total, f"记录数={count}, 期望 {total}"


def test_concurrent_update_progress(tmp_path):
    """模拟 3 个 worker 并发更新下载进度（高频写）。

    每个 worker 对自己的 task 执行 20 次 UPDATE，验证不锁库。
    """
    db = Database(str(tmp_path / "t.db"))
    task_ids = []
    for i in range(3):
        wid = db.add_work({
            "video_id": f"vid_{i:04d}",
            "author": "test",
            "title": f"video_{i}",
            "url": f"http://example.com/{i}",
            "video_url": f"http://example.com/{i}.mp4",
            "cover_url": "",
            "duration": "",
            "resolution": "",
        })
        tid = db.create_download_task(wid, "tiktok")
        task_ids.append(tid)

    errors = []
    updates_per_worker = 20

    def progress_updater(task_id, idx):
        try:
            for p in range(updates_per_worker):
                with db.connect() as con:
                    con.execute(
                        "UPDATE download_tasks SET progress=?, updated_at=? "
                        "WHERE id=?",
                        (p, str(p), task_id),
                    )
                    con.commit()
                time.sleep(0.001)
        except Exception as e:
            errors.append(str(e))

    threads = [
        threading.Thread(target=progress_updater, args=(tid, i))
        for i, tid in enumerate(task_ids)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"并发进度更新出错: {errors}"

    # 验证最终进度
    for tid in task_ids:
        with db.connect() as con:
            row = con.execute(
                "SELECT progress FROM download_tasks WHERE id=?", (tid,)
            ).fetchone()
        assert row is not None, f"task_id={tid} 不存在"
        assert row[0] == updates_per_worker - 1, (
            f"task_id={tid} progress={row[0]}, "
            f"期望 {updates_per_worker - 1}"
        )
