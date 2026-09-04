# Phase 7-A Release Freeze / Baseline Lock

> Freeze 时间：2026-09-04 17:00 (+08:00)
> Phase：7-A Final Acceptance
> Status：**PASS / LOCKED**

---

## 基线

```text
Project:
TK_Studio_V1_fixed

Production Entry:
TK_Studio_V1_6_4.py

Phase:
7-A Final Acceptance

Status:
PASS
```

---

## 测试

```text
compileall: PASS (exit 0)
pytest: 101 passed in 0.65s
```

| 维度 | 结果 |
|------|------|
| compileall | ✅ PASS (exit 0) |
| pytest | ✅ 101 passed |
| 基线测试数 | 101（92 原有 + 9 新增 Phase 7-A Final Acceptance） |

---

## 核心生产链

完整记录：

```text
ParseWorker
    → tiktok_service_ex.parse_url_ex()
    → tiktok_request.fetch_tiktok_html()
    → http_client.create_retry_session()  [Retry total=3, backoff=1, 429/5xx]
    → parser_ex.extract_tiktok_data_ex()  [JSON Layer + 正则优先]
    → parser.extract_tiktok_data()        [原 parser.py，parser_ex 内部调用]
    → tiktok_service.parse_url()           [legacy fallback，字段缺失时]
    → chrome_bridge.load_with_chrome()     [Chrome fallback，requests 失败时]
    → 最终返回结构化作品数据
```

接入确认：

| 节点 | 状态 |
|------|------|
| parser_ex 进入生产链 | ✅ |
| Retry 进入生产链 | ✅ |
| 原 parser.py 未删除 | ✅（parser_ex L73 + tiktok_service L64 调用） |
| Chrome fallback 未删除 | ✅（tiktok_service L84 load_with_chrome） |
| ResolveWorker 未重构 | ✅（git status 未修改） |
| ParseWorker QThread/Signal 架构未变 | ✅（仅 L14 import + data["success"] additive 字段） |
| UI 未重新设计 | ✅（仅 _parse_success_count 计数逻辑） |
| 下载入口检查 video_url | ✅（_start_download_worker L806 work[5]） |

---

## 假成功修复

```text
video_url != empty
    → parsed successfully

video_url == empty
    → not treated as successful parsing

download entry
    → blocked when video_url is empty
```

| 检查项 | 代码位置 | 状态 |
|--------|----------|------|
| ParseWorker success 标志 | parse_worker.py L67 `data["success"] = bool(video_url)` | ✅ |
| UI 成功计数 | TK_Studio L705 `self._parse_success_count += 1` | ✅ |
| UI 批级消息区分 | TK_Studio L732-740（count>0 → ✅，count==0 → ⚠️） | ✅ |
| 下载阻断 | TK_Studio L806-812 `if not video_url: 警告 + return` | ✅ |

**核心原则：**
- HTTP 200 ≠ 解析成功（以 video_url 是否有效为准）
- 任务执行完成 ≠ 解析成功（以 _parse_success_count > 0 为准）

---

## 实网

```text
Standard URL:
PASS

Short URL:
PASS

Chrome fallback:
PASS
```

| 测试 | URL | 结果 | 数据源 |
|------|-----|------|--------|
| 标准 URL | `@rfbxha/video/7681265056633326878` | ✅ PASS | parser_ex（二次 fetch） |
| 短链 | `t/ZTUNyfkNF/` | ✅ PASS | Chrome fallback |
| Chrome fallback | requests 返回 1462 字节空壳页 | ✅ PASS | Chrome 提取全部字段 |

---

## 已知限制

```text
TikTok anti-bot/rate-limit may cause requests HTML
to be incomplete or empty.

Chrome fallback is retained.

No attempt is made in Phase 7-A to bypass TikTok
anti-bot mechanisms.
```

| 限制 | 影响 | 应对 |
|------|------|------|
| TikTok 反爬导致 requests 返回空壳页 | parser_ex + parser 均空 | Chrome fallback 兜底 |
| 短时间重复请求同一 URL | TikTok 限流，全链可能失败 | 用户操作间隔 ≥30s |
| Retry 最坏 5 次请求（4 Retry + 1 fallback） | 风控场景下放大限流 | 设计如此（fallback 需独立请求），非代码缺陷 |
| Phase 7-A 不绕过 TikTok 反爬 | — | 后续 Phase 可考虑 Cookie/登录态注入 |

