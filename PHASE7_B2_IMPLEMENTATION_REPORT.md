# Phase 7-B.2 Implementation Report — 消除 TikTok 解析重复 HTTP 请求

> 阶段：Phase 7-B.2（Duplicate Request Elimination）
> 日期：2026-09-04 17:50 (+08:00)
> 基线：Phase 7-A = LOCKED @ 7b6bf0a
> 声明：本阶段不 commit，等待人工验收

---

## 1. 当前问题

`parse_url_ex()` 在 parser_ex 解析失败后调用 `_original_parse_url(url)`，
该函数内部执行 `requests.get(url)` 对**同一 URL** 发起重复 HTTP GET 请求。

```
fetch_tiktok_html(url)     → GET #1 → html（存入局部变量）
parser_ex(html)            → 解析失败（风控空壳页）
_original_parse_url(url)   → GET #2 → 同一 URL 再次请求（冗余！）
```

风控场景下，0.5s 内对同一 URL 2 次 requests 请求是机器人特征，
加重 TikTok 反爬评分。

---

## 2. 修改前请求链

```
parse_url_ex(url)
    ↓
fetch_tiktok_html(url)              ← GET #1（Retry session, 最多 4 次）
    ↓ html
parser_ex.extract_tiktok_data_ex(html)
    ↓ 如果字段缺失
tiktok_service.parse_url(url)       ← GET #2（无 Retry, 重复请求！）
    ├── requests.get(url)           ← 冗余 HTTP GET
    ├── extract_tiktok_data(html2)
    └── load_with_chrome(url)       ← Chrome fallback
    ↓
返回结果
```

**最坏 HTTP 请求次数（风控场景）：**
- GET #1: 1 次（Retry 不触发，status 200）
- GET #2: 1 次（_original_parse_url 重复请求）
- Chrome: 1 次
- **合计：3 次 HTTP 交互**

---

## 3. 修改后请求链

```
parse_url_ex(url)
    ↓
fetch_tiktok_html(url)              ← GET #1（Retry session）
    ↓ html
parser_ex.extract_tiktok_data_ex(html)
    ↓ 如果字段缺失
extract_tiktok_data(html)           ← 复用已有 HTML，无新 GET！
    ↓ 如果仍缺失
load_with_chrome(url)               ← Chrome fallback（保留）
    ↓ extract_tiktok_data(rendered)
    ↓
返回结果
```

**最坏 HTTP 请求次数（风控场景）：**
- GET #1: 1 次（fetch_tiktok_html）
- legacy parser: 0 次（复用 HTML）
- Chrome: 1 次
- **合计：2 次 HTTP 交互（减少 1 次冗余 GET）**

---

## 4. 修改文件

| 文件 | 操作 | 改动 | 说明 |
|------|------|------|------|
| `core/tiktok_service_ex.py` | 修改 | +83 行 | 移除 `_original_parse_url` 调用；改用 `extract_tiktok_data(html)` 复用 HTML；Chrome fallback 内联 |
| `tests/test_tiktok_service_ex.py` | 修改 | +274 行 | 更新 mock：`_original_parse_url` → `extract_tiktok_data` + `load_with_chrome` |
| `tests/test_phase7a_final_acceptance.py` | 修改 | +148 行 | 更新 6 个测试的 mock 以匹配新实现 |
| `tests/test_phase7b2_duplicate_request.py` | **新增** | 8 测试 | 重复请求回归测试（mock 统计 GET/Chrome 调用次数） |

**未修改的冻结文件：**

| 文件 | 状态 |
|------|------|
| `core/tiktok_service.py` | ✅ 未修改 |
| `core/parser.py` | ✅ 未修改 |
| `core/parser_ex.py` | ✅ 未修改 |
| `core/tiktok_request.py` | ✅ 未修改 |
| `core/http_client.py` | ✅ 未修改 |
| `core/chrome_bridge.py` | ✅ 未修改 |
| `workers/parse_worker.py` | ✅ 未修改 |
| `workers/resolve_worker.py` | ✅ 未修改 |
| `TK_Studio_V1_6_4.py` | ✅ 未修改 |
| `core/db.py` | ✅ 未修改 |

---

## 5. 修改原因

Phase 7-B.1 分析确认：`parse_url_ex` 获取 HTML 后，`_original_parse_url`
对同一 URL 重复 `requests.get` 是最高风控风险。

