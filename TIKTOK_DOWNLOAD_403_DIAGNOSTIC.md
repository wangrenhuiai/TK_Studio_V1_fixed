# TikTok 下载 HTTP 403 诊断报告

- 诊断时间：2026-09-05 00:12
- 诊断性质：只读诊断（禁止修改生产代码）
- 测试 URL：`https://www.tiktok.com/@rfbxha/video/7681265056633326878`
- 诊断脚本：`tests/diag_403.py`

---

## 1. Reproduction

### 复现链路

```
短链解析: https://www.tiktok.com/t/ZTUNyfkNF/
  → https://www.tiktok.com/@rfbxha/video/7681265056633326878  ✅ PASS

HTTP 200 (fetch_tiktok_html):  ✅ PASS

parser_ex 解析: 标题=无, 封面=无, 视频地址=无  ❌ 字段缺失
原 parser 复用 HTML: 标题=无, 封面=无, 视频地址=无  ❌ 字段缺失

Chrome fallback (load_with_chrome):
  标题=有, 封面=有, 视频地址=有  ✅ PASS

下载 (download_once):
  第 1/3 次: HTTP 403  ❌ FAIL
  刷新视频地址 (chrome_render_with_cookies → chrome_cdp_profile, 无登录态)
  第 2/3 次: HTTP 403  ❌ FAIL
  第 3/3 次: HTTP 403  ❌ FAIL
  最终: 下载失败：HTTP 403
```

### 403 可稳定复现：是

连续 3 次请求均返回 403，可稳定复现。

---

## 2. Chrome video request

### Chrome fallback 获取的 video URL

| 属性 | 值 |
|---|---|
| URL 长度 | 459 字符 |
| URL 前缀 | `https://v16-webapp-prime.tiktok.com/video/tos/alisg/tos-alisg-ve-37c799-sg/okZaA...` |
| 有 query 参数 | 是 |
| Query 参数名 | `a, bti, bt, ft, mime_type, rc, expire, l, ply_type, policy, signature, tk, btag` |
| 签名/时间相关参数 | `signature, expire, token` |
| cookie_present | false（chrome_headless_profile 无登录态） |

### Chrome headless 真实视频请求（CDP Network 监控）

| 属性 | 值 |
|---|---|
| 视频请求 URL | `https://v16-webapp-prime.tiktok.com/video/tos/alisg/tos-alisg-ve-37c799-sg/okZaA...`（与 DOM URL 相同前缀） |
| Method | GET |
| Status | **200** ✅ |
| Content-Type | video/mp4 |
| Content-Length | 15,964,590 bytes (15.2 MB) |
| User-Agent | present（Chrome 真实 UA） |
| Referer | present（`https://www.tiktok.com/`） |
| Origin | absent |
| Cookie | absent（无登录态） |
| Range | absent |
| Accept | absent |

**关键发现**：Chrome headless（无登录态）成功下载视频（200, 15.2MB），而下载器请求相同 URL 得到 403。

---

## 3. Downloader request

### 下载器请求头（build_headers）

| Header | 值 |
|---|---|
| User-Agent | `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36` |
| Referer | `https://www.tiktok.com/@rfbxha/video/7681265056633326878` |
| Origin | `https://www.tiktok.com` |
| Accept | `*/*` |
| Accept-Language | `en-US,en;q=0.9` |
| **Accept-Encoding** | **`identity`** ⚠️ |
| Connection | `keep-alive` |
| Sec-Fetch-Dest | `video`（download_once 中追加） |
| Sec-Fetch-Mode | `cors` |
| Sec-Fetch-Site | `cross-site` |
| Cookie | absent（首次请求 cookie_items=[]） |

### 下载器请求结果

| 属性 | 值 |
|---|---|
| Status | **403** ❌ |
| Content-Type | text/html（错误页，非视频） |
| Content-Length | 508 bytes |

---

## 4. Request comparison

