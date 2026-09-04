# Phase 7-F 实施报告：统一 Chrome Profile + 登录态正式接入

> 阶段：Phase 7-F Implementation
> 基线：Phase 7-B.2 freeze @ commit 9df18f4
> 实施时间：2026-09-04 (+08:00)
> 声明：未 commit，等待人工 review

---

## 1. 修改文件列表

### 生产代码（修改）

| 文件 | 修改内容 | 行数变化 |
|------|----------|----------|
| `core/chrome_bridge.py` | `chrome_render_with_cookies()` profile 从 `chrome_cdp_profile` 改为 `chrome_login_profile`；更新模块文档 | +12 -5 |
| `core/tiktok_service_ex.py` | Chrome fallback 从 `load_with_chrome()` 改为 `chrome_render_with_cookies()`；解析成功后写 `cookie_cache` | +28 -12 |
| `core/downloader.py` | `run_download()` 首次请求前从 `cookie_cache.get_cookie()` 取 cookies | +5 -1 |
| `TK_Studio_V1_6_4.py` | `_is_logged_in` 标志 + Parse/Download 前登录态门控 + 登出清 cookie_cache | +32 -0 |

### 生产代码（新增）

| 文件 | 用途 | 行数 |
|------|------|------|
| `core/cookie_cache.py` | 纯内存 cookie 缓存（线程安全 + TTL），parse→download 传递 cookies | ~65 |

### 测试（修改）

| 文件 | 修改原因 |
|------|----------|
| `tests/test_phase7b2_duplicate_request.py` | mock 从 `load_with_chrome` 改为 `chrome_render_with_cookies`；return_value 改为 tuple |
| `tests/test_phase7a_final_acceptance.py` | 同上 |
| `tests/test_tiktok_service_ex.py` | 同上 |

### 测试（新增）

| 文件 | 测试数 | 验证内容 |
|------|--------|----------|
| `tests/test_cookie_cache.py` | 8 | set/get/TTL/clear/线程安全/副本隔离 |
| `tests/test_phase7f_unified_profile.py` | 6 | login_profile 路径/CDP fallback/cookie_cache 写入/无 video_url 不写缓存/单 GET 约束/downloader 取缓存 |

### 未修改（冻结保持）

| 文件 | 原因 |
|------|------|
| `core/tiktok_login.py` | A.4 冻结 |
| `workers/login_worker.py` | A.4 冻结 |
| `core/parser.py` | 冻结 |
| `core/tiktok_service.py` | Phase 7-B.2 冻结 |
| `core/db.py` | DB 结构不变 |
| `workers/parse_worker.py` | parse_url_ex 内部已处理缓存，Worker 无需改 |
| `workers/download_worker.py` | run_download 内部已处理缓存，Worker 无需改 |
| `core/profile_snapshot.py` | 本方案直接用 chrome_login_profile，不依赖快照 |

---

## 2. 架构变化

### 修改前

```
Parse fallback: load_with_chrome(--dump-dom, chrome_headless_profile, 无 cookies)
Refresh:        chrome_render_with_cookies(CDP, chrome_cdp_profile, 有 cookies 但匿名)
→ Parse 与 Refresh 使用不同 Profile + Parse 无 cookies → CDN 403
```

### 修改后

```
Parse fallback: chrome_render_with_cookies(CDP, chrome_login_profile, 有 cookies 已登录)
Refresh:        chrome_render_with_cookies(CDP, chrome_login_profile, 有 cookies 已登录)
→ Parse 与 Refresh 使用同一已登录 Profile + cookies 传递给 download → HTTP 200
```

### 核心变化

1. **Profile 统一**：`chrome_cdp_profile`（匿名）→ `chrome_login_profile`（已登录态）
2. **Parse 方式升级**：`load_with_chrome(--dump-dom)` → `chrome_render_with_cookies(CDP)`
   - --dump-dom 仅输出 DOM 文本，不获取 cookies
   - CDP 同时获取 HTML + cookies（Network.getAllCookies）
3. **Cookie 链路贯通**：parse → cookie_cache（内存）→ download 首次请求
4. **登录态门控**：Parse/Download 前检查 `_is_logged_in`，未登录提示

---

## 3. Cookie 生命周期

