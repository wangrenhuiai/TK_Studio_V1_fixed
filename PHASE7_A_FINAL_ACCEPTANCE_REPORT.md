# Phase 7-A Final Acceptance Report — TikTok Parser Production Integration

> 验收时间：2026-09-04 16:30 (+08:00)
> 验收阶段：Phase 7-A Final Acceptance / Production Integration Audit
> 验收结论：**PASS**

---

## 1. 当前真实生产链

经代码级审计（以磁盘实际代码为准，非仅依赖报告），最终生产链确认为：

```
ParseWorker.run()                              [workers/parse_worker.py]
    ↓ L14: from core.tiktok_service_ex import parse_url
tiktok_service_ex.parse_url_ex(url)            [core/tiktok_service_ex.py]
    ↓
tiktok_request.fetch_tiktok_html(url)          [core/tiktok_request.py]
    ↓ Retry(total=3, backoff=1, 429/5xx)
http_client.create_retry_session()             [core/http_client.py]
    ↓
parser_ex.extract_tiktok_data_ex(html)         [core/parser_ex.py]
    ↓ JSON Layer + 正则优先
parser.extract_tiktok_data(html)               [core/parser.py] ← parser_ex 内部调用
    ↓ 字段缺失时
tiktok_service.parse_url(url)                  [core/tiktok_service.py] ← 原 fallback
    ↓ requests.get + parser.extract_tiktok_data
    ↓ 仍然缺失时
chrome_bridge.load_with_chrome(url)            [core/chrome_bridge.py] ← Chrome fallback
    ↓
parser.extract_tiktok_data(rendered)           [core/parser.py]
    ↓
最终返回结构化作品数据（video_id/author/title/url/video_url/cover_url/duration/resolution）
```

**接入确认：**

| 节点 | 验证 | 结果 |
|------|------|------|
| ParseWorker → tiktok_service_ex | L14 import 实读 | ✅ 已接入 |
| tiktok_service_ex → tiktok_request | L23/L59 调用 | ✅ 已接入 |
| tiktok_request → http_client Retry | L25/L39 调用 | ✅ 已接入 |
| tiktok_service_ex → parser_ex | L24/L63 调用 | ✅ 已接入 |
| parser_ex → parser.py fallback | L32/L73 调用 | ✅ 已接入 |
| 字段缺失 → 原 parse_url fallback | L82-91 调用 | ✅ 已接入 |
| 原 parse_url → Chrome fallback | tiktok_service.py L83-99 | ✅ 已保留 |

- ✅ parser_ex 确实被生产代码调用
- ✅ tiktok_request 确实被生产代码调用
- ✅ http_client Retry 确实生效
- ✅ 原 parser.py 仍然保留（parser_ex 内部调用 + 原 parse_url 调用）
- ✅ Chrome fallback 仍然保留（原 parse_url 内部）
- ✅ 没有 monkey-patch
- ✅ 没有重复实现 ParseWorker
- ✅ 没有改变 ResolveWorker 架构
- ✅ 没有修改 UI 架构

---

## 2. 修改文件清单

| 文件 | 操作 | 改动 | 说明 |
|------|------|------|------|
| `core/tiktok_service_ex.py` | 新增（Phase 7-A） | 102 行 | 增强解析层（Retry + JSON + fallback） |
| `workers/parse_worker.py` | 修改 L14 + L64-67 | 1 行 import + 4 行 success 标志 | L14 接入增强链；新增 data["success"] 显式成功标志 |
| `TK_Studio_V1_6_4.py` | 修改 4 处 | ~15 行 | 修复假成功：_parse_success_count 计数 + _on_parse_finished 区分消息 |
| `tests/test_tiktok_service_ex.py` | 新增（Phase 7-A） | 11 测试 | 集成层测试 |
| `tests/test_phase7a_final_acceptance.py` | **本次新增** | 9 测试 | 6 Case 回归 + success 标志 + 合并策略 |

---

## 3. 冻结边界变化

