# Phase FIX-DL.1 测试报告：下载模块权限问题加固

- 报告时间：2026-09-04 23:00
- 立项依据：用户指令「修复下载模块的权限问题」；前序基线 HomeFetch-A.3（未提交工作区）+ FIX-A.3-2
- 修改文件：仅 `core/downloader.py`（+219/-25）；新增 `tests/test_fix_dl1.py`（9 例）

## 一、诊断：已有防护与剩余缺口

已有防护（7-G.FIX.3 + HomeFetch-A.3 Task 7）：目录可写预检、.part 预清理、探测打开退避、os.replace 退避、失败自动清理、3 次 attempt 退避。

本轮定位的剩余缺口（按严重度）：

| # | 缺口 | 影响 |
|---|---|---|
| 1 | **并发同名冲突**：TaskManager `max_concurrent=3`，批量下载同作者多视频的 TikTok 自动标题高度重复（如 "COMMENTARY on TikTok"）→ 同名任务并行写同一 .part（字节交错损坏）、启动时互删对方 .part、`os.replace` 报 Permission denied、同名 .mp4 静默互相覆盖（数据丢失） | 高（批量下载场景新引入） |
| 2 | 写打开（原 L274）无退避：预检通过后 Defender 瞬间锁定 → 原始 PermissionError 直接进 attempt 重试，报错不友好且浪费重试 | 中 |
| 3 | 写入中 FileNotFoundError（AV 隔离 .part）→ 原始报错 | 中 |
| 4 | 只读属性残留：`os.remove` 对只读文件退避重试无效 | 低 |
| 5 | 跨会话同名 .mp4 静默覆盖其他作品文件 | 低 |

## 二、修复内容（core/downloader.py）

1. **最终文件名仲裁 `_claim_final_path` / `_release_final_path`**：
   - 进程内 in-flight 注册表（`threading.Lock` 保护，normcase(abs_dir, filename) 为键）防并发冲突
   - `works.local_path` 归属查询防跨会话覆盖其他作品文件（`run_download` 成功后本就写入该字段，零 schema 改动）
   - 干净名（`标题.mp4`）优先保持单任务体验；冲突时依次尝试 `标题 [video_id].mp4`、`标题 [video_id] (2).mp4`...
   - 同一作品重新下载仍覆盖自己的旧文件（id 匹配豁免）
2. **`.part` 跟随最终文件名** → 并发下天然唯一，不再混写/互删；旧版残留的 `标题.mp4.part` 与当前不同名时一并清理
3. **`_open_write_resilient`**：写打开 PermissionError 退避（0.4/0.8/1.6s）；FileNotFoundError（AV 隔离）转友好错误进通用重试；退避耗尽抛「临时文件无法写入」供 run_download 快速短路
4. **写入中 OSError 翻译**：FileNotFoundError/PermissionError 转人话错误（仍可自动重试）
5. **`_force_remove`**：只读属性先 `chmod(S_IWRITE)` 再删；`_cleanup_part_file`/`_prepare_part_file` 统一接入
6. 失败清理优先使用本次实际 .part 路径（`_part_path_for` DB 重建保留兜底）；注册表槽位在 finally 中释放（成功/失败/取消均覆盖）

未改动：下载状态机、SQLite 表结构、workers/download_worker.py、UI 层。

## 三、测试结果（tests/test_fix_dl1.py，9/9 PASS，6.44s）

| 测试 | 验证点 | 结果 |
|---|---|---|
| test_force_remove_readonly_part | 只读 .part 强制删除 | PASS |
| test_cleanup_part_file_readonly | 清理接口接入只读处理 | PASS |
| test_open_write_resilient_lock_released | Win32 独占锁 0.5s → 退避后打开成功 | PASS |
| test_open_write_resilient_lock_exhausted | 持续独占锁 → 「临时文件无法写入」友好报错 | PASS |
| test_prepare_part_file_locked_then_recover | run_download 级：.part 被锁 1s 后自动恢复下载且内容完整 | PASS |
| test_concurrent_same_title_downloads | **并发同名下载**：两任务成功、一干净名一去重名、哈希校验无损坏、无 .part 残留 | PASS |
| test_claim_release_registry | 注册表占用/释放语义 | PASS |
| test_cross_session_no_overwrite | 跨会话：B 不覆盖 A 已下载文件，改用去重名 | PASS |
| test_same_work_redownload_overwrites_own | 同作品重下允许覆盖自身 | PASS |

测试方法说明：用 ctypes `CreateFileW(dwShareMode=0)` 独占句柄精确模拟 Windows Defender 实时扫描锁定（Python `open()` 句柄共享模式无法复现）；本地 ThreadingHTTPServer 提供真实 HTTP 下载流。

**过程发现**：初版跨会话归属查询用 `download_tasks.message`（仅 TaskManager 写入，直调 run_download 的路径无记录）→ 修正为 `works.local_path`（run_download 自身必写）。另注意 pytest 对大字节串 `==` 断言失败时会用 difflib 做 O(n²) diff 导致假死，测试统一改用哈希比较。

### 回归
- 全量 pytest：**150 passed**（原 141 + 新增 9），7.87s
- `python -m compileall -q core workers tests`：PASS

## 四、冻结边界

- 修改：`core/downloader.py`、`tests/test_fix_dl1.py`（新增）
- 未触碰：core/tiktok_login.py（FIX-A.3-2 已冻结）、core/home_fetcher.py、tiktok_home_service.py、TK_Studio_V1_6_4.py、workers/*、db.py、parser、chrome_bridge、cookie_cache
- SQLite：零 schema 变更（仅新增读取既有 `works.local_path` 字段）

## 五、结论

**FIX-DL.1：PASS。** 下载模块权限类失败的四类场景（并发同名冲突、写打开窗口期锁定、AV 隔离、只读残留）全部有防护且有自动化测试背书；批量下载同名覆盖丢数据问题一并解决。