```
┌─ Parse 阶段（ParseWorker 线程）──────────────────────────┐
│                                                            │
│  chrome_render_with_cookies(url)                           │
│    ↓ CDP Network.getAllCookies                             │
│  cookie_items = [{name, value, domain}, ...]              │
│    ↓                                                       │
│  cookie_cache.set_cookie(video_id, cookie_items)          │
│    ↓ 存入内存 dict（threading.Lock 保护）                   │
│  [不打印 / 不日志 / 不写文件 / 不写 DB]                      │
│                                                            │
└────────────────────────────────────────────────────────────┘
                           ↓
┌─ Download 阶段（DownloadWorker 线程）─────────────────────┐
│                                                            │
│  cookie_cache.get_cookie(video_id)                        │
│    ↓ TTL 未过期 → 返回 cookie_items                        │
│    ↓ TTL 过期 / 不存在 → 返回 []（走 refresh fallback）      │
│  download_once(url, ..., cookie_items)                    │
│    ↓ 注入 Cookie header + session.cookies                  │
│  [cookies 仅在内存使用，download 完成后不主动清除]            │
│                                                            │
└────────────────────────────────────────────────────────────┘
                           ↓
┌─ 登出（主线程）───────────────────────────────────────────┐
│                                                            │
│  on_logout_clicked()                                       │
│    ↓ cookie_cache.clear_all()                             │
│  [内存中所有 cookies 立即清除]                              │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### Cookie 安全保证

| 规则 | 实现 |
|------|------|
| 纯内存 | `cookie_cache` 使用 Python dict，进程退出即丢失 |
| 不写 DB | DB 结构不变（works 表无 cookie 字段） |
| 不写文件 | 无任何文件 I/O |
| 不日志输出 | `set_cookie` / `get_cookie` 无 log_callback |
| 不打印 | 无 print 语句 |
| TTL 过期 | 默认 600s，过期自动清理 |
| 登出清除 | `clear_all()` 清除全部 |

---

## 4. Profile 生命周期

```
┌─ 首次登录 ────────────────────────────────────────────────┐
│                                                            │
│  on_login_clicked() → LoginWorker                         │
│    ↓ 可见 Chrome + chrome_login_profile                    │
│    ↓ 用户扫码                                               │
│    ↓ sessionid 等 cookies 持久化到 Profile 目录             │
│  LoginWorker.finished → chrome 关闭，释放 Profile 锁         │
│                                                            │
└────────────────────────────────────────────────────────────┘
                           ↓
┌─ Parse（CDP headless）─────────────────────────────────────┐
│                                                            │
│  parse_url_ex() → chrome_render_with_cookies(url)         │
│    ↓ headless Chrome + chrome_login_profile（复用登录态）   │
│    ↓ CDP: Page.navigate + Network.getAllCookies            │
│    ↓ 获取 HTML + cookies（来自已登录 session）              │
│    ↓ Chrome 关闭，释放 Profile 锁                            │
│                                                            │
└────────────────────────────────────────────────────────────┘
                           ↓
┌─ Download（requests HTTP）─────────────────────────────────┐
│                                                            │
│  run_download() → cookie_cache.get_cookie()                │
│    ↓ 注入 cookies 到 requests Session                       │
│    ↓ session.get(video_url) → HTTP 200                     │
│    ↓ [若 403] refresh_video_url() → 同一 chrome_login_profile│
│    ↓ 新 cookies + 新 video_url → 重试                       │
│                                                            │
└────────────────────────────────────────────────────────────┘
                           ↓
┌─ 登出 ─────────────────────────────────────────────────────┐
│                                                            │
│  on_logout_clicked() → TikTokLogin.logout()                │
│    ↓ 删除 chrome_login_profile 目录                         │
│    ↓ cookie_cache.clear_all()                              │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### Profile 锁冲突缓解

| 场景 | 处理 |
|------|------|
| LoginWorker 运行中 + 用户点 Parse | `_validate_and_parse` 检查 `_is_logged_in`；登录中标志可能未设置 → 提示登录 |
| LoginWorker 运行中 + 用户点 Download | `_start_download_worker` 检查 `_is_logged_in` → 阻止 |
| Parse CDP + Download refresh 同时 | Download 的 refresh 在 DownloadWorker 线程；Parse 的 CDP 在 ParseWorker 线程；两者用同一 Profile 但时序不重叠（Parse 先完成入库，Download 后启动） |

---

## 5. 测试结果

### pytest

```
123 passed in 1.78s
```