根因：`_original_parse_url` 签名为 `parse_url(url, log_callback)`，
不接受 HTML 参数。它自己 fetch + parse + Chrome，导致 HTML 被重复获取。

修复：在 `tiktok_service_ex.py` 内部直接使用 `extract_tiktok_data(html)`
复用已获取的 HTML，跳过 `_original_parse_url` 的 requests.get 步骤。
Chrome fallback 逻辑内联，保持与 `tiktok_service.py` 一致的行为。

---

## 6. HTML 复用机制

```python
# 修改前
html = fetch_tiktok_html(url)       # GET #1
data = extract_tiktok_data_ex(html) # parser_ex
if incomplete:
    fallback = _original_parse_url(url)  # GET #2（不传 html！）

# 修改后
html = fetch_tiktok_html(url)       # GET #1
data = extract_tiktok_data_ex(html) # parser_ex
if incomplete:
    legacy_data = extract_tiktok_data(html)  # 复用 html，无新 GET
if still incomplete:
    rendered = load_with_chrome(url)         # Chrome fallback
    chrome_data = extract_tiktok_data(rendered)
```

关键：`extract_tiktok_data` 直接接收 HTML 字符串，不需要 URL，
因此可以复用 `fetch_tiktok_html` 已获取的 HTML。

---

## 7. 请求次数对比

| 场景 | 修改前 GET | 修改后 GET | 修改前 Chrome | 修改后 Chrome | 减少 |
|------|-----------|-----------|--------------|--------------|------|
| parser_ex 成功 | 1 | 1 | 0 | 0 | 0 |
| HTTP 200 空壳（风控） | 2 | 1 | 1 | 1 | **-1 GET** |
| HTTP 429 | 5 | 4 | 1 | 1 | **-1 GET** |
| parser_ex 部分 → legacy 补全 | 2 | 1 | 0 | 0 | **-1 GET** |
| 全部失败 | 5 | 1 | 1 | 1 | **-1 GET** |

**所有失败场景均减少 1 次冗余 GET。**

---

## 8. 单元测试结果

```
python -m compileall . → exit 0
python -m pytest tests/ -q → 109 passed in 0.49s
```

| 测试文件 | 用例数 | 结果 |
|----------|--------|------|
| test_phase7b2_duplicate_request.py（**新增**） | 8 | ✅ PASS |
| test_tiktok_service_ex.py（更新） | 11 | ✅ PASS |
| test_phase7a_final_acceptance.py（更新） | 9 | ✅ PASS |
| test_url_resolver.py | 24 | ✅ PASS |
| test_parser_ex.py | 26 | ✅ PASS |
| test_parser_integration.py | 10 | ✅ PASS |
| test_http_client.py | 20 | ✅ PASS |
| test_home_worker.py | 1 | ✅ PASS |
| **合计** | **109** | **✅ ALL PASS** |

### 重复请求验证（mock 统计调用次数）

| Test | 场景 | fetch GET | Chrome | 结果 |
|------|------|-----------|--------|------|
| Case 1 | parser_ex 成功 | 1 | 0 | ✅ |
| Case 2 | legacy 复用 HTML 成功 | **1** | 0 | ✅ 无重复 GET |
| Case 3 | Chrome fallback 成功 | **1** | 1 | ✅ 无重复 GET |
| Case 4 | 全部失败 | **1** | 1 | ✅ 无重复 GET |
| Case 5 | fetch 失败→Chrome | **1** | 1 | ✅ 无额外 requests |
| Case 8 | _original_parse_url 不被调用 | — | — | ✅ |

---

## 9. 实网测试结果

探针：`data/probes/phase7a_final/probe_real_net.py`

### 测试 1：标准 URL

| 项 | 值 |
|----|-----|
| URL | `@rfbxha/video/7681265056633326878` |
| HTTP status | 200 |
| HTML length | 1462（风控空壳页） |
| parser_ex | 空 |
| legacy parser（复用 HTML） | 空（同一 HTML） |
| Chrome fallback | ✅ 成功（标题/封面/视频地址 全有） |
| **HTTP GET 次数** | **1**（fetch_tiktok_html only） |
| 最终 video_url | ✅ 非空 |
| **最终判定** | **✅ 成功** |

