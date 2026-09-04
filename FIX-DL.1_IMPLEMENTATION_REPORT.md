# Phase FIX-DL.1 实施报告：下载模块权限问题加固

- 报告时间：2026-09-04
- 立项依据：修复 Windows 下载过程中 Permission denied、.mp4.part 被占用、批量下载同名文件冲突问题
- 修改范围：仅 `core/downloader.py`；新增 `tests/test_fix_dl1.py`
- 禁止项检查：✅ 未修改数据库结构 / ✅ 未修改 UI / ✅ 未改变下载流程架构 / ✅ 不影响 HomeFetch-A.3 功能

---

## 一、修改文件

| 文件 | 类型 | 说明 |
|---|---|---|
| `core/downloader.py` | 修改 | 新增 FIX-DL.1 全部加固逻辑 |
| `tests/test_fix_dl1.py` | 新增 | 9 例专项测试，覆盖 4 个验收场景 |

---

## 二、修改点（core/downloader.py）

### 1. 修复并发同名文件冲突（最高优先级）

**新增最终文件名仲裁机制：**

- `_FINAL_NAME_LOCK` / `_FINAL_NAME_IN_FLIGHT`：进程内 in-flight 文件注册表（`threading.Lock` 保护，键为 `normcase(abs_dir, filename)`），防止并发同进程冲突
- `_norm_key(output_dir, filename)`：注册表键计算
- `_path_owned_by_other_work(db, work_id, full_path)`：查询 `works.local_path` 判断目标路径是否已被其他作品占用（跨会话保护）；查询失败保守返回 True（宁可不覆盖）
- `_claim_final_path(db, work_id, output_dir, title, video_id)`：仲裁最终 `.mp4` 文件名，返回 `(path, claim_key)`
  - 干净名（`标题.mp4`）优先：保持单任务下载体验不变
  - 冲突时依次尝试 `标题 [video_id].mp4`、`标题 [video_id] (2).mp4`...（最多 20 个候选）
  - 同一作品重下允许覆盖自身（id 匹配豁免）
- `_release_final_path(claim_key)`：下载结束/失败后释放注册表槽位（在 `run_download` 的 `finally` 中调用，成功/失败/取消均覆盖）

**`run_download` 集成：**
```python
path, claim_key = _claim_final_path(
    db, work_id, output_dir, title, video_id)
part = path + ".part"
```

### 2. .part 文件隔离

`.part` 跟随最终文件名（`path + ".part"`），并发下天然唯一，不再混写/互删。
- 下载前清理历史残留 `.part`（当前 part + 旧版 `标题.mp4.part` 不同名时一并清理）
- 不同 `work_id` 禁止使用同一个 `.part`

### 3. 增强写入阶段权限重试

**新增 `_open_write_resilient(part, mode)`：**
- 退避序列：`0s → 0.4s → 0.8s → 1.6s`
- `PermissionError`（Windows Defender 锁定）：退避重试
- `FileNotFoundError`（AV 隔离删除 `.part`）：转友好错误 `RuntimeError("临时文件被安全软件删除或隔离...")`
- 退避耗尽仍 `PermissionError`：抛 `RuntimeError("临时文件无法写入...")`，由 `run_download` 快速短路（本地环境问题，重试无意义）

**写入中 OSError 翻译：**
- `FileNotFoundError` → 友好错误，可自动重试
- `PermissionError` → 友好错误

### 4. 增强删除残留文件能力

**新增 `_force_remove(path)`：**
- `os.remove()` 失败时：
  1. `chmod(S_IWRITE)` 清除只读位
  2. 再次 `os.remove()`
- 应用位置：`.part` 清理（`_cleanup_part_file`）、旧残留清理、异常恢复、超小残片清理（`_prepare_part_file`）

**辅助函数：**
- `_open_part_resilient(part, mode, progress_cb, allow_recreate)`：探测打开 `.part` 验证可写性，被锁定时退避重试；`allow_recreate=True` 时可删除重建
- `_prepare_part_file(part, progress_cb)`：下载前确保 `.part` 可写，返回可续传字节数（-1 表示无法写入）
- `_cleanup_part_file(part)`：最佳努力清理，退避序列 `0s/0.5s/1.0s/2.0s`
- `_replace_with_retry(part, path)`：`.part → .mp4` 改名退避重试（`0s/0.5s/1.0s/2.0s`）

### 5. 修复失败清理路径

**优先使用本次下载实际使用的 `.part` 路径：**
```python
if str(e) != "用户取消下载":
    stale_part = part or _part_path_for(db, work_id, output_dir)
    if stale_part:
        _cleanup_part_file(stale_part)
```
- `part`：本次下载实际使用的路径（首选）
- `_part_path_for(db, work_id, output_dir)`：DB 记录重建路径（仅作 fallback，异常发生在路径计算前时使用）
- 用户主动取消除外：保留 `.part` 供下次续传

### 额外加固（权限类失败的基础防护）