| 测试文件 | 测试数 | 状态 |
|----------|--------|------|
| test_cookie_cache.py | 8 | ✅ PASS |
| test_phase7f_unified_profile.py | 6 | ✅ PASS |
| test_phase7b2_duplicate_request.py | 8 | ✅ PASS（mock 适配） |
| test_phase7a_final_acceptance.py | 6 | ✅ PASS（mock 适配） |
| test_tiktok_service_ex.py | 10 | ✅ PASS（mock 适配） |
| 其他现有测试 | 85 | ✅ PASS |
| **合计** | **123** | **ALL PASS** |

### compileall

```
PASS（无 error）
```

### Phase 7-B.2 约束验证

| 约束 | 验证结果 |
|------|----------|
| fetch_tiktok_html = 1（单 URL 一次初始 HTTP GET） | ✅ `test_single_get_constraint_maintained` PASS |
| legacy parser 复用 HTML（不重复 GET） | ✅ 现有 Case 2/3/7/8 PASS |
| Chrome fallback 保留 | ✅ 改为 CDP 模式，仍为 fallback |
| video_url 为空不算成功 | ✅ `test_parse_no_video_url_no_cache` PASS |
| CDP 不是 requests.get | ✅ 不违反"一次初始 HTTP GET"约束 |

---

## 6. 风险说明

| 风险 | 等级 | 说明 | 缓解 |
|------|------|------|------|
| chrome_login_profile 锁冲突 | MEDIUM | LoginWorker（可见 Chrome）与 CDP（headless）可能同时访问同一 Profile | UI 互斥：登录中阻止 Parse/Download；CDP 在 Worker 线程，与 LoginWorker 时序不重叠 |
| Cookie TTL 过期 | LOW | 600s 后 cookies 过期，download 首次请求无 cookies | refresh fallback 已用同一 chrome_login_profile，可重新获取 |
| CDP 比 --dump-dom 慢 | LOW | CDP ~7s vs --dump-dom ~3s | 仅在 fallback 时触发；parser_ex/legacy 成功时不走 CDP |
| 内存 cookie 缓存丢失 | LOW | 程序重启后缓存为空 | download 时 cache miss → refresh 补 cookies（同一 profile） |
| chrome_login_profile 未登录 | MEDIUM | 用户未登录时 CDP 匿名 | 登录态门控：Parse/Download 前检查 `_is_logged_in` |
| 破坏 Phase 7-B.2 | LOW | CDP 非 requests.get | `test_single_get_constraint_maintained` 验证通过 |

**总体风险：LOW**

---

## 7. git diff --stat

```
 TK_Studio_V1_6_4.py                      | 32 +++++++++++++++++++++++++
 core/chrome_bridge.py                    | 17 ++++++++++----
 core/downloader.py                       |  6 ++++-
 core/tiktok_service_ex.py                | 40 ++++++++++++++++++++++++--------
 tests/test_phase7a_final_acceptance.py   | 18 +++++++-------
 tests/test_phase7b2_duplicate_request.py | 26 ++++++++++-----------
 tests/test_tiktok_service_ex.py          | 22 +++++++++---------
 7 files changed, 112 insertions(+), 49 deletions(-)
```

### 新增文件（untracked）

```
core/cookie_cache.py                 (~65 行)
tests/test_cookie_cache.py           (~95 行, 8 tests)
tests/test_phase7f_unified_profile.py (~170 行, 6 tests)
PHASE7_F_IMPLEMENTATION_PLAN.md
PHASE7_F_IMPLEMENTATION_REPORT.md
```

---

## 8. Git 规则遵守

| 项 | 结果 |
|----|------|
| 禁止 commit | ✅ 未执行任何 commit |
| 禁止修改冻结文件 | ✅ tiktok_login.py / login_worker.py / parser.py / tiktok_service.py / db.py / parse_worker.py / download_worker.py 未触碰 |
| 禁止恢复 Phase 7-B.2 重复 GET | ✅ fetch_tiktok_html = 1，CDP 非 GET |
| 禁止打印/日志/写文件 Cookie | ✅ cookie_cache 纯内存，无 I/O |
| 禁止写 DB Cookie | ✅ DB 结构不变 |
| HEAD | 9df18f4（未变） |

---

## 9. STOP

Phase 7-F 实施完成，**未 commit**，等待人工 review。