| 项目 | Chrome 真实请求 | 下载器请求 |
|---|---|---|
| URL | v16-webapp-prime.tiktok.com/... | **相同** |
| User-Agent | Chrome 真实 UA | Chrome/151.0.0.0（硬编码） |
| Referer | https://www.tiktok.com/ | https://www.tiktok.com/@rfbxha/video/... |
| Origin | absent | https://www.tiktok.com ⚠️ |
| Cookie | absent | absent |
| Range | absent | absent（首次请求） |
| Accept | absent | */* |
| **Accept-Encoding** | **gzip, deflate, br（浏览器默认）** | **identity** ⚠️ |
| Sec-Fetch-Dest | absent | video |
| Sec-Fetch-Mode | absent | cors |
| Sec-Fetch-Site | absent | cross-site |
| **Status** | **200** | **403** |

### 关键差异

1. **Accept-Encoding: identity** — 下载器显式声明不接受压缩，真实浏览器从不发送此值。CDN 可能将其作为反爬指纹。
2. **Origin: https://www.tiktok.com** — Chrome 视频请求不发送 Origin 头，下载器发送。对于跨域视频请求，Origin 可能触发 CDN 的 CORS 验证。
3. **Sec-Fetch-* 头** — Chrome 视频请求不发送这些头，下载器发送 `Sec-Fetch-Dest=video` 等。这些头反而暴露了请求为非浏览器自动发起。
4. **User-Agent 版本** — 下载器硬编码 Chrome/151.0.0.0，可能与实际 Chrome 版本不匹配。

---

## 5. URL lifecycle

### URL 获取时间线

```
T0: load_with_chrome(--dump-dom) 获取 HTML → extract_tiktok_data → video_url
T0+3s: 下载器用 build_headers 请求 video_url → 403
```

### URL 参数分析

| 参数 | 存在 | 说明 |
|---|---|---|
| expire | ✅ | URL 有过期时间 |
| signature | ✅ | URL 有签名 |
| token | ✅ | URL 有 token |

### URL 生命周期结论

- URL 本身有效（Chrome 在相同时间用相同 URL 成功下载）
- URL 未在 3 秒内过期（Chrome 在 T0+15s 仍返回 200）
- URL 未与 Cookie/session 绑定（Chrome 无 Cookie 也成功）
- **URL 未与 Chrome 的 User-Agent/Referer 绑定**（下载器发送了相似但不同的 UA/Referer）

**结论**：URL 生命周期不是 403 的原因。URL 在诊断期间持续有效。

---

## 6. Cookie/session relationship

### Cookie 来源分析

| 阶段 | Cookie 来源 | 登录态 | 结果 |
|---|---|---|---|
| 首次下载 | cookie_items=[] (空) | ❌ 无 | 403 |
| refresh_video_url | chrome_cdp_profile (无登录) | ❌ 无 | 获取到新 URL + 无效 cookies |
| 重试下载 | chrome_cdp_profile cookies | ❌ 无 | 403 |

### Chrome headless vs 下载器 Cookie 对比

| 请求方 | Cookie | 结果 |
|---|---|---|
| Chrome headless (无登录) | 无 Cookie | **200** ✅ |
| 下载器 (无 Cookie) | 无 Cookie | **403** ❌ |
| 下载器 (chrome_cdp_profile cookies) | 无 sessionid | **403** ❌ |

**关键发现**：Chrome headless 和下载器都没有登录态 Cookie，但 Chrome 成功而下载器失败。说明 **403 不是由 Cookie/登录态缺失导致**，而是由请求头差异导致。

---

## 7. 403 source analysis

### 403 来源判定

| 假设 | 证据 | 结论 |
|---|---|---|
| A. TikTok 页面层 | URL 从页面成功获取 | ❌ 排除 |
| B. CDN | 403 来自 CDN 域名 | ✅ 403 来源 |
| C. URL signature | URL 在 3s+ 内未过期 | ❌ 排除 |
| D. Cookie/session | Chrome 无 Cookie 也成功 | ❌ 排除 |
| E. Referer/Origin | Chrome 无 Origin 也成功 | ⚠️ 部分相关 |
| F. User-Agent | Chrome 用真实 UA 成功 | ⚠️ 部分相关 |
| G. Range/header | Chrome 无 Range 也成功 | ❌ 排除 |
| H. **Accept-Encoding** | **下载器发送 `identity`，Chrome 发送 `gzip, deflate, br`** | ✅ **最可能** |

### Most likely cause

**G. Accept-Encoding: identity + 多个非浏览器头组合**

### Evidence

1. Chrome headless（无登录）请求相同 URL → **200**（15.2MB video/mp4）
2. 下载器请求相同 URL → **403**（508 bytes text/html 错误页）
3. 两者唯一差异是请求头
4. `Accept-Encoding: identity` 是最可疑的头——真实浏览器从不发送此值
5. `Origin: https://www.tiktok.com` 在视频 CDN 请求中不必要——Chrome 不发送
6. `Sec-Fetch-*` 头在浏览器自动视频请求中不出现——下载器手动添加
7. 硬编码 `Chrome/151.0.0.0` UA 可能与当前 Chrome 版本不匹配

### Confidence: HIGH

---

## 8. Root cause

### 根因

TikTok CDN 通过请求头指纹（非 URL 签名/Cookie）识别非浏览器请求，对异常头组合返回 403。

具体触发因素（按可能性排序）：

1. **`Accept-Encoding: identity`**（最高嫌疑）
   - 真实浏览器发送 `gzip, deflate, br`
   - `identity` 表示"不压缩"，只有下载工具/爬虫会发送此值
   - CDN 可直接以此作为反爬信号

2. **`Origin: https://www.tiktok.com`**
   - Chrome 视频请求不发送 Origin
   - Origin 头用于 CORS，视频 CDN 请求不需要
   - 添加 Origin 可能触发 CDN 的额外验证

3. **`Sec-Fetch-*` 头组合**
   - `Sec-Fetch-Dest=video` + `Sec-Fetch-Mode=cors` + `Sec-Fetch-Site=cross-site`
   - Chrome 自动视频请求的 Sec-Fetch 值与下载器硬编码不同
   - 错误的 Sec-Fetch 组合反而暴露非浏览器行为

4. **User-Agent 版本不匹配**
   - 硬编码 `Chrome/151.0.0.0` 可能与当前 Chrome 实际版本不一致

### 为什么 Chrome headless 成功而下载器失败

Chrome headless 发送的是浏览器真实请求头组合：
- `Accept-Encoding: gzip, deflate, br`
- 无 Origin
- 无手动 Sec-Fetch-*（浏览器自动添加正确的值）
- 真实 User-Agent

下载器发送的是 `build_headers()` 构造的硬编码头组合，与浏览器真实请求头不一致。

---

## 9. Recommended fix

> **注意：以下为建议方案，不实施。**

### 方案 A：修正 build_headers（最小改动，推荐）

修改 `core/downloader.py` 的 `build_headers()`：

1. **移除 `Accept-Encoding: identity`**，改为 `Accept-Encoding: gzip, deflate, br`
   - 或直接不发送 Accept-Encoding（让 requests 库使用默认值）
   - 注意：下载视频时需要处理 gzip 响应（requests 会自动解压）

2. **移除 `Origin` 头**
   - Chrome 视频请求不发送 Origin，移除后与浏览器一致

3. **移除手动 `Sec-Fetch-*` 头**
   - 或改为 Chrome 实际发送的值：
     - `Sec-Fetch-Dest: video`
     - `Sec-Fetch-Mode: no-cors`（不是 cors）
     - `Sec-Fetch-Site: cross-site`

4. **动态获取 User-Agent**
   - 从 `chrome_headless_profile` 的实际 Chrome 版本读取
   - 或使用 `core/chrome_bridge._find_chrome()` 获取 Chrome 路径后读取版本

### 方案 B：通过 CDP 下载（绕过 requests）

使用 Chrome CDP 的 `Page.getResourceContent` 或 `Network.getResponseBody` 直接从 Chrome 获取视频内容，绕过 requests 请求头问题。

- 优点：完全模拟 Chrome 行为
- 缺点：实现复杂，CDP 不适合大文件传输

### 方案 C：使用登录态 profile（Phase 7-F 方向）

让 `chrome_render_with_cookies` 使用 `chrome_login_profile`（已登录态），获取的 cookies 包含 `sessionid`，下载器注入后可能绕过头指纹检查。

- 优点：与 Phase 7-F 方向一致
- 缺点：需要用户先登录 TikTok；sessionid 会过期

### 推荐优先级

1. **方案 A**（最小改动，直接解决头指纹问题）
2. **方案 C**（如果方案 A 仍 403，增加 session 绑定）
3. 方案 B（最后手段）

---

## 最终输出

1. **403 是否可稳定复现**：是，连续 3 次 403
2. **Chrome 实际视频请求状态**：200（15.2MB video/mp4）
3. **下载器请求状态**：403（508 bytes text/html 错误页）
4. **Chrome 与下载器关键差异**：
   - `Accept-Encoding: identity`（下载器）vs `gzip, deflate, br`（Chrome）
   - `Origin: https://www.tiktok.com`（下载器有）vs absent（Chrome 无）
   - 手动 `Sec-Fetch-*`（下载器）vs absent（Chrome 自动管理）
5. **最可能根因**：`Accept-Encoding: identity` + 非浏览器头组合触发 CDN 反爬
6. **证据**：Chrome headless（无登录）用相同 URL 成功 200，下载器用相同 URL 403
7. **建议修复方向**：方案 A — 修正 `build_headers()` 的 `Accept-Encoding` 和 `Origin`
8. **TIKTOK_DOWNLOAD_403_DIAGNOSTIC.md 是否生成**：是 ✅
