# RELEASE FREEZE — Phase 8-D Final

## Release Identity

| 项目 | 值 |
|---|---|
| Project | TK Studio V1.6.4 |
| Phase | Phase 8-D Release Candidate (includes 403 fix) |
| Git commit | `67597d7` |
| Freeze time | 2026-09-05 00:30:00 +0800 |
| EXE path | `D:\TK_Studio_V1_fixed\dist\TKStudio\TKStudio.exe` |
| EXE size | 3,284,463 bytes (3.13 MB) |
| EXE SHA-256 | `442628A7BF7FB45B7F881F1A02CFB62B33FBF934A1D19A54B062F344DCF50252` |
| Build time | 2026-09-05 00:24:04 |

## Acceptance

| 项目 | 结果 |
|---|---|
| EXE Build | PASS |
| EXE Startup | PASS (PID=41008, 124.4MB, 5s stable) |
| Data Directory | PASS (`%LOCALAPPDATA%\TK_Studio`) |
| SQLite WAL | PASS (journal_mode=wal, busy_timeout=5000) |
| Chrome profile | PASS (chrome_headless_profile created) |
| Functional Black-box Proxy | PASS |
| Exception Tests | PASS |
| Real TikTok Download | PASS (HTTP 403 → HTTP 200, video/mp4) |
| Final Regression | PASS |
| Full Automated Regression | 122 passed |

## Phase 8-D 403 Fix

| 项 | 修改前 | 修改后 |
|---|---|---|
| Accept-Encoding | `identity` | `gzip, deflate, br` |
| Origin | `https://www.tiktok.com` | 移除 |
| Sec-Fetch-Dest/Mode/Site | 手动硬编码 | 移除 |

### Verification

```
Before: HTTP 403 (text/html, 508 bytes)
After:  HTTP 200 (video/mp4, 2914 bytes)
Download: PASS
```

## Known Transient Event

`test_concurrent_same_title_downloads`

- 首次: `disk I/O error`
- 重测: `PASS`
- 结论: `non-reproducible transient I/O event`

## Freeze Rules

> Release Freeze 后禁止修改生产代码、测试代码及核心构建配置。

## Supersedes

本 Release Freeze 取代 Phase 8-C Release Freeze（commit `c692641`），因为 Phase 8-D 修改了生产代码 `core/downloader.py`。
