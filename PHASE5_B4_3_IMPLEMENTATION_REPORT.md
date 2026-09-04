# Phase 5-B4.3 实施报告 — TikTok 短链解析增强与稳定性优化

> 阶段：Phase 5-B4.3（实施）
> 基线：B4.2 验收 PASS（commit `17b41dbd557683bc1a3ef754abf9e1ad4b207a1d`）
> 设计：[PHASE5_B4_3_DESIGN.md](file:///d:/TK_Studio_V1_fixed/PHASE5_B4_3_DESIGN.md)
> 实施时间：2026-09-04
> 状态：**待验收**（不进入 B4.4）

---

## 1. 修改文件

| 文件 | 类型 | 说明 |
|------|------|------|
| [core/url_resolver.py](file:///d:/TK_Studio_V1_fixed/core/url_resolver.py) | 修改 | P1-P5 核心增强（B4.2 基线 → B4.3） |
| [tests/test_url_resolver.py](file:///d:/TK_Studio_V1_fixed/tests/test_url_resolver.py) | 新增 | 基础测试套件（24 项 mock 测试） |

**未修改文件**（冻结边界完整）：
- `TK_Studio_V1_6_4.py` — parse_single 调用方式不变
- 12 个冻结模块 + B3.4 `core/profile_snapshot.py` — 全部未触碰

---

## 2. 新增能力

### P1 — 短链格式扩展（4 种）

[core/url_resolver.py `_SHORT_URL_PATTERN`](file:///d:/TK_Studio_V1_fixed/core/url_resolver.py#L38-L45) 新增两个分支：

| 格式 | 示例 | 状态 |
|------|------|------|
| `www.tiktok.com/t/{token}` | `https://www.tiktok.com/t/ZTUNyfkNF/` | B4.2 已有 |
| `www.tiktok.com/tiktok/t/{token}` | `https://www.tiktok.com/tiktok/t/ZTUNyfkNF/` | **B4.3 新增** |
| `vm.tiktok.com/{token}` | `https://vm.tiktok.com/ZTUNyfkNF/` | B4.2 已有 |
| `vt.tiktok.com/{token}` | `https://vt.tiktok.com/ZTUNyfkNF/` | **B4.3 新增** |

`is_short_url(url)` API 签名不变，自动支持 4 种格式。token 提取扩展为 `group(1) or group(2) or group(3) or group(4)`。

### P2 — HEAD + GET fallback

[resolve_short_url()](file:///d:/TK_Studio_V1_fixed/core/url_resolver.py#L96-L160) 流程：

```
HEAD 请求（跟随重定向）
  ├─ 成功 + 标准视频 URL → 标准化 + 缓存 + 返回
  ├─ 成功 + 非 video URL → GET fallback
  └─ 异常（Timeout/ConnectionError/任意 Exception）→ GET fallback
GET 请求（stream，不下载 body）
  ├─ 成功 + 标准视频 URL → 标准化 + 缓存 + 返回
  └─ 失败/非 video URL → 返回原 URL
```

**B4.2 → B4.3 改进**：B4.2 中 HEAD 抛异常直接返回原 URL（丢失 GET 机会）；B4.3 中 HEAD 异常也触发 GET fallback（[`_try_head`](file:///d:/TK_Studio_V1_fixed/core/url_resolver.py#L223-L233) 返回 None → 进入 GET 路径）。

### P3 — urllib3 Retry

[_build_session()](file:///d:/TK_Studio_V1_fixed/core/url_resolver.py#L205-L226) 构建 `requests.Session` + `HTTPAdapter` + `Retry`：

```python
Retry(
    total=2, connect=2, read=2, status=2,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "HEAD"]),
    raise_on_status=False,
)
```

配置与 [downloader.py L192-200](file:///d:/TK_Studio_V1_fixed/core/downloader.py#L192-L200) 对齐。每次 `resolve_short_url` 调用构建独立 session（线程安全，无共享状态）。

### P4 — URL 标准化

[normalize_video_url()](file:///d:/TK_Studio_V1_fixed/core/url_resolver.py#L75-L87) 新增公开函数：

```python
>>> normalize_video_url("https://www.tiktok.com/@u/video/123?_r=1&_t=abc")
'https://www.tiktok.com/@u/video/123'
```

- 剥离 query / fragment
- 统一输出 `https://www.tiktok.com/@user/video/{id}`
- [`_finalize_success()`](file:///d:/TK_Studio_V1_fixed/core/url_resolver.py#L262-L270) 在返回前调用标准化，缓存写入的也是标准化后的 URL

### P5 — TTL + LRU 缓存（线程安全）

| 配置 | 值 |
|------|-----|
| TTL | 300 秒 |
| 最大条目 | 256 |
| 数据结构 | `OrderedDict`（token → (url, timestamp)） |
| 线程安全 | `threading.Lock` 保护 `_cache_get` / `_cache_put` |

[`_cache_get()`](file:///d:/TK_Studio_V1_fixed/core/url_resolver.py#L272-L285)：命中时校验 TTL，过期自动删除；LRU `move_to_end`。
[`_cache_put()`](file:///d:/TK_Studio_V1_fixed/core/url_resolver.py#L288-L295)：写入后 LRU 淘汰（`popitem(last=False)`）。

### 暂缓项（B4.3 不含）

| 项 | 说明 | 后续 |
|----|------|------|
| P6 | `resolve_urls()` ThreadPoolExecutor 并发 | 当前保持串行，后续阶段 |
| P7 | `resolve_short_url_ex()` 结构化返回 | 旧接口 `resolve_short_url()` 不变 |
| P8 | 完整测试套件 | 已创建基础版 24 项，后续扩展 |

---

## 3. API 兼容确认

| API | B4.2 签名 | B4.3 签名 | 兼容 |
|-----|-----------|-----------|------|
| `is_short_url(url)` | `-> bool` | `-> bool`（支持 4 格式） | ✅ |
| `resolve_short_url(url, log_callback=None, timeout=10)` | `-> str` | `-> str`（内部 HEAD+GET+Retry+normalize） | ✅ |
| `resolve_urls(urls, log_callback=None, timeout=10)` | `-> list[dict]` | `-> list[dict]`（串行，未加 max_workers） | ✅ |
| `clear_cache()` | `-> None` | `-> None` | ✅ |
| `normalize_video_url(url)` | — | `-> str`（新增） | 新增 |

**parse_single() 调用方式零改动**：[TK_Studio_V1_6_4.py L558-570](file:///d:/TK_Studio_V1_fixed/TK_Studio_V1_6_4.py#L558-L570) 仍为 `is_short_url(url)` + `resolve_short_url(url, log_callback=...)` 两步，未修改。

**行为变化**（P4 标准化）：`resolve_short_url` 返回值从 B4.2 的含 query URL（如 `...video/123?_r=1&_t=...`）变为标准化 URL（`...video/123`）。`parse_single` 用 `"/video/" in resolved.lower()` 判断，标准化后仍含 `/video/`，**不影响下游**。

---

## 4. 测试结果

### 4.1 静态检查

| 检查 | 命令 | 结果 |
|------|------|------|
| py_compile | `python -m py_compile core/url_resolver.py` | exit 0 ✅ |
| import | `python -c "from core.url_resolver import resolve_short_url"` | IMPORT_OK ✅ |

### 4.2 pytest 结果

```
24 passed in 0.31s
```

| 测试类 | 用例数 | 覆盖项 | 结果 |
|--------|--------|--------|------|
| TestIsShortUrl | 6 | P1（vm/vt/t/tiktok-t/ + 非法） | 6/6 PASS |
| TestResolveShortUrl | 7 | P2（HEAD redirect / GET fallback×2 / timeout / non-video / 非法 / 标准 URL） | 7/7 PASS |
| TestNormalizeVideoUrl | 4 | P4（剥离 query/fragment / 无 query / 非 video） | 4/4 PASS |
| TestCache | 4 | P5（缓存命中 / TTL 过期 / LRU 淘汰 / clear） | 4/4 PASS |
| TestResolveUrls | 3 | 批量（空列表 / 混合输入 / 全超时） | 3/3 PASS |

全部使用 `unittest.mock.patch("core.url_resolver._build_session")` mock 网络层，**零真实 TikTok 网络依赖**。

---

## 5. 冻结边界确认

### 5.1 B4.3 修改文件时间窗

B4.3 实际修改时间窗：`2026/9/4 14:34:00` ~ `14:35:19`（`url_resolver.py` + `test_url_resolver.py`）。

### 5.2 冻结模块状态

| 冻结模块 | 最近修改时间 | B4.3 是否触碰 |
|----------|-------------|---------------|
| `TK_Studio_V1_6_4.py` | 2026/9/4 13:55（B4.2） | 否 ✅ |
| `core/parser.py` | 2026/9/3 11:42 | 否 ✅ |
| `core/tiktok_service.py` | 2026/9/3 13:28 | 否 ✅ |
| `core/downloader.py` | 2026/9/3 16:20 | 否 ✅ |
| `core/db.py` | 2026/9/3 23:49 | 否 ✅ |
| `core/tiktok_login.py` | 2026/9/4 02:28 | 否 ✅ |
| `workers/login_worker.py` | 2026/9/3 18:57 | 否 ✅ |
| `workers/task_manager.py` | 2026/9/4 02:46（B1.x） | 否 ✅ |
| `core/home_fetcher.py` | 2026/9/4 12:45（B2.x） | 否 ✅ |
| `core/profile_snapshot.py`（B3.4） | 2026/9/4 13:16 | 否 ✅ |
| 其它 B1.x 模块（tiktok_home_*/home_worker/home_fetch_worker） | 2026/9/4 12:45-12:46 | 否 ✅ |

### 5.3 禁止改变的机制

| 机制 | 是否保持 |
|------|----------|
| B3.4 登录 snapshot | ✅ |
| B3.1 `profile_dir` 参数 | ✅ |
| M1-M5 登录 UI | ✅ |
| parse_single 调用方式 | ✅（`is_short_url` + `resolve_short_url` 两步不变） |
| works 表结构 / Signal 接口 | ✅ |

**冻结边界结论：** B4.3 仅改动 `core/url_resolver.py` + `tests/test_url_resolver.py`，未触碰任何冻结模块或机制。

---

## 6. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| P3 Retry 导致最坏耗时翻倍（HEAD+GET 各 3 次尝试，最坏 ~60s/短链） | 中 | parse_single 主线程阻塞 | 单作品场景影响小；批量短链场景推迟到 P6 并发/P7 后台化 |
| P4 标准化误剥有用 query | 低 | parser 解析失败 | parser 从 HTML 抽取 video_id，不依赖 URL query；24 项测试验证标准化后仍含 `/video/` |
| P5 TTL 过期导致重复请求 | 低 | 性能轻微下降 | TTL 300s 足够覆盖单次会话；缓存命中测试验证 |
| HEAD 异常 + GET fallback 放大请求量 | 低 | 被风控概率上升 | 仅 HEAD 异常时触发 GET；正常路径 HEAD 优先 |
| urllib3 Retry 与 requests 版本兼容性 | 低 | import 失败 | `_build_session` 内 try/except 兼容 `urllib3.util.retry` 和 `urllib3.util` 两种 import 路径 |

**整体风险**：中低。改动集中在 `url_resolver.py` 单文件，不改 UI 调用方式，不改冻结模块，24 项 mock 测试覆盖。

---

## 7. 后续建议

1. **P6 并发**：`resolve_urls()` 改为 ThreadPoolExecutor，需评估 log_callback 线程安全（Qt 主线程限制）
2. **P7 结构化返回**：`resolve_short_url_ex()` 返回 `{resolved, success, error}`，便于 UI 区分"网络失败"/"被风控"
3. **P8 完整测试**：扩展 `tests/test_url_resolver.py`，增加 captcha 检测、Retry 行为、并发等用例
4. **parse_single 后台化**：将短链解析移入后台线程，避免批量短链卡 UI（需改 TK_Studio_V1_6_4.py，属 UI 层改动）
5. **Cookie 注入**：复用 B3.4 `chrome_home_auth_profile` 的 Cookie 提升风控场景解析率（需触碰 B3.4 边界，谨慎）

---

## 8. 回滚方案

```bash
# 还原 url_resolver.py 至 B4.2 版本
git checkout 17b41dbd557683bc1a3ef754abf9e1ad4b207a1d -- core/url_resolver.py
# 删除测试文件
rm tests/test_url_resolver.py
```

回滚后恢复 B4.2 基线（2 格式 / HEAD-only fallback / 无 Retry / 无标准化 / 无 TTL 缓存），不影响其它 B 阶段冻结基线。

---

按指令**不进入 Phase 5-B4.4**，等待人工验收。
