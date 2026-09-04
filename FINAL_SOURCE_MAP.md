# 最终源码地图 — TK Studio V1.6.4

> 生成时间：2026-09-04 15:48 (+08:00)
> Phase 6-H Release Cleanup

---

## 1. 入口文件

| 文件 | 路径 | 说明 |
|------|------|------|
| **TK_Studio_V1_6_4.py** | `./TK_Studio_V1_6_4.py` | ✅ **唯一正式入口**（L1253 `__main__`） |

### 入口验证

- ✅ `TKStudio.spec` Analysis 入口：`['TK_Studio_V1_6_4.py']`
- ✅ git commit `61d271f` 包含此文件
- ✅ `python -c "import TK_Studio_V1_6_4"` → ENTRY_OK
- ✅ `__main__` 块位于 L1253

---

## 2. 核心模块（core/）

| 文件 | 功能 | Phase | 冻结 |
|------|------|-------|------|
| `parser.py` | TikTok HTML 正则解析 | Initial | ✅ |
| `parser_ex.py` | JSON 结构化解析层（3 种 blob） | C1/C2 | ✅ |
| `tiktok_service.py` | TikTok URL → HTML → 数据 | Initial | ✅ |
| `url_resolver.py` | 短链解析（HEAD+GET+Retry+缓存） | B4.2/B4.3 | ✅ |
| `http_client.py` | Retry Session 工厂 | C2 | ✅ |
| `tiktok_request.py` | 带 Retry 的 HTML 获取 | C2 | ✅ |
| `downloader.py` | 视频下载 | Initial | ✅ |
| `db.py` | SQLite 数据库 | Initial | ✅ |
| `tiktok_login.py` | Chrome 扫码登录 | Initial | ✅ |
| `profile_snapshot.py` | 登录态 snapshot | B3.4 | ✅ |
| `home_fetcher.py` | 主页 URL 抓取 | B1/B2/B3 | ✅ |
| `home_worker.py` | 主页抓取协调器 | B1 | ✅ |
| `tiktok_home_fetcher.py` | TikTok 主页数据提取 | B1 | ✅ |
| `tiktok_home_service.py` | TikTok 主页服务层 | B1 | ✅ |
| `tiktok_home_worker.py` | TikTok 主页 Worker | B1 | ✅ |
| `tiktok_home_adapter.py` | TikTok 主页数据适配器 | B1 | ✅ |

---

## 3. Worker 模块（workers/）

| 文件 | 功能 | Phase | 冻结 |
|------|------|-------|------|
| `parse_worker.py` | 解析 QThread | Initial | ✅ |
| `resolve_worker.py` | 短链解析 QThread | C1 | ✅ |
| `home_fetch_worker.py` | 主页抓取 QThread | B2.2 | ✅ |
| `login_worker.py` | 登录 QThread | Initial | ✅ |
| `task_manager.py` | 下载任务管理 | Initial/B1 | ✅ |

---

## 4. 测试（tests/）

| 文件 | 用例数 | Phase |
|------|--------|-------|
| `test_url_resolver.py` | 24 | B4.3 |
| `test_parser_ex.py` | 26 | C1 |
| `test_parser_integration.py` | 10 | C2 |
| `test_http_client.py` | 20 | C2 |
| `test_home_worker.py` | 1 | B1 |
| `test_tiktok_home_adapter.py` | — | B1 |
| `test_tiktok_home_service.py` | — | B1 |
| `test_tiktok_home_worker.py` | — | B1 |
| `tiktok_home_dom_probe.py` | — | B1（探针） |

---

## 5. 归档文件（archive/）

以下文件已移入 `archive/`，不参与构建，仅作历史保留：

| 文件 | 大小 | 原因 |
|------|------|------|
| `main.py` | 14,931 B | 旧 demo 版本，无 Phase 5 功能 |
| `TK_Studio_V1_1.py` | 25,569 B | V1.1 旧版本 |
| `TK_Studio_V1_2.py` | 31,014 B | V1.2 旧版本 |
| `TK_Studio_V1_3.py` | 34,144 B | V1.3 旧版本 |
| `TK_Studio_V1_4.py` | 38,776 B | V1.4 旧版本 |
| `TK_Studio_V1_5.py` | 44,842 B | V1.5 旧版本 |
| `TK_Studio_V1_6_1.py` | 44,842 B | V1.6.1 旧版本 |
| `TK_Studio_V1_6_2.py` | 44,844 B | V1.6.2 旧版本 |
| `TK_Studio_V1_6_3.py` | 44,887 B | V1.6.3 旧版本 |
| `add_task_methods.py` | 4,407 B | 一次性 DB 迁移脚本 |

---

## 6. 引用关系

### 6.1 入口引用链

```
TK_Studio_V1_6_4.py (入口)
    ↓
    ├── core.url_resolver (B4.x)
    ├── workers.resolve_worker (C1)
    ├── workers.parse_worker (Initial)
    ├── workers.home_fetch_worker (B2.x)
    ├── workers.login_worker (Initial)
    ├── workers.task_manager (Initial/B1)
    ├── core.profile_snapshot (B3.4)
    └── core.db / parser / downloader / tiktok_login / home_fetcher
```

### 6.2 无引用文件（已归档）

- `main.py` — 0 引用
- `TK_Studio_V1_1.py` ~ `TK_Studio_V1_6_3.py` — 0 引用
- `add_task_methods.py` — 0 引用（一次性脚本）

---

## 7. 打包配置

| 文件 | 说明 |
|------|------|
| `TKStudio.spec` | PyInstaller 配置，入口 `TK_Studio_V1_6_4.py` |
| `requirements.txt` | 4 依赖（PySide6 / requests / urllib3 / websocket-client） |
| `README.txt` | 用户说明 |

---

## 8. 冻结文件确认

| 冻结文件 | 状态 |
|----------|------|
| 16+ Phase 5 冻结文件 | ✅ 全部未触碰 |
| `TK_Studio_V1_6_4.py` | ✅ 入口确认，内容未修改（仅位置不变） |
| `core/*.py` | ✅ 未修改 |
| `workers/*.py` | ✅ 未修改 |

**结论：源码入口唯一确定，归档完整，引用关系清晰。**
