# Phase FIX-DL.2 稳定性审计报告：下载模块上线前审计

- 审计时间：2026-09-04
- 审计性质：只读分析（禁止修改代码）
- 审计范围：下载全链路 `core/downloader.py` → `workers/download_worker.py` → `workers/task_manager.py` → `TK_Studio_V1_6_4.py`（UI 集成）→ `core/db.py`（持久化）→ `core/chrome_bridge.py`（CDP 刷新）→ `TKStudio.spec`（EXE 打包）
- 基线：commit 76888c0（FIX-DL.1 re-impl）

---

## 审计结论

| # | 审计项 | 风险等级 | 结论 |
|---|---|---|---|
| 1 | downloader 生命周期 | 低 | 生命周期完整，FIX-DL.1 加固覆盖主要权限场景；重试退避略保守 |
| 2 | worker 释放 | 低 | 三层回收（业务回调 → QThread.finished → deleteLater）+ 安全网兜底；shutdown 依赖进程退出终止 QThread |
| 3 | 异常恢复 | 中 | 启动恢复 + 双层 try/except + 线程安全网；Chrome CDP 刷新路径有 profile 锁风险 |
| 4 | EXE 环境差异 | **高** | 无 `sys.frozen` 适配；DB/Chrome profile 写入 EXE `_internal/` 目录，Program Files 部署会全部失败 |
| 5 | 长时间运行风险 | 中 | SQLite 无 busy_timeout（并发写锁冲突）；`self.tasks` 字典不清理（轻微内存泄漏）；Chrome 进程清理可靠 |

**上线建议**：审计项 4（EXE 环境差异）为 **阻塞项**，必须解决后方可上线。其余为非阻塞项，可后续迭代修复。

---

## 一、downloader 生命周期

### 1.1 调用链

```
UI._start_download_worker(work_id, source)
  → TaskManager.enqueue(work_id, video_url, output_dir, source)
    → _maybe_start_next()  # 并发上限内立即启动
      → _start_task(task)
        → DownloadWorker(QThread).start()
          → run() → run_download(...)
            → download_once(url, page_url, path, session, ...)
              → _prepare_part_file / _open_write_resilient / _replace_with_retry
```

### 1.2 生命周期完整性

| 阶段 | 实现 | 评估 |
|---|---|---|
| 入队互斥 | `TaskManager.is_busy(work_id)` + `work_tasks` 字典 + DB `get_active_tasks_by_work` | ✅ 三层保护，防止同一作品重复排队 |
| 并发控制 | `max_concurrent=3`，`_maybe_start_next` while 循环补位 | ✅ 队列+自动补位 |
| 最终名仲裁 | `_claim_final_path` → in-flight 注册表 + `works.local_path` 归属查询 | ✅ FIX-DL.1 解决并发同名冲突 |
| .part 隔离 | `part = path + ".part"`（跟随仲裁后文件名） | ✅ 并发唯一 |
| 目录可写预检 | `__tk_writetest_{pid}_{tid}.tmp` 探针文件 | ✅ 尽早失败 |
| 写打开退避 | `_open_write_resilient`（0/0.4/0.8/1.6s） | ✅ 覆盖 Defender 锁窗口 |
| 写入中 AV 隔离 | `FileNotFoundError`/`PermissionError` 翻译为友好错误 | ✅ 可自动重试 |
| 改名退避 | `_replace_with_retry`（0/0.5/1.0/2.0s） | ✅ 覆盖目标文件被占用 |
| 失败清理 | 优先实际 part 路径，`_part_path_for` DB 推算兜底 | ✅ FIX-DL.1 要求 5 |
| 注册表释放 | `finally: _release_final_path(claim_key)` | ✅ 成功/失败/取消均释放 |

### 1.3 发现的问题

**[低] 重试退避时间偏长**
`run_download` 在普通重试间 `time.sleep(1.0)`，3 次 attempt 最坏增加 3s 延迟。对网络抖动型失败合理，但对可快速恢复的瞬时故障略保守。非阻塞。

**[低] `_path_owned_by_other_work` 异常时保守返回 True**
DB 查询失败（如 "database is locked"）时返回 True → 不必要地去重文件名。影响：文件名多一个 `[video_id]` 后缀，不影响数据正确性。非阻塞。

---

## 二、worker 释放

### 2.1 释放路径

```
DownloadWorker.run() 结束
  → emit finished_ok / failed（业务信号）
    → TaskManager._on_finished / _on_failed
      → running_workers.pop(task_id)
      → work_tasks.pop(work_id)
      → db.update_download_task(终态)
      → _maybe_start_next()（自动补位）
  → QThread.finished（Qt 信号）
    → worker.deleteLater()（Qt 托管回收）
    → _worker_thread_finished(task_id)（安全网）
```

