# Phase 5-C 基线报告 — 全链路只读分析

> 阶段：Phase 5-C（只读分析，不修改代码）
> 基线：B4.3 验收 PASS（[PHASE5_B4_3_ACCEPTANCE_REPORT.md](file:///d:/TK_Studio_V1_fixed/PHASE5_B4_3_ACCEPTANCE_REPORT.md)）
> 分析时间：2026-09-04
> commit：`17b41dbd557683bc1a3ef754abf9e1ad4b207a1d`（自 B1.x 起未提交，累积改动见 git status）

---

## 1. 项目结构概览

### 1.1 模块分层（50+ Python 文件）

```
┌─────────────────────────────────────────────────────────┐
│  UI 层                                                    │
│  TK_Studio_V1_6_4.py (1031行)  main.py (343行)           │
│  add_task_methods.py (126行, 迁移脚本)                    │
├─────────────────────────────────────────────────────────┤
│  Workers 层（QThread 封装）                                │
│  parse_worker.py    download_worker.py                    │
│  home_fetch_worker.py  login_worker.py  task_manager.py   │
├─────────────────────────────────────────────────────────┤
│  Core 层（业务逻辑，不依赖 PySide6）                      │
│  parser.py  tiktok_service.py  url_resolver.py             │
│  downloader.py  db.py  chrome_bridge.py                   │
│  home_fetcher.py  home_worker.py                          │
│  tiktok_home_fetcher/service/worker/adapter               │
│  tiktok_login.py  profile_snapshot.py                      │
└─────────────────────────────────────────────────────────┘
```

### 1.2 Phase 5 已完成阶段

| 阶段 | 内容 | 状态 |
|------|------|------|
| 5-A1~A3 | Chrome CDP 探针 + meta/JSON 解析 | 已完成 |
| 5-A4 | 主页 fetcher + QR 登录 | FROZEN |
| 5-B1.x | TikTok 主页数据链路（fetcher/service/adapter/worker） | FROZEN |
| 5-B2.x | HomeFetchWorker QThread 封装 + UI wiring | FROZEN |
| 5-B3.x | profile_dir + 匿名/认证模式 + login_success snapshot | FROZEN |
| 5-B4.2 | TikTok 短链 URL Resolver | FROZEN（验收 PASS） |
| 5-B4.3 | 短链解析增强（4 格式/GET fallback/Retry/normalize/TTL+LRU） | 验收 PASS |

### 1.3 冻结模块清单

| 模块 | 行数 | 冻结阶段 |
|------|------|----------|
| `core/parser.py` | 92 | 全局冻结 |
| `core/tiktok_service.py` | 85 | 全局冻结 |
| `core/home_fetcher.py` | 236 | B2.x 基线 |
| `core/tiktok_home_fetcher.py` | 32 | B1.x |
| `core/tiktok_home_service.py` | 99 | B1.x |
| `core/tiktok_home_worker.py` | 79 | B1.x |
| `core/home_worker.py` | 87 | B1.x |
| `workers/home_fetch_worker.py` | 67 | B2.x |
| `core/downloader.py` | 242 | 全局冻结 |
| `core/db.py` | 430 | 全局冻结（表结构不变） |
| `workers/task_manager.py` | 433 | B1.x 基线 |
| `core/tiktok_login.py` | 512 | A4 FROZEN |
| `workers/login_worker.py` | 106 | A4 FROZEN |
| `core/profile_snapshot.py` | 159 | B3.4 FROZEN |
| `TK_Studio_V1_6_4.py` | 1031 | UI 层（可改，但需保持核心逻辑不变） |

---

## 2. 五大重点分析

### 2.1 TikTok 作品采集链路

#### 完整调用链

```
用户粘贴 URL
  ↓
parse_single() [TK_Studio_V1_6_4.py L541]
  ↓ is_short_url() → resolve_short_url()    [主线程同步，B4.3]
  ↓ tiktok.com / /video/ 校验
  ↓
ParseWorker(valid_urls, db) [workers/parse_worker.py L16]
  ↓ QThread.run()
  ↓
tiktok_service.parse_url(url) [core/tiktok_service.py L25]
  ├─ requests.get(url, timeout=20)           [无 Retry，无 Session]
  ├─ parser.extract_tiktok_data(html)         [正则 meta + JSON]
  └─ Chrome fallback: load_with_chrome(url)   [core/chrome_bridge.py L30]
     └─ --headless --dump-dom
  ↓
db.add_work() 入库
  ↓
ParseWorker.success signal → _on_parse_success() [UI 更新]
```

#### 稳定性薄弱点

| 环节 | 问题 | 严重度 |
|------|------|--------|
| `tiktok_service.parse_url` L54 | `requests.get` 无 Retry，单次网络抖动即触发 Chrome fallback | 高 |
| `tiktok_service.parse_url` L78 | `except Exception` 吞所有异常，仅日志，不区分网络错误/解析错误/超时 | 中 |
| `chrome_bridge.load_with_chrome` | 无超时控制，Chrome 可能长时间挂起 | 高 |
| `parser.extract_tiktok_data` | 完全正则，TikTok 页面结构变化即失效 | 高 |
| 主页采集 `home_fetcher` | 依赖 Chrome CDP，无 HTTP fallback，Chrome 启动慢 | 中 |
| `ParseWorker.run` | 串行解析多个 URL，无并发 | 低 |

### 2.2 URL 输入体验

#### 现状

| 功能 | 状态 | 说明 |
|------|------|------|
| 单作品 URL 多行输入 | ✅ | `parse_single` 支持 splitlines |
| 短链解析（vm/vt/t/tiktok-t/） | ✅ B4.3 | 4 种格式 + Retry + 缓存 |
| 短链解析 UI 集成 | ✅ B4.2 | `parse_single` 中同步调用 |
| 主页 URL 短链解析 | ❌ | `start_home_fetch` 未集成 url_resolver |
| URL 历史记录 | ❌ | 无 |
| URL 书签/收藏 | ❌ | 无 |
| 批量 URL 文件导入 | ❌ | 无 |
| 短链解析后台化 | ❌ | `parse_single` 中 `resolve_short_url` 主线程同步，批量短链卡 UI |

#### 主线程阻塞风险

[TK_Studio_V1_6_4.py L559-561](file:///d:/TK_Studio_V1_fixed/TK_Studio_V1_6_4.py#L559-L561)：

```python
if is_short_url(url):
    resolved = resolve_short_url(
        url, log_callback=self.single_log.append  # 主线程同步 HTTP
    )
```

B4.3 加了 Retry（total=2），最坏单短链耗时 = 3×(HEAD timeout) + 3×(GET timeout) = 60s。N 个短链串行 = N×60s 主线程阻塞。

### 2.3 Parser 稳定性

#### 现状（[core/parser.py](file:///d:/TK_Studio_V1_fixed/core/parser.py)，92 行）

解析策略：
1. **meta tags**：`og:title` / `og:image` / `og:video` / `twitter:*` → 标题/封面/视频地址
2. **内嵌 JSON 正则**：`"uniqueId"` / `"desc"` / `"cover"` / `"playAddr"` → 作者/标题/封面/视频
3. **数值正则**：`"duration"` / `"width"` / `"height"` → 时长/分辨率

#### 薄弱点

| 问题 | 影响 | 严重度 |
|------|------|--------|
| 无结构化 JSON 解析（如 `json.loads` + 字段路径） | TikTok JSON 结构变化时正则脆弱 | 高 |
| 无 SIGIState / `__UNIVERSAL_DATA_FOR_REHYDRATION__` 解析 | TikTok 新版页面主数据在此 JSON blob 中，正则可能遗漏 | 高 |
| 无单元测试覆盖 parser | 回归无保障 | 中 |
| `_clean_tiktok_value` 用 `unicode_escape` 解码 | 非标准解码，可能产生乱码 | 低 |
| `find_json_string` 正则匹配 `"key":"value"` | JSON 值含转义引号时可能截断 | 中 |

### 2.4 下载队列效率

#### 现状（[workers/task_manager.py](file:///d:/TK_Studio_V1_fixed/workers/task_manager.py)，433 行）

| 机制 | 状态 | 说明 |
|------|------|------|
| 内存队列 `waiting_queue` | ✅ | FIFO，无优先级 |
| 并发上限 `max_concurrent=3` | ✅ | 达到上限直接提示用户，不排队 |
| `running_workers` dict | ✅ | work_id → DownloadWorker |
| `work_tasks` 防重复 | ✅ | 内存 + DB `get_active_tasks_by_work` 双重检查 |
| 进度节流写库 | ✅ | ≥1% 或 ≥2s 才写 download_tasks |
| urllib3 Retry | ✅ | [downloader.py L192-200](file:///d:/TK_Studio_V1_fixed/core/downloader.py#L192-L200) |
| 断点续传 | ✅ | `.part` 文件 + Range header |
| 队列持久化恢复 | ❌ | 启动时 `reset_download_tasks_on_startup` 标记为"失败"，不恢复 |
| 批量暂停/恢复 | ❌ | 无 |
| 优先级队列 | ❌ | 无 |
| 下载限速 | ❌ | 无 |

#### 数据库写入热点

| 操作 | 频率 | 表 |
|------|------|-----|
| `update_download_task` (进度) | 每 ≥1% 或 ≥2s | download_tasks |
| `update_work` (视频地址) | 每作品 1-2 次 | works |
| `get_active_tasks_by_work` | 每次 enqueue | download_tasks |

### 2.5 UI / 后台任务体验

#### Worker 管理现状

| Worker | 启动方式 | 取消方式 | 完成回调 | UI 阻塞风险 |
|--------|----------|----------|----------|-------------|
| ParseWorker | `parse_single` → `worker.start()` | 无显式取消 | `_on_parse_success/failed/finished` | 低（解析在 QThread） |
| DownloadWorker | `TaskManager.enqueue` → `_start_task` | `DownloadWorker.cancel()` | `_on_dl_progress/finished/failed` | 低（下载在 QThread） |
| HomeFetchWorker | `start_home_fetch` → `worker.start()` | 无显式取消 | `home_success/failed/log` | 低（采集在 QThread） |
| LoginWorker | 登录按钮 → `worker.start()` | Chrome 进程退出 | `_on_login_success/worker_finished` | 低 |

#### 用户体验短板

| 问题 | 影响 | 严重度 |
|------|------|--------|
| `parse_single` 短链解析主线程同步 | 批量短链输入卡 UI | 中 |
| 无全局进度总览面板 | 用户无法一览所有任务状态 | 中 |
| 错误提示仅文本日志 | 无法区分"网络失败"/"被风控"/"解析失败" | 中 |
| 无任务统计（总数/完成/失败） | 用户缺乏整体进度感知 | 低 |
| `closeEvent` 有界等待登录 worker | 可能残留 Chrome 进程 | 低 |
| 主页采集结果仅文本列表 | 无结构化展示（缩略图/标题预览） | 低 |

---

## 3. 当前能力矩阵

| 能力域 | 已实现 | 缺失 |
|--------|--------|------|
| 短链解析 | 4 格式 / HEAD+GET / Retry / normalize / TTL+LRU 缓存 | 并发 / 后台化 / 结构化返回 |
| 作品解析 | requests + Chrome fallback / meta + JSON 正则 | 结构化 JSON 解析 / Retry / 单元测试 |
| 主页采集 | Chrome CDP / 滚动懒加载 / profile 模式 | HTTP fallback / 短链解析集成 |
| 下载队列 | 并发 3 / Retry / 断点续传 / 进度节流 | 持久化恢复 / 批量操作 / 优先级 |
| UI/UX | 多 Worker / 信号回调 / closeEvent 清理 | 进度总览 / 异步短链 / 结构化错误 |
| 登录 | QR 扫码 / profile snapshot / 匿名/认证切换 | — |

---

## 4. B4.3 暂缓项状态

| 暂缓项 | 说明 | Phase 5-C 候选 |
|--------|------|----------------|
| B4.3-P6 | `resolve_urls()` ThreadPoolExecutor 并发 | 可纳入 |
| B4.3-P7 | `resolve_short_url_ex()` 结构化返回 | 可纳入 |
| B4.3-P8 | 完整测试套件 | 可纳入 |
| parse_single 后台化 | 短链解析移入后台线程 | 可纳入（高收益） |

---

## 5. 冻结边界约束总结

Phase 5-C 任何方案需遵守：

| 约束 | 说明 |
|------|------|
| 不改 `core/parser.py` | 冻结，需新增解析层 |
| 不改 `core/tiktok_service.py` | 冻结，需新增 wrapper/中间层 |
| 不改 `core/downloader.py` | 冻结 |
| 不改 `core/db.py` 表结构 | 冻结（works 13 字段不变） |
| 不改 `workers/task_manager.py` | B1.x 基线（可评估新增方法，不改现有逻辑） |
| 不改 B1.x/B3.x/A4 文件 | 全部 FROZEN |
| `TK_Studio_V1_6_4.py` 可改 | 但需保持 ParseWorker/DownloadWorker 调用链、Signal 接口、核心业务逻辑不变 |
| `core/url_resolver.py` 可改 | B4.3 已验收，作为新基线可演进 |