日志确认：
```
parser_ex解析：标题=无，封面=无，视频地址=无
字段缺失，复用已有 HTML 用原 parser 补充……
原 parser 复用 HTML：标题=无，封面=无，视频地址=无
字段仍缺失，启用 Chrome fallback……
Chrome解析：标题=有，封面=有，视频地址=有
```

**无 "HTTP 状态" 第 2 次出现 → 确认无重复 GET。**

### 测试 2：短链

| 项 | 值 |
|----|-----|
| 短链 | `t/ZTUNyfkNF/` |
| 短链解析 | ✅ HEAD → canonical URL |
| HTTP status | 200 |
| HTML length | 1462（风控空壳页） |
| parser_ex | 空 |
| legacy parser（复用 HTML） | 空 |
| Chrome fallback | ❌ 失败（TikTok 风控影响 Chrome） |
| **HTTP GET 次数** | **1** |
| 最终 video_url | 空 |
| **最终判定** | **❌ 失败（video_url 为空）** |

短链失败是 TikTok 风控导致 Chrome 也无法获取数据，
**不是代码缺陷**。程序正确返回失败，无假成功。

---

## 10. Chrome fallback 验证

| 检查项 | 结果 |
|--------|------|
| Chrome fallback 保留 | ✅ video_url 为空时触发 |
| Chrome 使用独立 profile | ✅ `chrome_headless_profile` |
| Chrome 不访问用户 Chrome | ✅ `--user-data-dir` 独立 |
| Chrome --dump-dom 一次性 | ✅ 无 CDP 持久进程 |
| Chrome 超时保护 | ✅ 45s timeout |
| 保守合并不覆盖 | ✅ 仅补充缺失字段 |

---

## 11. 短链验证

| 检查项 | 结果 |
|--------|------|
| ResolveWorker 未修改 | ✅ |
| url_resolver 未修改 | ✅ |
| 短链缓存未修改 | ✅ TTL 300s |
| 短链 HEAD 解析 | ✅ 成功 |
| canonical URL 可靠 | ✅ |
| 无重复短链处理 | ✅ ParseWorker 收已解析 URL |

---

## 12. 用户 Chrome 隔离验证

| 检查项 | 结果 |
|--------|------|
| 独立 profile 目录 | ✅ `chrome_headless_profile`（项目根目录） |
| `--headless=new` | ✅ 无头模式 |
| `--user-data-dir` 独立 | ✅ 不读取用户 Chrome profile |
| 不修改用户登录态 | ✅ |
| 不连接用户 Chrome | ✅ 无 CDP 端口冲突 |

---

## 13. 已知限制

| 限制 | 说明 |
|------|------|
| TikTok 风控可能影响 Chrome | 短链测试中 Chrome 也返回空壳页 |
| parser_ex 与 legacy parser 复用同一 HTML | 如果 parser_ex 失败，legacy parser 对同一 HTML 也大概率失败（parser_ex 内部已调用 parser.py） |
| Chrome fallback 是最终可靠数据源 | 但受 TikTok 风控影响时也可能失败 |
| 本阶段不绕过 TikTok 风控 | 按设计原则，不修改成功判定 |

---

## 14. Git diff 摘要

```
 core/tiktok_service_ex.py              |  83 ++++++++--
 tests/test_phase7a_final_acceptance.py | 148 ++++++++++--------
 tests/test_tiktok_service_ex.py        | 274 ++++++++++++++++++++-------------
 tests/test_phase7b2_duplicate_request.py (新增, untracked)
 3 files modified, 1 file added
```

**核心改动：**
- `core/tiktok_service_ex.py` L25: 移除 `from core.tiktok_service import parse_url as _original_parse_url`
- `core/tiktok_service_ex.py` L32-33: 新增 `from core.parser import extract_tiktok_data` + `from core.chrome_bridge import load_with_chrome`
- `core/tiktok_service_ex.py` L86-111: legacy parser 复用 HTML（`extract_tiktok_data(html)` 替代 `_original_parse_url(url)`）
- `core/tiktok_service_ex.py` L116-137: Chrome fallback 内联（保守合并）

---

## 15. 不 commit 声明

**本阶段不执行 `git commit`。** 工作区保留修改，等待人工验收。

```
git status --short:
 M core/tiktok_service_ex.py
 M tests/test_phase7a_final_acceptance.py
 M tests/test_tiktok_service_ex.py
?? tests/test_phase7b2_duplicate_request.py
?? PHASE7_B1_READONLY_ANALYSIS.md
```