### 2.2 三层回收机制

| 层 | 触发 | 职责 | 评估 |
|---|---|---|---|
| L1 业务回调 | `finished_ok`/`failed` 信号 | 更新 DB 终态、清理运行映射、补位 | ✅ 正常路径 |
| L2 QThread.finished | Qt 线程结束信号 | `deleteLater` 回收对象 | ✅ Qt 托管 |
| L3 安全网 | `_worker_thread_finished` | 状态仍为"下载中"时标记失败 | ✅ 兜底孤儿线程 |

### 2.3 发现的问题

**[低] `self.tasks` 字典不清理**
`_on_finished`/`_on_failed`/`_worker_thread_finished` 均从 `running_workers` 和 `work_tasks` 中 pop，但 **不从 `self.tasks` 中 pop**。`self.tasks[task_id]` 在整个会话期间累积，每个条目约 7 个键值对。数百次下载后内存占用轻微增长。进程重启后清空。非阻塞。

**[低] shutdown 不等待线程退出**
`TaskManager.shutdown()` 标记 DB 终态后 `worker.cancel()`，然后 `running_workers.clear()`，不调用 `worker.wait()`。依赖进程退出终止 QThread。这在 `closeEvent` 语境下合理（进程即将退出），但如果 shutdown 后程序继续运行（非退出场景），Worker 线程可能仍在后台执行 `run_download`，其 DB 写入可能与新任务冲突。当前代码无此调用路径（shutdown 仅在 closeEvent 中调用），非阻塞。

**[低] `deleteLater` 依赖事件循环**
如果主线程被长时间阻塞（如模态对话框），`deleteLater` 队列不处理，Worker 对象暂时累积。Qt 正常运行时无影响。非阻塞。

---

## 三、异常恢复

### 3.1 异常处理层次

| 层 | 位置 | 处理 | 评估 |
|---|---|---|---|
| L0 写打开 | `_open_write_resilient` | PermissionError 退避；FileNotFoundError 友好翻译 | ✅ FIX-DL.1 |
| L1 写入中 | `download_once` f.write | OSError 翻译为友好错误 | ✅ FIX-DL.1 |
| L2 单次下载 | `download_once` 整体 | HTTP 4xx/5xx/HTML → RuntimeError | ✅ |
| L3 下载主循环 | `run_download` 3 次 attempt | 403/404/410 → Chrome CDP 刷新重试；取消立即抛出 | ✅ |
| L4 快速短路 | `run_download` except | "临时文件无法写入"前缀不重试 | ✅ FIX-DL.1 |
| L5 Worker | `DownloadWorker.run` try/except | 兜底 emit failed | ✅ |
| L6 安全网 | `_worker_thread_finished` | 线程结束但无业务回调 → 标记失败 | ✅ |
| L7 启动恢复 | `reset_downloading_to_failed` | "下载中" → "下载失败" | ✅ |

### 3.2 发现的问题

