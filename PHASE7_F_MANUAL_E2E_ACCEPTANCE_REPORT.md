# Phase 7-F 人工 Review + 真实 E2E 验收报告

- 验收日期：2026-09-04
- 验收方式：人工 Review（只读静态检查）+ 真实登录态 E2E（READ / EXECUTE / REPORT）
- 约束遵守：未修改任何生产代码 / 测试 / 冻结模块；未 commit；未删除测试；未隐藏失败

---

## 1. Git Baseline

```
HEAD = 9df18f4  （确认与验收要求一致）
9df18f4 Phase 7-B.2 eliminate duplicate TikTok HTTP requests
```

验收开始与结束时工作树完全一致（无 E2E 过程污染）：

- 修改（M，7 个）：`TK_Studio_V1_6_4.py`、`core/chrome_bridge.py`、`core/downloader.py`、`core/tiktok_service_ex.py`、`tests/test_phase7a_final_acceptance.py`、`tests/test_phase7b2_duplicate_request.py`、`tests/test_tiktok_service_ex.py`
- 新增（??，6 个）：`core/cookie_cache.py`、`tests/test_cookie_cache.py`、`tests/test_phase7f_unified_profile.py`、`PHASE7_F_IMPLEMENTATION_PLAN.md`、`PHASE7_F_IMPLEMENTATION_REPORT.md` 及此前各阶段报告文档

## 2. Regression

| 项目 | 结果 |
|---|---|
| `pytest -q tests` | **123 passed**（1.75s；验收结束时复跑仍 123 passed） |
| `python -m compileall .` | **PASS**（exit 0） |

测试弱化检查（git diff 全量审查）：3 个已修改测试文件的改动**全部为机械性 API 适配**——mock 目标由 `load_with_chrome` 改为 `chrome_render_with_cookies`，mock 返回值由 `str` 改为 `(html, cookie_items)` 元组。**所有测试用例与断言均保留，无删除、无弱化。** 123 = 109（Phase 7-B.2 基线）+ 14（Phase 7-F 新增 8 + 6）。

## 3. Profile Verification（静态只读）

| 检查项 | 结果 |
|---|---|
| `chrome_render_with_cookies()` 使用的 profile | `chrome_login_profile`（`--user-data-dir` 指向项目根该目录）✅ |
| `chrome_cdp_profile` 是否残留 | 无（`core/chrome_bridge.py` 全文零处引用，且有测试 `test_chrome_uses_login_profile` 断言兜底）✅ |
| `load_with_chrome()` 保留情况 | 保留 `chrome_headless_profile`，仅供冻结的 `core/tiktok_service.py` 向后兼容；生产 ParseWorker 不走此路径 ✅ |
| `refresh_video_url()`（下载刷新链路） | 经 `chrome_render_with_cookies` → 同样使用 `chrome_login_profile` ✅ |

结论：生产解析 / 刷新 / CDP 链路已统一使用 `chrome_login_profile`。

## 4. Login Persistence

测试环境：专用 Chrome（`--user-data-dir=D:\TK_Studio_V1_fixed\chrome_login_profile`），未使用用户正常 Chrome Profile。人工扫码登录由用户在专用 Chrome 窗口完成；验证过程仅输出计数与布尔值，未读取 / 导出 / 打印任何 cookie 内容。

| 轮次 | DOM 指标 | tiktok 域 cookie 数 | 登录态 cookie 计数 | 判定 |
|---|---|---|---|---|
| 第 1 次（登录后） | 无登录按钮，头像存在 | 33 | 8 | 已登录 ✅ |
| 第 2 次（重启 Chrome 后） | 无登录按钮，头像存在 | 33 | 8 | 登录态持久 ✅ |

结论：登录态在 Chrome 完整重启后持久保持（持久化 Profile 生效）。

## 5. Parse E2E

- 测试 URL（Phase 7-C / 7-E 既定成功样本）：`https://www.tiktok.com/@rfbxha/video/7681265056633326878`
- 执行方式：直接调用生产解析链路 `parse_url_ex(url, log_callback)`

实测解析链路（与 Phase 7-F 设计完全一致）：

```
TikTok URL
  ↓ HTTP HTML（状态 200）
  ↓ parser_ex（TikTok 风控 → 字段全空）
  ↓ legacy parser（复用同一 HTML，不重复 GET → 仍空）
  ↓ CDP fallback 触发（chrome_render_with_cookies，chrome_login_profile）
  ↓ HTML + cookies
  ↓ video_url（v16-webapp-prime.us.tiktok.com，14 个 query 参数）
  ↓ cookie_cache（写入 34 条，含登录态 cookie 6 条，仅计数）
```

