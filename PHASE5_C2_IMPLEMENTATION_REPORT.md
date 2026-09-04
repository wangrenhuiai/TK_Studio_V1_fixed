# Phase 5-C2 实施报告 — parser_ex 集成 + Retry Wrapper

> 阶段：Phase 5-C2（parser_ex 正式接入 + TikTok 请求 Retry Wrapper）
> 实施时间：2026-09-04 15:06 ~ 15:08 (+08:00)
> 基线：[PHASE5_C1_ACCEPTANCE_REPORT.md](file:///d:/TK_Studio_V1_fixed/PHASE5_C1_ACCEPTANCE_REPORT.md) PASS
> 状态：实施完成，等待验收

---

## 1. 修改文件列表

### 1.1 新增文件（4 个）

| 文件 | 行数 | 说明 |
|------|------|------|
| [core/http_client.py](file:///d:/TK_Studio_V1_fixed/core/http_client.py) | 88 | C2-B — Retry Session 工厂 |
| [core/tiktok_request.py](file:///d:/TK_Studio_V1_fixed/core/tiktok_request.py) | 62 | C2-B — TikTok HTML 获取层 |
| [tests/test_parser_integration.py](file:///d:/TK_Studio_V1_fixed/tests/test_parser_integration.py) | 154 | C2-C — parser 集成测试（10 项） |
| [tests/test_http_client.py](file:///d:/TK_Studio_V1_fixed/tests/test_http_client.py) | 195 | C2-C — http_client 测试（20 项） |

### 1.2 修改文件（1 个）

| 文件 | 修改区域 | 说明 |
|------|----------|------|
| [core/parser_ex.py](file:///d:/TK_Studio_V1_fixed/core/parser_ex.py) | L57-86, L255-273 | C2-A — docstring 修正 + `extract_json_data` 别名 |

---

## 2. C2-A — parser_ex 集成

### 2.1 修改内容

| 修改点 | 位置 | 说明 |
|--------|------|------|
| docstring 修正 | L57-86 | `extract_tiktok_data_ex` docstring 统一为"正则优先，JSON 补充缺失字段" |
| docstring 修正 | L255-268 | `_merge` docstring 统一为"正则优先，JSON 只补充正则缺失字段" |
| 别名添加 | L273 | `extract_json_data = extract_tiktok_data_ex` |
| `__all__` 更新 | L275 | `["extract_tiktok_data_ex", "extract_json_data"]` |

### 2.2 集成链路

parser_ex 内部已集成 parser.py（C1 实现）：

```
extract_tiktok_data_ex(html)
    ↓
1. base = extract_tiktok_data(html)          ← 正则解析（始终执行）
    ↓
2. json_data = _extract_structured_json(html) ← JSON blob 提取
    ↓
3. structured = _parse_from_structured(json_data) ← JSON 字段解析
    ↓
4. return _merge(base, structured)           ← 合并：正则优先，JSON 补充缺失
```

**不修改冻结的 tiktok_service.py**。tiktok_service.py 仍调用原 `extract_tiktok_data`。
parser_ex 作为增强层，可通过 tiktok_request.py 或未来 wrapper 集成到生产链路。

### 2.3 docstring 修正对比

| 位置 | 修正前 | 修正后 |
|------|--------|--------|
| L58 | "结构化 JSON 优先，正则兜底" | "正则优先，JSON 补充缺失字段" |
| L85 | "合并：JSON 优先，正则补充缺失" | "合并：正则优先，JSON 只补充正则缺失字段" |
| L258 | "结构化（JSON）优先，正则补充缺失字段" | "正则优先，JSON 只补充正则缺失字段" |

---

## 3. C2-B — Retry Wrapper

### 3.1 core/http_client.py

```python
def create_retry_session(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    timeout=20,
):
```

| 配置项 | 值 | 说明 |
|--------|-----|------|
| `total` | 3 | Retry 总次数 |
| `backoff_factor` | 1 | 退避因子（0s, 1s, 2s） |
| `status_forcelist` | (429, 500, 502, 503, 504) | 触发重试的 HTTP 状态码 |
| `connect/read/status` | 3 | 各维度重试次数 |
| `timeout` | 20 | 默认超时（与 tiktok_service.py L57 对齐） |
| `allowed_methods` | GET, HEAD | 允许重试的 HTTP 方法 |
| `raise_on_status` | False | 不抛异常，返回响应 |

配置与 [downloader.py L192-200](file:///d:/TK_Studio_V1_fixed/core/downloader.py#L192-L200) 对齐。

### 3.2 core/tiktok_request.py

```python
def fetch_tiktok_html(url, timeout=None, log_callback=None):
```

| 行为 | 说明 |
|------|------|
| 成功（200） | 返回 `response.text` |
| 非 200 | 返回 `""` + 日志 |
| 网络异常 | 返回 `""` + 日志（不抛异常） |
| Session 清理 | `finally: session.close()` |

### 3.3 不修改冻结的 tiktok_service.py

tiktok_service.py 是冻结模块，不修改。tiktok_request.py 作为独立的 HTML 获取层提供：
- 带 Retry 的请求能力
- 可被未来 wrapper 或 parse_worker 替代调用
- 当前不强制集成到生产链路（保持现有行为不变）

---

## 4. API 兼容确认

### 4.1 现有 API 不变

| 接口 | 调用方 | C2 是否修改 | 兼容性 |
|------|--------|------------|--------|
| `parse_url(url, log_callback)` | ParseWorker / parse_single | 否 | ✅ 不变 |
| `parse_single()` | UI 按钮 | 否 | ✅ 不变 |
| `ParseWorker(urls, db)` | parse_single / _validate_and_parse | 否 | ✅ 不变 |
| `extract_tiktok_data(html)` | tiktok_service.py | 否 | ✅ 不变 |

### 4.2 新增 API

| 接口 | 说明 | 影响 |
|------|------|------|
| `extract_json_data` | `extract_tiktok_data_ex` 别名 | 新增，不影响现有 |
| `create_retry_session()` | Retry Session 工厂 | 新增，不影响现有 |
| `fetch_tiktok_html(url)` | TikTok HTML 获取 | 新增，不影响现有 |

---

## 5. 测试结果

### 5.1 py_compile

```
parser_ex.py: exit 0 ✅
http_client.py: exit 0 ✅
tiktok_request.py: exit 0 ✅
test_parser_integration.py: exit 0 ✅
test_http_client.py: exit 0 ✅
```

### 5.2 Import 检查

```
from core.parser_ex import extract_tiktok_data_ex, extract_json_data
from core.http_client import create_retry_session
from core.tiktok_request import fetch_tiktok_html
→ IMPORT_OK ✅
```

### 5.3 pytest

```
81 passed in 0.38s
```

| 测试文件 | 用例数 | 结果 |
|----------|--------|------|
| test_parser_integration.py | 10 | ✅ 全 PASS |
| test_http_client.py | 20 | ✅ 全 PASS |
| test_parser_ex.py（C1 回归） | 26 | ✅ 全 PASS |
| test_url_resolver.py（B4.3 回归） | 24 | ✅ 全 PASS |

#### test_parser_integration.py 覆盖

| 测试 | 说明 | 结果 |
|------|------|------|
| test_regex_priority_over_json | 正则优先于 JSON | ✅ |
| test_json_supplements_missing_regex_fields | JSON 补充正则缺失 | ✅ |
| test_json_supplements_duration_resolution | JSON 补充 duration/resolution | ✅ |
| test_no_json_blob_returns_regex_only | 无 JSON 返回纯正则 | ✅ |
| test_extract_json_data_alias | 别名兼容 | ✅ |
| test_field_structure_consistency | 字段结构一致 | ✅ |
| test_regex_and_json_both_complete | 正则+JSON 均完整时正则优先 | ✅ |
| test_empty_html | 空 HTML 不崩溃 | ✅ |
| test_regex_empty_json_supplements_all | 正则全空 JSON 补充全部 | ✅ |
| test_invalid_json_fallback_to_regex | JSON 失败回退正则 | ✅ |

#### test_http_client.py 覆盖

| 测试类 | 用例数 | 覆盖内容 |
|--------|--------|----------|
| TestRetryConfig | 8 | Session 创建/Retry total=3/backoff=1/status_forcelist/timeout=20/headers/挂载/自定义 |
| TestFetchTiktokHtml | 7 | 成功返回/非200返回空/网络错误返回空/日志回调/自定义timeout/Session关闭 |
| TestRetryBehavior | 6 | 429/500/502/503/504 在 forcelist + connect/read/status 均配置 |

---

## 6. 冻结边界确认

### 6.1 C2 时间窗

15:06:16 ~ 15:08:11

### 6.2 修改文件

| 文件 | 修改时间 | 允许范围 | 状态 |
|------|----------|----------|------|
| `core/parser_ex.py` | 15:06:16 | ✅ 修改（C1 基线可演进） | 允许 |
| `core/http_client.py` | 15:06:39 | ✅ 新增 | 允许 |
| `core/tiktok_request.py` | 15:07:00 | ✅ 新增 | 允许 |
| `tests/test_parser_integration.py` | 15:07:37 | ✅ 新增 | 允许 |
| `tests/test_http_client.py` | 15:08:11 | ✅ 新增 | 允许 |

### 6.3 冻结文件未触碰确认

| 冻结文件 | 最近修改时间 | C2 是否触碰 |
|----------|-------------|-------------|
| `core/parser.py` | 2026/9/3 11:42 | 否 ✅ |
| `core/tiktok_service.py` | 2026/9/3 13:28 | 否 ✅ |
| `core/downloader.py` | 2026/9/3 16:20 | 否 ✅ |
| `core/db.py` | 2026/9/3 23:49 | 否 ✅ |
| `workers/parse_worker.py` | 2026/9/3 16:51 | 否 ✅ |
| `workers/login_worker.py` | 2026/9/3 18:57 | 否 ✅ |
| `core/tiktok_login.py` | 2026/9/4 02:28 | 否 ✅ |
| `workers/task_manager.py` | 2026/9/4 02:46 | 否 ✅ |
| `core/home_fetcher.py` | 2026/9/4 12:45 | 否 ✅ |
| `core/profile_snapshot.py`（B3.4） | 2026/9/4 13:16 | 否 ✅ |
| `TK_Studio_V1_6_4.py`（C1） | 2026/9/4 14:55 | 否 ✅（C1 已冻结） |
| `workers/resolve_worker.py`（C1） | 2026/9/4 14:53 | 否 ✅（C1 已冻结） |

**所有冻结文件最近修改时间均早于 C2 时间窗（15:06）。**

### 6.4 特别确认

| 检查项 | 状态 |
|--------|------|
| `core/downloader.py` 未修改 | ✅ |
| `core/db.py` 未修改 | ✅ |
| `workers/task_manager.py` 未修改 | ✅ |
| `core/profile_snapshot.py` 未修改 | ✅ |
| B3.4 登录 snapshot 未触碰 | ✅ |
| B3.1 profile_dir 未触碰 | ✅ |
| M1-M5 登录 UI 未触碰 | ✅ |

---

## 7. 风险评估

| 风险项 | 严重度 | 缓解措施 |
|--------|--------|----------|
| tiktok_request.py 未集成到生产链路 | 低 | 当前为独立能力，后续 wrapper 可集成 |
| http_client Retry 配置与 downloader 不一致 | 低 | 已对齐（total=3, backoff=1, status_forcelist 相同） |
| parser_ex 别名可能与未来命名冲突 | 低 | `extract_json_data` 明确指向 `extract_tiktok_data_ex` |
| fetch_tiktok_html 网络失败静默返回空 | 低 | 有 log_callback 支持，调用方可感知 |

---

## 8. 下一阶段建议

1. **tiktok_request + parser_ex 集成到 ParseWorker**：新增 `parse_url_ex(url)` wrapper，使用 `fetch_tiktok_html` + `extract_tiktok_data_ex`，在 ParseWorker 中可选调用
2. **实网验证**：用真实 TikTok URL 验证 `fetch_tiktok_html` 的 Retry 行为和 `extract_tiktok_data_ex` 的 JSON 提取
3. **方案 E（UI 进度面板）**：利用 C1 ResolveWorker 的信号做进度可视化

---

## 9. 回滚方案

如需回滚 C2：

1. 删除 `core/http_client.py`
2. 删除 `core/tiktok_request.py`
3. 删除 `tests/test_parser_integration.py`
4. 删除 `tests/test_http_client.py`
5. 还原 `core/parser_ex.py` 到 C1 验收时状态（删除别名 + 恢复旧 docstring）

回滚后恢复到 C1 验收 PASS 状态。
