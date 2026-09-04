# Phase 7-B.1 Read-Only Analysis — TikTok 解析稳定性分析

> 阶段：Phase 7-B.1（Read-Only Analysis）
> 日期：2026-09-04 17:30 (+08:00)
> 基线：Phase 7-A = PASS / LOCKED @ commit 7b6bf0a
> 声明：**本阶段不修改任何生产代码**

---

## 1. 当前架构

```
TK_Studio_V1_6_4.py (UI)
    ├── parse_single()           入口：URL 校验 + 短链检测
    │   ├── ResolveWorker         短链后台解析（HEAD + GET fallback + TTL cache）
    │   │   └── resolve_short_url()
    │   └── _validate_and_parse() canonical URL 校验
    │       └── ParseWorker        单作品后台解析 QThread
    │           └── parse_url()    ← workers/parse_worker.py L14 import
    │               = tiktok_service_ex.parse_url_ex()
    │                   ├── fetch_tiktok_html()         [tiktok_request.py]
    │                   │   └── create_retry_session()   [http_client.py]
    │                   │       Retry(total=3, backoff=1, 429/5xx)
    │                   ├── extract_tiktok_data_ex()     [parser_ex.py]
    │                   │   └── extract_tiktok_data()    [parser.py] ← 内部调用
    │                   └── _original_parse_url()        [tiktok_service.py] ← fallback
    │                       ├── requests.get()           ← 无 Retry
    │                       ├── extract_tiktok_data()    [parser.py]
    │                       └── load_with_chrome()       [chrome_bridge.py] ← Chrome
    ├── _on_parse_success()      成功回调：区分 video_url 有无
    ├── _on_parse_finished()     批级完成：_parse_success_count 区分消息
    └── _start_download_worker() 下载入口：检查 video_url 空则阻断
```

---

## 2. 实际调用链

### 2.1 完整链路（含 fallback）

```
ParseWorker.run()
    ↓ data = parse_url(url)     # = tiktok_service_ex.parse_url_ex(url)
    ↓
parse_url_ex(url)
    ↓ html = fetch_tiktok_html(url)     # 第 1 次 HTTP（Retry session）
    ↓ data = extract_tiktok_data_ex(html) # parser_ex → 内部调 parser.py
    ↓ if 字段缺失:
    ↓   fallback = _original_parse_url(url)  # tiktok_service.parse_url
    ↓     ↓ html2 = requests.get(url)        # 第 2 次 HTTP（无 Retry）← 重复请求
    ↓     ↓ data2 = extract_tiktok_data(html2)
    ↓     ↓ if 仍缺失:
    ↓     ↓   rendered = load_with_chrome(url)  # Chrome 渲染（第 3 次 HTTP，不同引擎）
    ↓     ↓   data3 = extract_tiktok_data(rendered)
    ↓   合并缺失字段
    ↓ return result
```

### 2.2 关键发现

| 发现 | 位置 | 影响 |
|------|------|------|
| fetch_tiktok_html 的 HTML 被丢弃 | parse_url_ex L87 调用 _original_parse_url 时不传 HTML | _original_parse_url 重新 requests.get 同一 URL |
| _original_parse_url 无 Retry | tiktok_service.py L54 纯 requests.get | 429/5xx 直接失败，无重试 |
| parser_ex 内部调用 parser.py | parser_ex.py L73 | parser.py 非冗余，是 parser_ex 的基础层 |
| Chrome 用 --dump-dom | chrome_bridge.py L43-53 | 一次性渲染，无 CDP 持久进程，僵尸风险低 |

---

## 3. HTTP 200 空数据原因分析

### 3.1 TikTok 风控页面特征

实网探针观测到（Phase 7-A Final Acceptance）：

| 项 | 值 |
|----|-----|
| HTTP status | 200 |
| HTML length | 1462 字节 |
| parser_ex result | 全空 |
| parser.py result | 全空 |
| 页面内容 | TikTok 验证页/风控空壳页 |

TikTok 对无 Cookie/无登录态的 requests 返回 HTTP 200 + 空壳页面（非 4xx），
伪装成正常响应，但不含任何作品数据。

### 3.2 当前系统如何处理 HTTP 200 空数据

```python
# tiktok_request.py L50-57
if response.status_code == 200:
    return response.text          # ← 返回空壳 HTML，不判断内容有效性
else:
    return ""
```

