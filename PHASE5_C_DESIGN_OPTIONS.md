# Phase 5-C 设计候选方案 — 高收益优化方向

> 阶段：Phase 5-C（只读分析，不修改代码）
> 基线：[PHASE5_C_BASELINE_REPORT.md](file:///d:/TK_Studio_V1_fixed/PHASE5_C_BASELINE_REPORT.md)
> 状态：**等待人工批准，未进入实施**
> 输出：5 个候选方案 A-E，含收益/风险/范围/冻结/工时评估

---

## 方案总览

| 方案 | 名称 | 收益 | 风险 | 触碰冻结 | 推荐度 |
|------|------|------|------|----------|--------|
| A | Parser 结构化 JSON 解析层 | 高 | 低 | 否 | ★★★★★ |
| B | parse_single 短链解析后台化 | 高 | 低 | 否 | ★★★★★ |
| C | tiktok_service 请求重试 wrapper | 高 | 中 | 否（新增 wrapper） | ★★★★ |
| D | 下载队列持久化恢复 + 批量操作 | 中 | 高 | 是（task_manager/db） | ★★ |
| E | UI 进度总览面板 + 结构化错误 | 中 | 低 | 否 | ★★★ |

---

## 方案 A：Parser 结构化 JSON 解析层

### A.1 目标
提升 TikTok 作品解析成功率，解决正则解析在 TikTok 页面结构变化时失效的问题。

### A.2 问题
- [core/parser.py](file:///d:/TK_Studio_V1_fixed/core/parser.py) 完全基于正则，脆弱
- TikTok 新版页面主数据在 `SIGI_STATE` / `__UNIVERSAL_DATA_FOR_REHYDRATION__` JSON blob 中
- 正则匹配 `"key":"value"` 在值含转义引号时可能截断
- parser.py 无单元测试

### A.3 方案
**新增** `core/parser_ex.py`（不修改冻结的 parser.py）：

```python
def extract_tiktok_data_ex(html):
    """增强解析：结构化 JSON 优先，正则兜底。"""
    # 1. 尝试提取 SIGI_STATE / UNIVERSAL_DATA JSON
    json_data = _extract_structured_json(html)
    if json_data:
        result = _parse_from_structured(json_data)
        if _is_complete(result):
            return result
    # 2. 回退到原 parser（保持兼容）
    from core.parser import extract_tiktok_data
    base = extract_tiktok_data(html)
    # 3. 用结构化结果补充 base 缺失字段
    return _merge(base, json_data)
```

### A.4 评估

| 维度 | 评估 |
|------|------|
| 收益 | **高** — 解析是采集链路核心，成功率提升直接转化为可用性 |
| 风险 | **低** — 新增文件，不改 parser.py，fallback 到原 parser |
| 修改范围 | 新增 `core/parser_ex.py` + `tests/test_parser_ex.py` |
| 触碰冻结 | **否** — parser.py 不变，tiktok_service.py 不变 |
| 工时 | 中（JSON 结构分析 + 解析 + 测试） |
| 集成方式 | 后续可在 tiktok_service 新增 wrapper 调用 parser_ex，或 ParseWorker 优先用 parser_ex |

### A.5 风险点
- TikTok JSON blob 结构需实网抓取分析（一次性）
- `json.loads` 失败时需安全 fallback
- 需保证与原 parser 输出字段完全一致

---

## 方案 B：parse_single 短链解析后台化

### B.1 目标
解决批量短链输入时 `resolve_short_url` 主线程同步阻塞 UI 的问题。

### B.2 问题
- [TK_Studio_V1_6_4.py L559-561](file:///d:/TK_Studio_V1_fixed/TK_Studio_V1_6_4.py#L559-L561) `resolve_short_url` 在主线程同步调用
- B4.3 加了 Retry（total=2），最坏单短链 60s
- N 个短链串行 = N×60s 主线程阻塞，UI 完全冻结
- 用户无法取消、无进度反馈

### B.3 方案
**新增** `workers/resolve_worker.py`（QThread），**修改** `TK_Studio_V1_6_4.py` parse_single：

```python
# parse_single 修改后流程
URL 输入
  ↓
启动 ResolveWorker(urls)          ← 后台线程
  ↓
ResolveWorker.run():
  for url in urls:
    resolved = resolve_short_url(url, log_callback)
    emit resolved_signal(url, resolved)
  emit finished_signal(all_results)
  ↓
_on_url_resolved(url, resolved):  ← 主线程回调
  日志 + 替换 URL
  ↓
_on_resolve_finished(results):    ← 主线程回调
  tiktok.com / /video/ 校验
  ParseWorker(valid_urls, db)
```

### B.4 评估

| 维度 | 评估 |
|------|------|
| 收益 | **高** — 彻底解决 UI 阻塞，批量短链输入体验质变 |
| 风险 | **低** — 新增 Worker，parse_single 流程调整但核心不变 |
| 修改范围 | 新增 `workers/resolve_worker.py` + 修改 `TK_Studio_V1_6_4.py` parse_single 区域 |
| 触碰冻结 | **否** — TK_Studio_V1_6_4.py 可改，url_resolver.py 可改 |
| 工时 | 低-中（QThread 封装 + UI 回调接线） |
| API 兼容 | resolve_short_url 签名不变；parse_single 对用户行为不变 |

### B.5 风险点
- Worker 生命周期管理（需处理用户在解析中关闭窗口）
- closeEvent 需增加 ResolveWorker 清理
- 信号竞态（用户快速多次点击解析）

---

## 方案 C：tiktok_service 请求重试 wrapper

### C.1 目标
为冻结的 `tiktok_service.parse_url` 增加 Retry 能力，不修改冻结模块。

### C.2 问题
- [core/tiktok_service.py L54](file:///d:/TK_Studio_V1_fixed/core/tiktok_service.py#L54) `requests.get` 无 Retry
- 单次网络抖动即触发 Chrome fallback（启动 Chrome 耗时 3-10s）
- downloader.py 已有 Retry 配置，tiktok_service 未对齐

### C.3 方案
**新增** `core/tiktok_service_ex.py`（wrapper，不修改冻结的 tiktok_service.py）：

```python
def parse_url_ex(url, log_callback=None):
    """带 Retry 的 parse_url wrapper。"""
    # 1. 用带 Retry 的 Session 预请求页面 HTML
    html = _fetch_with_retry(url, timeout=20, retries=2)
    # 2. 用原 parser 解析
    from core.parser import extract_tiktok_data
    data = extract_tiktok_data(html)
    # 3. 如果缺失字段，回退到原 tiktok_service.parse_url（含 Chrome fallback）
    if not data["title"] or not data["video_url"]:
        from core.tiktok_service import parse_url
        return parse_url(url, log_callback)
    # 4. 补充 URL 提取的 video_id / author
    return _enrich_result(url, data)
```

### C.4 评估

| 维度 | 评估 |
|------|------|
| 收益 | **高** — 减少不必要的 Chrome fallback，解析速度提升 3-10s/次 |
| 风险 | **中** — 需保证 wrapper 输出与原 parse_url 完全一致；HTML 预请求可能触发风控 |
| 修改范围 | 新增 `core/tiktok_service_ex.py` + 修改 `workers/parse_worker.py`（调用 wrapper） |
| 触碰冻结 | **否** — tiktok_service.py 不变，parser.py 不变 |
| 工时 | 中（Retry 配置 + wrapper + 回归验证） |
| 集成方式 | ParseWorker 优先调用 `parse_url_ex`，失败回退 `parse_url` |

### C.5 风险点
- **parse_worker.py 是冻结模块**（B1.x 基线）→ 需确认是否可改
- 实际上 parse_worker.py 未列入冻结清单（只 task_manager 是 B1.x 基线）→ **可改**
- 预请求 HTML 与原 parse_url 的 requests.get 重复（浪费一次请求）
- 风控场景下双倍请求量可能加剧封禁

### C.6 替代方案（更低风险）
不改 parse_worker.py，改在 `TK_Studio_V1_6_4.py` 的 `_on_parse_success` 之前加一层：
- 但这样会改变 ParseWorker 的职责边界，不推荐

**推荐**：方案 C 改为**只新增 wrapper + 可选集成**，不强制改 parse_worker.py，由 UI 层决定是否使用。

---

## 方案 D：下载队列持久化恢复 + 批量操作

### D.1 目标
程序重启后恢复未完成下载；支持批量暂停/恢复/重试。

### D.2 问题
- [task_manager.py](file:///d:/TK_Studio_V1_fixed/workers/task_manager.py) 队列是内存态，重启即丢失
- [db.py L135-153](file:///d:/TK_Studio_V1_fixed/core/db.py#L135-L153) `reset_download_tasks_on_startup` 直接标记为"失败"，不恢复
- 无批量暂停/恢复/重试

### D.3 方案
1. **新增** `db.list_pending_tasks()` 查询"等待中"任务
2. **修改** `task_manager.py` `__init__` 启动时加载 pending tasks 到 waiting_queue
3. **新增** `task_manager.pause_all()` / `resume_all()` / `retry_failed()`
4. **修改** `TK_Studio_V1_6_4.py` 增加批量操作按钮

### D.4 评估

| 维度 | 评估 |
|------|------|
| 收益 | **中** — 用户体验提升，但非核心链路稳定性 |
| 风险 | **高** — 需改 task_manager.py（B1.x 基线）+ db.py（冻结） |
| 修改范围 | `workers/task_manager.py` + `core/db.py` + `TK_Studio_V1_6_4.py` |
| 触碰冻结 | **是** — task_manager B1.x 基线 + db.py 表结构不变但需新增方法 |
| 工时 | 中-高（持久化 + 批量操作 + UI + 回归） |
| 约束冲突 | project_memory: "SQLite works 表结构必须保持不变" — 新增方法不冲突，但需谨慎 |

### D.5 风险点
- task_manager.py 是 B1.x 基线，修改需严格回归
- 启动恢复可能与内存队列状态不一致
- 批量操作需处理竞态（暂停时正在下载的任务）
- **不推荐在本阶段实施**，风险高且非核心链路

---

## 方案 E：UI 进度总览面板 + 结构化错误提示

### E.1 目标
提供全局任务进度总览，区分错误类型，提升用户体验。

### E.2 问题
- 无全局进度面板（用户无法一览所有任务状态）
- 错误仅文本日志，无法区分"网络失败"/"被风控"/"解析失败"/"下载失败"
- 无任务统计（总数/完成/失败/进行中）

### E.3 方案
**仅修改** `TK_Studio_V1_6_4.py`（纯 UI 层）：

1. **新增** 任务总览面板（QTabWidget 或 QDockWidget）：
   - 表格展示：作品标题 / 状态 / 进度 / 类型（解析/下载/采集）
   - 实时更新（监听 TaskManager / ParseWorker / HomeFetchWorker 信号）
   - 统计栏：总数 / 完成 / 失败 / 进行中

2. **新增** 结构化错误提示：
   - 错误类型 enum：`NETWORK_ERROR` / `BLOCKED` / `PARSE_FAILED` / `DOWNLOAD_FAILED` / `TIMEOUT`
   - 不同错误类型不同 UI 反馈（颜色/图标/建议操作）

3. **可选** B4.3-P7 `resolve_short_url_ex()` 结构化返回，集成到 UI

### E.4 评估

| 维度 | 评估 |
|------|------|
| 收益 | **中** — 用户体验提升，但不改变核心功能 |
| 风险 | **低** — 纯 UI 层改动 |
| 修改范围 | `TK_Studio_V1_6_4.py`（可能 + `core/url_resolver.py` B4.3-P7） |
| 触碰冻结 | **否** |
| 工时 | 中（UI 设计 + 信号接线 + 错误分类） |
| 依赖 | 可选依赖方案 B（后台化后进度反馈更自然） |

### E.5 风险点
- UI 改动量大（需新增 widget + 布局调整）
- 可能影响现有 UI 布局（需回归测试）
- 用户偏好"现代、简洁、专业桌面应用风格"（user_profile），需精心设计

---

## 方案对比矩阵

| 维度 | A (Parser) | B (后台化) | C (Retry wrapper) | D (队列持久化) | E (UI 面板) |
|------|-----------|-----------|-------------------|---------------|-------------|
| 收益 | ★★★★★ | ★★★★★ | ★★★★ | ★★★ | ★★★ |
| 风险 | ★ (低) | ★ (低) | ★★ (中) | ★★★★ (高) | ★ (低) |
| 触碰冻结 | 否 | 否 | 否 | **是** | 否 |
| 工时 | 中 | 低-中 | 中 | 中-高 | 中 |
| 核心链路 | 是 | 是 | 是 | 否 | 否 |
| 依赖 | 无 | 无 | 无 | 无 | 可选 B |
| B4.3 延续 | 否 | 是（P6/P7 集成） | 否 | 否 | 是（P7 集成） |

---

## 推荐实施顺序

### 第一优先级（高收益 + 低风险 + 不触碰冻结）

1. **方案 B** — parse_single 短链解析后台化
   - 直接解决 B4.3 引入的 UI 阻塞回归风险（Retry 最坏 60s/短链）
   - 延续 B4.3-P6（并发）+ parse_single 后台化暂缓项
   - 可集成 B4.3-P7（结构化返回）用于进度反馈

2. **方案 A** — Parser 结构化 JSON 解析层
   - 核心链路稳定性提升
   - 新增文件不触碰冻结
   - 为后续方案 C 提供基础

### 第二优先级（高收益 + 中风险）

3. **方案 C** — tiktok_service Retry wrapper
   - 依赖方案 A 的 parser_ex（可选）
   - 新增 wrapper 不触碰冻结
   - 减少 Chrome fallback 触发频率

### 第三优先级（中收益 + 低风险）

4. **方案 E** — UI 进度总览面板
   - 依赖方案 B（后台化后进度反馈更自然）
   - 纯 UI 层改动

### 不推荐本阶段实施

5. **方案 D** — 下载队列持久化恢复
   - 触碰冻结（task_manager + db）
   - 非核心链路
   - 建议后续独立阶段实施

---

## 推荐组合

### 组合 1：核心链路稳定性（A + B + C）
- 收益：采集链路全面强化（解析 + 短链 + 请求重试）
- 风险：低-中
- 工时：中-高
- 触碰冻结：否

### 组合 2：用户体验优先（B + E）
- 收益：解决 UI 阻塞 + 进度可视化
- 风险：低
- 工时：中
- 触碰冻结：否

### 组合 3：B4.3 延续（B only）
- 收益：闭环 B4.3 暂缓项（P6 并发 + P7 结构化 + parse_single 后台化）
- 风险：低
- 工时：低-中
- 触碰冻结：否

---

## 待人工批准的决策点

| 决策点 | 选项 | 推荐 |
|--------|------|------|
| 实施哪些方案 | A/B/C/D/E 单选或多选 | 组合 3（B only）或组合 1（A+B+C） |
| 方案 A JSON blob 来源 | 实网抓取分析 / 参考开源项目 | 实网抓取 + 参考 tiktok-scraper 等 |
| 方案 B ResolveWorker 设计 | 独立 QThread / 复用 ParseWorker | 独立 QThread（职责分离） |
| 方案 C parse_worker.py 是否可改 | 是 / 否（只新增 wrapper） | 需确认 parse_worker.py 冻结状态 |
| 方案 E UI 面板位置 | 新 Tab / DockWidget / 独立窗口 | 新 Tab（与现有布局一致） |
| B4.3 暂缓项是否纳入 | P6/P7/P8 全纳入 / 选择性纳入 | P7 纳入（配合 B/E），P6 可选 |

---

**本方案未修改任何代码，等待人工批准后进入实施阶段。**
