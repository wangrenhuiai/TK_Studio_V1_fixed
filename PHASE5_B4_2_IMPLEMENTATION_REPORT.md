# Phase 5-B4.2 实施报告 — TikTok 短链 URL Resolver

> 阶段：Phase 5-B4.2（实施）
> 基线 commit：`17b41dbd557683bc1a3ef754abf9e1ad4b207a1d`
> 日期：2026-09-04
> 状态：**待验收**（不进入 B4.3）

---

## 1. 修改文件列表

| 文件 | 类型 | 说明 |
|------|------|------|
| `core/url_resolver.py` | 新增 | TikTok 短链解析器（纯 stdlib + requests，不依赖 PySide6） |
| `TK_Studio_V1_6_4.py` | 修改 | `parse_single()` 集成短链解析；新增 import |

### 1.1 新增：`core/url_resolver.py`

公开接口（`__all__`）：

| 函数 | 签名 | 说明 |
|------|------|------|
| `is_short_url` | `is_short_url(url) -> bool` | 检测 `/t/{token}` 与 `vm.tiktok.com/{token}` 两种短链格式 |
| `resolve_short_url` | `resolve_short_url(url, log_callback=None, timeout=10) -> str` | 非短链原样返回；短链经 `requests.head(allow_redirects=True)` 跟随重定向，返回 `response.url`；HEAD 结果非标准 URL 时回退 GET（stream）；失败返回原 URL |
| `resolve_urls` | `resolve_urls(urls, log_callback=None, timeout=10) -> list[dict]` | 批量接口，返回 `{original, resolved, changed, success}` |
| `clear_cache` | `clear_cache() -> None` | 清空短链 token → 解析 URL 缓存 |

安全处理（对应设计第 3 项）：
- 不抛异常到 UI：所有网络路径 `try/except`，捕获 `Timeout` / `ConnectionError` / `Exception`
- 网络失败返回原 URL
- `timeout` 可控（默认 10s）
- 内置 `User-Agent`（与 `tiktok_service.py` 一致，避免 WAF 拦截）
- 保留 `log_callback` 支持，经 `_log()` 安全调用（回调异常被吞掉）

### 1.2 修改：`TK_Studio_V1_6_4.py`

- **L20** 新增 import：
  ```python
  from core.url_resolver import resolve_short_url, is_short_url
  ```
- **L541 `parse_single()`** 流程调整，URL 输入后先调用 `url_resolver`：

  ```
  URL 输入
    ↓ is_short_url(url) → resolve_short_url(url, log_callback=self.single_log.append)
  短链转换
    ↓
  检查 tiktok.com  →  检查 /video/  →  ParseWorker
  ```

  转换成功日志（`L563-568`）：
  ```
  🔗 TikTok短链解析:
  原始:
  {url}
  解析:
  {resolved}
  ```
  转换失败日志（`L570`）：
  ```
  ⚠️ TikTok短链解析失败，保留原URL
  ```

  仅当 `resolved != url and "/video/" in resolved.lower()` 时视为转换成功并替换 `url`，否则保留原 URL 继续走后续校验。

---

## 2. 冻结边界确认

### 2.1 禁止修改的模块（B4.2 是否触碰）

| 冻结模块 | B4.2 是否修改 | 修改时间（最近） |
|----------|---------------|------------------|
| `core/parser.py` | 否 | 2026/9/3 11:42 |
| `core/tiktok_service.py` | 否 | 2026/9/3 13:28 |
| `core/home_fetcher.py` | 否（B2.x 基线，非 B4.2） | 2026/9/4 12:45 |
| `core/tiktok_home_service.py` | 否 | 2026/9/4 12:45 |
| `core/tiktok_home_worker.py` | 否 | 2026/9/4 12:46 |
| `core/home_worker.py` | 否 | 2026/9/4 12:46 |
| `workers/home_fetch_worker.py` | 否 | 2026/9/4 12:46 |
| `core/downloader.py` | 否 | 2026/9/3 16:20 |
| `core/db.py` | 否 | 2026/9/3 23:49 |
| `workers/task_manager.py` | 否（B1.x 基线，非 B4.2） | 2026/9/4 02:46 |
| `core/tiktok_login.py` | 否 | 2026/9/4 02:28 |
| `workers/login_worker.py` | 否 | 2026/9/3 18:57 |