**问题：HTTP 200 不等于有效页面。** 当前系统只检查 status_code，不检查 HTML 内容
是否包含 TikTok 数据标记。

### 3.3 无页面有效性判断

当前系统**没有**以下检测：

| 检测项 | 当前 | 说明 |
|--------|------|------|
| HTML 长度阈值 | ❌ 无 | 1462 字节 vs 正常页面 ~50KB+ |
| SIGI_STATE 存在 | ❌ 无 | parser_ex 会尝试但仅用于提取字段 |
| __UNIVERSAL_DATA__ 存在 | ❌ 无 | 同上 |
| __NEXT_DATA__ 存在 | ❌ 无 | 同上 |
| video_id 在 HTML 中 | ❌ 无 | 仅在 URL 中提取 |
| 关键 DOM 元素 | ❌ 无 | 无 |

系统完全依赖 parser 能否提取到 video_url 来间接判断页面有效性。
这是"内容型检测"而非"页面型检测"。

### 3.4 HTTP 200 空数据时的完整流转

```
fetch_tiktok_html → HTTP 200, 返回 1462 字节空壳
    ↓
parser_ex.extract_tiktok_data_ex(空壳)
    ↓ extract_tiktok_data(空壳) → 全空
    ↓ _extract_structured_json(空壳) → None（无 JSON blob）
    ↓ _merge(全空, 全空) → 全空
    ↓ 返回全空
    ↓
parse_url_ex: not title or not cover or not video_url → True
    ↓ 调用 _original_parse_url(url) ← 再次请求同一 URL
    ↓ requests.get(url) → HTTP 200, 同一空壳（风控仍在）
    ↓ extract_tiktok_data(空壳) → 全空
    ↓ not title or not cover or not video_url → True
    ↓ load_with_chrome(url) → Chrome 渲染 → 获得真实数据 ✅
```

**结论：HTTP 200 空数据时，系统会对同一 URL 发起 2 次 requests + 1 次 Chrome，
其中第 2 次 requests 是完全冗余的（风控页不会因为再次请求而变化）。**

---

## 4. Retry 分析

### 4.1 Retry 配置

| 项 | 值 | 位置 |
|----|-----|------|
| total | 3 | http_client.py L16 |
| backoff_factor | 1 | http_client.py L17 |
| status_forcelist | 429, 500, 502, 503, 504 | http_client.py L18 |
| allowed_methods | GET, HEAD | http_client.py L64 |
| raise_on_status | False | http_client.py L65 |
| timeout | 20s | http_client.py L21 |

Retry 退避序列：0s → 1s → 2s（3 次重试间隔）

### 4.2 Retry 生效条件

Retry **仅对 fetch_tiktok_html 生效**（tiktok_request.py 使用 create_retry_session）。
_original_parse_url（tiktok_service.py L54）使用裸 `requests.get`，**无 Retry**。

### 4.3 Retry × legacy 重复请求

**不存在 Retry × Retry 倍增**：
- fetch_tiktok_html: Retry(total=3) → 最多 4 次请求
- _original_parse_url: 无 Retry → 最多 1 次请求

但存在**顺序重复请求**：fetch_tiktok_html 的 HTML 在 fallback 时不被复用，
_original_parse_url 重新请求同一 URL。

---

## 5. 重复请求分析

### 5.1 各场景 HTTP 请求计数

| 场景 | fetch_tiktok_html | _original_parse_url | Chrome | 合计 |
|------|-------------------|---------------------|--------|------|
| A. 首次成功 | 1 | 0 | 0 | **1** |
| B. HTTP 200 空壳 | 1 | 1（冗余） | 1 | **3** |
| C. HTTP 429 | 4（Retry） | 1 | 1 | **6** |
| D. HTTP 5xx | 4（Retry） | 1 | 1 | **6** |
| E. 网络异常 | 4（Retry） | 1（异常） | 1 | **6** |
| F. parser_ex 部分 → legacy 补全 | 1 | 1（冗余） | 0 | **2** |
| G. 全部失败 | 4 | 1 | 1（失败） | **6** |

### 5.2 核心问题

**场景 B（HTTP 200 空壳）是最高频场景**（TikTok 风控），产生 3 次 HTTP 交互：
1. fetch_tiktok_html: HTTP 200 → 空壳 HTML（被 parser_ex 解析为空）
2. _original_parse_url: 再次 requests.get 同一 URL → 同一空壳（冗余）
3. Chrome: 渲染同一 URL → 成功

