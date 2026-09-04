# Phase 5-B4.3 基线报告 — TikTok 短链解析增强与稳定性优化

> 阶段：Phase 5-B4.3（只读分析，不修改代码）
> 基线来源：B4.2 验收通过版本（[PHASE5_B4_2_ACCEPTANCE_REPORT.md](file:///d:/TK_Studio_V1_fixed/PHASE5_B4_2_ACCEPTANCE_REPORT.md)，结论 PASS）
> 分析时间：2026-09-04
> 基线 commit：`17b41dbd557683bc1a3ef754abf9e1ad4b207a1d`
> B4.2 冻结代码：`core/url_resolver.py`（13:54）、`TK_Studio_V1_6_4.py` parse_single 集成（L555-577，13:55）

---

## 1. 当前 resolver 架构

### 1.1 模块定位

[core/url_resolver.py](file:///d:/TK_Studio_V1_fixed/core/url_resolver.py)（201 行，B4.2 新增）是**纯 stdlib + requests 的工具模块**：
- 不依赖 PySide6（可在任意线程/进程复用）
- 不依赖 SQLite / parser / downloader
- 不修改任何冻结模块
- 失败时返回原 URL，不抛异常、不阻塞调用方

### 1.2 公开接口

| 函数 | 签名 | 职责 |
|------|------|------|
| `is_short_url` | `(url) -> bool` | 检测 `/t/{token}` 与 `vm.tiktok.com/{token}` 两种短链格式 |
| `resolve_short_url` | `(url, log_callback=None, timeout=10) -> str` | 单个短链解析：HEAD 跟随重定向，结果非标准 URL 时回退 GET(stream) |
| `resolve_urls` | `(urls, log_callback=None, timeout=10) -> list[dict]` | 批量解析，返回 `{original, resolved, changed, success}` |
| `clear_cache` | `() -> None` | 清空 token→URL 缓存 |

### 1.3 关键内部常量

| 常量 | 当前值 | 作用 |
|------|--------|------|
| `_SHORT_URL_PATTERN` | `(?:tiktok\.com/t/([A-Za-z0-9]+))\|(?:vm\.tiktok\.com/([A-Za-z0-9]+))` | 短链检测（**仅两种格式**） |
| `_VIDEO_URL_PATTERN` | `tiktok\.com/@[\w.-]+/video/\d+` | 解析结果验证 |
| `_HEADERS` | Accept + UA(Chrome 151) + Accept-Language | 请求头（与 tiktok_service 一致） |
| `_cache` | `{}` 进程内 dict | token→resolved URL 缓存（无 TTL） |

### 1.4 解析主流程（resolve_short_url L68-144）

```
is_short_url? No → 返回原 url
  ↓ Yes
提取 token → 查 _cache → 命中返回
  ↓ miss
requests.head(url, allow_redirects=True, timeout)
  ↓
final_url 命中 _VIDEO_URL_PATTERN? Yes → 写缓存、返回
  ↓ No
requests.get(url, stream=True, allow_redirects=True, timeout) → response.close()
  ↓
命中 _VIDEO_URL_PATTERN? Yes → 写缓存、返回
  ↓ No
返回原 url
异常路径：Timeout / ConnectionError / Exception → 返回原 url + 日志
```

---

## 2. 当前调用链

### 2.1 唯一调用点

[TK_Studio_V1_6_4.py L555-577](file:///d:/TK_Studio_V1_fixed/TK_Studio_V1_6_4.py#L555-L577) `parse_single()`：

```
URL 输入（self.single_url_edit 多行）
  ↓ splitlines 去空
for url in urls:
  ↓ is_short_url(url)?                            [L559]
  ↓   resolve_short_url(url, log_callback=...)    [L560-562]
  ↓   resolved != url 且含 /video/ → 替换 + 成功日志  [L563-568]
  ↓   否则 → 警告日志，保留原 url                     [L570]
  ↓
检查 tiktok.com                                    [L572]
  ↓
检查 /video/                                       [L575]
  ↓
valid_urls.append(url)
ParseWorker(valid_urls, self.db)                   [L582]
```

### 2.2 调用点覆盖度

- ✅ `parse_single()` 单作品解析：已集成
- ❌ 主页 URL 输入框 `start_home_fetch()`：**未集成**（B3.2 路径，仍按原 URL 直送 HomeFetcher）
- ❌ 批量任务录入路径（如有）：**未集成**
- ❌ DownloadWorker 视频地址刷新路径：**未集成**（不需要，video_url 由 parser 从页面抽取，非短链）

### 2.3 import 现状

[TK_Studio_V1_6_4.py L20](file:///d:/TK_Studio_V1_fixed/TK_Studio_V1_6_4.py#L20)：
```python
from core.url_resolver import resolve_short_url, is_short_url
```
（`resolve_urls` 批量接口已实现但未被任何 UI 调用点使用）

---

## 3. 已存在能力

| 能力 | 状态 | 说明 |
|------|------|------|
| `/t/{token}` 短链检测 | ✅ | `_SHORT_URL_PATTERN` 第一分支 |
| `vm.tiktok.com/{token}` 检测 | ✅ | 第二分支 |
| HEAD 重定向跟随 | ✅ | `allow_redirects=True` |
| GET 回退（HEAD 结果非标准 URL） | ✅ | `stream=True` + 立即 `close()`，不下载 body |
| 标准视频 URL 验证 | ✅ | `_VIDEO_URL_PATTERN` |
| 进程内 token 缓存 | ✅ | `_cache` dict |
| timeout 可控 | ✅ | 默认 10s |
| User-Agent | ✅ | Chrome 151 桌面 UA |
| log_callback 日志回调 | ✅ | `_log()` 安全调用，回调异常被吞 |
| 批量接口 | ✅ | `resolve_urls()`（未被使用） |
| 非法输入兜底（None/空/非字符串） | ✅ | `is_short_url` / `resolve_short_url` 入口校验 |
| 网络异常兜底（Timeout/ConnError/Exception） | ✅ | 三层 except，返回原 url |
| 缓存清理 | ✅ | `clear_cache()` |

---

## 4. 当前限制

### 4.1 短链格式覆盖不全

- ❌ **`vt.tiktok.com/{token}` 未支持**：`_SHORT_URL_PATTERN` 只匹配 `vm.tiktok.com`，遗漏 `vt.` 子域（TikTok 第三种短链域名，移动端分享常用）。
- ❌ 大小写敏感问题：正则已加 `re.I`，但 `vm.`/`vt.` 子域字符串硬编码，新增子域需改正则。

### 4.2 URL 标准化缺失

- ❌ **无 URL 规范化**：解析结果保留 TikTok 附加的 query 参数（如 `?_r=1&_t=ZT-99RX3SOusFJ`，见 B4.2 Test 1 实测输出）。
- ❌ 解析结果未统一为 `https://www.tiktok.com/@user/video/{id}` 标准形态，下游 parser 需自行容忍 query。
- 当前 `parse_single()` 用 `"/video/" in resolved.lower()` 做粗判，可接受 query，但**非严格的 URL 标准化**。

### 4.3 稳定性短板

- ❌ **无重试机制**：单次 HEAD/GET 失败即返回原 url。对比 [downloader.py L192-200](file:///d:/TK_Studio_V1_fixed/core/downloader.py#L192-L200) 已用 `urllib3 Retry(total=2, backoff_factor=1, status_forcelist=(429,500,502,503,504))`，url_resolver 未对齐。
- ❌ **无 Cookie 支持**：TikTok 部分短链重定向依赖会话 Cookie（如已登录态）。当前请求不带 Cookie，匿名场景通常可解析，但**风控触发时可能拿到验证页 URL**（非 `/video/`，被当作解析失败）。
- ⚠️ **HEAD 可能被 TikTok 拒绝**：部分 CDN/WAF 对 HEAD 返回 403/405。当前用"HEAD 结果非标准 URL → GET 回退"间接处理，但若 HEAD 直接抛异常（如 403），会进 `Exception` 分支直接返回原 url，**未触发 GET 回退**。
- ⚠️ **User-Agent 单一**：与 tiktok_service 一致的 Chrome 151 桌面 UA，足够但无 UA 轮换，长期高频请求可能被风控。

### 4.4 异常处理覆盖面

| 异常类型 | 当前处理 | 缺口 |
|----------|---------|------|
| `requests.Timeout` | ✅ 返回原 url | 无 |
| `requests.ConnectionError` | ✅ 返回原 url | 无 |
| `Exception`（兜底） | ✅ 返回原 url | 无 |
| HTTP 4xx/5xx（非异常） | ⚠️ 不抛异常，`response.url` 可能是错误页 URL，靠 `_VIDEO_URL_PATTERN` 不命中 → 走 GET 回退 → 再不命中 → 返回原 url | **未明确区分"被风控"与"网络错误"日志** |
| 重定向到验证页/captcha | ⚠️ 靠 `_VIDEO_URL_PATTERN` 不命中过滤 | **未识别 captcha URL 特征**，可能误判为"解析失败"而非"被风控" |
| 重定向链路过长 | ⚠️ requests 默认 30 跳上限 | 无显式控制（实际够用） |

### 4.5 性能与并发

- ✅ **缓存**：token→URL 进程内缓存，重复短链零网络开销。
- ❌ **无 TTL / 容量上限**：`_cache` 只增不减，长期运行内存增长（实际 token 数量有限，风险低但非工程化）。
- ❌ **无并发解析**：`resolve_urls()` 串行 `for` 循环，N 个短链 = N 次串行 HTTP（每次最多 timeout 秒）。当前 `parse_single()` 多行输入场景下，**主线程串行阻塞**（虽然单次 timeout 10s，5 个短链最坏 50s 阻塞 UI）。
- ⚠️ **UI 阻塞风险**：`parse_single()` 在主线程同步调用 `resolve_short_url()`，未移入后台线程。B4.2 单作品场景影响小，但批量短链输入会卡 UI。

### 4.6 可观测性

- ✅ log_callback 支持逐条日志。
- ❌ **无结构化结果统计**：`resolve_short_url` 只返回 str，调用方无法区分"非短链"/"短链解析成功"/"短链解析失败"三类结果（`resolve_urls` 有 `success` 字段但未被使用）。
- ❌ **无失败原因码**：日志是字符串，无 enum/code 便于 UI 区分提示（如"网络失败"vs"被风控"vs"非标准 URL"）。

---

## 5. B4.3 可优化方向

按"稳定性优先、URL 标准化次之、性能与可观测性补充"排序：

### 方向 A：短链格式扩展（必做，低风险）
- 正则新增 `vt\.tiktok\.com/{token}` 第三分支
- 验证：B4.2 Test 1 同款 token 通过 `vt.tiktok.com` 域名可达

### 方向 B：稳定性增强（必做，中风险）
- B1：HEAD 异常时也触发 GET 回退（当前 HEAD 抛异常直接返回原 url，丢失 GET 机会）
- B2：引入 urllib3 Retry（对齐 downloader，total=2, backoff=1, status_forcelist 429/5xx）
- B3：可选 Cookie 注入（复用 B3.4 `chrome_home_auth_profile` 的 Cookie，匿名模式不注入）—— **需评估是否触碰冻结边界**，倾向 B4.3 **不引入 Cookie**，保留为后续阶段

### 方向 C：URL 标准化（建议，低风险）
- 解析成功后剥离 query 参数，统一输出 `https://www.tiktok.com/@user/video/{id}`
- 需保留原 resolved URL 用于日志展示，标准化后 URL 送下游 parser

### 方向 D：性能（建议，中风险）
- D1：`resolve_urls()` 改为线程池并发（`concurrent.futures.ThreadPoolExecutor`，max_workers=4）
- D2：缓存加 TTL（如 1 小时）或容量上限（如 1000 条 LRU）
- D3：**评估**将 `parse_single()` 中的短链解析移入后台线程（避免批量短链卡 UI）—— **需修改 TK_Studio_V1_6_4.py parse_single 流程**，属 UI 层改动，需谨慎

### 方向 E：可观测性（可选，低风险）
- 失败原因 enum（`NETWORK_TIMEOUT` / `CONNECTION_ERROR` / `BLOCKED` / `NON_VIDEO_URL` / `UNKNOWN`）
- 结构化返回（保留 `resolve_short_url` str 兼容，新增 `resolve_short_url_ex` 返回 dict）

### 方向 F：测试沉淀（必做，低风险）
- 将 B4.2 三项验收测试持久化为 `tests/test_url_resolver.py`（含 mock 网络层）
- 纳入 phase-based 回归集

---

## 6. B4.3 候选范围与冻结边界预判

| 候选项 | 是否触碰冻结边界 | 建议 |
|--------|------------------|------|
| A 扩展 vt.tiktok.com | 否（仅改 url_resolver.py） | **纳入 B4.3** |
| B1 HEAD 异常触发 GET 回退 | 否 | **纳入 B4.3** |
| B2 urllib3 Retry | 否 | **纳入 B4.3** |
| B3 Cookie 注入 | ⚠️ 触碰 B3.4 snapshot 读取路径，风险高 | **推迟**，B4.3 不做 |
| C URL 标准化（剥离 query） | 否 | **纳入 B4.3**（仅 url_resolver 内部） |
| D1 并发 resolve_urls | 否 | **纳入 B4.3** |
| D2 缓存 TTL/LRU | 否 | **纳入 B4.3** |
| D3 parse_single 后台化 | ⚠️ 改 parse_single 流程，UI 层改动 | **推迟**，B4.3 不做 |
| E 结构化返回 | 否（新增函数，不改旧签名） | **可选**，B4.3 可做轻量版 |
| F 测试沉淀 | 否（新增 tests/） | **纳入 B4.3** |

**B4.3 预期修改文件**（待 DESIGN 确认）：
- `core/url_resolver.py`（B4.2 已冻结，B4.3 作为新阶段可改）
- `tests/test_url_resolver.py`（新增）
- **不改** `TK_Studio_V1_6_4.py`（D3 推迟，parse_single 调用方式不变）
- **不改** 任何 B1.x/B3.x 冻结模块

---

## 7. 基线快照（用于 B4.3 完成后回归对比）

| 文件 | 行数 | 最近修改 | sha（待 B4.3 完成时记录） |
|------|------|----------|---------------------------|
| `core/url_resolver.py` | 201 | 2026/9/4 13:54 | （基线 commit 17b41db） |
| `TK_Studio_V1_6_4.py` parse_single | L541-597 | 2026/9/4 13:55 | （基线 commit 17b41db） |

B4.3 完成后需验证：
1. `parse_single()` 调用方式不变（`is_short_url` + `resolve_short_url` 两步）
2. B4.2 三项验收测试仍 PASS（回归）
3. 新增 vt.tiktok.com 测试 PASS
4. 冻结模块（B1.x/B3.x/12 个冻结文件）未触碰
