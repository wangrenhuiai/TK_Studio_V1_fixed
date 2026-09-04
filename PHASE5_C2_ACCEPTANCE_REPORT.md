# Phase 5-C2 验收报告 — parser_ex 集成 + Retry Wrapper

> 阶段：Phase 5-C2（验收执行）
> 验收时间：2026-09-04 15:12 (+08:00)
> 验收基线：[PHASE5_C2_IMPLEMENTATION_REPORT.md](file:///d:/TK_Studio_V1_fixed/PHASE5_C2_IMPLEMENTATION_REPORT.md)
> 前置：C1 验收 PASS
> 验收结论：**PASS**
> 状态：等待人工确认，不进入 C3

---

## A. 文件检查

### A.1 文件存在确认

| 文件 | 存在 | 类型 |
|------|------|------|
| [core/parser_ex.py](file:///d:/TK_Studio_V1_fixed/core/parser_ex.py) | ✅ | 修改（C1 基线 → C2） |
| [core/http_client.py](file:///d:/TK_Studio_V1_fixed/core/http_client.py) | ✅ | 新增 |
| [core/tiktok_request.py](file:///d:/TK_Studio_V1_fixed/core/tiktok_request.py) | ✅ | 新增 |
| [tests/test_parser_integration.py](file:///d:/TK_Studio_V1_fixed/tests/test_parser_integration.py) | ✅ | 新增 |
| [tests/test_http_client.py](file:///d:/TK_Studio_V1_fixed/tests/test_http_client.py) | ✅ | 新增 |

### A.2 parser_ex.py 标记确认

| 行号 | 标记 | 确认 |
|------|------|------|
| L57 | `def extract_tiktok_data_ex(html):` | ✅ 存在 |
| L58 | docstring: "正则优先，JSON 补充缺失字段" | ✅ 已修正 |
| L258 | _merge docstring: "正则优先，JSON 只补充正则缺失字段" | ✅ 已修正 |
| L273 | `extract_json_data = extract_tiktok_data_ex` | ✅ 别名存在 |
| L275 | `__all__ = ["extract_tiktok_data_ex", "extract_json_data"]` | ✅ 导出更新 |

---

## B. 编译检查

| 文件 | py_compile | 结果 |
|------|-----------|------|
| `core/parser_ex.py` | exit 0 | ✅ PASS |
| `core/http_client.py` | exit 0 | ✅ PASS |
| `core/tiktok_request.py` | exit 0 | ✅ PASS |
| `tests/test_parser_integration.py` | exit 0 | ✅ PASS |
| `tests/test_http_client.py` | exit 0 | ✅ PASS |

---

## C. Import 检查

```python
from core.parser_ex import extract_tiktok_data_ex, extract_json_data
from core.http_client import create_retry_session
from core.tiktok_request import fetch_tiktok_html
→ IMPORT_OK ✅
```

---

## D. Retry 配置验证

### D.1 运行时配置验证

```
total=3
backoff=1
forcelist=[429, 500, 502, 503, 504]
connect=3 read=3 status=3
```

### D.2 配置确认

| 配置项 | 要求 | 实际 | 确认 |
|--------|------|------|------|
| `total` | 3 | 3 | ✅ |
| `backoff_factor` | 1 | 1 | ✅ |
| `status_forcelist` | 429, 500, 502, 503, 504 | [429, 500, 502, 503, 504] | ✅ |
| `connect` | — | 3 | ✅ |
| `read` | — | 3 | ✅ |
| `status` | — | 3 | ✅ |

### D.3 fetch_tiktok_html 使用 Retry Session

[core/tiktok_request.py L39](file:///d:/TK_Studio_V1_fixed/core/tiktok_request.py#L39)：

```python
session = create_retry_session()  # ← 使用 Retry Session
```

**确认：✅ PASS**

---

## E. parser_ex 验证

### E.1 JSON blob 格式支持

| 优先级 | Script ID | 代码位置 | 确认 |
|--------|-----------|----------|------|
| 1 | `__UNIVERSAL_DATA_FOR_REHYDRATION__` | [L39-43](file:///d:/TK_Studio_V1_fixed/core/parser_ex.py#L39-L43) | ✅ |
| 2 | `SIGI_STATE` | [L44-48](file:///d:/TK_Studio_V1_fixed/core/parser_ex.py#L44-L48) | ✅ |
| 3 | `__NEXT_DATA__` | [L49-53](file:///d:/TK_Studio_V1_fixed/core/parser_ex.py#L49-L53) | ✅ |

### E.2 Merge 逻辑

[core/parser_ex.py L72-86](file:///d:/TK_Studio_V1_fixed/core/parser_ex.py#L72-L86)：

```
1. base = extract_tiktok_data(html)           ← 正则解析（基础）
2. json_data = _extract_structured_json(html)  ← JSON blob 提取
3. structured = _parse_from_structured(json_data) ← JSON 字段
4. return _merge(base, structured)            ← 合并
```

### E.3 合并规则

[_merge() L255-269](file:///d:/TK_Studio_V1_fixed/core/parser_ex.py#L255-L269)：

| 规则 | 代码 | 确认 |
|------|------|------|
| 正则字段存在 → 保持正则 | `merged = dict(base)` + `pass`（有值时不覆盖） | ✅ |
| 正则字段缺失 → JSON 补充 | `if not merged.get(key) and structured.get(key):` | ✅ |

**确认：✅ PASS**

---

## F. 测试

### F.1 pytest 结果

```
81 passed in 0.35s
```

### F.2 测试分布

| 测试文件 | 用例数 | 结果 |
|----------|--------|------|
| test_parser_integration.py | 10 | ✅ 全 PASS |
| test_http_client.py | 20 | ✅ 全 PASS |
| test_parser_ex.py（C1 回归） | 26 | ✅ 全 PASS |
| test_url_resolver.py（B4.3 回归） | 24 | ✅ 全 PASS |
| **总计** | **81** | **✅ 全 PASS** |

### F.3 关键测试覆盖

| 测试 | 说明 | 结果 |
|------|------|------|
| test_regex_priority_over_json | 正则优先于 JSON | ✅ |
| test_json_supplements_missing_regex_fields | JSON 补充正则缺失 | ✅ |
| test_extract_json_data_alias | 别名兼容 | ✅ |
| test_retry_total_is_3 | Retry total=3 | ✅ |
| test_retry_status_forcelist | 429/5xx 在 forcelist | ✅ |
| test_429_in_forcelist | 429 重试 | ✅ |
| test_500_in_forcelist | 500 重试 | ✅ |
| test_502_in_forcelist | 502 重试 | ✅ |
| test_503_in_forcelist | 503 重试 | ✅ |
| test_504_in_forcelist | 504 重试 | ✅ |
| test_success_returns_html | fetch_tiktok_html 成功 | ✅ |
| test_network_error_returns_empty | 网络失败返回空 | ✅ |

---

## G. API 兼容检查

### G.1 tiktok_service.py 未修改

[core/tiktok_service.py](file:///d:/TK_Studio_V1_fixed/core/tiktok_service.py)（最近修改 2026/9/3 13:28，C2 未触碰）：

| 行号 | 代码 | 确认 |
|------|------|------|
| L10 | `from core.parser import extract_tiktok_data` | ✅ 仍用原 parser |
| L25 | `def parse_url(url, log_callback=None):` | ✅ 签名不变 |
| L64 | `data = extract_tiktok_data(html)` | ✅ 调用不变 |
| L86 | `data = extract_tiktok_data(rendered)` | ✅ 调用不变 |

### G.2 ParseWorker 未修改

[workers/parse_worker.py](file:///d:/TK_Studio_V1_fixed/workers/parse_worker.py)（最近修改 2026/9/3 16:51，C2 未触碰）：

| 行号 | 代码 | 确认 |
|------|------|------|
| L14 | `from core.tiktok_service import parse_url` | ✅ 不变 |
| L17 | `class ParseWorker(QThread):` | ✅ 不变 |
| L38 | `data = parse_url(url, log_callback=...)` | ✅ 调用不变 |

### G.3 parse_single 未修改

[TK_Studio_V1_6_4.py](file:///d:/TK_Studio_V1_fixed/TK_Studio_V1_6_4.py)（最近修改 2026/9/4 14:55=C1，C2 未触碰）：

| 行号 | 代码 | 确认 |
|------|------|------|
| L13 | `from core.tiktok_service import parse_url` | ✅ 不变 |
| L15 | `from workers.parse_worker import ParseWorker` | ✅ 不变 |
| L547 | `def parse_single(self):` | ✅ 不变 |
| L647 | `worker = ParseWorker(valid_urls, self.db)` | ✅ 调用不变 |

**API 兼容确认：✅ PASS** — `parse_url()` / `parse_single()` / `ParseWorker` 调用方式全部未变。

---

## H. 冻结边界检查

### H.1 C2 时间窗

15:06:16 ~ 15:08:11

### H.2 修改文件

| 文件 | 修改时间 | 允许范围 | 状态 |
|------|----------|----------|------|
| `core/parser_ex.py` | 15:06:16 | ✅ C1 基线可演进 | 允许 |
| `core/http_client.py` | 15:06:39 | ✅ 新增 | 允许 |
| `core/tiktok_request.py` | 15:07:00 | ✅ 新增 | 允许 |
| `tests/test_parser_integration.py` | 15:07:37 | ✅ 新增 | 允许 |
| `tests/test_http_client.py` | 15:08:11 | ✅ 新增 | 允许 |

### H.3 冻结文件未触碰确认

| 冻结文件 | 最近修改时间 | C2 是否触碰 |
|----------|-------------|-------------|
| `core/tiktok_service.py` | 2026/9/3 13:28 | 否 ✅ |
| `core/parser.py` | 2026/9/3 11:42 | 否 ✅ |
| `core/downloader.py` | 2026/9/3 16:20 | 否 ✅ |
| `core/db.py` | 2026/9/3 23:49 | 否 ✅ |
| `workers/task_manager.py` | 2026/9/4 02:46 | 否 ✅ |
| `core/profile_snapshot.py`（B3.4） | 2026/9/4 13:16 | 否 ✅ |
| `workers/parse_worker.py` | 2026/9/3 16:51 | 否 ✅ |

### H.4 特别确认（验收要求逐项）

| 检查项 | 状态 |
|--------|------|
| `core/tiktok_service.py` 未修改 | ✅ 否 |
| `core/downloader.py` 未修改 | ✅ 否 |
| `core/db.py` 未修改 | ✅ 否 |
| `workers/task_manager.py` 未修改 | ✅ 否 |
| `core/profile_snapshot.py` 未修改 | ✅ 否 |

**所有冻结文件最近修改时间均早于 C2 时间窗（15:06）。无冻结模块变化。**

---

## I. 最终结论

| 验收项 | 结果 |
|--------|------|
| A. 文件检查（5 文件 + parser_ex 标记） | ✅ PASS |
| B. 编译检查（py_compile × 5） | ✅ PASS（exit 0 × 5） |
| C. Import 检查 | ✅ PASS（IMPORT_OK） |
| D. Retry 配置（total=3, backoff=1, 429/5xx） | ✅ PASS（运行时验证） |
| E. parser_ex（3 JSON 格式 + 合并规则） | ✅ PASS |
| F. 测试（81 项） | ✅ PASS（81/81 in 0.35s） |
| G. API 兼容（parse_url/parse_single/ParseWorker） | ✅ PASS（全部未变） |
| H. 冻结边界（5 冻结文件 + B3.4） | ✅ PASS（全部未触碰） |

### 综合结论：**PASS**

Phase 5-C2（parser_ex 集成 + Retry Wrapper）满足设计要求：
- C2-A：parser_ex docstring 修正 + `extract_json_data` 别名 + 正则优先 JSON 补充缺失
- C2-B：`create_retry_session()` Retry(total=3, backoff=1, 429/5xx) + `fetch_tiktok_html()` 使用 Retry Session
- C2-C：30 项新增测试 + 50 项回归测试全 PASS
- API 完全兼容（tiktok_service.py / parse_worker.py / parse_single 全部未修改）
- 冻结边界无破坏（仅改动 5 个允许文件）

---

## J. 后续

按指令**不进入 Phase 5-C3**，停止并等待人工确认。
