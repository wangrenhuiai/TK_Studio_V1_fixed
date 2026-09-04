# Phase 5-B4.3 设计方案 — TikTok 短链解析增强与稳定性优化

> 阶段：Phase 5-B4.3（设计，待人工批准）
> 基线：[PHASE5_B4_3_BASELINE_REPORT.md](file:///d:/TK_Studio_V1_fixed/PHASE5_B4_3_BASELINE_REPORT.md)
> 前置：B4.2 已验收 PASS（commit `17b41dbd557683bc1a3ef754abf9e1ad4b207a1d`）
> 状态：**只读分析输出，未写任何代码，等待人工批准**

---

## 1. 当前问题（来自 BASELINE 报告 §4）

| # | 问题 | 严重度 | 来源 |
|---|------|--------|------|
| P1 | `vt.tiktok.com/{token}` 短链未支持（移动端分享常用） | 高 | §4.1 |
| P2 | HEAD 抛异常（如 403）时直接返回原 url，丢失 GET 回退机会 | 中 | §4.3 |
| P3 | 无重试机制，单次网络抖动即失败（downloader 已有 Retry，resolver 未对齐） | 中 | §4.3 |
| P4 | 解析结果保留 query 参数（`?_r=1&_t=...`），未标准化为 `https://www.tiktok.com/@user/video/{id}` | 中 | §4.2 |
| P5 | `_cache` 无 TTL/容量上限，长期运行内存只增不减 | 低 | §4.5 |
| P6 | `resolve_urls()` 串行解析，N 个短链最坏 N×timeout 秒 | 中 | §4.5 |
| P7 | 失败原因仅字符串日志，UI 无法区分"网络失败"/"被风控"/"非标准 URL" | 低 | §4.6 |
| P8 | B4.2 三项验收测试未沉淀为持久用例 | 中 | §4.6 |

**推迟项（不在 B4.3 范围）：**
- Cookie 注入（需读 B3.4 snapshot，触碰冻结边界风险高）→ 后续阶段
- `parse_single()` 后台线程化（改 UI 层流程）→ 后续阶段
- UA 轮换（风控对抗，非本阶段目标）→ 后续阶段

---

## 2. 优化方案

### 2.1 P1 — 扩展短链格式（vt.tiktok.com）

**改动**：`_SHORT_URL_PATTERN` 新增第三分支 `vt\.tiktok\.com/([A-Za-z0-9]+)`。

```python
_SHORT_URL_PATTERN = re.compile(
    r'(?:tiktok\.com/t/([A-Za-z0-9]+))'      # /t/{token}
    r'|(?:vm\.tiktok\.com/([A-Za-z0-9]+))'   # vm.tiktok.com/{token}
    r'|(?:vt\.tiktok\.com/([A-Za-z0-9]+))',  # vt.tiktok.com/{token}  ← B4.3 新增
    re.I
)
```

`is_short_url` / `resolve_short_url` 的 token 提取逻辑同步扩展为 `match.group(1) or group(2) or group(3)`。

**风险**：低。纯正则扩展，不影响现有两种格式的匹配。

### 2.2 P2 — HEAD 异常触发 GET 回退

**改动**：将 HEAD 的 try 包在内层，HEAD 抛异常时进 GET 分支，而非整体返回原 url。

```python
final_url = None
# HEAD 尝试（异常不致命，仅记录）
try:
    resp = requests.head(url, headers=_HEADERS, allow_redirects=True, timeout=timeout)
    final_url = resp.url
except requests.RequestException as e:
    _log(log_callback, f"HEAD 失败（{e}），回退 GET")

# GET 回退条件：HEAD 未拿到标准 URL（含 HEAD 异常情况）
if not final_url or not _VIDEO_URL_PATTERN.search(final_url):
    if final_url:
        _log(log_callback, f"HEAD 结果非标准 URL，尝试 GET：{final_url}")
    resp = requests.get(url, headers=_HEADERS, allow_redirects=True,
                        timeout=timeout, stream=True)
    final_url = resp.url
    resp.close()
```

外层仍保留 `Timeout/ConnectionError/Exception` 兜底（GET 也失败才返回原 url）。

**风险**：低。GET 回退本就存在，只是触发条件从"HEAD 结果非标准"扩展为"HEAD 结果非标准 **或** HEAD 异常"。

### 2.3 P3 — urllib3 Retry

**改动**：引入 `requests.Session` + `HTTPAdapter` + `urllib3 Retry`，对齐 [downloader.py L192-200](file:///d:/TK_Studio_V1_fixed/core/downloader.py#L192-L200) 配置。

```python
def _build_session():
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    s = requests.Session()
    retry = Retry(
        total=2, connect=2, read=2, status=2,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update(_HEADERS)
    return s
```

`resolve_short_url` 内 `requests.head/get` 改为 `session.head/get`（session 局部变量，函数结束即释放）。

**风险**：中。Retry 会使最坏耗时翻倍（total=2 → 单短链最坏 3×timeout=30s）。需在 DESIGN 中明确 timeout 与 retry 的关系：**retry 的 read/connect 各 2 次，但受 timeout 约束**，实际最坏耗时 ≈ retry 次数 × timeout，需评估是否调小 timeout（如 10→8）。

### 2.4 P4 — URL 标准化（剥离 query）

**改动**：新增内部函数 `_canonicalize(url)`，解析成功后剥离 query/fragment，输出 `https://www.tiktok.com/@user/video/{id}`。

```python
def _canonicalize(url):
    """剥离 query/fragment，返回标准视频 URL。无法解析则原样返回。"""
    if not url:
        return url
    m = _VIDEO_URL_PATTERN.search(url)
    if not m:
        return url
    return f"https://www.tiktok.com{m.group(0)[len('tiktok.com'):]}"
    # 即 https://www.tiktok.com/@user/video/{id}
```

`resolve_short_url` 在返回前调用 `_canonicalize(final_url)`：
- **写缓存**的是标准化后的 URL（缓存值干净）
- **日志展示**保留原始 resolved（含 query）便于排查
- **返回给调用方**的是标准化 URL（下游 parser 收到干净 URL）

**风险**：低。剥离 query 不影响 parser（parser 从页面 HTML 抽取 video_id，不依赖 URL query）。需回归 B4.2 Test 1 确认标准化后仍含 `/video/`。

### 2.5 P5 — 缓存 TTL + 容量上限

**改动**：`_cache` 改为 `OrderedDict`，每条记录带时间戳；命中时校验 TTL（默认 3600s），超时剔除；新增容量上限（默认 1000，LRU 淘汰）。

```python
from collections import OrderedDict
_CACHE_TTL = 3600       # 秒
_CACHE_MAX = 1000

_cache = OrderedDict()  # token -> (resolved_url, timestamp)

def _cache_get(token):
    if token not in _cache:
        return None
    resolved, ts = _cache[token]
    if time.time() - ts > _CACHE_TTL:
        del _cache[token]
        return None
    _cache.move_to_end(token)  # LRU
    return resolved

def _cache_put(token, resolved):
    _cache[token] = (resolved, time.time())
    _cache.move_to_end(token)
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
```

**风险**：低。纯内部实现，公开接口 `clear_cache()` 不变。

### 2.6 P6 — resolve_urls 并发

**改动**：`resolve_urls()` 改用 `ThreadPoolExecutor(max_workers=4)` 并发。

```python
from concurrent.futures import ThreadPoolExecutor

def resolve_urls(urls, log_callback=None, timeout=10, max_workers=4):
    results = [None] * len(urls)
    def _worker(idx, url):
        # ... 原 resolve_short_url 逻辑 ...
        results[idx] = {...}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_worker, i, u) for i, u in enumerate(urls)]
        for f in futures:
            f.result()  # 等待全部完成
    return results
```

**注意**：
- `log_callback` 在多线程并发调用，调用方需保证线程安全（`parse_single` 中 `self.single_log.append` 是 QTextEdit，Qt 要求主线程更新，**当前 parse_single 在主线程同步调用 resolve_short_url，无并发问题**；但 `resolve_urls` 并发后 log_callback 会被多线程触发）。
- **B4.3 不改 parse_single 调用方式**，parse_single 仍用 `resolve_short_url`（单 URL 串行），`resolve_urls` 并发仅对未来的批量调用点有用。
- 为避免 log_callback 线程安全问题，**`resolve_urls` 并发时 log_callback 默认不传给子任务**，仅在主线程聚合后输出汇总日志。

**风险**：中。并发引入线程安全考量，但 B4.3 不动 parse_single，实际无并发调用点，风险可控。

### 2.7 P7 — 失败原因 enum（轻量版）

**改动**：新增 `resolve_short_url_ex(url, log_callback=None, timeout=10) -> dict`，返回 `{resolved, success, reason}`。

```python
REASON_OK = "ok"
REASON_NOT_SHORT = "not_short"
REASON_NETWORK_TIMEOUT = "network_timeout"
REASON_CONNECTION_ERROR = "connection_error"
REASON_BLOCKED = "blocked"          # 重定向到非视频页（疑似风控/captcha）
REASON_NON_VIDEO_URL = "non_video_url"
REASON_UNKNOWN = "unknown"

def resolve_short_url_ex(url, log_callback=None, timeout=10):
    # ... 同 resolve_short_url，但各分支记录 reason ...
    return {"resolved": ..., "success": ..., "reason": ...}
```

`resolve_short_url` 保留原签名（str 返回），内部委托 `resolve_short_url_ex` 取 `resolved` 字段，**B4.2 调用方零改动**。

**风险**：低。纯新增函数，不改旧签名。

### 2.8 P8 — 测试沉淀

**改动**：新增 `tests/test_url_resolver.py`，包含：
- B4.2 三项验收测试（用 mock 网络层，避免实网依赖导致 CI 抖动）
- vt.tiktok.com 检测测试（P1）
- HEAD 异常触发 GET 回退测试（P2）
- Retry 配置测试（P3，mock 验证 session.mount）
- URL 标准化测试（P4，输入含 query 的 resolved，验证输出剥离 query）
- 缓存 TTL/LRU 测试（P5）
- resolve_urls 并发测试（P6，mock 验证 ThreadPoolExecutor 调用）
- resolve_short_url_ex reason 测试（P7）

使用 `unittest.mock.patch` mock `requests.head/get`，零实网依赖。

**风险**：低。纯新增测试文件。

---

## 3. 修改文件列表

| 文件 | 类型 | 改动范围 | 是否触碰冻结 |
|------|------|----------|--------------|
| `core/url_resolver.py` | 修改 | P1-P7 全部（B4.2 已冻结，B4.3 作为新阶段可改） | 否（B4.2 非永久冻结，是阶段基线） |
| `tests/test_url_resolver.py` | 新增 | P8 测试沉淀 | 否 |
| `TK_Studio_V1_6_4.py` | **不改** | — | —（D3 后台化推迟） |
| 12 个冻结模块 | **不改** | — | — |
| B3.4 `core/profile_snapshot.py` | **不改** | — | —（B3 Cookie 注入推迟） |

**预期 diff 规模**：`url_resolver.py` +~150 行（P1-P7），`test_url_resolver.py` +~200 行。

---

## 4. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| P3 Retry 导致最坏耗时翻倍（30s/短链） | 中 | UI 卡顿（parse_single 主线程） | timeout 保持 10s，retry total=2；B4.3 不动 parse_single，单作品场景影响小；批量短链场景推迟到 D3 后台化 |
| P4 标准化误剥有用 query | 低 | parser 解析失败 | parser 从 HTML 抽取 video_id，不依赖 URL query；回归 B4.2 Test 1 确认 |
| P6 并发 log_callback 线程不安全 | 中 | Qt 崩溃 | `resolve_urls` 并发时不传 log_callback 给子任务，仅主线程聚合日志；B4.3 无并发调用点 |
| P1 vt.tiktok.com 实际不可达 | 低 | 测试无法实网验证 | 用 mock 测试格式检测；实网验证作为人工验收项 |
| P2 GET 回退放大请求量 | 低 | 被风控概率上升 | 仅 HEAD 异常时触发，正常路径仍是 HEAD 优先 |
| P5 TTL 过期导致重复请求 | 低 | 性能轻微下降 | TTL 3600s 足够长，单次会话内基本命中 |

**整体风险等级**：中低。核心改动集中在 `url_resolver.py` 单文件，不改 UI 调用方式，不改冻结模块，有完整测试覆盖。

---

## 5. 是否需要新增测试

**需要。** 新增 `tests/test_url_resolver.py`，覆盖：

| 测试用例 | 对应优化项 | 类型 |
|----------|-----------|------|
| `test_is_short_url_vt` | P1 | 单元（mock） |
| `test_is_short_url_vm_www` | P1 回归 | 单元 |
| `test_resolve_short_url_head_exception_triggers_get` | P2 | 单元（mock requests.head 抛异常） |
| `test_resolve_short_url_retry_on_429` | P3 | 单元（mock 429→200） |
| `test_canonicalize_strips_query` | P4 | 单元 |
| `test_cache_ttl_expiry` | P5 | 单元（mock time） |
| `test_cache_lru_eviction` | P5 | 单元 |
| `test_resolve_urls_concurrent` | P6 | 单元（mock，验证并发） |
| `test_resolve_short_url_ex_reason_blocked` | P7 | 单元（mock 重定向到 captcha） |
| `test_resolve_short_url_ex_reason_timeout` | P7 | 单元（mock Timeout） |
| B4.2 回归：Test1/2/3 | 全部 | 集成（mock，不依赖实网） |

**不新增**：UI 层测试（B4.3 不改 UI）。

---

## 6. 验收标准（B4.3 实施后）

1. `python -m py_compile core/url_resolver.py` exit 0
2. `from core.url_resolver import resolve_short_url, is_short_url, resolve_urls, resolve_short_url_ex` IMPORT_OK
3. `tests/test_url_resolver.py` 全部 PASS（含 mock 测试）
4. B4.2 三项验收测试回归 PASS（用实网或 mock）
5. 新增 vt.tiktok.com 检测 PASS
6. 冻结边界：12 个冻结模块 + B3.4 profile_snapshot + TK_Studio_V1_6_4.py parse_single 调用方式未变
7. `parse_single()` 调用方式不变（仍是 `is_short_url` + `resolve_short_url` 两步，不改 UI 流程）

---

## 7. 实施顺序建议（待批准后执行）

1. P1 vt.tiktok.com 扩展 → 跑 B4.2 回归
2. P2 HEAD 异常 GET 回退 → 单测
3. P3 urllib3 Retry → 单测
4. P4 URL 标准化 → B4.2 Test 1 回归
5. P5 缓存 TTL/LRU → 单测
6. P6 resolve_urls 并发 → 单测
7. P7 resolve_short_url_ex → 单测
8. P8 tests/test_url_resolver.py 沉淀
9. 全量回归 + 冻结边界检查
10. 输出 `PHASE5_B4_3_IMPLEMENTATION_REPORT.md`

每步完成后跑 py_compile + 相关单测，逐步推进。

---

## 8. 待人工批准的决策点

| 决策点 | 推荐方案 | 备选 | 需用户确认 |
|--------|---------|------|-----------|
| P3 Retry timeout | timeout=10, retry total=2（最坏 30s/短链） | timeout=8, retry total=1（最坏 16s） | ☐ |
| P4 标准化是否剥 query | 剥离（下游 parser 不依赖 query） | 保留 query，仅日志展示标准化 | ☐ |
| P6 resolve_urls 并发是否纳入 | 纳入（max_workers=4，B4.3 无调用点但为未来铺路） | 推迟（B4.3 仅做串行优化） | ☐ |
| P7 resolve_short_url_ex 是否纳入 | 纳入（轻量，为 UI 区分失败原因铺路） | 推迟 | ☐ |
| P8 测试用 mock 还是实网 | mock（CI 稳定）+ 实网人工验收 | 仅实网 | ☐ |

---

**本设计方案未修改任何代码，等待人工批准后进入 B4.3 实施阶段。**