| 文件 | Phase 7-A 前 | Phase 7-A Final Acceptance 后 | 状态 |
|------|-------------|-------------------------------|------|
| `core/parser.py` | 冻结 | 未修改 | ✅ |
| `core/tiktok_service.py` | 冻结 | 未修改 | ✅ |
| `core/parser_ex.py` | 冻结 | 未修改 | ✅ |
| `core/tiktok_request.py` | 冻结 | 未修改 | ✅ |
| `core/http_client.py` | 冻结 | 未修改 | ✅ |
| `core/downloader.py` | 冻结 | 未修改 | ✅ |
| `core/db.py` | 冻结 | 未修改 | ✅ |
| `core/chrome_bridge.py` | 冻结 | 未修改 | ✅ |
| `workers/parse_worker.py` | L14 import | L14 import + L64-67 success 标志 | ⚠️ 新增 4 行（必要性见下） |
| `workers/resolve_worker.py` | 冻结 | 未修改 | ✅ |
| `workers/home_fetch_worker.py` | 冻结 | 未修改 | ✅ |
| `workers/login_worker.py` | 冻结 | 未修改 | ✅ |
| `workers/task_manager.py` | 冻结 | 未修改 | ✅ |
| `core/profile_snapshot.py` | 冻结 | 未修改 | ✅ |
| `TK_Studio_V1_6_4.py` | 冻结(6-G) | 4 处修改（假成功修复） | ⚠️ 必要性见下 |

**冻结边界突破必要性：**

1. `workers/parse_worker.py` L64-67：新增 `data["success"] = bool(video_url)`。
   - 必要性：原 `success` signal 语义为"URL 处理完成"，不区分 video_url 是否有效。
   - 不改则 UI 无法区分"任务完成"与"解析成功"，假成功问题无法根治。
   - 改动方式：纯 additive（新增 dict 字段），不改 Signal 签名、不改 run() 控制流。

2. `TK_Studio_V1_6_4.py` 4 处修改：假成功日志修复。
   - 必要性：`_on_parse_finished` 原总输出 "✅ 解析任务完成。" 即使 video_url 全空。
   - 改动方式：新增 `_parse_success_count` 状态字段 + 在 `_on_parse_success` 累计 + 在 `_on_parse_finished` 按 count 区分消息。
   - 不改 download 入口逻辑、不改 Signal 接口、不改 parse_single 流程。

---

## 4. parser_ex 接入确认

- ✅ `workers/parse_worker.py` L14: `from core.tiktok_service_ex import parse_url`
- ✅ `core/tiktok_service_ex.py` L24: `from core.parser_ex import extract_tiktok_data_ex`
- ✅ `parse_url_ex()` L63: `data = extract_tiktok_data_ex(html)`
- ✅ parser_ex 内部 L73: `base = extract_tiktok_data(html)`（调用原 parser.py）
- ✅ JSON Layer 支持 `__UNIVERSAL_DATA_FOR_REHYDRATION__` / `SIGI_STATE` / `__NEXT_DATA__`
- ✅ 合并策略：正则优先，JSON 补充缺失字段（`_merge` 函数 L255-269）

---

## 5. Retry 接入确认

- ✅ `core/tiktok_service_ex.py` L23/L59: `from core.tiktok_request import fetch_tiktok_html`
- ✅ `core/tiktok_request.py` L25/L39: `create_retry_session()`
- ✅ `core/http_client.py` Retry 配置：
  - total=3, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504)
  - allowed_methods=frozenset(["GET", "HEAD"])
  - raise_on_status=False
  - timeout=20s（DEFAULT_TIMEOUT）
- ✅ Retry 在 `fetch_tiktok_html` 内生效，session 在 finally 中 close

---

## 6. Fallback 顺序

| 优先级 | 层 | 代码位置 | 验证 |
|--------|-----|----------|------|
| 1 | parser_ex JSON Layer | parser_ex.py L76 `_extract_structured_json` | ✅ |
| 2 | 原 parser.py 正则 | parser_ex.py L73 `extract_tiktok_data`（parser_ex 内部） | ✅ |
| 3 | 原 tiktok_service.parse_url | tiktok_service_ex.py L87 `_original_parse_url` | ✅ |
| 4 | Chrome fallback | tiktok_service.py L84 `load_with_chrome` | ✅ 实网验证成功 |
| 5 | 最终失败 | 返回部分结果（不崩溃） | ✅ 测试 Case 5 验证 |

**保守合并策略：**
- ✅ JSON 缺字段时由 regex 补充（parser_ex `_merge` L263）
- ✅ regex 缺字段时由 JSON 补充（parser_ex `_merge` L263）
- ✅ 空字符串不覆盖有效值（测试 `test_merge_empty_does_not_overwrite_valid` 验证）
- ✅ fallback 不覆盖 parser_ex 已有值（tiktok_service_ex L89-91 `if not result.get(key)`）

---

## 7. 假成功问题检查结果

### 7.1 问题发现

| 位置 | 问题 | 严重度 |
|------|------|--------|
| `ParseWorker.run()` | `success` signal 在 video_url 为空时仍 emit | 高 |
| `TK_Studio_V1_6_4.py` `_on_parse_finished` L721 | 总输出 "✅ 解析任务完成。" 即使 video_url 全空 | 高 |

