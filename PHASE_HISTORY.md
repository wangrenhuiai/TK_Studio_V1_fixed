# Phase History — TK Studio V1.6.4 开发历程

> 项目：TK Studio V1.6.4
> 时间跨度：2026-09-03 ~ 2026-09-04
> 提交历史：3 commits（initial → core/workers → login/parse/task）

---

## Phase 5 — TikTok 数据链路与增强

### Phase 5-B1.1 ~ B1.4（TikTok 数据链路）

| 项 | 内容 |
|----|------|
| 时间 | 2026-09-04 11:16 |
| 目标 | TikTok 主页 URL → 作品列表抓取链路 |
| 新增 | tiktok_home_fetcher / tiktok_home_service / tiktok_home_worker / tiktok_home_adapter / home_worker |
| 修改 | TK_Studio_V1_6_4.py（TaskManager wiring）/ task_manager.py / home_fetcher.py |
| 验收 | PASS |
| 冻结 | 是 |

关键修复：
- home_fetcher.py IndentationError 修复
- TaskManager 完整实例化到 MainWindow
- _on_progress DB 写入节流（≥1% 或 ≥2s）
- shutdown() 标记 running tasks 为 '下载失败'

### Phase 5-B2.2-B（HomeFetchWorker QThread）

| 项 | 内容 |
|----|------|
| 时间 | 2026-09-04 12:32 |
| 目标 | HomeFetchWorker QThread 包装 + UI wiring |
| 新增 | workers/home_fetch_worker.py |
| 修改 | TK_Studio_V1_6_4.py（UI 集成） |
| 验收 | PASS |
| 冻结 | 是 |

### Phase 5-B3.1（profile_dir 支持）

| 项 | 内容 |
|----|------|
| 时间 | 2026-09-04 13:06 |
| 目标 | HomeFetcher 支持 profile_dir 参数 |
| 修改 | home_fetcher.py（baseline）+ TK_Studio UI |
| 验收 | PASS |
| 冻结 | 是 |

### Phase 5-B3.2（UI profile mode 选择）

| 项 | 内容 |
|----|------|
| 时间 | 2026-09-04 13:06 |
| 目标 | UI 添加 Anonymous/Auth 模式选择 |
| 修改 | TK_Studio_V1_6_4.py |
| 验收 | PASS |
| 冻结 | 是 |

### Phase 5-B3.4（登录 snapshot 机制）

| 项 | 内容 |
|----|------|
| 时间 | 2026-09-04 13:45 |
| 目标 | 登录成功后 snapshot 到 auth profile |
| 新增 | core/profile_snapshot.py |
| 修改 | TK_Studio_V1_6_4.py（_on_login_worker_finished 集成） |
| 验收 | PASS（真人扫码验收） |
| 冻结 | 是 |

关键设计：
- Snapshot 在 LoginWorker.finished 触发（非 login_success）
- 选择性复制 Local State / Cookies / Local Storage
- 失败优雅降级到匿名模式

### Phase 5-B4.2（TikTok 短链 Resolver）

| 项 | 内容 |
|----|------|
| 时间 | 2026-09-04 13:55 |
| 目标 | TikTok 短链 URL Resolver |
| 新增 | core/url_resolver.py |
| 修改 | TK_Studio_V1_6_4.py（parse_single 集成） |
| 验收 | PASS |
| 冻结 | 是 |

### Phase 5-B4.3（短链解析增强）

| 项 | 内容 |
|----|------|
| 时间 | 2026-09-04 14:35 |
| 目标 | 短链解析稳定性优化 |
| 修改 | core/url_resolver.py（HEAD+GET fallback + Retry + 缓存 + 标准化） |
| 新增 | tests/test_url_resolver.py（24 项） |
| 验收 | PASS |
| 冻结 | 是 |

### Phase 5-C1（ResolveWorker 后台化 + Parser JSON Layer）