**[中] Chrome CDP 刷新期间 profile 锁冲突**
`refresh_video_url` → `chrome_render_with_cookies` 使用 `chrome_cdp_profile`（[chrome_bridge.py:84](file:///d:/TK_Studio_V1_fixed/core/chrome_bridge.py#L84)）。如果同一时刻其他组件（LoginWorker、HomeFetcher）也在使用 Chrome，虽 profile 目录不同，但端口范围 9222~9231 可能与并行 Chrome 实例冲突。当前 `_find_free_port` 会探测并跳过已占用端口，但有 10 个端口的限制。多个并发刷新场景下可能因端口耗尽返回空结果 → 下载重试失败。非阻塞（需极多重并发才触发），但建议后续增大端口范围。

**[低] `refresh_video_url` 失败后仍继续 attempt**
`run_download` 中 `refresh_video_url` 返回空 `fresh` 时，不 continue 而是走 `progress_cb("重试")` → `time.sleep(1.0)` → 下一次 attempt 用旧 URL。旧 URL 已过期时会再次 403，最终 3 次耗尽报"下载失败"。行为合理但错误信息不精确（报"下载失败"而非"视频地址刷新失败"）。非阻塞。

---

## 四、EXE 环境差异

### 4.1 路径分析

| 资源 | 路径计算 | 开发环境 | EXE (onedir) 环境 | 可写性 |
|---|---|---|---|---|
| SQLite DB | `core/db.py` → `dirname(dirname(abspath(__file__)))` | `d:\TK_Studio_V1_fixed\tk_studio.db` | `<app_dir>/_internal/tk_studio.db` | **❌ Program Files 不可写** |
| Chrome headless profile | `chrome_bridge.py` → `_PROJECT_ROOT` | `d:\TK_Studio_V1_fixed\chrome_headless_profile` | `<app_dir>/_internal/chrome_headless_profile` | **❌ Program Files 不可写** |
| Chrome CDP profile | `chrome_bridge.py` → `_PROJECT_ROOT` | `d:\TK_Studio_V1_fixed\chrome_cdp_profile` | `<app_dir>/_internal/chrome_cdp_profile` | **❌ Program Files 不可写** |
| 下载目录 | UI `download_path_edit` 默认 `~/Downloads/TK_Studio` | 用户目录 | 用户目录 | ✅ 可写 |
| Chrome exe | `%LOCALAPPDATA%\Google\Chrome\...` | 用户目录 | 用户目录 | ✅ 可读 |

### 4.2 发现的问题

**[高-阻塞] 无 `sys.frozen` 适配，DB/Chrome profile 写入 EXE `_internal/` 目录**
全代码库无 `sys.frozen` / `_MEIPASS` 处理。PyInstaller onedir 模式下，`core/db.py` 和 `core/chrome_bridge.py` 的 `__file__` 指向 `<app_dir>/_internal/` 目录。如果 EXE 部署到 `C:\Program Files\`（UAC 保护），则：
- `sqlite3.connect()` 写 DB → `OperationalError: unable to open database file`
- `os.makedirs(profile_dir)` → `PermissionError`
- FIX-DL.1 的目录可写预检会立即报"下载目录不可写"（实际是 DB/profile 目录不可写，但用户看到的下载目录可写）

**影响**：EXE 在 Program Files 部署时，下载功能完全不可用。

**[中] `console=False` 抑制 stderr**
[TKStudio.spec:48](file:///d:/TK_Studio_V1_fixed/TKStudio.spec#L48) 设置 `console=False`（GUI 模式）。Python traceback 输出到 stderr 被抑制。`run_download` 的 `except Exception` 捕获了所有下载异常并 emit `failed`，但 Chrome CDP 层的未预期异常（如 websocket 连接超时）只通过 `log_callback` 返回空字符串，用户无法看到根因。建议在 EXE 模式下将关键错误写入日志文件。

**[低] `upx=True` 可能触发 AV 误报**
[TKStudio.spec:46](file:///d:/TK_Studio_V1_fixed/TKStudio.spec#L46) 使用 UPX 压缩。UPX 压缩的二进制常被杀毒软件标记为可疑，可能触发 Windows Defender 对 EXE 本身的扫描锁定，与 FIX-DL.1 解决的 .part 锁定形成叠加效应。非阻塞但需注意。

**[低] `download_tasks` 表无清理**
`download_tasks` 表只有 INSERT/UPDATE，无 DELETE。长期使用后表行数无限增长，启动恢复查询 `WHERE status IN ('下载中', '等待中')` 需全表扫描。建议后续增加定期清理已完成/取消/失败超过 N 天的记录。非阻塞。

---

## 五、长时间运行风险

### 5.1 SQLite 并发写

**[中] 无 busy_timeout，并发写可能冲突**
[db.py:35](file:///d:/TK_Studio_V1_fixed/core/db.py#L35) `sqlite3.connect(self.path)` 未设置 `timeout` 参数（默认 0s）。SQLite 默认 busy_timeout=0，意味着并发写立即报 `database is locked` 而不等待。

并发写来源：
- 3 个 DownloadWorker 并发下载，各自每 ≥1% 或 ≥2s 写一次 `update_download_task`（进度）
- 同时 `run_download` 写 `update_download`（状态变更）、`add_work`（刷新地址时）
- UI 主线程读 DB

写操作本身很快（单条 UPDATE），碰撞概率低，但在 3 并发下载 + 频繁进度更新时存在碰撞窗口。一旦碰撞，`_on_progress` 的 `update_download_task` 抛异常，被 `with` 上下文吞掉（不重试），该次进度不落库（下次 ≥1%/≥2s 落库补上）。`run_download` 的 `update_download`/`add_work` 异常会被 `except Exception` 捕获 → 可能误判为下载失败。

**建议**：`sqlite3.connect(self.path, timeout=5)` 增加 5s busy_timeout，或启用 WAL 模式 `PRAGMA journal_mode=WAL`（读不阻塞写）。非阻塞但推荐。

### 5.2 内存累积

| 累积点 | 增长率 | 清理 | 风险 |
|---|---|---|---|
| `TaskManager.tasks` 字典 | 每任务 ~200 bytes | 无（会话级） | 低：千次下载 ~200KB |
| `_FINAL_NAME_IN_FLIGHT` 注册表 | 每并发任务 1 条 | `finally` 释放 | ✅ 无泄漏 |
| `download_tasks` 表 | 每任务 1 行 | 无（DB 级） | 低：千次下载 ~千行，查询仍快 |
| Chrome 进程 | 每次 refresh 1 个 | `finally: proc.terminate()` | ✅ 清理可靠 |

### 5.3 Chrome 进程清理

[chrome_bridge.py:210-225](file:///d:/TK_Studio_V1_fixed/core/chrome_bridge.py#L210-L225) finally 块：
1. `ws.close()` — WebSocket 关闭
2. `proc.terminate()` — Chrome 进程终止
3. `proc.wait(timeout=3)` — 等待退出（3s）
4. 失败时 `proc.kill()` — 强制终止

清理路径完整，无残留风险。极端情况（proc.wait 超时 + kill 失败）下 Chrome 可能残留，但操作系统会在进程退出时回收。

### 5.4 网络资源

| 资源 | 生命周期 | 风险 |
|---|---|---|
| `requests.Session` | 每 `run_download` 创建 | ✅ 随 Worker 退出释放 |
| urllib3 连接池 | Session 内复用（3 attempts） | ✅ Session 关闭即释放 |
| TCP 连接 | 下载流式连接 | `r.close()` 在 finally 中 | ✅ |

`download_once` 中 `r = session.get(..., stream=True)`，`r.close()` 在写入完成后调用。如果 `cancel_check` 抛 `RuntimeError("用户取消下载")`，`r.close()` 在 `raise` 前调用（[downloader.py:139](file:///d:/TK_Studio_V1_fixed/core/downloader.py#L139)）。但 `_open_write_resilient` 或 `_replace_with_retry` 抛异常时 `r` 可能未关闭——不过这些异常发生时 `r` 的数据已读完或未建立，影响小。

---

## 六、冻结边界检查

本次审计为只读分析，未修改任何文件。以下文件均未被修改：

- `core/downloader.py` ✅
- `workers/download_worker.py` ✅
- `workers/task_manager.py` ✅
- `TK_Studio_V1_6_4.py` ✅
- `core/db.py` ✅
- `core/chrome_bridge.py` ✅
- `TKStudio.spec` ✅

---

## 七、风险汇总与优先级

| 优先级 | 风险 | 影响 | 建议修复阶段 |
|---|---|---|---|
| **P0-阻塞** | EXE 无 `sys.frozen` 适配，DB/Chrome profile 写入 `_internal/` | Program Files 部署时下载完全不可用 | 上线前必须修复（新 FIX 立项） |
| P1-中 | SQLite 无 busy_timeout | 并发写偶发 "database is locked" | 后续迭代（`timeout=5` + WAL） |
| P1-中 | Chrome CDP 端口范围仅 10 个 | 多组件并发刷新可能端口耗尽 | 后续迭代（扩大范围或动态分配） |
| P2-低 | `self.tasks` 字典不清理 | 长会话轻微内存增长 | 后续迭代（完成时 pop） |
| P2-低 | `download_tasks` 表无清理 | 长期使用表增长 | 后续迭代（定期清理） |
| P2-低 | `console=False` 抑制错误输出 | EXE 模式排查困难 | 后续迭代（日志文件） |
| P3-低 | UPX 压缩触发 AV 误报 | 可能与 .part 锁定叠加 | 视实际部署情况决定 |

---

## 八、上线建议

1. **必须修复（P0）**：EXE 环境 DB/Chrome profile 路径适配。需新 Phase/FIX 立项，涉及 `core/db.py` 和 `core/chrome_bridge.py` 的路径计算逻辑（使用 `sys.frozen` 检测 + `~/AppData/Local/TKStudio/` 作为 EXE 模式存储根目录）。此修复超出 FIX-DL.1 范围（仅 `core/downloader.py`），需独立立项。

2. **推荐修复（P1）**：SQLite `timeout=5` + WAL 模式。一行改动即可显著降低并发写冲突概率。可纳入 DB 维护 FIX 立项。

3. **可接受现状**：P2/P3 级风险在单会话百次下载量级下无实际影响，可后续迭代修复。

**结论**：FIX-DL.1 下载模块加固本身实现完整、测试覆盖充分（9/9 PASS + 118 回归 PASS），可冻结。上线阻塞项为 EXE 环境路径适配（P0），需独立立项修复后方可发布。
