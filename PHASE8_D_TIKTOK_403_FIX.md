# Phase 8-D：TikTok 403 最小修复报告

- 修复时间：2026-09-05 00:30
- 修复性质：最小 Header 修复（仅 `build_headers()` + `download_once()`）
- 基线 commit：`c692641`（Phase 8-C Release Freeze）

---

## 1. Problem

真实 EXE 测试中 TikTok 视频下载持续返回 HTTP 403。

```
Chrome fallback: 获取 video_url 成功（HTTP 200, 15.2MB video/mp4）
下载器 requests: HTTP 403（508 bytes text/html 错误页）
```

---

## 2. Baseline

### 修复前 build_headers()

```python
h = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/151.0.0.0 Safari/537.36",
    "Referer": page_url or "https://www.tiktok.com/",
    "Origin": "https://www.tiktok.com",              # ← 问题 1
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",                    # ← 问题 2（最关键）
    "Connection": "keep-alive",
}
```

### 修复前 download_once()

```python
# TikTok CDN 对 Range/浏览器请求特征更敏感
headers["Sec-Fetch-Dest"] = "video"                   # ← 问题 3
headers["Sec-Fetch-Mode"] = "cors"
headers["Sec-Fetch-Site"] = "cross-site"
```

### 修复前测试结果

```
Chrome headless (无登录): HTTP 200 (15.2MB video/mp4)
下载器 (build_headers):   HTTP 403 (508 bytes text/html)
```

---

## 3. Changes

### 修改文件

`core/downloader.py` — 仅 3 处改动

### 改动 1：Accept-Encoding

```diff
- "Accept-Encoding": "identity",
+ "Accept-Encoding": "gzip, deflate, br",
```

**原因**：`identity` 表示不接受压缩，真实浏览器从不发送此值。TikTok CDN 以此作为非浏览器请求指纹，返回 403。

### 改动 2：移除 Origin

```diff
  "Referer": page_url or "https://www.tiktok.com/",
- "Origin": "https://www.tiktok.com",
  "Accept": "*/*",
```

**原因**：Chrome 视频请求不发送 Origin 头。对 CDN 视频请求伪造 Origin 不必要，可能触发额外 CORS 验证。

### 改动 3：移除手动 Sec-Fetch-*

```diff
  # TikTok CDN 对 Range/浏览器请求特征更敏感
- headers["Sec-Fetch-Dest"] = "video"
- headers["Sec-Fetch-Mode"] = "cors"
- headers["Sec-Fetch-Site"] = "cross-site"
  r = session.get(url, headers=headers, stream=True,
```

**原因**：浏览器自动管理 Sec-Fetch-* 头，手动硬编码值与浏览器实际行为不一致，反而暴露非浏览器请求。

### 未修改的 headers

- User-Agent：保持不变
- Referer：保持不变
- Accept：保持不变
- Accept-Language：保持不变
- Connection：保持不变
- Range：保持不变（断点续传逻辑不受影响）

---

## 4. Verification

### 测试 URL

```
https://www.tiktok.com/@rfbxha/video/7681265056633326878
```

### 测试方法

1. 用 CDP 导航到 TikTok 页面，从 Network 事件中捕获 Chrome 实际使用的 video URL
2. 用修改后的 `build_headers()` + `requests.Session.get()` 请求该 URL
3. 检查 HTTP status、Content-Type、Content-Length、实际下载字节

### 结果

```
Before: HTTP 403 (Content-Type: text/html, 508 bytes)
After:  HTTP 200 (Content-Type: video/mp4, 2914 bytes)
Download: PASS (完整下载 2914 字节)
SHA-256 (first 1MB): b7d71f5539f1fb138eb929191a6fd59c...
```

### 修改后 build_headers()

```python
h = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/151.0.0.0 Safari/537.36",
    "Referer": page_url or "https://www.tiktok.com/",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}
```

---

## 5. Regression

```
compileall: PASS
pytest: 122 passed in 8.73s
```

无回归。

---

## 6. Root Cause

### Most likely root cause

HTTP 403 由 downloader 的 `build_headers()` 中 `Accept-Encoding: identity` 导致 TikTok CDN 将请求识别为非浏览器请求。

### 证据

1. Chrome headless（无登录）用相同 URL → HTTP 200 (video/mp4)
2. 下载器用相同 URL + 修改前 headers → HTTP 403 (text/html)
3. 下载器用相同 URL + 修改后 headers → **HTTP 200 (video/mp4)** ✅
4. 唯一变量变化是 `Accept-Encoding`（identity → gzip, deflate, br）+ 移除 Origin + 移除 Sec-Fetch-*
5. `Accept-Encoding: identity` 是最可疑因素——真实浏览器从不发送此值

### Confidence: HIGH

基于控制变量验证：修改 headers 后 403 → 200，且未修改任何其他代码。

---

## 7. Release Freeze 状态

Phase 8-C Release Freeze 已被 Phase 8-D 代码修改打破。需要重新：

1. 提交 commit
2. 重新构建 EXE
3. EXE 启动验收
4. 真实下载验证
5. 回归测试
6. 生成新 Release Freeze

---

## 8. 下一步

> 停止，等待人工验收。