**第 2 次请求完全冗余**：风控页不会因短时间内再次 requests.get 而变化。
且第 2 次请求会增加 TikTok 风控评分（快速重复请求 = 机器人特征）。

### 5.3 重复请求根因

```python
# tiktok_service_ex.py L59-87
html = fetch_tiktok_html(url)        # ← 第 1 次请求，HTML 存入局部变量
data = extract_tiktok_data_ex(html)  # ← 解析第 1 次 HTML
if not result["title"] or ...:
    fallback = _original_parse_url(url)  # ← 第 2 次请求（不传 html！）
```

`_original_parse_url` 签名为 `parse_url(url, log_callback)`，不接受 HTML 参数。
这是冻结函数的签名限制。

---

## 6. parser_ex / parser.py 分析

### 6.1 职责分工

| 模块 | 职责 | 调用关系 |
|------|------|----------|
| parser.py | 纯正则解析（meta 标签 + JSON 字符串模式） | 被 parser_ex 内部调用 + 被 tiktok_service 直接调用 |
| parser_ex.py | JSON Layer + 正则，合并策略 | 调用 parser.py 作为基础层 |

### 6.2 parser_ex 是否覆盖 parser.py？

**否 — parser_ex 依赖 parser.py。**

```python
# parser_ex.py L73
base = extract_tiktok_data(html)  # ← 调用 parser.py
```

parser_ex 的流程：
1. 先调用 parser.py 获得正则结果（base）
2. 尝试 JSON blob 提取（structured）
3. 合并：正则优先，JSON 补充缺失字段

### 6.3 parser.py 是否仍然必要？

**是。** parser.py 是 parser_ex 的基础层，不可删除。
- parser_ex 内部调用它（L73）
- tiktok_service.py 直接调用它（L64）
- Chrome fallback 后也调用它解析渲染后 HTML（L86）

### 6.4 两者是否重复解析？

**在同一 HTML 上不重复。** parser_ex 调用 parser.py 一次，然后合并 JSON 结果。

**但在 fallback 链路中存在重复解析：**
1. parse_url_ex: parser_ex 解析 HTML1（含 parser.py 调用）
2. _original_parse_url: parser.py 再次解析 HTML2（HTML2 = 重新 requests.get）

这是**不同 HTML 上的相同解析逻辑**，不是 parser 层冗余，而是 HTTP 层冗余导致
parser 被多调用一次。

---

## 7. Chrome fallback 分析

### 7.1 触发条件

```python
# tiktok_service.py L83
if not result["title"] or not result["cover_url"] or not result["video_url"]:
    rendered = load_with_chrome(url, log_callback)
```

**触发条件：title / cover_url / video_url 任一为空。**

### 7.2 Chrome 行为

| 项 | 值 | 说明 |
|----|-----|------|
| 模式 | `--headless=new --dump-dom` | 一次性渲染，输出 DOM stdout |
| profile | `chrome_headless_profile` | 独立于用户 Chrome 和登录 profile |
| 超时 | 45s | subprocess.run timeout |
| 端口 | 无（非 CDP 模式） | 不占用 9222-9231 端口 |
| 进程 | subprocess.run 同步 | 超时后进程被 kill |

### 7.3 风险评估

| 风险 | 评估 |
|------|------|
| 影响用户 Chrome | ✅ 无（独立 profile） |
| 僵尸 Chrome | 低（--dump-dom 一次性，subprocess.run 管理生命周期） |
| profile 锁冲突 | 低（chrome_headless_profile 专用，不与登录/home_fetcher 冲突） |
| 同一 URL 再次请求 | 是（Chrome 加载同一 URL，但从不同引擎/IP 标识） |

### 7.4 Chrome 触发频率问题

当前条件是 **title OR cover OR video_url 任一缺失** 即触发 Chrome。
但 Chrome 渲染耗时 ~3-7s（实网观测），是最慢的环节。

如果 parser_ex 提取到 title + cover 但缺 video_url（关键字段），
仍然会触发 Chrome——这是合理的（video_url 是下载必需）。
但如果 title 缺失但 video_url 已获取，也会触发 Chrome——这是**不必要**的
（title 非下载必需，可后续补充）。

---

## 8. 短链分析

### 8.1 短链解析链路

