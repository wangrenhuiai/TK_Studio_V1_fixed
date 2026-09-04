# Phase FIX-DB.1 实施报告：SQLite 并发写稳定性修复

- 实施时间：2026-09-04
- 基线：commit 9635742（FIX-EXE.1）+ FIX-DL.2 审计 P1 推荐修复
- 范围：仅数据库连接初始化相关代码，不修改业务逻辑

---

## 一、修改文件清单

| 文件 | 类型 | 修改内容 |
|---|---|---|
| `core/db.py` | 修改 | `connect()` 增加 timeout=5 + WAL + busy_timeout=5000 |
| `tests/test_fix_db1.py` | 新增 | 4 例并发写稳定性测试 |

---

## 二、修改点详解

### 2.1 `core/db.py` `connect()` 方法

**修改前**：
```python
def connect(self):
    return sqlite3.connect(self.path)
```

**修改后**：
```python
def connect(self):
    con = sqlite3.connect(self.path, timeout=5)
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA journal_mode=WAL")
    return con
```

| 参数 | 值 | 作用 |
|---|---|---|
| `timeout` | 5（秒） | `sqlite3.connect` 层面的 busy timeout，写锁冲突时等待最多 5 秒而非立即报错 |
| `PRAGMA busy_timeout` | 5000（毫秒） | SQLite 层面 busy timeout，与 timeout 参数冗余保护 |
| `PRAGMA journal_mode` | WAL | Write-Ahead Logging：写不阻塞读，读写并发性能大幅提升；多线程写入不再串行等待读锁 |

**影响范围**：`connect()` 被 Database 类的所有方法调用（`add_work`、`update_download`、`create_download_task`、`update_download_task`、`get_active_tasks_by_work` 等），修改后全部受益，无需逐方法改动。

### 2.2 不修改项

- 数据库表结构：未修改 ✅
- 业务逻辑：未修改 ✅
- SQL 查询语句：未修改 ✅
- UI：未修改 ✅
- 下载流程：未修改 ✅

---

## 三、WAL 模式说明

### 3.1 WAL vs 回滚日志

| 特性 | 回滚日志（默认 DELETE） | WAL |
|---|---|---|
| 读写并发 | 写阻塞读 | 写不阻塞读 |
| 多线程写入 | 串行（写锁互斥） | 并发改善（仍需写锁，但等待超时而非立即失败） |
| 额外文件 | 无 | `-wal` + `-shm`（自动管理） |
| 持久性 | 同步写入 | 同步写入（synchronous=FULL 时同等） |

### 3.2 WAL 文件

启用 WAL 后，SQLite 会创建两个辅助文件：
- `tk_studio.db-wal`：Write-Ahead Log（未提交事务缓冲）
- `tk_studio.db-shm`：共享内存索引

这些文件由 SQLite 自动管理，正常关闭时自动 checkpoint 合并回主 DB。测试中 `tmp_path` 临时目录自动清理，不影响测试隔离。

---

## 四、测试结果

### 4.1 compileall
```
python -m compileall -q core workers tests
COMPILEALL_EXIT: 0
```
**PASS** ✅

### 4.2 FIX-DB.1 专项测试（4 例）

| 测试 | 验证点 | 结果 |
|---|---|---|
| `test_wal_mode_enabled` | `PRAGMA journal_mode` 返回 `wal` | ✅ PASS |
| `test_busy_timeout_set` | `PRAGMA busy_timeout` 返回 5000 | ✅ PASS |
| `test_concurrent_writes_no_lock` | 4 线程并发写 48 条记录，无 "database is locked" | ✅ PASS |
| `test_concurrent_update_progress` | 3 线程并发更新进度 20 次/线程，无锁库 | ✅ PASS |

```
4 passed in 0.54s
```

### 4.3 全量回归测试
```
python -m pytest tests/ -q
122 passed in 7.08s
```
**PASS** ✅（118 原有 + 4 新增 = 122）

---

## 五、验收结论

| 验收项 | 状态 |
|---|---|
| 1. 只修改数据库连接初始化相关代码 | ✅ 仅 `connect()` 方法 |
| 2. 增加 sqlite timeout | ✅ `timeout=5` |
| 3. 启用 WAL | ✅ `PRAGMA journal_mode=WAL` |
| 4. 增加 busy_timeout | ✅ `PRAGMA busy_timeout=5000` |
| 5. 不修改业务逻辑 | ✅ 仅连接初始化 |
| 6. FIX-DB.1_IMPLEMENTATION_REPORT.md | ✅ 本报告 |
| compileall | ✅ PASS |
| 全量测试 | ✅ 122 passed |
| 多 worker 写入测试 | ✅ 4 线程 48 条 + 3 线程 60 次更新 |

**验收通过。**
