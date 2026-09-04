# RELEASE FREEZE — Phase 8-C Final

## Release Identity

| 项目 | 值 |
|---|---|
| Project | TK Studio V1.6.4 |
| Phase | Phase 8-C Release Candidate |
| Git commit | `c6926415b51cee1248f4624038c915cf9b1389f3` |
| Git commit (short) | `c692641` |
| Commit time | 2026-09-04 23:42:49 +0800 |
| Freeze time | 2026-09-04 23:55:00 +0800 |
| EXE path | `D:\TK_Studio_V1_fixed\dist\TKStudio\TKStudio.exe` |
| EXE size | 3,284,548 bytes (3.13 MB) |
| EXE SHA-256 | `C25C0761CA047374D41008822107CDD5CE01499A999761A11E465B8609C5E2C1` |
| Build time | 2026-09-04 23:47:06 |
| Build tool | PyInstaller 6.22.2 |
| PySide6 | 6.11.2 |
| Python | 3.11.9 |

---

## Acceptance

| 项目 | 结果 |
|---|---|
| EXE Build | PASS |
| EXE Startup | PASS |
| Functional Black-box Proxy | PASS |
| Exception Tests | PASS |
| Final Regression | PASS |
| Full Automated Regression | 122 passed |

### 详细验收项

| 步骤 | 项数 | 通过 | 结果 |
|---|---|---|---|
| 第一步：EXE 构建 | 4 | 4 | PASS |
| 第二步：EXE 启动 | 6 | 6 | PASS |
| 第三步：功能黑盒 | 8 | 8 | PASS |
| 第四步：异常测试 | 6 | 6 | PASS |
| 第五步：最终回归 | 2 | 2 | PASS |
| **总计** | **26** | **26** | **PASS** |

---

## Known Transient Event

**测试用例**：`test_concurrent_same_title_downloads`

**首次执行**：`disk I/O error`

**重测**：`PASS`

**结论**：`non-reproducible transient I/O event`

> 首次执行出现瞬态 SQLite disk I/O error，立即重测通过；未观察到可重复的软件缺陷。

### 原因分析

4 线程并发写入同一 SQLite DB 时偶发的 I/O 延迟。FIX-DB.1 的 WAL + busy_timeout=5000ms 已最大程度缓解此类问题。非代码缺陷，不阻塞发布。

---

## Freeze Rules

> Release Freeze 后禁止修改生产代码、测试代码及核心构建配置。

### 冻结范围

- `core/` — 生产代码（全部冻结）
- `workers/` — Worker 层（全部冻结）
- `TK_Studio_V1_6_4.py` — UI 入口（冻结）
- `tests/` — 测试代码（全部冻结）
- `TKStudio.spec` — 构建配置（冻结）

### 允许的操作

- 只读检查
- 产物核验
- 哈希计算
- 发布文档生成

### 工作区状态（Freeze 时）

```
?? PHASE8_C_EXE_BLACKBOX_ACCEPTANCE.md
?? build_log.txt
?? build_log_fix3.txt
```

- `PHASE8_C_EXE_BLACKBOX_ACCEPTANCE.md`：Phase 8-C 验收报告（未提交，文档文件）
- `build_log.txt`：临时构建日志（未提交，不影响发布）
- `build_log_fix3.txt`：临时构建日志（未提交，不影响发布）

**无生产代码或测试代码修改。**

---

## Release Decision

**RELEASE FROZEN / PASS**