```
parse_single()
    ↓ has_short = any(is_short_url(u) for u in urls)
    ↓ if has_short:
    ↓   ResolveWorker(urls)
    ↓     resolve_short_url(url)
    ↓       HEAD 优先 → 302 → Location header → canonical URL
    ↓       GET fallback（HEAD 失败时）
    ↓       TTL cache（300s, 256 entries）
    ↓   _on_resolve_finished(results)
    ↓     resolved_urls = [canonical or original]
    ↓   _validate_and_parse(resolved_urls)
    ↓     ParseWorker(resolved_urls)  ← 收到的是 canonical URL，非短链
```

### 8.2 实际案例

```
短链: https://www.tiktok.com/t/ZTUNyfkNF/
  ↓ ResolveWorker HEAD
canonical: https://www.tiktok.com/@rfbxha/video/7681265056633326878
  ↓ ParseWorker
parse_url_ex(canonical) → 解析
```

### 8.3 重复请求检查

| 请求 | URL | 是否重复 |
|------|-----|----------|
| ResolveWorker HEAD | 短链 URL | 否（不同 URL） |
| ParseWorker GET | canonical URL | 否（不同 URL） |

**短链解析与作品解析请求不同 URL，不存在重复。**

### 8.4 短链缓存

url_resolver 内置 TTL+LRU 缓存（300s, 256 entries），同一短链 5 分钟内不重复解析。
ParseWorker 不涉及短链缓存（它收到的是已解析的 canonical URL）。

### 8.5 canonical URL 可靠性

实网验证：HEAD 请求短链 → 302 → Location header 提取 canonical URL，可靠。
GET fallback 确保 HEAD 失败时仍能解析。

---

## 9. 成功/失败状态机分析

### 9.1 当前状态机

| 场景 | video_url | data["success"] | UI 消息 |
|------|-----------|-----------------|---------|
| 完整成功 | 非空 | True | ✅ 已解析视频地址并写入作品库 |
| 有 title/cover 无 video_url | 空 | False | ⚠️ 已写入作品库，但暂未获取视频地址 |
| HTTP 200 全空（风控） | 空 | False | ⚠️ 同上 + 批级 ⚠️ 未获取到任何视频地址 |
| Chrome 成功 | 非空 | True | ✅ |
| Chrome 失败 | 空 | False | ⚠️ |
| 异常 | — | failed signal | ❌ 解析失败 |

### 9.2 Phase 7-A 修复评估

`data["success"] = bool(video_url)` 已形成可靠的最终状态机：
- ✅ 区分"URL 处理完成"与"解析成功"
- ✅ UI 批级消息不再假成功
- ✅ 下载入口阻断空 video_url

### 9.3 状态机缺口

当前不区分失败原因：
- TikTok 风控页（可重试，间隔 30s）
- 视频不存在（永久失败）
- 网络错误（可立即重试）
- Chrome 超时（可重试）

但这在 Phase 7-A 范围内是可接受的——video_url 导向的状态机足以保护下载流程。

---

## 10. 风控风险分析

### 10.1 风险行为清单

| 行为 | 风险等级 | 说明 |
|------|----------|------|
| fetch_tiktok_html + _original_parse_url 对同一 URL 快速双请 | **高** | 机器人特征，触发 429/challenge |
| Retry total=3 对 429 重试 4 次 | **中** | 加重限流，但 Retry 设计即此目的 |
| Chrome fallback 额外请求 | **低** | 不同引擎/IP 标识，TikTok 可能不同对待 |
| 短链 HEAD 请求 | **低** | 不同 URL，不触发作品页风控 |

### 10.2 最高风险

**场景 B（HTTP 200 空壳）的快速双请求是最高风险。**

```
T+0s:   fetch_tiktok_html → requests.get(url) → 200 空壳
T+0.5s: _original_parse_url → requests.get(url) → 200 空壳（同一 URL，0.5s 内）
```

TikTok 反爬系统检测到 0.5s 内对同一作品页 2 次 requests 请求（无 Cookie），
会加重风控评分，可能导致后续请求全部返回空壳。

### 10.3 Retry 对风控的影响

Retry 对 429 重试 3 次（退避 0s/1s/2s），最坏 4 次请求在 ~3s 内完成。
这会加重 429 限流，但 Retry 是标准 HTTP 实践，TikTok 应容忍合理重试。

**不建议降低 Retry total**（会减少 429 自愈机会）。建议减少的是**冗余的
第 2 次 requests.get**（_original_parse_url）。

---

