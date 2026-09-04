# 发布结构 — TK Studio V1.6.4

> 生成时间：2026-09-04 15:48 (+08:00)
> Phase 6-H Release Cleanup

---

## 1. 项目根目录结构

```
d:\TK_Studio_V1_fixed\
├── TK_Studio_V1_6_4.py          ← ✅ 唯一入口（L1253 __main__）
├── TKStudio.spec                ← PyInstaller 打包配置
├── requirements.txt             ← 依赖清单
├── README.txt                   ← 用户说明
├── .gitignore                   ← Git 忽略规则
│
├── core/                        ← 核心业务模块（16 文件）
│   ├── parser.py                ← TikTok HTML 正则解析
│   ├── parser_ex.py             ← JSON 结构化解析层
│   ├── tiktok_service.py        ← TikTok URL → 数据
│   ├── url_resolver.py          ← 短链解析
│   ├── http_client.py           ← Retry Session
│   ├── tiktok_request.py        ← Retry HTML 获取
│   ├── downloader.py            ← 视频下载
│   ├── db.py                    ← SQLite 数据库
│   ├── tiktok_login.py          ← 扫码登录
│   ├── profile_snapshot.py      ← 登录态 snapshot
│   ├── home_fetcher.py          ← 主页抓取
│   ├── home_worker.py           ← 主页协调器
│   ├── tiktok_home_fetcher.py   ← TikTok 主页提取
│   ├── tiktok_home_service.py   ← TikTok 主页服务
│   ├── tiktok_home_worker.py    ← TikTok 主页 Worker
│   └── tiktok_home_adapter.py   ← 数据适配器
│
├── workers/                     ← QThread Worker（5 文件）
│   ├── parse_worker.py          ← 解析 Worker
│   ├── resolve_worker.py        ← 短链解析 Worker
│   ├── home_fetch_worker.py     ← 主页抓取 Worker
│   ├── login_worker.py          ← 登录 Worker
│   └── task_manager.py          ← 任务管理器
│
├── tests/                       ← 单元测试（9 文件，81 项）
│   ├── test_url_resolver.py
│   ├── test_parser_ex.py
│   ├── test_parser_integration.py
│   ├── test_http_client.py
│   ├── test_home_worker.py
│   ├── test_tiktok_home_adapter.py
│   ├── test_tiktok_home_service.py
│   ├── test_tiktok_home_worker.py
│   └── tiktok_home_dom_probe.py
│
├── archive/                     ← 📦 归档（10 文件，不参与构建）
│   ├── main.py                  ← 旧 demo
│   ├── TK_Studio_V1_1.py        ← V1.1
│   ├── TK_Studio_V1_2.py        ← V1.2
│   ├── TK_Studio_V1_3.py        ← V1.3
│   ├── TK_Studio_V1_4.py        ← V1.4
│   ├── TK_Studio_V1_5.py        ← V1.5
│   ├── TK_Studio_V1_6_1.py      ← V1.6.1
│   ├── TK_Studio_V1_6_2.py      ← V1.6.2
│   ├── TK_Studio_V1_6_3.py      ← V1.6.3
│   └── add_task_methods.py      ← 一次性迁移脚本
│
├── data/                        ← 运行时数据（gitignored）
│   └── probes/                  ← 探针脚本
│
├── dist/                        ← EXE 打包输出（gitignored）
│   └── TKStudio/
│       └── TKStudio.exe         ← 可执行文件（115 MB）
│
└── *.md                         ← 18 份阶段报告 + 发布文档
```

---

## 2. 发布产物

### 2.1 源码发布

| 项 | 值 |
|----|-----|
| Git commit | `61d271f` |
| 入口 | `TK_Studio_V1_6_4.py` |
| Python 版本 | 3.8+ |
| 依赖 | 4 个（PySide6 / requests / urllib3 / websocket-client） |

### 2.2 EXE 发布

