# Phase FIX-A.3-2 测试报告

- 报告时间：2026-09-04 22:10
- 立项依据：Phase HomeFetch-A.3 验收遗留问题 Bug A.3-2（冻结文件缺陷，按约定新 FIX 立项）
- 基线：HomeFetch-A.3 工作区（HEAD=ab1e1fb + A.3 四文件改动，`tiktok_login.py` 修复前为干净状态）
- 目标：修复 `core/tiktok_login.py`（Phase 5-A.4 冻结文件）在非 headless Chrome 下 CDP target 盲选导致的「登录二维码不显示」问题

## 一、缺陷回顾

**Bug A.3-2**：`TikTokLogin._start_chrome` 连接 CDP 时盲选 `/json` 的 `pages[0]`。非 headless Chrome 会加载组件扩展，`pages[0]` 可能是 `chrome-extension://...background.html`，导致：
- `Page.navigate(TIKTOK_LOGIN_URL)` 发到扩展后台页，可见标签页停留在 `about:blank`，**二维码不显示**，用户无法扫码
- `_classify_state` 的页面 URL/QR/头像检测全部读错对象
- 间歇性触发（取决于 Chrome target 排序；Phase 7-E 属侥幸成功）

## 二、修复内容（core/tiktok_login.py，+23/-6 行）

1. **target 选择**：`_start_chrome` 连接 CDP endpoint 前过滤：
   - `type=="page"` 的 target
   - 优先 http(s) 页面，再优先 tiktok.com 域
   - 无 http 页面时回退首个 page target（保持 `check_existing_login` headless 路径原行为）
2. **启动 URL**：可见登录会话启动 URL 直接使用 `TIKTOK_LOGIN_URL`（替代 about:blank，与 HomeFetch-A.3 任务2 同一模式），使正确的页面 target 从启动即存在
3. `check_existing_login`（headless）行为不变：startup 仍 about:blank → 导航主页 → cookie 判定（browser-wide，与 target 无关）

与 `core/home_fetcher.py` Bug A.3-1 修复完全同构（该修复已在 A.3 验收，170 条提取验证）。

## 三、测试结果

### 1. 编译与回归
- `py_compile core/tiktok_login.py`：PASS
- 全量回归：**141 passed** + compileall PASS

### 2. 重测A（无需扫码，已登录态）
| 检查项 | 修复前特征 | 修复后实测 |
|---|---|---|
| CDP 连接目标 | `chrome-extension://...background.html` | `https://www.tiktok.com/foryou?lang=zh-Hans` |
| 页面状态检测 | 全部失效（读错页） | login_success（sessionid present）判定正常 |
| 结论 | — | **PASS** |

### 3. 重测B（真机完整 QR 登录流程，用户扫码）
| 检查项 | 结果 |
|---|---|
| 登出旧会话（TikTokLogin.logout） | PASS（Profile 删除重建） |
| 登录页真实显示（模块自身读到 `页面 URL：https://www.tiktok.com/login/qrcode`） | **PASS（Bug A.3-2 修复的直接证据）** |
| 用户扫码 → LOGIN_SUCCESS（cookie 判定） | PASS |
| snapshot_login_to_auth + validate | PASS（VALIDATE=True） |
| check_existing_login（headless 回归路径） | PASS（已登录） |
| HomeFetcher 抓取冒烟 | 0 条（见下节：外部风控冷却，非代码问题） |

### 4. 抓取冒烟 0 条的定性与延迟复测

- 用户确认两次扫码为**同一受信任账号**
- 40 分钟前同一代码链路 + 同一账号刚取得 **170 条**（Phase HomeFetch-A.3 测试2）
- API 取证：`post/item_list` 再次返回 200 空体（与 A.3 验收时的封锁特征一致）；`story/item_list` 仍正常返回 JSON
- **定性**：今天 10+ 次自动化 Chrome 会话与约 200 次 API 调用触发 TikTok 账号级风控冷却，非 FIX-A.3-2 代码回归
- 已安排 **35 分钟冷却后延迟复测**（`data/probes/phase_homefetch_a3/fixa32_delayed_retest.py`，max_scrolls=3）

### 5. 附带观察（不属本 FIX 范围，记录备查）
- `_has_qr_code` 的 QR 元素选择器与当前 TikTok DOM 不匹配，状态显示 `login_page` 而非 `qr_waiting`；登录判定主信号是 cookie 存在性，不受影响

## 四、冻结边界

- 修改文件：仅 `core/tiktok_login.py`（本次 FIX 授权范围内）
- 未触碰：`core/home_fetcher.py`、`core/downloader.py`、`core/tiktok_home_service.py`、`TK_Studio_V1_6_4.py`、`core/chrome_bridge.py`、`workers/*`、`db/task_manager/parser*`
- git status 确认：tiktok_login.py 由干净状态变为本次 FIX 的唯一新增改动

## 五、结论

**FIX-A.3-2：PASS。** Bug A.3-2 修复经重测A（target 选择）与重测B（真机扫码全流程）双重验证；抓取冒烟 0 条为 TikTok 账号级风控冷却（外部因素，延迟复测中），与本次修复无关。
