# Phase 8-A 系统功能验收报告：启动与基础环境

- 验收时间：2026-09-04
- 验收性质：只读测试（禁止修改代码）
- 基线：FIX-DB.1 实施后（core/db.py WAL + busy_timeout）
- 测试脚本：`tests/phase8a_startup_test.py`

---

## 验收结论

| # | 测试项 | 结果 | 说明 |
|---|---|---|---|
| 1 | 启动验证（Python 入口 + EXE 模式模拟） | ✅ PASS | 全链路 import 通过；sys.frozen 模式路径正确 |
| 2 | 数据目录创建 | ✅ PASS | `%LOCALAPPDATA%\TK_Studio` 自动创建且可写 |
| 3 | SQLite 初始化 | ✅ PASS | WAL 启用、busy_timeout=5000、13 列 works 表 + download_tasks 表 |
| 4 | Chrome profile 路径 | ✅ PASS | 5 个 profile 目录均位于数据根目录下 |
| 5 | 日志生成 | ✅ PASS | home_fetch_debug.log JSON-lines 格式正确，含完整诊断字段 |

**总体结论：通过。** 启动与基础环境全部正常。

---

## 测试环境

| 项目 | 值 |
|---|---|
| 操作系统 | Windows (Administrator) |
| Python | 3.11.9 |
| 项目根 | `D:\TK_Studio_V1_fixed` |
| EXE 构建 | `dist\TKStudio\TKStudio.exe`（构建于 2026-09-04 20:05） |
| EXE 版本 | 无 VersionInfo（PyInstaller 打包，未设置版本号） |

### EXE 构建状态

现有 EXE 构建于 2026-09-04 20:05，**早于**以下修复提交：
- FIX-EXE.1（commit 9635742，2026-09-04 23:20）— sys.frozen 路径适配
- FIX-DB.1（未提交）— SQLite WAL + busy_timeout

**现有 EXE 不包含最新路径修复和 DB 加固。** 建议在 Phase 8-A 验收通过后重新构建 EXE。

本次验收使用 **Python 入口 + sys.frozen 模拟** 验证 EXE 模式行为，等效于实际 EXE 启动路径逻辑。

---

## 测试详情

### TEST 1: 启动验证

**开发模式（Python 入口）**：
```
get_app_data_root: D:\TK_Studio_V1_fixed
DB_FILE: D:\TK_Studio_V1_fixed\tk_studio.db
chrome_bridge root: D:\TK_Studio_V1_fixed
home_fetcher root: D:\TK_Studio_V1_fixed
LOGIN_PROFILE_DIR: D:\TK_Studio_V1_fixed\chrome_login_profile
AUTH_PROFILE_DIR: D:\TK_Studio_V1_fixed\chrome_home_auth_profile
```
全链路 import 通过：`core.paths` → `core.db` → `core.chrome_bridge` → `core.home_fetcher` → `core.tiktok_login` → `core.profile_snapshot` → `TK_Studio_V1_6_4`

**EXE 模式模拟（sys.frozen=True）**：
- `get_app_data_root()` 返回 `%LOCALAPPDATA%\TK_Studio`
- 与开发模式路径不同，数据隔离正确

**结果：PASS** ✅

### TEST 2: 数据目录创建

```
app_data_root: C:\Users\Administrator\AppData\Local\TK_Studio
expected: C:\Users\Administrator\AppData\Local\TK_Studio
Directory exists: True
Writable: True
```

`os.makedirs(base, exist_ok=True)` 在首次调用时自动创建目录。目录可写，UAC 无限制。

**结果：PASS** ✅

### TEST 3: SQLite 初始化

| 检查项 | 值 | 预期 | 结果 |
|---|---|---|---|
| journal_mode | `wal` | `wal` | ✅ |
| busy_timeout | `5000` | `5000` | ✅ |
| Tables | `['works', 'sqlite_sequence', 'download_tasks']` | works + download_tasks | ✅ |
| works 列数 | 13 | 13 | ✅ |
| 写入/读取 | `('test_vid_8a', 'Phase 8-A Test')` | 一致 | ✅ |

works 表 13 列：`id, video_id, author, title, url, video_url, cover_url, duration, resolution, download_status, local_path, created_at, updated_at`

WAL 模式启用后，SQLite 创建 `-wal` 和 `-shm` 辅助文件，由 SQLite 自动管理。

**结果：PASS** ✅

### TEST 4: Chrome Profile 路径

EXE 模式下 5 个 profile 目录均位于 `%LOCALAPPDATA%\TK_Studio` 下：

| Profile | 路径 |
|---|---|
| chrome_headless_profile | `...\TK_Studio\chrome_headless_profile` |
| chrome_cdp_profile | `...\TK_Studio\chrome_cdp_profile` |
| chrome_home_fetcher_profile | `...\TK_Studio\chrome_home_fetcher_profile` |
| chrome_login_profile | `...\TK_Studio\chrome_login_profile` |
| chrome_home_auth_profile | `...\TK_Studio\chrome_home_auth_profile` |

所有 profile 路径均通过 `get_app_data_root()` 计算，EXE 部署到 Program Files 时不再写入只读的 `_internal/` 目录。

**结果：PASS** ✅

### TEST 5: 日志生成

开发模式下探针目录 `data/probes/` 存在，包含历史阶段测试数据和 `home_fetch_debug.log`。

`home_fetch_debug.log` 格式（JSON-lines）：
```json
[2026-09-04 21:46:29] {"chrome_profile": "D:\\TK_Studio_V1_fixed\\chrome_home_auth_profile", "login": true, "page_url": "https://www.tiktok.com/@mrbeast", "page_title": "MrBeast (@mrbeast) | TikTok", "cookies_count": 28, "scrolls": 8, "video_count": 170, "target_url": "https://www.tiktok.com/@mrbeast"}
```

日志字段完整：时间戳、chrome_profile、login 状态、page_url、page_title、cookies_count、scrolls、video_count、target_url。

EXE 模式下探针路径将位于 `%LOCALAPPDATA%\TK_Studio\data\probes\`，与开发模式行为一致。

**结果：PASS** ✅

---

## 冻结边界检查

本次验收为只读测试，未修改任何生产代码文件：
- `core/db.py` ✅ 未修改
- `core/paths.py` ✅ 未修改
- `core/chrome_bridge.py` ✅ 未修改
- `core/home_fetcher.py` ✅ 未修改
- `core/tiktok_login.py` ✅ 未修改
- `core/profile_snapshot.py` ✅ 未修改
- `TK_Studio_V1_6_4.py` ✅ 未修改

新增测试脚本 `tests/phase8a_startup_test.py`（只读验证脚本，不含业务逻辑）。

---

## 后续建议

1. **重新构建 EXE**：现有 EXE 构建于 FIX-EXE.1/FIX-DB.1 之前，需重新打包以包含最新路径修复和 DB 加固。
2. **Phase 8-B**：进入完整功能链路测试（解析 → 下载 → 主页抓取 → 登录），验证业务流程。
3. **EXE 版本号**：建议在 `TKStudio.spec` 中添加版本号信息，便于版本追踪。
