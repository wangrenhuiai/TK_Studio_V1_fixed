# Release Notes — TK Studio V1.6.4 + Phase 5

> 版本：V1.6.4 + Phase 5 全量增强
> 发布日期：2026-09-04
> 前一版本：V1.6.3（Initial commit + core/workers）

---

## 新增功能

### TikTok 主页采集链路（Phase 5-B1.x / B2.x）

- 新增 TikTok 主页 URL → 作品列表抓取链路
- 支持 HomeFetchWorker QThread 后台抓取，不阻塞 UI
- 主页作品自动去重入库（video_id UNIQUE）
- 匿名模式（anonymous profile）抓取，不干扰登录态

### 登录态管理与 Snapshot（Phase 5-B3.x）

- 扫码登录后自动 snapshot 到 auth profile（B3.4）
- Auth 模式主页抓取使用登录态 profile
- 登出自动清理 auth profile + metadata
- Snapshot 失败优雅降级到匿名模式

### TikTok 短链解析（Phase 5-B4.x）

- 支持 `vm.tiktok.com` / `vt.tiktok.com` / `www.tiktok.com/t/` 短链
- 短链自动解析为标准 `/video/` URL
- HEAD 优先 + GET fallback + urllib3 Retry（total=2）
- TTL 缓存（300s）+ LRU 淘汰（256）+ 线程安全

### ResolveWorker 后台化（Phase 5-C1）

- 短链解析移入 QThread 后台线程，不阻塞 UI
- 批量短链逐条解析 + 实时日志反馈
- closeEvent 保护（运行中退出提示）

### Parser JSON Layer（Phase 5-C1 / C2）

- 支持 3 种 TikTok JSON blob：`__UNIVERSAL_DATA_FOR_REHYDRATION__` / `SIGI_STATE` / `__NEXT_DATA__`
- 正则结果优先，JSON 只补充缺失字段
- `extract_tiktok_data_ex` + `extract_json_data` 别名

### Retry Wrapper（Phase 5-C2）

- `create_retry_session()` — Retry(total=3, backoff=1, 429/5xx)
- `fetch_tiktok_html(url)` — 带 Retry 的 HTML 获取层
- 不修改冻结的 tiktok_service.py

### UI 状态优化（Phase 5-C3）

- 解析按钮运行时显示 "解析中..."（与 home 按钮一致）
- 完成时恢复 "开始解析" 文本
- 异常路径无条件恢复按钮状态

---

## 改进

- TaskManager 互斥 + 排队 + 并发上限（max=3）
- CloseEvent 标记活动下载为失败
- 进度 DB 写入节流（≥1% 或 ≥2s）
- Chrome profile 独立目录（避免锁冲突）

---

## 测试

- 81 项单元测试全 PASS（0.32s）
- 45 个 Python 文件编译全 PASS
- 10 个核心模块 import OK
- 实网探针 17/19 PASS（2 项 FAIL 为 TikTok 反爬限流）

---

## 已知问题

1. **`main.py` 是旧 demo 版本** — 不含 Phase 5 功能，正式入口为 `TK_Studio_V1_6_4.py`
2. **TikTok 反爬限流** — 短时间重复解析同一 URL 可能失败，等待 30s 重试
3. **tiktok_request + parser_ex 未集成生产链路** — 独立能力，后续 Phase 集成

---

## 依赖

| 依赖 | 版本 |
|------|------|
| PySide6 | >=6.8,<7 |
| requests | >=2.31 |
| urllib3 | >=2.0 |
| websocket-client | >=1.6 |

---

## 启动方式

```cmd
cd d:\TK_Studio_V1_fixed
python TK_Studio_V1_6_4.py
```
