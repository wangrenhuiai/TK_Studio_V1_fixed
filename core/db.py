"""SQLite 作品库模块。

数据库结构与 TK_Studio_V1_6_4.py 中的 Database 完全一致，
works 表字段不增不减。DB_FILE 指向项目根目录的 tk_studio.db，
保留现有数据。
"""
import os
import sqlite3
from datetime import datetime

# 数据库文件位于项目根目录（core/db.py 的上一级）。
DB_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tk_studio.db"
)


class Database:
    def __init__(self, path=DB_FILE):
        self.path = path
        self.init_db()

    def connect(self):
        return sqlite3.connect(self.path)

    def init_db(self):
        with self.connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS works (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT UNIQUE,
                    author TEXT,
                    title TEXT,
                    url TEXT,
                    video_url TEXT,
                    cover_url TEXT,
                    duration TEXT,
                    resolution TEXT,
                    download_status TEXT DEFAULT '未下载',
                    local_path TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            con.commit()

    def add_work(self, data):
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as con:
            con.execute("""
                INSERT INTO works
                (video_id, author, title, url, video_url, cover_url,
                 duration, resolution, download_status, local_path,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, '未下载', '', ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    author=excluded.author,
                    title=excluded.title,
                    url=excluded.url,
                    video_url=excluded.video_url,
                    cover_url=excluded.cover_url,
                    duration=excluded.duration,
                    resolution=excluded.resolution,
                    updated_at=excluded.updated_at
            """, (
                data.get("video_id", ""),
                data.get("author", ""),
                data.get("title", ""),
                data.get("url", ""),
                data.get("video_url", ""),
                data.get("cover_url", ""),
                data.get("duration", ""),
                data.get("resolution", ""),
                now, now
            ))
            con.commit()
            row = con.execute(
                "SELECT id FROM works WHERE video_id=?",
                (data.get("video_id", ""),)
            ).fetchone()
            return row[0] if row else None

    def list_works(self, keyword=""):
        with self.connect() as con:
            if keyword:
                rows = con.execute("""
                    SELECT id, author, title, url, duration, resolution,
                           download_status, video_id
                    FROM works
                    WHERE author LIKE ? OR title LIKE ? OR video_id LIKE ?
                    ORDER BY id DESC
                """, (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%")).fetchall()
            else:
                rows = con.execute("""
                    SELECT id, author, title, url, duration, resolution,
                           download_status, video_id
                    FROM works ORDER BY id DESC
                """).fetchall()
        return rows

    def get_work(self, work_id):
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM works WHERE id=?", (work_id,)
            ).fetchone()

    def update_download(self, work_id, status, local_path=""):
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as con:
            con.execute("""
                UPDATE works
                SET download_status=?, local_path=?, updated_at=?
                WHERE id=?
            """, (status, local_path, now, work_id))
            con.commit()


def get_latest_work_id(db):
    rows = db.list_works()
    return rows[0][0] if rows else None