## 11. 候选优化方案

### Candidate A: HTTP 200 页面有效性检测

| 项 | 内容 |
|----|------|
| 方案名 | Page Validity Detection |
| 解决问题 | 无法区分 HTTP 200 真实页面 vs 风控空壳页 |
| 涉及文件 | core/tiktok_service_ex.py（新增 _is_valid_tiktok_page() 辅助函数） |
| 修改规模 | ~30-50 行 |
| 风险 | 低（additive，不改现有流程） |
| 收益 | 启用智能 fallback 决策；风控页可直接跳过 requests fallback 进 Chrome |
| 影响测试 | 新增测试，现有测试不受影响 |
| 影响 Chrome | 间接（可减少不必要的 requests fallback） |
| 影响短链 | 无 |
| 影响 Chrome 隔离 | 无 |

检测标记：HTML 长度阈值、SIGI_STATE/__UNIVERSAL_DATA__/__NEXT_DATA__ 存在性、
og:video meta 标签存在性。

### Candidate B: 减少 requests / legacy parser 重复请求

| 项 | 内容 |
|----|------|
| 方案名 | Eliminate Duplicate HTTP Request |
| 解决问题 | parse_url_ex 的 HTML 被丢弃，_original_parse_url 重新请求同一 URL |
| 涉及文件 | core/tiktok_service_ex.py（修改 fallback 逻辑） |
| 修改规模 | ~20-30 行 |
| 风险 | 中（改变 fallback 流程，须保留 Chrome fallback） |
| 收益 | 消除每次失败解析的 1 次冗余 HTTP 请求，降低风控风险 |
| 影响测试 | 需更新 test_tiktok_service_ex.py |
| 影响 Chrome | 保留（仍作为最终 fallback） |
| 影响短链 | 无 |
| 影响 Chrome 隔离 | 无 |

核心思路：parse_url_ex 已有 HTML，当 parser_ex 解析失败时，直接调用
`load_with_chrome(url)` + `extract_tiktok_data(rendered)`，跳过
_original_parse_url 的 requests.get 步骤。或新增一个接受 HTML 参数的
fallback 函数，复用已有 HTML 走 parser.py + Chrome。

### Candidate C: 统一 parser fallback 策略

| 项 | 内容 |
|----|------|
| 方案名 | Unified Parser Fallback |
| 解决问题 | parser_ex 和 _original_parse_url 都调用 parser.py，fallback 路径分散 |
| 涉及文件 | core/tiktok_service_ex.py |
| 修改规模 | ~15-20 行 |
| 风险 | 中高（绕过 legacy parse_url 的 parser 步骤，仅用 Chrome） |
| 收益 | 消除重复请求 + 重复解析 |
| 影响测试 | 需更新测试 |
| 影响 Chrome | 改变触发路径（Chrome 更早介入） |
| 影响短链 | 无 |
| 影响 Chrome 隔离 | 无 |

核心思路：parse_url_ex 解析失败后，直接调 Chrome fallback，完全跳过
_original_parse_url（因为 requests 风控页拿不到数据，Chrome 是唯一可靠源）。

### Candidate D: 优化 Chrome fallback 触发条件

| 项 | 内容 |
|----|------|
| 方案名 | Chrome Trigger Optimization |
| 解决问题 | title/cover 任一缺失即触发 Chrome，但 video_url 已有时不需要 Chrome |
| 涉及文件 | core/tiktok_service_ex.py（控制 _original_parse_url 调用条件） |
| 修改规模 | ~10 行 |
| 风险 | 低中 |
| 收益 | 减少 Chrome 调用（~3-7s/次），仅在 video_url 缺失时触发 |
| 影响测试 | 需更新测试 |
| 影响 Chrome | 改变触发频率（降低） |
| 影响短链 | 无 |
| 影响 Chrome 隔离 | 无 |

核心思路：在 parse_url_ex 中，仅当 video_url 为空时才调 fallback
（而非 title 或 cover 为空时）。

### Candidate E: 统一解析状态机

| 项 | 内容 |
|----|------|
| 方案名 | Unified Parse State Machine |
| 解决问题 | success flag 仅检查 video_url，不区分失败原因 |
| 涉及文件 | core/tiktok_service_ex.py, workers/parse_worker.py, TK_Studio_V1_6_4.py |
| 修改规模 | ~40-60 行 |
| 风险 | 中（触及多层） |
| 收益 | 更好的用户反馈，启用智能重试策略 |
| 影响测试 | 新增测试 |
| 影响 Chrome | 无 |
| 影响短链 | 无 |
| 影响 Chrome 隔离 | 无 |

