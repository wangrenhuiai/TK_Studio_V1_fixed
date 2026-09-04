from pathlib import Path

p = Path("core/db.py")

text = p.read_text(encoding="utf-8")


# 1. 在 init_db 中增加 download_tasks 表
if "CREATE TABLE IF NOT EXISTS download_tasks" not in text:

    old = """
            con.commit()
"""

    new = """
            con.execute(\"\"\"
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
            \"\"\")

            con.commit()
"""

    text = text.replace(old, new, 1)


# 2. 增加 Database 方法
if "def create_download_task" not in text:

    methods = r'''

    # ==========================
    # 下载任务管理
    # ==========================

    def create_download_task(self, work_id, source):
        now = datetime.now().isoformat(timespec="seconds")

        with self.connect() as con:
            cur = con.execute("""
                INSERT INTO download_tasks
                (work_id, source, status, progress, message,
                 created_at, updated_at)
                VALUES (?, ?, '等待中', 0, '', ?, ?)
            """, (
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
                "SELECT * FROM download_tasks WHERE id=?",
                (task_id,)
            ).fetchone()


    def list_download_tasks(self):

        with self.connect() as con:
            return con.execute(
                "SELECT * FROM download_tasks ORDER BY id DESC"
            ).fetchall()


    def update_download_task(
            self,
            task_id,
            status=None,
            progress=None,
            message=None):

        now = datetime.now().isoformat(timespec="seconds")

        with self.connect() as con:

            row = con.execute(
                "SELECT * FROM download_tasks WHERE id=?",
                (task_id,)
            ).fetchone()

            if not row:
                return False


            con.execute("""
                UPDATE download_tasks
                SET status=?,
                    progress=?,
                    message=?,
                    updated_at=?
                WHERE id=?
            """, (
                status if status is not None else row[3],
                progress if progress is not None else row[4],
                message if message is not None else row[5],
                now,
                task_id
            ))

            con.commit()

        return True


    def get_active_tasks_by_work(self, work_id):

        with self.connect() as con:

            return con.execute("""
                SELECT *
                FROM download_tasks
                WHERE work_id=?
                AND status NOT IN ('完成','失败')
            """, (
                work_id,
            )).fetchall()


    def reset_download_tasks_on_startup(self):

        now = datetime.now().isoformat(timespec="seconds")

        with self.connect() as con:

            cur = con.execute("""
                UPDATE download_tasks
                SET status='失败',
                    message='程序异常退出',
                    updated_at=?
                WHERE status IN ('等待中','下载中')
            """, (
                now,
            ))

            con.commit()

            return cur.rowcount


    def delete_tasks_by_work(self, work_id):

        with self.connect() as con:

            cur = con.execute(
                "DELETE FROM download_tasks WHERE work_id=?",
                (work_id,)
            )

            con.commit()

            return cur.rowcount > 0

'''

    text = text.replace(
        "\ndef get_latest_work_id",
        methods + "\n\ndef get_latest_work_id"
    )


p.write_text(text, encoding="utf-8")

print("db.py patched OK")