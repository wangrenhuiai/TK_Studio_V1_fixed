"""SQLite 作品库模块。

数据库结构与 TK_Studio_V1_6_4.py 中的 Database 完全一致，
works 表字段不增不减。

新增：
download_tasks 下载任务表

Phase 5-B.1.1：
- 增加下载任务状态管理
- 支持等待中 / 下载中 / 完成 / 失败 / 取消
- 支持启动时恢复异常任务
- 保持 works 原有字段结构不变
"""

import os
import sqlite3
from datetime import datetime


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

            # ==================================================
            # 原作品表
            # ==================================================

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


            # ==================================================
            # 下载任务表
            # ==================================================

            con.execute("""
                CREATE TABLE IF NOT EXISTS download_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_id INTEGER,
                    source TEXT,
                    status TEXT,
                    progress INTEGER DEFAULT 0,
                    message TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)


            con.commit()


    # ==========================================================
    # 作品管理
    # ==========================================================

    def add_work(self, data):

        now = datetime.now().isoformat(
            timespec="seconds"
        )

        with self.connect() as con:

            con.execute("""
                INSERT INTO works
                (
                    video_id,
                    author,
                    title,
                    url,
                    video_url,
                    cover_url,
                    duration,
                    resolution,
                    download_status,
                    local_path,
                    created_at,
                    updated_at
                )

                VALUES
                (
                    ?, ?, ?, ?, ?, ?, ?, ?, '未下载', '', ?, ?
                )

                ON CONFLICT(video_id) DO UPDATE SET

                    author=excluded.author,
                    title=excluded.title,
                    url=excluded.url,
                    video_url=excluded.video_url,
                    cover_url=excluded.cover_url,
                    duration=excluded.duration,
                    resolution=excluded.resolution,
                    updated_at=excluded.updated_at

            """,
            (
                data.get("video_id", ""),
                data.get("author", ""),
                data.get("title", ""),
                data.get("url", ""),
                data.get("video_url", ""),
                data.get("cover_url", ""),
                data.get("duration", ""),
                data.get("resolution", ""),
                now,
                now
            ))


            con.commit()


            row = con.execute(
                """
                SELECT id
                FROM works
                WHERE video_id=?
                """,
                (
                    data.get("video_id", ""),
                )
            ).fetchone()


            return row[0] if row else None


    def list_works(self, keyword=""):

        with self.connect() as con:

            if keyword:

                rows = con.execute("""
                    SELECT
                        id,
                        author,
                        title,
                        url,
                        duration,
                        resolution,
                        download_status,
                        video_id
                    FROM works
                    WHERE
                        author LIKE ?
                        OR title LIKE ?
                        OR video_id LIKE ?
                    ORDER BY id DESC
                """,
                (
                    f"%{keyword}%",
                    f"%{keyword}%",
                    f"%{keyword}%"
                )).fetchall()

            else:

                rows = con.execute("""
                    SELECT
                        id,
                        author,
                        title,
                        url,
                        duration,
                        resolution,
                        download_status,
                        video_id
                    FROM works
                    ORDER BY id DESC
                """).fetchall()


        return rows


    def get_work(self, work_id):

        with self.connect() as con:

            return con.execute(
                """
                SELECT *
                FROM works
                WHERE id=?
                """,
                (
                    work_id,
                )
            ).fetchone()


    def update_download(
        self,
        work_id,
        status,
        local_path=""
    ):

        now = datetime.now().isoformat(
            timespec="seconds"
        )

        with self.connect() as con:

            con.execute("""
                UPDATE works

                SET
                    download_status=?,
                    local_path=?,
                    updated_at=?

                WHERE id=?

            """,
            (
                status,
                local_path,
                now,
                work_id
            ))

            con.commit()


    def delete_work(self, work_id):

        with self.connect() as con:

            cur = con.execute(
                """
                DELETE FROM works
                WHERE id=?
                """,
                (
                    work_id,
                )
            )

            con.commit()

            return cur.rowcount > 0


    # ==========================================================
    # 下载任务管理
    # ==========================================================

    def create_download_task(
        self,
        work_id,
        source
    ):

        now = datetime.now().isoformat(
            timespec="seconds"
        )

        with self.connect() as con:

            cur = con.execute("""
                INSERT INTO download_tasks
                (
                    work_id,
                    source,
                    status,
                    progress,
                    message,
                    created_at,
                    updated_at
                )

                VALUES
                (
                    ?, ?, '等待中', 0, '', ?, ?
                )

            """,
            (
                work_id,
                source,
                now,
                now
            ))

            con.commit()

            return cur.lastrowid


    def get_download_task(self, task_id):

        with self.connect() as con:

            return con.execute(
                """
                SELECT *
                FROM download_tasks
                WHERE id=?
                """,
                (
                    task_id,
                )
            ).fetchone()


    def list_download_tasks(self):

        with self.connect() as con:

            return con.execute(
                """
                SELECT *
                FROM download_tasks
                ORDER BY id DESC
                """
            ).fetchall()


    def update_download_task(
        self,
        task_id,
        status=None,
        progress=None,
        message=None
    ):

        now = datetime.now().isoformat(
            timespec="seconds"
        )

        with self.connect() as con:

            row = con.execute(
                """
                SELECT *
                FROM download_tasks
                WHERE id=?
                """,
                (
                    task_id,
                )
            ).fetchone()


            if not row:
                return False


            con.execute("""
                UPDATE download_tasks

                SET
                    status=?,
                    progress=?,
                    message=?,
                    updated_at=?

                WHERE id=?

            """,
            (
                status if status is not None else row[3],
                progress if progress is not None else row[4],
                message if message is not None else row[5],
                now,
                task_id
            ))


            con.commit()


        return True


    def get_active_tasks_by_work(
        self,
        work_id
    ):

        """获取指定作品当前仍然有效的下载任务。

        只有：
            等待中
            下载中

        才属于 active task。

        完成 / 失败 / 取消 都不再阻止重新下载。
        """

        with self.connect() as con:

            return con.execute("""
                SELECT *
                FROM download_tasks
                WHERE
                    work_id=?
                    AND status IN ('等待中', '下载中')
                ORDER BY id DESC
            """,
            (
                work_id,
            )).fetchall()


    def reset_download_tasks_on_startup(self):

        """程序启动时恢复异常退出的下载任务。

        旧任务如果停留在：
            等待中
            下载中

        说明上一次程序可能异常退出。

        这些任务统一标记为：
            失败
        """

        now = datetime.now().isoformat(
            timespec="seconds"
        )

        with self.connect() as con:

            cur = con.execute("""
                UPDATE download_tasks

                SET
                    status='失败',
                    message='程序异常退出',
                    updated_at=?

                WHERE status IN ('下载中', '等待中')

            """,
            (
                now,
            ))


            con.commit()

            return cur.rowcount


    def reset_downloading_to_failed(self):

        """兼容 MainWindow 启动恢复逻辑。

        将异常退出残留的：

            works.download_status='下载中'

        恢复为：

            works.download_status='下载失败'

        同时将 download_tasks 中残留的：

            等待中
            下载中

        恢复为：

            失败
        """

        now = datetime.now().isoformat(
            timespec="seconds"
        )

        with self.connect() as con:

            # ----------------------------------------------
            # 恢复 works 表中的异常下载状态
            # ----------------------------------------------

            work_cur = con.execute("""
                UPDATE works

                SET
                    download_status='下载失败',
                    updated_at=?

                WHERE download_status='下载中'

            """,
            (
                now,
            ))


            # ----------------------------------------------
            # 恢复 download_tasks 表中的异常任务
            # ----------------------------------------------

            task_cur = con.execute("""
                UPDATE download_tasks

                SET
                    status='失败',
                    message='程序异常退出',
                    updated_at=?

                WHERE status IN ('下载中', '等待中')

            """,
            (
                now,
            ))


            con.commit()


            return (
                work_cur.rowcount
                +
                task_cur.rowcount
            )


    def delete_tasks_by_work(self, work_id):

        """删除指定作品对应的所有下载任务记录。"""

        with self.connect() as con:

            cur = con.execute(
                """
                DELETE FROM download_tasks
                WHERE work_id=?
                """,
                (
                    work_id,
                )
            )

            con.commit()

            return cur.rowcount > 0


# ==============================================================
# 工具函数
# ==============================================================

def get_latest_work_id(db):

    rows = db.list_works()

    return rows[0][0] if rows else None