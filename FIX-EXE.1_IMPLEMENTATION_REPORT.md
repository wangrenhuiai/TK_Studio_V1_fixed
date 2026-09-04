# Phase FIX-EXE.1 实施报告：PyInstaller EXE 环境路径修复

- 实施时间：2026-09-04
- 基线：commit 76888c0（FIX-DL.1 re-impl）+ FIX-DL.2 审计
- 范围：仅运行路径相关代码，不修改业务逻辑

---

## 一、修改文件清单

| 文件 | 类型 | 修改内容 |
|---|---|---|
| `core/paths.py` | **新增** | `get_app_data_root()`：sys.frozen 判断 + `%LOCALAPPDATA%\TK_Studio` 数据根目录 |
| `core/db.py` | 修改 | `DB_FILE` 使用 `get_app_data_root()` 替代 `__file__` 推算 |
| `core/chrome_bridge.py` | 修改 | `_PROJECT_ROOT` 使用 `get_app_data_root()` |
| `core/home_fetcher.py` | 修改 | `_PROJECT_ROOT` 使用 `get_app_data_root()` |
| `core/tiktok_login.py` | 修改 | `_PROJECT_ROOT` 使用 `get_app_data_root()` |
| `core/profile_snapshot.py` | 修改 | `_PROJECT_ROOT` 使用 `get_app_data_root()` |
| `TK_Studio_V1_6_4.py` | 修改 | `chrome_home_auth_profile` 路径使用 `get_app_data_root()` |
| `tests/test_fix_dl1.py` | 修复 | `test_concurrent_same_title_downloads` 断言改为对称（修复预存 flaky test） |

---

## 二、修改点详解

### 2.1 新增 `core/paths.py`

统一数据路径解析入口，消除 6 个文件中重复的 `__file__` 推算逻辑。

```python
def get_app_data_root():
    if getattr(sys, 'frozen', False):
        base = os.path.expandvars(r"%LOCALAPPDATA%\TK_Studio")
        os.makedirs(base, exist_ok=True)
        return base
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
```

- **开发模式**：返回项目根目录（`core/` 的上一级），与历史行为完全一致
- **EXE 模式**（`sys.frozen=True`）：返回 `%LOCALAPPDATA%\TK_Studio`，用户可写

### 2.2 路径迁移映射

| 数据 | 开发环境 | EXE 环境 | 可写性 |
|---|---|---|---|
| SQLite DB | `项目根/tk_studio.db` | `%LOCALAPPDATA%\TK_Studio\tk_studio.db` | ✅ |
| chrome_headless_profile | `项目根/chrome_headless_profile` | `%LOCALAPPDATA%\TK_Studio\chrome_headless_profile` | ✅ |
| chrome_cdp_profile | `项目根/chrome_cdp_profile` | `%LOCALAPPDATA%\TK_Studio\chrome_cdp_profile` | ✅ |
| chrome_home_fetcher_profile | `项目根/chrome_home_fetcher_profile` | `%LOCALAPPDATA%\TK_Studio\chrome_home_fetcher_profile` | ✅ |
| chrome_login_profile | `项目根/chrome_login_profile` | `%LOCALAPPDATA%\TK_Studio\chrome_login_profile` | ✅ |
| chrome_home_auth_profile | `项目根/chrome_home_auth_profile` | `%LOCALAPPDATA%\TK_Studio\chrome_home_auth_profile` | ✅ |
| 快照元数据 | `项目根/chrome_home_auth_profile.snapshot.json` | `%LOCALAPPDATA%\TK_Studio\...` | ✅ |
| 下载目录 | 用户配置 `~/Downloads/TK_Studio` | 不变 | ✅ |

### 2.3 下载目录保持不变

下载目录由 UI `download_path_edit` 控制，默认 `~/Downloads/TK_Studio`，与 `sys.frozen` 无关，不修改。

### 2.4 test_fix_dl1.py flaky test 修复

**问题**：`test_concurrent_same_title_downloads` 断言硬编码 `assert any("[2222222222222222222]" in n for n in mp4s)`，假设 Thread B（video_id=2222...）总是获得去重后缀。但并发竞态下哪个线程先占名不确定，Thread A 也可能获得后缀 `[1111111111111111111]`。

**修复**：断言改为对称——检查另一个文件携带任一 video_id 后缀，内容校验按实际归属反推。5 次连续运行全部通过。

---

## 三、不修改项

- 数据库表结构：未修改 ✅
- UI 布局/控件：未修改 ✅
- 下载流程架构：未修改 ✅
- 业务逻辑：未修改 ✅
- HomeFetch-A.3 功能：未修改 ✅
- FIX-DL.1 加固逻辑：未修改 ✅

---

## 四、测试结果

### 4.1 compileall
```
python -m compileall -q core workers tests
COMPILEALL_EXIT: 0
```
**PASS** ✅

### 4.2 路径解析验证（开发模式）
```
app_data_root: D:\TK_Studio_V1_fixed
DB_FILE: D:\TK_Studio_V1_fixed\tk_studio.db
chrome_bridge _PROJECT_ROOT: D:\TK_Studio_V1_fixed
LOGIN_PROFILE_DIR: D:\TK_Studio_V1_fixed\chrome_login_profile
AUTH_PROFILE_DIR: D:\TK_Studio_V1_fixed\chrome_home_auth_profile
--- ALL PATH CHECKS PASSED ---
```
**PASS** ✅（与历史行为一致，向后兼容）

### 4.3 路径解析验证（EXE 模式模拟）
```
EXE app_data_root: C:\Users\Administrator\AppData\Local\TK_Studio
EXE DB_FILE: C:\Users\Administrator\AppData\Local\TK_Studio\tk_studio.db
EXE chrome_bridge root: C:\Users\Administrator\AppData\Local\TK_Studio
EXE LOGIN_PROFILE_DIR: C:\Users\Administrator\AppData\Local\TK_Studio\chrome_login_profile
EXE AUTH_PROFILE_DIR: C:\Users\Administrator\AppData\Local\TK_Studio\chrome_home_auth_profile
--- EXE MODE PATH CHECKS PASSED ---
```
**PASS** ✅

### 4.4 DB 可写性验证（EXE 数据目录）
```
DB writable at C:\Users\Administrator\AppData\Local\TK_Studio: OK
```
**PASS** ✅

### 4.5 回归测试
```
python -m pytest tests/ -q
118 passed in 6.81s
```
**PASS** ✅（118/118）

### 4.6 flaky test 稳定性验证
```
Run 1: 9 passed
Run 2: 9 passed
Run 3: 9 passed
Run 4: 9 passed
Run 5: 9 passed
```
**PASS** ✅（5/5 稳定）

---

## 五、验收结论

| 验收项 | 状态 |
|---|---|
| 1. 增加 sys.frozen 判断 | ✅ `core/paths.py` `getattr(sys, 'frozen', False)` |
| 2. EXE 使用 %LOCALAPPDATA%\TK_Studio | ✅ 模拟验证通过 |
| 3. DB 使用用户数据目录 | ✅ EXE 模式 DB 写入验证通过 |
| 4. Chrome profile 使用用户数据目录 | ✅ 5 个 profile 目录全部迁移 |
| 5. 下载目录保持不变 | ✅ 未修改 UI 默认路径 |
| 6. 不修改业务逻辑 | ✅ 仅路径计算逻辑 |
| 7. FIX-EXE.1_IMPLEMENTATION_REPORT.md | ✅ 本报告 |
| compileall | ✅ PASS |
| 基础启动测试 | ✅ 路径解析 + DB 可写 + 118 回归 |

**验收通过。**
