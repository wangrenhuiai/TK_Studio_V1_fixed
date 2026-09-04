"""下载任务管理器。

Phase 5-B.1.1

职责：
1. 创建下载任务
2. 管理等待队列
3. 控制最大并发数
4. 创建/回收 DownloadWorker
5. 处理取消
6. 自动补位
7. 向 MainWindow 转发任务状态
"""

import time
from collections import deque

from PySide6.QtCore import QObject, Signal

from workers.download_worker import DownloadWorker


class TaskManager(QObject):

    # work_id, percent, status, message, source
    progress = Signal(int, int, str, str, str)

    # work_id, path, source
    finished_ok = Signal(int, str, str)

    # work_id, error, source
    failed = Signal(int, str, str)

    # 队列/运行状态发生变化
    state_changed = Signal()

    def __init__(self, db, max_concurrent=3):
        super().__init__()

        self.db = db
        self.max_concurrent = max(1, int(max_concurrent))

        # 等待中的任务：
        # [(task_id, work_id, video_url, output_dir, source), ...]
        self.waiting_queue = deque()

        # task_id -> DownloadWorker
        self.running_workers = {}

        # task_id -> task information
        self.tasks = {}

        # work_id -> task_id
        # 用于防止同一个作品重复排队/下载。
        self.work_tasks = {}

        self._shutdown = False

    # ==========================================================
    # 公共接口
    # ==========================================================

    def enqueue(
        self,
        work_id,
        video_url,
        output_dir,
        source="single",
    ):
        """创建任务并加入队列。

        返回：
            task_id
        """

        if self._shutdown:
            return None

        # 内存状态优先。
        existing = self.work_tasks.get(work_id)
        if existing is not None:
            task = self.tasks.get(existing)

            if task and task["status"] in ("等待中", "下载中"):
                return existing

            self.work_tasks.pop(work_id, None)

        # DB 二次保护。
        active = self.db.get_active_tasks_by_work(work_id)

        if active:
            task_id = active[0][0]
            self.work_tasks[work_id] = task_id
            return task_id

        task_id = self.db.create_download_task(
            work_id,
            source,
        )

        task = {
            "task_id": task_id,
            "work_id": work_id,
            "video_url": video_url,
            "output_dir": output_dir,
            "source": source,
            "status": "等待中",
        }

        self.tasks[task_id] = task
        self.work_tasks[work_id] = task_id

        self.waiting_queue.append(task_id)

        self.state_changed.emit()

        self._maybe_start_next()

        return task_id

    def cancel(self, work_id):
        """取消指定作品。

        等待中的任务：
            直接从逻辑队列移除，并标记为取消。

        下载中的任务：
            请求 DownloadWorker 协作式退出。
        """

        task_id = self.work_tasks.get(work_id)

        if task_id is None:
            return False

        task = self.tasks.get(task_id)

        if task is None:
            self.work_tasks.pop(work_id, None)
            return False

        status = task["status"]

        # --------------------------
        # 等待中
        # --------------------------
        if status == "等待中":

            task["status"] = "取消"

            self.db.update_download_task(
                task_id,
                status="取消",
                message="用户取消下载",
            )

            self.work_tasks.pop(work_id, None)

            try:
                self.waiting_queue.remove(task_id)
            except ValueError:
                pass

            self.state_changed.emit()
            return True

        # --------------------------
        # 下载中
        # --------------------------
        if status == "下载中":

            worker = self.running_workers.get(task_id)

            if worker is not None:
                worker.cancel()

            return True

        return False

    def is_busy(self, work_id):
        """作品是否处于等待中或下载中。"""

        task_id = self.work_tasks.get(work_id)

        if task_id is None:
            return False

        task = self.tasks.get(task_id)

        if task is None:
            return False

        return task["status"] in ("等待中", "下载中")

    def is_running(self, work_id):
        """兼容旧调用：仅判断正在下载。"""

        task_id = self.work_tasks.get(work_id)

        if task_id is None:
            return False

        task = self.tasks.get(task_id)

        return bool(
            task and task["status"] == "下载中"
        )

    def running_count(self):
        return len(self.running_workers)

    def waiting_count(self):
        return sum(
            1
            for task_id in self.waiting_queue
            if self.tasks.get(task_id, {}).get("status") == "等待中"
        )

    def active_count(self):
        return self.running_count() + self.waiting_count()

    # ==========================================================
    # Worker 调度
    # ==========================================================

    def _maybe_start_next(self):

        if self._shutdown:
            return

        while (
            len(self.running_workers) < self.max_concurrent
            and self.waiting_queue
        ):

            task_id = self.waiting_queue.popleft()

            task = self.tasks.get(task_id)

            if task is None:
                continue

            if task["status"] != "等待中":
                continue

            self._start_task(task)

    def _start_task(self, task):

        task_id = task["task_id"]
        work_id = task["work_id"]

        worker = DownloadWorker(
            work_id,
            task["video_url"],
            task["output_dir"],
            self.db,
        )

        task["status"] = "下载中"

        self.running_workers[task_id] = worker

        self.db.update_download_task(
            task_id,
            status="下载中",
            progress=0,
            message="",
        )

        source = task["source"]

        worker.progress.connect(
            lambda p, s, m, tid=task_id, wid=work_id, src=source:
            self._on_progress(
                tid,
                wid,
                p,
                s,
                m,
                src,
            )
        )

        worker.finished_ok.connect(
            lambda path, tid=task_id, wid=work_id, src=source:
            self._on_finished(
                tid,
                wid,
                path,
                src,
            )
        )

        worker.failed.connect(
            lambda error, tid=task_id, wid=work_id, src=source:
            self._on_failed(
                tid,
                wid,
                error,
                src,
            )
        )

        worker.finished.connect(
            worker.deleteLater
        )

        worker.finished.connect(
            lambda tid=task_id:
            self._worker_thread_finished(tid)
        )

        self.state_changed.emit()

        worker.start()

    # ==========================================================
    # Worker 回调
    # ==========================================================

    def _on_progress(
        self,
        task_id,
        work_id,
        progress,
        status,
        message,
        source,
    ):

        task = self.tasks.get(task_id)

        if task is None:
            return

        # Worker 已经进入结束流程后不再覆盖最终状态。
        if task["status"] != "下载中":
            return

        # 进度写库节流：downloader 每 512KB chunk 触发一次本回调，
        # 进度变化 ≥1% 或距上次写库 ≥2s 才落库，避免 SQLite 写放大；
        # 终态在 _on_finished/_on_failed 中立即写库，不受节流影响。
        now = time.monotonic()
        last_pct = task.get("_db_pct", -1)
        last_ts = task.get("_db_ts", 0.0)
        if progress - last_pct >= 1 or now - last_ts >= 2.0:
            self.db.update_download_task(
                task_id,
                status="下载中",
                progress=progress,
                message=message,
            )
            task["_db_pct"] = progress
            task["_db_ts"] = now

        self.progress.emit(
            work_id,
            progress,
            status,
            message,
            source,
        )

    def _on_finished(
        self,
        task_id,
        work_id,
        path,
        source,
    ):

        task = self.tasks.get(task_id)

        if task is None:
            return

        task["status"] = "完成"

        self.db.update_download_task(
            task_id,
            status="完成",
            progress=100,
            message=path,
        )

        self.running_workers.pop(
            task_id,
            None,
        )

        self.work_tasks.pop(
            work_id,
            None,
        )

        self.finished_ok.emit(
            work_id,
            path,
            source,
        )

        self.state_changed.emit()

        self._maybe_start_next()

    def _on_failed(
        self,
        task_id,
        work_id,
        error,
        source,
    ):

        task = self.tasks.get(task_id)

        if task is None:
            return

        # 用户取消：
        # works 表由 downloader 标记为“下载失败”，
        # download_tasks 保留更准确的“取消”状态。
        cancelled = str(error) == "用户取消下载"

        if cancelled:
            task["status"] = "取消"

            self.db.update_download_task(
                task_id,
                status="取消",
                message="用户取消下载",
            )
        else:
            task["status"] = "失败"

            self.db.update_download_task(
                task_id,
                status="失败",
                message=str(error),
            )

        self.running_workers.pop(
            task_id,
            None,
        )

        self.work_tasks.pop(
            work_id,
            None,
        )

        self.failed.emit(
            work_id,
            str(error),
            source,
        )

        self.state_changed.emit()

        self._maybe_start_next()

    def _worker_thread_finished(self, task_id):
        """QThread finished 信号兜底。

        正常情况下 _on_finished/_on_failed 已经移除 running_workers。
        如果底层出现异常导致 Worker 线程结束但没有业务回调，
        这里避免并发槽永久占用。
        """

        worker = self.running_workers.get(task_id)

        if worker is None:
            return

        task = self.tasks.get(task_id)

        if task is not None and task["status"] == "下载中":

            work_id = task["work_id"]
            source = task["source"]

            task["status"] = "失败"

            self.db.update_download_task(
                task_id,
                status="失败",
                message="下载线程异常结束",
            )

            self.running_workers.pop(
                task_id,
                None,
            )

            self.work_tasks.pop(
                work_id,
                None,
            )

            self.failed.emit(
                work_id,
                "下载线程异常结束",
                source,
            )

            self.state_changed.emit()

            self._maybe_start_next()

    # ==========================================================
    # 关闭
    # ==========================================================

    def shutdown(self):
        """程序关闭时的任务回收（与 Phase 3.13 语义一致）。

        - 等待中任务：从未创建 Worker，直接标记「取消」；
        - 下载中任务：先同步把 works 表标记为「下载失败」（不依赖线程退出后
          写库，因为进程随即退出会终止 QThread），download_tasks 标记「取消」，
          再请求 Worker 协作式取消；
        - 不等待线程结束，不调用 terminate。
        """

        self._shutdown = True

        # 等待中的任务直接取消。
        for task_id in list(self.waiting_queue):

            task = self.tasks.get(task_id)

            if task is None:
                continue

            if task["status"] != "等待中":
                continue

            task["status"] = "取消"

            self.db.update_download_task(
                task_id,
                status="取消",
                message="程序关闭",
            )

            self.work_tasks.pop(
                task["work_id"],
                None,
            )

        self.waiting_queue.clear()

        # 正在运行的任务：同步标记后协作式取消。
        for task_id, worker in list(self.running_workers.items()):

            task = self.tasks.get(task_id)

            if task is not None:

                task["status"] = "取消"

                try:
                    self.db.update_download(
                        task["work_id"],
                        "下载失败",
                    )
                except Exception:
                    pass

                try:
                    self.db.update_download_task(
                        task_id,
                        status="取消",
                        message="程序关闭",
                    )
                except Exception:
                    pass

            try:
                worker.cancel()
            except Exception:
                pass

        self.running_workers.clear()

        self.state_changed.emit()