核心思路：data 增加 failure_reason 字段（risk_control / not_found /
network_error / chrome_fail），UI 据此显示不同提示。

---

## 12. 方案评分表

| 维度 | A | B | C | D | E |
|------|---|---|---|---|---|
| 稳定性 (5=最稳定) | 4 | 5 | 3 | 4 | 3 |
| 风控风险降低 (5=最高) | 4 | 5 | 4 | 3 | 2 |
| 代码复杂度 (5=最简) | 4 | 3 | 3 | 5 | 2 |
| 兼容性 (5=最兼容) | 5 | 4 | 3 | 4 | 3 |
| 回归风险 (5=最低) | 5 | 3 | 2 | 4 | 2 |
| **合计** | **22** | **20** | **15** | **20** | **12** |
| **排名** | 1 | 2 | 4 | 2 | 5 |

---

## 13. 推荐方案

### 推荐：B + A 组合（D 作为可选第三优先级）

**第一优先级：Candidate B — 消除重复 HTTP 请求**

理由：B 直接解决最高风控风险（同一 URL 快速双请求），收益最直接。
消除 _original_parse_url 的冗余 requests.get，每次失败解析减少 1 次 HTTP 请求。
在 TikTok 风控场景（最高频失败场景）下，从 3 次 HTTP 交互降为 2 次。

**第二优先级：Candidate A — 页面有效性检测**

理由：A 提供基础设施（判断页面是否风控空壳），使 B 的 fallback 决策更智能。
A + B 组合后：风控空壳页 → 直接跳 Chrome，不浪费 requests fallback。
A 单独价值有限，但与 B 配合后形成"检测 → 智能跳转"闭环。

**第三优先级（可选）：Candidate D — Chrome 触发条件优化**

理由：D 减少 Chrome 调用频率（仅 video_url 缺失时触发），降低 ~3-7s/次的
Chrome 渲染开销。但优先级低于 B/A，因为 Chrome 是可靠数据源，减少其调用
是优化而非修复。

### 不推荐

- **C**：风险较高（绕过 legacy parse_url 完整步骤），可能丢失 legacy parser
  对特定页面的解析能力。B 已能解决核心问题，无需 C 的激进重构。
- **E**：触及多层（service_ex + parse_worker + UI），回归风险高，且 Phase 7-A
  的 video_url 导向状态机已足够保护下载流程。E 属于后续 Phase 范围。

---

## 14. 不修改生产代码声明

**本阶段（Phase 7-B.1）为只读分析，未修改任何生产代码。**

| 文件 | 状态 |
|------|------|
| core/tiktok_service_ex.py | ✅ 未修改 |
| core/tiktok_service.py | ✅ 未修改 |
| core/tiktok_request.py | ✅ 未修改 |
| core/http_client.py | ✅ 未修改 |
| core/parser_ex.py | ✅ 未修改 |
| core/parser.py | ✅ 未修改 |
| core/chrome_bridge.py | ✅ 未修改 |
| workers/parse_worker.py | ✅ 未修改 |
| workers/resolve_worker.py | ✅ 未修改 |
| TK_Studio_V1_6_4.py | ✅ 未修改 |

仅新增本分析报告 `PHASE7_B1_READONLY_ANALYSIS.md`。

---

## 15. 当前基线

```text
Git Commit: 7b6bf0a
Phase: 7-A Final Acceptance = PASS / LOCKED
Working Tree: CLEAN
compileall: PASS (exit 0)
pytest: 101 passed
```

---

## 附录：实网观测数据（Phase 7-A Final Acceptance）

| 测试 | URL | HTTP | HTML len | parser_ex | Chrome | 最终 |
|------|-----|------|----------|-----------|--------|------|
| 标准 URL | @rfbxha/video/7681265056633326878 | 200 | 1462→完整 | 空→有 | — | ✅ |
| 短链 | t/ZTUNyfkNF/ | 200 | 1462 | 空 | ✅ 有 | ✅ |

观测结论：requests 首次返回 1462 字节空壳页（风控），Chrome fallback
是可靠数据源。标准 URL 在 parse_url_ex 二次 fetch 时偶然获取到完整页面
（TikTok 风控非确定性）。
