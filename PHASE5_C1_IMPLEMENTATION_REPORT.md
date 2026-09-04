# Phase 5-C1 实施报告 — ResolveWorker 后台化 + Parser JSON Layer

> 阶段：Phase 5-C1（方案 B + 方案 A）
> 实施时间：2026-09-04 14:53 ~ 14:58 (+08:00)
> 基线：[PHASE5_C_DESIGN_OPTIONS.md](file:///d:/TK_Studio_V1_fixed/PHASE5_C_DESIGN_OPTIONS.md) 推荐组合 1（A+B+C）
> 状态：实施完成，等待验收

---

## 1. 修改文件列表

### 1.1 新增文件（3 个）

| 文件 | 行数 | 说明 |
|------|------|------|
| [workers/resolve_worker.py](file:///d:/TK_Studio_V1_fixed/workers/resolve_worker.py) | 105 | 方案 B — ResolveWorker QThread 封装短链解析 |
| [core/parser_ex.py](file:///d:/TK_Studio_V1_fixed/core/parser_ex.py) | 240 | 方案 A — 结构化 JSON 解析层（SIGI_STATE / UNIVERSAL_DATA / NEXT_DATA） |
| [tests/test_parser_ex.py](file:///d:/TK_Studio_V1_fixed/tests/test_parser_ex.py) | 252 | 方案 A — 26 项单元测试 |

### 1.2 修改文件（1 个）

| 文件 | 修改区域 | 说明 |
|------|----------|------|
| [TK_Studio_V1_6_4.py](file:///d:/TK_Studio_V1_fixed/TK_Studio_V1_6_4.py) | L18, L167-170, L547-654, L1178-1182, L1213-1214 | 方案 B — parse_single 后台化集成 + closeEvent 扩展 |

---

## 2. 方案 B — ResolveWorker 后台化

### 2.1 问题
B4.3 加 Retry 后，最坏单短链耗时 60s。`parse_single` 在主线程同步调用 `resolve_short_url`，批量短链输入 = N×60s UI 阻塞。

### 2.2 解决方案
新增 [workers/resolve_worker.py](file:///d:/TK_Studio_V1_fixed/workers/resolve_worker.py)：

```python
class ResolveWorker(QThread):
    resolved = Signal(dict)      # 逐条完成
    finished_ok = Signal(list)   # 全部完成
    log = Signal(str)            # 日志
```

**parse_single 两阶段流程**：

```
URL 输入
 ↓
has_short = any(is_short_url(u) for u in urls)
 ↓
├─ 无短链 → _validate_and_parse(urls) → ParseWorker
└─ 有短链 → ResolveWorker(urls) 后台线程
              ↓ resolved 信号 → _on_url_resolved（日志展示）
              ↓ finished_ok → _on_resolve_finished
              → _validate_and_parse(resolved_urls) → ParseWorker
```

### 2.3 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| ResolveWorker 独立 QThread | ✅ | 职责分离，镜像 ParseWorker 模式 |
| 无短链时跳过 ResolveWorker | ✅ | 避免无谓线程启动开销 |
| 逐条 resolved 信号 | ✅ | 用户实时看到解析进度 |
| closeEvent 加入 resolve_running | ✅ | 防止退出时 Worker 残留 |
| _pending_urls 暂存 | ✅ | resolve 完成后传递给 validate |

### 2.4 新增方法

| 方法 | 位置 | 说明 |
|------|------|------|
| `_on_url_resolved(item)` | L584 | 逐条解析回调，展示短链转换日志 |
| `_on_resolve_finished(results)` | L599 | 全部完成回调，汇总后走校验+ParseWorker |
| `_on_resolve_worker_finished()` | L616 | 线程结束清理，释放 _resolve_worker |
| `_validate_and_parse(urls)` | L620 | 统一 URL 校验 + ParseWorker 启动（从原 parse_single 提取） |

---

## 3. 方案 A — Parser JSON Layer

### 3.1 问题
[core/parser.py](file:///d:/TK_Studio_V1_fixed/core/parser.py) 完全基于正则，TikTok 页面结构变化时脆弱。新版页面主数据在 `SIGI_STATE` / `__UNIVERSAL_DATA_FOR_REHYDRATION__` JSON blob 中。

### 3.2 解决方案
新增 [core/parser_ex.py](file:///d:/TK_Studio_V1_fixed/core/parser_ex.py)：

```python
def extract_tiktok_data_ex(html):
    # 1. 尝试从 JSON blob 提取结构化数据
    json_data = _extract_structured_json(html)
    # 2. 原正则解析（兜底，始终执行）
    base = extract_tiktok_data(html)
    # 3. 无 JSON blob → 返回正则结果
    if not json_data: return base
    # 4. 从 JSON 提取结构化字段
    structured = _parse_from_structured(json_data)
    # 5. 合并：JSON 补充正则缺失
    return _merge(base, structured)
```

### 3.3 支持的 JSON blob 格式

| 优先级 | Script ID | 路径 | 说明 |
|--------|-----------|------|------|
| 1 | `__UNIVERSAL_DATA_FOR_REHYDRATION__` | `__DEFAULT_SCOPE__.webapp.video-detail.itemInfo.itemStruct` | 新版页面 |
| 2 | `SIGI_STATE` | `ItemModule.<video_id>` | 旧版页面 |
| 3 | `__NEXT_DATA__` | `props.pageProps.itemInfo.itemStruct` | Next.js 框架 |

### 3.4 字段映射

| JSON 路径 | 输出字段 |
|-----------|----------|
| `author.uniqueId` | `author` |
| `desc` | `title` |
| `video.cover` | `image` |
| `video.playAddr` | `video_url` |
| `video.duration` | `duration` |
| `video.width` × `video.height` | `resolution` |

### 3.5 合并策略

- 正则有值 → 保留正则结果（保守，不破坏现有行为）
- 正则为空 → JSON 补充
- JSON 解析失败 → 回退纯正则

### 3.6 集成方式

**当前未集成到 tiktok_service.py / parse_worker.py**（冻结模块）。
parser_ex 作为独立能力提供，后续可通过 wrapper（方案 C）集成。

---

## 4. API 兼容确认

### 4.1 ResolveWorker API

| 接口 | 签名 | 兼容性 |
|------|------|--------|
| `ResolveWorker(urls)` | 构造函数 | 新增，不影响现有 |
| `resolved` 信号 | `Signal(dict)` | 新增 |
| `finished_ok` 信号 | `Signal(list)` | 新增 |
| `log` 信号 | `Signal(str)` | 新增 |

### 4.2 parser_ex API

| 接口 | 签名 | 兼容性 |
|------|------|--------|
| `extract_tiktok_data_ex(html)` | 输入 HTML，返回 dict | 新增，不影响现有 |
| 输出字段 | `{author, title, image, video_url, duration, resolution}` | 与原 `extract_tiktok_data` 完全一致 |

### 4.3 parse_single 行为兼容

| 场景 | B4.3 行为 | C1 行为 | 兼容 |
|------|-----------|---------|------|
| 无短链 URL | 直接校验+ParseWorker | 直接校验+ParseWorker（_validate_and_parse） | ✅ |
| 有短链 URL | 主线程同步 resolve | 后台 ResolveWorker + 完成后校验+ParseWorker | ✅（行为等价，异步化） |
| 短链解析失败 | 保留原 URL | 保留原 URL | ✅ |
| 短链解析成功 | 替换为 resolved URL | 替换为 resolved URL | ✅ |
| 日志文案 | `🔗 TikTok短链解析:` | `🔗 TikTok短链解析:` | ✅ |
| 按钮禁用 | parse 开始时禁用 | resolve 开始时禁用 | ✅（更早禁用） |

### 4.4 closeEvent 兼容

| 场景 | B4.3 行为 | C1 行为 | 兼容 |
|------|-----------|---------|------|
| ResolveWorker 运行中退出 | 不检查（B4.3 无 Worker） | 检查 + 提示 + 进程退出终止 | ✅ 新增保护 |

---

## 5. 测试结果

### 5.1 py_compile

```
resolve_worker.py: exit 0 ✅
parser_ex.py: exit 0 ✅
TK_Studio_V1_6_4.py: exit 0 ✅
```

### 5.2 Import 检查

```
from core.parser_ex import extract_tiktok_data_ex
from workers.resolve_worker import ResolveWorker
→ IMPORT_OK ✅
```

### 5.3 pytest

```
50 passed in 0.25s
```

| 测试文件 | 用例数 | 结果 |
|----------|--------|------|
| tests/test_parser_ex.py | 26 | ✅ 全 PASS |
| tests/test_url_resolver.py | 24 | ✅ 全 PASS（B4.3 回归） |

#### test_parser_ex.py 覆盖

| 测试类 | 用例数 | 覆盖内容 |
|--------|--------|----------|
| TestExtractStructuredJson | 6 | SIGI/UNIVERSAL/NEXT_DATA/无 blob/无效 JSON/优先级 |
| TestParseFromStructured | 6 | SIGI/UNIVERSAL/NEXT_DATA/空/None/无 ItemModule |
| TestFillFromItem | 4 | 完整 item/缺 video/author 为字符串/duration 为浮点 |
| TestMerge | 2 | JSON 补充正则缺失/双方均空 |
| TestExtractTiktokDataEx | 8 | SIGI/UNIVERSAL/NEXT_DATA HTML/meta 回退/空 HTML/无效 JSON 回退/字段一致性/JSON 补充 meta |

---

## 6. 冻结边界确认

### 6.1 C1 时间窗

14:53:32 ~ 14:58:09

### 6.2 修改文件

| 文件 | 修改时间 | 允许范围 |
|------|----------|----------|
| `workers/resolve_worker.py` | 14:53:32 | ✅ 新增 |
| `TK_Studio_V1_6_4.py` | 14:55:00 | ✅ UI 层可改 |
| `core/parser_ex.py` | 14:57:13 | ✅ 新增 |
| `tests/test_parser_ex.py` | 14:58:09 | ✅ 新增 |

### 6.3 冻结文件未触碰确认

| 冻结文件 | 最近修改时间 | C1 是否触碰 |
|----------|-------------|-------------|
| `core/parser.py` | 2026/9/3 11:42 | 否 ✅ |
| `core/tiktok_service.py` | 2026/9/3 13:28 | 否 ✅ |
| `core/downloader.py` | 2026/9/3 16:20 | 否 ✅ |
| `core/db.py` | 2026/9/3 23:49 | 否 ✅ |
| `workers/parse_worker.py` | 2026/9/3 16:51 | 否 ✅ |
| `workers/login_worker.py` | 2026/9/3 18:57 | 否 ✅ |
| `core/tiktok_login.py` | 2026/9/4 02:28 | 否 ✅ |
| `workers/task_manager.py` | 2026/9/4 02:46 | 否 ✅ |
| `core/tiktok_home_fetcher.py` | 2026/9/4 11:23 | 否 ✅ |
| `core/home_fetcher.py` | 2026/9/4 12:45 | 否 ✅ |
| `core/tiktok_home_service.py` | 2026/9/4 12:45 | 否 ✅ |
| `core/tiktok_home_worker.py` | 2026/9/4 12:46 | 否 ✅ |
| `core/home_worker.py` | 2026/9/4 12:46 | 否 ✅ |
| `workers/home_fetch_worker.py` | 2026/9/4 12:46 | 否 ✅ |
| `core/profile_snapshot.py`（B3.4） | 2026/9/4 13:16 | 否 ✅ |
| `core/url_resolver.py`（B4.3） | 2026/9/4 14:34 | 否 ✅（B4.3 已冻结） |

**所有冻结文件最近修改时间均早于 C1 时间窗（14:53）。**

### 6.4 B3.4 登录 snapshot / B3.1 profile_dir / M1-M5 登录 UI

- B3.4 `profile_snapshot.py` 未触碰 ✅
- B3.1 `profile_dir` 相关代码未触碰 ✅
- M1-M5 登录 UI 区域未触碰 ✅

---

## 7. 风险评估

| 风险项 | 严重度 | 缓解措施 |
|--------|--------|----------|
| ResolveWorker 生命周期管理 | 低 | closeEvent 加入 resolve_running 检查 + _on_resolve_worker_finished 清理 |
| 信号竞态（快速多次点击解析） | 低 | parse_single 检查 _resolve_worker is not None 拒绝重复 |
| parser_ex JSON 字段路径与实际 TikTok 页面不符 | 中 | 保守合并策略（正则优先），需实网验证 |
| parser_ex 未集成到生产链路 | 低 | 当前为独立能力，方案 C 将集成 |
| ResolveWorker 异常未传播 | 低 | run() 内 try/except 兜底，失败返回原 URL |

---

## 8. 下一阶段建议

1. **方案 C（tiktok_service Retry wrapper）**：集成 parser_ex 到生产链路
   - 新增 `core/tiktok_service_ex.py` wrapper
   - 修改 `workers/parse_worker.py` 调用 wrapper（需确认 parse_worker.py 可改）
   - 或在 UI 层间接集成

2. **parser_ex 实网验证**：用真实 TikTok 视频页面 HTML 验证 JSON blob 提取
   - 抓取真实视频页面 HTML 样本
   - 验证 SIGI_STATE / UNIVERSAL_DATA 字段路径
   - 补充测试用例

3. **方案 E（UI 进度总览面板）**：利用 ResolveWorker 的 resolved 信号做进度可视化

---

## 9. 回滚方案

如需回滚 C1：

1. 删除 `workers/resolve_worker.py`
2. 删除 `core/parser_ex.py`
3. 删除 `tests/test_parser_ex.py`
4. 还原 `TK_Studio_V1_6_4.py` 到 B4.3 验收时状态（git checkout 或手动还原 parse_single/closeEvent/__init__ 区域）

回滚后恢复到 B4.3 验收 PASS 状态。