| 项 | 值 |
|----|-----|
| EXE 路径 | `dist\TKStudio\TKStudio.exe` |
| 目录大小 | 115 MB |
| 打包模式 | onedir |
| 控制台 | 隐藏（GUI 模式） |
| 目标系统 | Windows 10/11 64-bit |
| 依赖 | Chrome 浏览器（登录/抓取用） |

### 2.3 分发方式

**源码分发：**
```cmd
git clone <repo>
cd TK_Studio_V1_fixed
pip install -r requirements.txt
python TK_Studio_V1_6_4.py
```

**EXE 分发：**
- 复制整个 `dist\TKStudio\` 目录到目标机器
- 双击 `TKStudio.exe` 启动
- 无需安装 Python

---

## 3. 文档清单

| 类别 | 文件 |
|------|------|
| 发布文档 | FINAL_RELEASE_CHECKLIST.md / RELEASE_NOTES.md / PHASE_HISTORY.md |
| 冻结文档 | PHASE6_G_RELEASE_FREEZE.md / PHASE5_C3_FINAL_FREEZE_REPORT.md |
| 源码文档 | FINAL_SOURCE_MAP.md / RELEASE_STRUCTURE.md（本文档） |
| Phase 报告 | PHASE5_*.md × 13 / PHASE6_*.md × 2 |
| QA 报告 | FINAL_RELEASE_REPORT.md / PHASE6_E_MANUAL_ACCEPTANCE_REPORT.md |

---

## 4. 清理操作记录

### 4.1 已归档（10 文件）

| 文件 | 原位置 | 新位置 | 原因 |
|------|--------|--------|------|
| main.py | 根目录 | archive/ | 旧 demo，无 Phase 5 功能 |
| TK_Studio_V1_1.py | 根目录 | archive/ | V1.1 旧版本 |
| TK_Studio_V1_2.py | 根目录 | archive/ | V1.2 旧版本 |
| TK_Studio_V1_3.py | 根目录 | archive/ | V1.3 旧版本 |
| TK_Studio_V1_4.py | 根目录 | archive/ | V1.4 旧版本 |
| TK_Studio_V1_5.py | 根目录 | archive/ | V1.5 旧版本 |
| TK_Studio_V1_6_1.py | 根目录 | archive/ | V1.6.1 旧版本 |
| TK_Studio_V1_6_2.py | 根目录 | archive/ | V1.6.2 旧版本 |
| TK_Studio_V1_6_3.py | 根目录 | archive/ | V1.6.3 旧版本 |
| add_task_methods.py | 根目录 | archive/ | 一次性迁移脚本 |

### 4.2 已删除

| 文件 | 原因 |
|------|------|
| `tests/tiktok_home_dom_probe - 副本.py` | 临时副本 |
| `build/` | PyInstaller 中间文件 |

### 4.3 未修改

- ✅ `core/*.py` — 16 文件全部未修改
- ✅ `workers/*.py` — 5 文件全部未修改
- ✅ `TK_Studio_V1_6_4.py` — 入口文件未修改
- ✅ `tests/*.py` — 9 文件全部未修改

---

## 5. 质量验证

| 检查项 | 结果 |
|--------|------|
| 入口唯一性 | ✅ 根目录仅 1 个 .py（TK_Studio_V1_6_4.py） |
| 入口可用性 | ✅ `import TK_Studio_V1_6_4` → ENTRY_OK |
| 引用完整性 | ✅ 入口引用链完整，无断裂 |
| 旧版本无引用 | ✅ 10 个归档文件零引用 |
| 冻结边界 | ✅ core/workers/TK_Studio 未修改 |
| 编译 | ✅ 45 文件全 PASS |
| 测试 | ✅ 81 项全 PASS |

---

## 6. 最终结论

**发布结构清晰，源码入口唯一，归档完整，可发布。**

- 根目录仅保留唯一入口 `TK_Studio_V1_6_4.py`
- 10 个旧版本/脚本已归档到 `archive/`（不删除，历史保留）
- `core/` + `workers/` + `tests/` 结构清晰
- EXE 打包产物在 `dist/TKStudio/`
- 文档齐全（20+ 份报告）