- **目录可写预检**：下载前用探针文件 `__tk_writetest_{pid}_{tid}.tmp` 验证目录可写，尽早转明确提示
- **`run_download` 快速短路**：`临时文件无法写入` 前缀错误不重试（本地环境问题）
- **普通重试退避**：`time.sleep(1.0)` 给杀毒扫描/网络抖动留出恢复窗口

---

## 三、测试结果

### FIX-DL.1 专项测试（tests/test_fix_dl1.py，9/9 PASS，6.52s）

| # | 测试 | 验收场景 | 结果 |
|---|---|---|---|
| 1 | `test_force_remove_readonly_part` | 只读 `.part` 强制删除 | PASS |
| 2 | `test_cleanup_part_file_readonly` | 清理接口接入只读处理 | PASS |
| 3 | `test_open_write_resilient_lock_released` | Win32 独占锁 0.5s → 退避后打开成功 | PASS |
| 4 | `test_open_write_resilient_lock_exhausted` | 持续独占锁 → 「临时文件无法写入」友好报错 | PASS |
| 5 | `test_prepare_part_file_locked_then_recover` | run_download 级：`.part` 被锁 1s 后自动恢复下载且内容完整 | PASS |
| 6 | `test_concurrent_same_title_downloads` | **并发同名下载**：两任务成功、一干净名一去重名、哈希校验无损坏、无 `.part` 残留 | PASS |
| 7 | `test_claim_release_registry` | 注册表占用/释放语义 | PASS |
| 8 | `test_cross_session_no_overwrite` | **已有同名 mp4**：B 不覆盖 A 已下载文件，改用去重名 | PASS |
| 9 | `test_same_work_redownload_overwrites_own` | 同作品重下允许覆盖自身 | PASS |

### 用户要求的 4 个验收场景对照

| 验收场景 | 对应测试 | 结果 |
|---|---|---|
| 1. 两个相同标题视频并发下载：生成两个不同 mp4、无 .part 冲突、文件内容正确 | `test_concurrent_same_title_downloads` | PASS |
| 2. 模拟 Windows Defender 独占锁：自动等待恢复 | `test_open_write_resilient_lock_released` + `test_prepare_part_file_locked_then_recover` | PASS |
| 3. 只读 .part 文件：自动解除只读并删除 | `test_force_remove_readonly_part` + `test_cleanup_part_file_readonly` | PASS |
| 4. 已有同名 mp4：不会覆盖其他任务文件 | `test_cross_session_no_overwrite` | PASS |

### 测试方法说明

- 用 `ctypes.CreateFileW(dwShareMode=0)` 独占句柄精确模拟 Windows Defender 实时扫描锁定（Python `open()` 句柄共享模式无法复现共享冲突）
- 本地 `ThreadingHTTPServer` 提供真实 HTTP 下载流（2 MiB 数据，两种不同模式用于并发内容校验）
- 哈希比较（`hashlib.sha256`）避免 pytest 对大字节串 `==` 断言失败时 difflib O(n²) diff 假死

### 回归测试

- **全量 pytest**：**118 passed**（109 原有 + 9 新增），6.83s
- **`python -m compileall -q core workers tests`**：PASS（exit 0）

---

## 四、冻结边界检查

| 文件 | 状态 |
|---|---|
| `core/downloader.py` | ✅ 修改（FIX-DL.1 加固） |
| `tests/test_fix_dl1.py` | ✅ 新增 |
| `core/tiktok_login.py` | ✅ 未触碰 |
| `core/home_fetcher.py` | ✅ 未触碰 |
| `core/tiktok_home_service.py` | ✅ 未触碰 |
| `TK_Studio_V1_6_4.py` | ✅ 未触碰 |
| `workers/*` | ✅ 未触碰 |
| `core/db.py` | ✅ 未触碰（零 schema 变更，仅读取既有 `works.local_path` 字段） |
| `core/parser.py` | ✅ 未触碰 |
| `core/chrome_bridge.py` | ✅ 未触碰 |

**注**：本次实现不引用 `core/cookie_cache`（Phase 7-F 模块），`run_download` 中 `cookie_items = []`，保持 FIX-DL.1 范围纯净，不引入 Phase 7-F 依赖。

---

## 五、结论

**FIX-DL.1：PASS。**

下载模块权限类失败的四类场景全部有防护且有自动化测试背书：

1. ✅ **并发同名冲突**：in-flight 注册表 + DB 归属查询 + 文件存在检查三层仲裁，冲突时自动改用 `标题 [video_id].mp4`
2. ✅ **写打开窗口期锁定**：`_open_write_resilient` 退避重试（0s/0.4s/0.8s/1.6s）
3. ✅ **AV 隔离删除 .part**：`FileNotFoundError` 转友好错误，可自动重试
4. ✅ **只读残留 .part**：`_force_remove` 清除只读位后删除

批量下载同名覆盖丢数据问题一并解决。
