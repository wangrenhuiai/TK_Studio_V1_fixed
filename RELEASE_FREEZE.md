# RELEASE FREEZE — Phase 8-D Final (incl. login fix)

## Release Identity

| 项目 | 值 |
|---|---|
| Project | TK Studio V1.6.4 |
| Phase | Phase 8-D Release Candidate (403 fix + login orphan cleanup) |
| Git commit | `ee617be` |
| Freeze time | 2026-09-05 00:45:00 +0800 |
| EXE path | `D:\TK_Studio_V1_fixed\dist\TKStudio\TKStudio.exe` |
| EXE size | 3,285,298 bytes (3.13 MB) |
| EXE SHA-256 | `640D1A2C1F38567C13B472B30206BB5BC7087146EDCAEA8CAF73055FDE6769B5` |
| Build time | 2026-09-05 00:45:14 |

## Acceptance

| 项目 | 结果 |
|---|---|
| EXE Build | PASS |
| EXE Startup | PASS (PID=15336, 120.7MB, 5s stable) |
| Data Directory | PASS (`%LOCALAPPDATA%\TK_Studio`) |
| SQLite WAL | PASS (journal_mode=wal, busy_timeout=5000) |
| Chrome profile | PASS (chrome_headless_profile created) |
| Functional Black-box Proxy | PASS |
| Exception Tests | PASS |
| Real TikTok Download | PASS (HTTP 403 → HTTP 200, video/mp4) |
| Login Module | PASS (orphan Chrome cleanup) |
| Final Regression | PASS |
| Full Automated Regression | 122 passed |

## Phase 8-D Changes

### 403 Fix (core/downloader.py)
| 项 | 修改前 | 修改后 |
|---|---|---|
| Accept-Encoding | `identity` | `gzip, deflate, br` |
| Origin | `https://www.tiktok.com` | 移除 |
| Sec-Fetch-Dest/Mode/Site | 手动硬编码 | 移除 |

### Login Orphan Cleanup (core/tiktok_login.py)
- 新增 `_cleanup_orphan_chrome(profile_dir)` 方法
- 在 `_start_chrome()` 开头清理占用同一 profile 的孤儿 Chrome 进程
- 防止 EXE 强制终止后 profile 锁残留导致登录失败

## Known Transient Event

`test_concurrent_same_title_downloads`
- 首次: `disk I/O error`
- 重测: `PASS`
- 结论: `non-reproducible transient I/O event`

## Freeze Rules

> Release Freeze 后禁止修改生产代码、测试代码及核心构建配置。

## Supersedes

本 Release Freeze 取代之前的 Phase 8-D Release Freeze（commit `67597d7`），因为增加了登录模块孤儿进程清理修复。