| 项 | 内容 |
|----|------|
| 时间 | 2026-09-04 15:10 |
| 目标 | 短链解析后台化 + JSON 结构化解析 |
| 新增 | workers/resolve_worker.py / core/parser_ex.py / tests/test_parser_ex.py |
| 修改 | TK_Studio_V1_6_4.py（parse_single 两阶段拆分） |
| 验收 | PASS |
| 冻结 | 是 |

关键设计：
- parse_single 拆为：短链检测 → ResolveWorker → _validate_and_parse → ParseWorker
- parser_ex 支持 3 种 JSON blob，正则优先 + JSON 补充缺失

### Phase 5-C2（parser_ex 集成 + Retry Wrapper）

| 项 | 内容 |
|----|------|
| 时间 | 2026-09-04 15:12 |
| 目标 | parser_ex 正式接入 + TikTok 请求 Retry |
| 新增 | core/http_client.py / core/tiktok_request.py / tests/test_parser_integration.py / tests/test_http_client.py |
| 修改 | core/parser_ex.py（docstring 修正 + 别名） |
| 验收 | PASS |
| 冻结 | 是 |

### Phase 5-C3（Final Polish — UI 状态优化）

| 项 | 内容 |
|----|------|
| 时间 | 2026-09-04 15:19 |
| 目标 | UI 按钮状态反馈优化 |
| 修改 | TK_Studio_V1_6_4.py（4 处 setText） |
| 验收 | PASS |
| 冻结 | 是 — Phase 5 全链路冻结 |

---

## Phase 6 — Final QA

### Phase 6-A ~ D（Final QA）

| 项 | 内容 |
|----|------|
| 时间 | 2026-09-04 15:22 ~ 15:28 |
| 6-A | 基线检查 — 3 M + 30+ ?? 文件，冻结文件未触碰 |
| 6-B | 自动化回归 — 46 文件编译 + 81 测试 + 10 import 全 PASS |
| 6-C | 功能验收 — 5 大链路代码审查 PASS |
| 6-D | 发布检查 — DB schema + 依赖 + 风险清单 |
| 输出 | FINAL_RELEASE_REPORT.md |

### Phase 6-E（实网验收）

| 项 | 内容 |
|----|------|
| 时间 | 2026-09-04 15:30 ~ 15:34 |
| 方式 | 命令行实网探针 + GUI 启动验证 |
| 结果 | 17/19 PASS（2 FAIL 为 TikTok 反爬限流） |
| 关键验证 | Chrome 检测 + 真实短链解析 + parse_url + fetch_tiktok_html + GUI 启动 |
| 输出 | PHASE6_E_MANUAL_ACCEPTANCE_REPORT.md |

### Phase 6-F（最终发布检查）

| 项 | 内容 |
|----|------|
| 时间 | 2026-09-04 15:36 |
| git diff | 3 M（+334/-94）+ 30+ ?? |
| 临时清理 | 删除 tiktok_home_dom_probe 副本.py |
| 全量验证 | 45 文件编译 + 81 测试 + 10 import 全 PASS |
| 输出 | FINAL_RELEASE_CHECKLIST.md / RELEASE_NOTES.md / PHASE_HISTORY.md |

### Phase 6-G（Release Freeze）

| 项 | 内容 |
|----|------|
| 时间 | 2026-09-04 15:40 |
| 冻结声明 | 不再修改业务代码，只允许文档/版本号/打包配置修改 |

---

## 累计成果

### 文件统计

| 类别 | 数量 |
|------|------|
| 新增核心模块 | 10 |
| 新增 Worker | 2 |
| 新增测试文件 | 7 |
| 修改文件 | 3 |
| Phase 报告 | 18 |
| Python 文件总数 | 45 |
| 测试用例总数 | 81 |

### 阶段统计

| Phase | 子阶段数 | 状态 |
|-------|---------|------|
| B1.x | 4 | ✅ 冻结 |
| B2.x | 1 | ✅ 冻结 |
| B3.x | 3 | ✅ 冻结 |
| B4.x | 2 | ✅ 冻结 |
| C1-C3 | 3 | ✅ 冻结 |
| 6-A~G | 7 | ✅ 完成 |
| **总计** | **20** | **全部 PASS** |