| 记录项 | 结果 |
|---|---|
| parse success | True ✅ |
| video_url 非空 | True ✅ |
| Chrome 使用 chrome_login_profile | 是（运行时证据：CDP 获取的 cookies 中含登录态 cookie，匿名 profile 不可能产生）✅ |
| CDP 成功 | True（标题/封面/视频地址全部补齐）✅ |
| cookie 数量 > 0 | 34（>0）✅ |
| 敏感信息输出 | 无（仅记录 cookie_count=N / video_url_present=True / host，未输出任何 cookie name/value、签名参数）✅ |

CDP fallback 确认为浏览器内导航（Page.navigate + Network.getAllCookies + Runtime.evaluate），**不是额外 HTTP requests.get**，Phase 7-B.2 的"一次初始 GET"约束保持（有测试 `test_single_get_constraint_maintained` + 实测每次解析仅 1 次 `www.tiktok.com` GET）。

## 6. Cookie Cache Verification

静态审查（`core/cookie_cache.py`）+ 动态行为（E2E）：

| 检查项 | 结果 |
|---|---|
| 仅内存保存 | ✅（进程内 dict，无任何文件 I/O） |
| 有 TTL | ✅（默认 600s，过期自动清理并返回 []） |
| 线程安全 | ✅（`threading.Lock` 全程持有；含多线程并发测试） |
| 不写磁盘 | ✅ |
| 不输出 cookie 内容到日志 | ✅（全项目扫描无 cookie 内容打印；仅 2 处状态文案提及"Cookie"字样，无内容） |
| parse 成功后写入 cache | ✅（`video_url + video_id + cookie_items` 齐备时 `set_cookie`；实测写入 34 条） |
| download 按 video_id 读取 | ✅（`run_download` 在 attempt 循环前 `get_cookie(video_id)`；实测命中 34 条） |
| logout 可以清理 | ✅（`clear_all()`；登出实测后为空） |
| 失败不写 cache | ✅（无 video_url 时不写入，有测试覆盖；稳定性 Run 1/2 解析失败时 cache 正确为空，无假成功） |

## 7. Download E2E

执行方式：**同一进程内**镜像生产链路 `parse_url_ex → db.add_work（与 ParseWorker 一致）→ run_download（与 DownloadWorker 一致）`。cookie_cache 为进程内存，同进程执行与生产 App 行为一致。

第一次 HTTP request 观测（对 TikTok 域做只读插桩，仅记录 host + status）：

| 记录项 | 结果 |
|---|---|
| attempt=1 cookie_cache hit | **True**（34 条 cookies 注入首请求）✅ |
| attempt=1 HTTP status | **200**（CDN：v16-webapp-prime.us.tiktok.com）✅ |
| refresh fallback | 未触发（无 403 → refresh → 403 循环）✅ |
| 重复 HTTP GET | 无（TikTok 域全链路仅 2 次请求：1 次解析 GET + 1 次下载 GET）✅ |

下载产物与 DB 验证：

| 记录项 | 结果 |
|---|---|
| MP4 文件存在 | ✅ |
| 文件大小 > 0 | ✅（15,964,590 字节 ≈ 15.2 MB） |
| 文件头正确 | ✅（`ftyp` box header） |
| ffprobe 可识别 | ✅（h264, 720x1280，exit 0） |
| DB download_status | `已下载` ✅ |
| local_path 非空 | ✅ |

**结论：第一次下载请求即带登录态 cookies 并 HTTP 200 —— Phase 7-F 核心目标成立。**

## 8. Logout Gating

执行方式：生产登出链路（`TikTokLogin.logout()` → `delete_auth_profile()` → `cookie_cache.clear_all()`，与 `on_logout_clicked` 序列一致）+ offscreen MainWindow 实测 UI 门控（QMessageBox 打桩捕获，不阻塞）。

| 验证项 | 结果 |
|---|---|
| 登出执行 | True（Profile 目录删除） |
| `chrome_login_profile` | 已删除（登出设计如此） |
| `chrome_home_auth_profile` | 已删除 ✅ |
| `cookie_cache` | 已清空 ✅ |
| 登出后 `check_existing_login()` | False ✅ |
| UI `_is_logged_in` | False（启动检查 Worker 真实检测后）✅ |
| Parse 门控 | 弹出「未登录」确认框 → **ParseWorker 未创建**、按钮未进入解析态 → 未发出任何 TikTok 请求 ✅ |
| Download 门控 | 弹出「无法下载」警告框 → `task_manager.is_busy` 未被调用（未入队）✅ |

结论：登出后 Parse / Download 均被 UI 在发起实际 TikTok 请求**之前**阻止。

## 9. Chrome Isolation

| 验证项 | 结果 |
|---|---|
| 代码引用用户默认 Chrome Profile | 零处（`core/`、`workers/`、主程序全文无 "User Data" 引用）✅ |
| 用户 Profile 被修改 / 登录 / 注入 cookie | 否（所有 Chrome 启动均显式 `--user-data-dir` 指向项目内专用目录）✅ |
| 用户 Profile 被占用 lock / 强制关闭 | 否（验收全程仅终止命令行匹配 `chrome_login_profile` 的进程；用户 Chrome 未受影响）✅ |
| 专用 `chrome_login_profile` 独立启动 / 退出 | ✅（启动后 CDP 端点返回 200；退出后残留进程数为 0） |
| Profile lock 冲突 | 无（E2E 全程 CDP 启动/退出 8 次以上，无一次冲突；E2E 前均先释放 profile 锁）✅ |