### 7.2 修复措施

1. **ParseWorker**：新增 `data["success"] = bool(video_url)` 显式成功标志。
   - `success` signal 仍 emit（语义=URL 处理完成，不抛异常）
   - `data["success"]` 字段标识真正解析成功（video_url 有效）

2. **UI `_on_parse_finished`**：
   - 新增 `self._parse_success_count` 计数器
   - `_on_parse_success` 中 `if video_url: self._parse_success_count += 1`
   - `_on_parse_finished` 按 count 区分：
     - count > 0 → "✅ 解析任务完成（N 个作品获取到视频地址）。"
     - count == 0 → "⚠️ 解析任务完成，但未获取到任何视频地址。（可能 TikTok 风控/验证页...）"

### 7.3 验证

- ✅ `test_parse_worker_success_flag_true_when_video_url`：video_url 有效 → success=True
- ✅ `test_parse_worker_success_flag_false_when_no_video_url`：video_url 空 → success=False
- ✅ `test_case2_http200_no_data_failure`：HTTP 200 但无数据 → 判定失败
- ✅ `test_case5_all_fail_final_failure`：全部失败 → 判定失败

### 7.4 TikTok 风控场景区分

| 场景 | 判定 | 日志 |
|------|------|------|
| A. 页面有有效数据 | 解析成功 | "✅ 已解析视频地址并写入作品库。" |
| B. TikTok 返回空壳/验证页 | 解析失败 | "⚠️ 已写入作品库，但暂未获取视频地址" + 批级 "⚠️ 未获取到任何视频地址" |
| C. Chrome 可获得数据 | Chrome fallback 成功 | "Chrome解析：标题=有，封面=有，视频地址=有" |
| D. Chrome 也无法获得 | 最终失败 | 批级 "⚠️ 未获取到任何视频地址" |

**核心原则确认：**
- ✅ HTTP 200 ≠ 解析成功（以 video_url 是否有效为准）
- ✅ 任务执行完成 ≠ 解析成功（以 _parse_success_count > 0 为准）

---

## 8. 下载阻断检查结果

| 检查点 | 代码位置 | 结果 |
|--------|----------|------|
| `download_current_work()` | TK_Studio L739-753 | 委托 `_start_download_worker` |
| `_start_download_worker` video_url 检查 | TK_Studio L787-793 | ✅ `work[5]` 为空 → "无法下载" 警告 + return |
| DB work tuple 字段顺序 | db.py `get_work` SELECT * | ✅ work[5] = video_url |
| TaskManager.enqueue | 仅在 video_url 有效后调用 | ✅ 不会假启动 |

**确认：解析失败（video_url 空）→ 不会创建可下载任务 → 不会开始下载。**

- ✅ `test_case6_download_blocked_when_no_video_url` 验证阻断逻辑

---

## 9. 自动化测试数量及结果

```
python -m compileall core/ workers/ tests/ TK_Studio_V1_6_4.py → exit 0
python -m pytest tests/ -q → 101 passed in 0.43s
```

| 测试文件 | 用例数 | 结果 |
|----------|--------|------|
| test_phase7a_final_acceptance.py（**新增**） | 9 | ✅ PASS |
| test_tiktok_service_ex.py | 11 | ✅ PASS |
| test_url_resolver.py | 24 | ✅ PASS |
| test_parser_ex.py | 26 | ✅ PASS |
| test_parser_integration.py | 10 | ✅ PASS |
| test_http_client.py | 20 | ✅ PASS |
| test_home_worker.py | 1 | ✅ PASS |
| **合计** | **101** | **✅ ALL PASS** |

### 6 Case 覆盖

| Case | 描述 | 测试函数 | 结果 |
|------|------|----------|------|
| 1 | video_url != "" → 成功 | test_case1_valid_result_success | ✅ |
| 2 | HTTP 200 但无数据 → 失败 | test_case2_http200_no_data_failure | ✅ |
| 3 | parser_ex 失败但原 parser 成功 | test_case3_parser_ex_fail_original_success | ✅ |
| 4 | requests/parser 失败但 Chrome 成功 | test_case4_chrome_fallback_success | ✅ |
| 5 | 全部失败 → 最终失败 | test_case5_all_fail_final_failure | ✅ |
| 6 | 无 video_url → 下载被阻止 | test_case6_download_blocked_when_no_video_url | ✅ |

---

## 10. 实网测试结果

探针：`data/probes/phase7a_final/probe_real_net.py`