---

## 冻结文件

### 实际修改文件

| 文件 | 操作 | 改动 | 冻结状态 |
|------|------|------|----------|
| `core/tiktok_service_ex.py` | 新增 | 102 行 | Phase 7-A 新增，本次冻结 |
| `workers/parse_worker.py` | 修改 | L14 import + L64-67 success 标志 | ⚠️ 突破 Phase 5 冻结（必要性已记录） |
| `TK_Studio_V1_6_4.py` | 修改 | 4 处假成功修复 | ⚠️ 突破 Phase 6-G 冻结（必要性已记录） |
| `tests/test_tiktok_service_ex.py` | 新增 | 11 测试 | Phase 7-A 新增 |
| `tests/test_phase7a_final_acceptance.py` | 新增 | 9 测试 | Phase 7-A Final Acceptance 新增 |
| `PHASE7_A_IMPLEMENTATION_REPORT.md` | 新增 | 报告 | Phase 7-A 文档 |
| `PHASE7_A_ACCEPTANCE_REPORT.md` | 新增 | 报告 | Phase 7-A 文档 |
| `PHASE7_A_FINAL_ACCEPTANCE_REPORT.md` | 新增 | 报告 | Phase 7-A Final Acceptance 文档 |
| `PHASE7_A_RELEASE_FREEZE.md` | 新增 | 报告 | 本冻结报告 |
| `FINAL_SOURCE_MAP.md` | 新增 | 报告 | Phase 6-H 文档 |
| `RELEASE_STRUCTURE.md` | 新增 | 报告 | Phase 6-H 文档 |
| `archive/` | 新增 | 9 个旧版本文件 | Phase 6-H 归档 |

### 未修改的冻结文件（保护确认）

| 文件 | 状态 |
|------|------|
| `core/parser.py` | ✅ 未修改 |
| `core/tiktok_service.py` | ✅ 未修改 |
| `core/parser_ex.py` | ✅ 未修改 |
| `core/tiktok_request.py` | ✅ 未修改 |
| `core/http_client.py` | ✅ 未修改 |
| `core/downloader.py` | ✅ 未修改 |
| `core/db.py` | ✅ 未修改 |
| `core/chrome_bridge.py` | ✅ 未修改 |
| `workers/resolve_worker.py` | ✅ 未修改 |
| `workers/home_fetch_worker.py` | ✅ 未修改 |
| `workers/login_worker.py` | ✅ 未修改 |
| `workers/task_manager.py` | ✅ 未修改 |
| `core/profile_snapshot.py` | ✅ 未修改 |

### Phase 6-H 归档文件（删除 = 移入 archive/）

| 文件 | 归档位置 |
|------|----------|
| `TK_Studio_V1_1.py` | `archive/TK_Studio_V1_1.py` |
| `TK_Studio_V1_2.py` | `archive/TK_Studio_V1_2.py` |
| `TK_Studio_V1_3.py` | `archive/TK_Studio_V1_3.py` |
| `TK_Studio_V1_4.py` | `archive/TK_Studio_V1_4.py` |
| `TK_Studio_V1_5.py` | `archive/TK_Studio_V1_5.py` |
| `TK_Studio_V1_6_1.py` | `archive/TK_Studio_V1_6_1.py` |
| `TK_Studio_V1_6_2.py` | `archive/TK_Studio_V1_6_2.py` |
| `TK_Studio_V1_6_3.py` | `archive/TK_Studio_V1_6_3.py` |
| `add_task_methods.py` | `archive/add_task_methods.py` |
| `main.py` | `archive/main.py` |

---

## Freeze 声明

**Phase 7-A 自本报告生成起 FROZEN。**

任何后续修改必须新立 Phase/FIX，拥有独立基线与验收流程，
不得直接编辑 Phase 7-A 冻结文件（core/tiktok_service_ex.py、
workers/parse_worker.py 的 Phase 7-A 改动、TK_Studio_V1_6_4.py 的
Phase 7-A 改动、tests/test_tiktok_service_ex.py、
tests/test_phase7a_final_acceptance.py）。

**Next Phase：NOT STARTED**（按指令不进入 Phase 7-B，等待人工确认）