B4.2 实际修改文件时间窗：`core/url_resolver.py` 13:54:53、`TK_Studio_V1_6_4.py` 13:55:24。所有冻结模块最近修改时间均早于该窗口，**未触碰冻结边界**。

### 2.2 禁止改变的机制（B4.2 是否影响）

| 机制 | 是否保持 |
|------|----------|
| B3.4 登录 snapshot（`core/profile_snapshot.py` + `_on_login_worker_finished`） | 是，未触碰 |
| B3.1 `profile_dir` 参数 | 是，未触碰 |
| M1-M5 登录 UI | 是，未触碰 |
| ParseWorker / TaskManager 调用链 | 是，`parse_single()` 末尾仍 `ParseWorker(valid_urls, self.db)`，仅 `valid_urls` 来源经过短链解析 |
| works 表结构 / Signal 接口 | 是，未触碰 |

---

## 3. 测试结果

### 3.1 静态检查

| 检查 | 命令 | 结果 |
|------|------|------|
| py_compile | `python -m py_compile core/url_resolver.py` | exit 0 |
| py_compile | `python -m py_compile TK_Studio_V1_6_4.py` | exit 0 |
| import | `from core.url_resolver import resolve_short_url` | IMPORT_OK |

### 3.2 单元测试

| # | 输入 | 预期 | 实际 | 结果 |
|---|------|------|------|------|
| 1 | `https://www.tiktok.com/t/ZTUNyfkNF/` | 返回含 `/video/` 的标准 URL | `https://www.tiktok.com/@rfbxha/video/7681265056633326878?_r=1&_t=ZT-99RX3SOusFJ` | **PASS** |
| 2 | `https://www.tiktok.com/@test/video/123456789` | 保持不变 | 原样返回 | **PASS** |
| 3 | 非法 URL（`""`/`None`/`"not a url"`/`"ftp://..."`/`"https://example.com/t/abc"`/`12345`/`"javascript:alert(1)"`） | 不崩溃 | 全部原样返回，无异常 | **PASS** |

附加冒烟：`resolve_urls([std, short, "garbage"])` 返回 3 个 dict，`changed`/`success` 字段正确（短链 `changed=True, success=True`，其余 `False`）。**PASS**。

> 注：测试 1 依赖 TikTok 实网重定向，token `ZTUNyfkNF` 当前可正常解析为 `@rfbxha` 的视频。该 token 后续可能失效，属正常网络行为，不影响解析器逻辑正确性（失效时按设计返回原 URL）。

---

## 4. 下一阶段建议

1. **B4.3（等待验收后启动）**：可在 `parse_single()` 之外扩展短链解析覆盖面，例如 `start_home_fetch()` 的主页 URL 输入框、批量任务录入路径，使短链支持全局一致。建议复用 `resolve_urls()` 批量接口，避免重复实现。
2. **缓存生命周期**：当前 `_cache` 为进程内 dict，无 TTL。长期运行可考虑加容量上限或基于时间的失效，避免无限增长（当前 token 数量有限，风险低）。
3. **HEAD → GET 回退成本**：部分 TikTok 边缘节点对 HEAD 返回非标准 URL，触发 GET 回退。若线上观察到大量回退，可评估直接用 GET（stream + 立即 close）以减少一次往返。
4. **回归测试基线**：建议将本次 3 个单测沉淀为 `tests/test_url_resolver.py` 持久用例（含 mock 网络层），纳入 phase-based 回归集，避免实网依赖导致 CI 抖动。
5. **不进入 B4.3**：按指令在此停止，等待 B4.2 验收。

---

## 5. 回滚方案

- 删除新增文件 `core/url_resolver.py`
- 还原 `TK_Studio_V1_6_4.py` 至基线 commit `17b41db`：
  ```
  git checkout 17b41dbd557683bc1a3ef754abf9e1ad4b207a1d -- TK_Studio_V1_6_4.py
  ```
回滚后 `parse_single()` 恢复为“URL → 检查 tiktok.com → 检查 /video/ → ParseWorker”原流程，无短链解析能力，不影响其它 B 阶段冻结基线。