### 测试 1：标准 URL

| 项 | 值 |
|----|-----|
| URL | `https://www.tiktok.com/@rfbxha/video/7681265056633326878` |
| HTTP status | 200 |
| HTML length | 1462（首请求，风控页） |
| parser_ex result（首请求 HTML） | 空 |
| parser.py result（首请求 HTML） | 空 |
| parse_url_ex 内部二次 fetch | ✅ 获取到完整页面 |
| parser_ex（二次 HTML） | 标题=有，封面=有，视频地址=有 |
| 最终 title | ✓（有，含编码问题） |
| 最终 cover_url | ✓（tiktokcdn.com） |
| 最终 video_url | ✓（v16-webapp-prime.tiktok.com） |
| **最终判定** | **✅ 成功** |

### 测试 2：短链

| 项 | 值 |
|----|-----|
| 短链 URL | `https://www.tiktok.com/t/ZTUNyfkNF/` |
| 短链解析 | HEAD 成功 → `@rfbxha/video/7681265056633326878` |
| HTTP status | 200 |
| HTML length | 1462 |
| parser_ex result | 空（风控页） |
| parser.py result | 空 |
| fallback 触发 | ✅ "字段缺失，启用原解析链 fallback……" |
| requests 解析 | 空 |
| **Chrome fallback** | **✅ 标题=有，封面=有，视频地址=有** |
| 最终 title | ✓ |
| 最终 cover_url | ✓ |
| 最终 video_url | ✓ |
| **最终判定** | **✅ 成功（Chrome fallback 成功）** |

### 实网结论

- ✅ 短链解析成功
- ✅ 标准 URL 解析成功（parser_ex 在二次 fetch 获取数据）
- ✅ Chrome fallback 是可靠数据源（测试 2 中 requests 全空，Chrome 成功）
- ✅ fallback 链路完整有效
- ✅ 无假成功（video_url 均非空）

---

## 11. TikTok 风控影响

| 现象 | 原因 | 影响 | 应对 |
|------|------|------|------|
| 首次 requests 返回 1462 字节空壳页 | TikTok 反爬验证 | parser_ex + parser 均空 | Chrome fallback 兜底 |
| 短时间重复请求同一 URL | TikTok 限流 | 可能全链失败 | 用户操作间隔 ≥30s |
| Retry 最坏 5 次请求（4 Retry + 1 fallback） | 设计如此（fallback 需独立请求） | 风控场景下放大限流 | 非代码缺陷，记录在案 |

**重要：本次实网未出现"假成功"。** 所有成功判定均基于 video_url 非空，符合严格标准。

---

## 12. 是否达到 Phase 7-A Final Acceptance

**PASS**

| 维度 | 评估 | 结果 |
|------|------|------|
| 代码链路正确 | parser_ex + Retry + fallback 全链接入 | ✅ |
| 失败判定正确 | video_url 空 = 失败；HTTP 200 ≠ 成功 | ✅ |
| 下载不会假启动 | _start_download_worker 检查 video_url | ✅ |
| 回归测试覆盖 | 6 Case + success 标志 + 合并策略 = 9 新增 | ✅ |
| 实网行为符合预期 | 标准 URL + 短链均成功；Chrome fallback 有效 | ✅ |
| 假成功问题已修复 | ParseWorker success 标志 + UI 消息区分 | ✅ |
| 全量测试 | 101/101 PASS | ✅ |
| 编译检查 | compileall exit 0 | ✅ |

---

## 13. 是否允许进入 Phase 7-B

**否 — 按指令停止，不进入 Phase 7-B。**

Phase 7-A Final Acceptance 已完成：
- 代码级审计完成
- 假成功问题已发现并修复
- 回归测试已添加（9 新增）
- 全量测试 101/101 PASS
- 实网验证通过（标准 URL + 短链）
- 冻结边界变化已记录（parse_worker.py + TK_Studio_V1_6_4.py，必要性已论证）

等待人工确认后方可进入 Phase 7-B。

---

## 附录：探针与测试产物

| 文件 | 用途 |
|------|------|
| `data/probes/phase7a_final/probe_real_net.py` | 实网验证探针 |
| `tests/test_phase7a_final_acceptance.py` | 6 Case 回归测试 |
| `PHASE7_A_IMPLEMENTATION_REPORT.md` | Phase 7-A 实施报告（原始） |
| `PHASE7_A_ACCEPTANCE_REPORT.md` | Phase 7-A 验收报告（原始） |
| `PHASE7_A_FINAL_ACCEPTANCE_REPORT.md` | 本报告（Final Acceptance） |