## 10. 3x Stability

**执行顺序说明**：验收指令顺序为登出（步骤 7）在前、稳定性（步骤 9）在后，但稳定性要求"已登录的专用 profile"，故稳定性在登出之前执行（与 Parse/Download E2E 同一时段），登出验收在其后完成。此为合理顺序调整，非流程遗漏。

**第一轮（间隔 20s）**：Run 1 FAIL / Run 2 FAIL / Run 3 PASS。
失败均发生在 parse 阶段：HTTP GET 与 CDP 均正常运行，但 TikTok 返回空字段（video_url 为空，cache 正确未写入）。该现象与项目已记录的外部限制一致——"TikTok 对同一 URL 短时间重复解析触发限流，需间隔 30s 以上"。按 Phase 7-C 惯例记为外部因素，不判定为代码失败。

**第二轮（间隔 35s，符合既定缓解措施）**：

| 项目 | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| parse success | True | True | True |
| CDP fallback（chrome_login_profile） | 触发 | 触发 | 触发 |
| cookie_cache hit / count | True / 34 | True / 34 | True / 34 |
| CDN 首请求（attempt=1）status | 200 | 200 | 200 |
| refresh fallback | 未触发 | 未触发 | 未触发 |
| 重复 HTTP GET | 无（每 run 恰 2 次） | 无 | 无 |
| 403 | 无 | 无 | 无 |
| 文件大小 / ftyp 头 | 15,964,590 B / ✓ | 同 | 同 |
| DB download_status | 已下载 | 已下载 | 已下载 |
| **判定** | **PASS** | **PASS** | **PASS** |

稳定性观察点确认：无重复 HTTP GET ✅ / 无 profile lock 冲突 ✅ / 无 cookie cache race ✅ / 无假成功（第一轮失败 run 正确报告失败且不写 cache）✅ / 无 403 ✅ / 下载文件均有效 ✅。

## 11. Known Limitations

1. **TikTok 外部限流（外部因素）**：对同一作品 URL 以 <30s 间隔连续解析时，TikTok 返回空字段导致 parse 失败（第一轮 Run 1/2）。间隔 35s 后 3/3 通过。链路行为正确：失败如实上报、不写 cache、不假成功。建议使用侧保持 ≥30s 解析间隔（与 Phase 7-C 结论一致）。
2. **`chrome_render_with_cookies` 早期失败分支返回类型不一致（轻微）**：`chrome_bridge.py` 中 "无 Chrome" 与 "无端口" 两个早期分支返回 `("", {})`（dict），与成功路径 `list` 类型不一致。因空 dict 为 falsy，`set_cookie` 不会误触发，**无功能影响**；仅建议后续统一为 `[]`（本次验收未修改）。
3. **cookie_cache 为单进程内存**：parse 与 download 必须在同一 App 进程内（生产 App 即如此）。若 App 在 parse 与 download 之间重启，cache 丢失 → 走既有 refresh fallback（设计内行为，非缺陷）。
4. **登出删除整个 `chrome_login_profile`**（既有设计）：登出验收后该 profile 登录态已清除，后续使用需重新扫码登录。
5. **测试脚手架说明**：Part B offscreen 验证中 `login_status_label` 因测试脚本未运行 Qt 事件循环而停留于「检测登录态...」文案，属脚手架伪影，非应用缺陷（`_is_logged_in=False` 门控判定与真实检测结果一致）。
6. **E2E 临时产物**：验收脚本（已删除）位于 %TEMP%，未入项目目录、不会 commit；4 个下载样例文件保留于 `%TEMP%\tk_phase7f_downloads*`（约 64 MB，App DB 中 work 120 的 local_path 指向其中之一），可自行删除。

## 12. Final Verdict

**PASS**

判定依据：
- Phase 7-F 统一 Chrome Profile（chrome_login_profile）+ 登录态 + CDP cookies → Downloader 完整链路在真实登录态下全部打通
- 第一次下载请求即命中 cookie_cache 并 HTTP 200（核心目标成立），无 403、无 refresh 循环、无重复 GET
- cookie_cache 内存 / TTL / 线程安全 / 无泄露设计全部满足；登出清理与 UI 门控有效
- 123 tests passed + compileall PASS；测试零弱化；工作树与基线一致；未 commit
- 唯一失败场景（短间隔重复解析）为已记录的 TikTok 外部限流，链路失败行为正确，不影响本阶段结论

按验收规则：本阶段到此结束——不 commit、未修改冻结模块、未删除测试、未隐藏失败。
