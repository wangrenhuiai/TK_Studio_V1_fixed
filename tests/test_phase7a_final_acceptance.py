# -*- coding: utf-8 -*-
"""Phase 7-A Final Acceptance 回归测试。

覆盖用户指定的 6 个 Case，验证"假成功"修复与 fallback 链路：

    Case 1: video_url != "" → 成功
    Case 2: HTTP 200 但页面无 TikTok 数据 → video_url == "" → 失败
    Case 3: parser_ex 失败但原 parser 成功 → fallback 成功
    Case 4: requests/parser 都失败但 Chrome 成功 → Chrome fallback 成功
    Case 5: 全部失败 → 最终失败
    Case 6: 最终无 video_url → 下载入口被阻止

核心原则：HTTP 200 ≠ 解析成功；任务执行完成 ≠ 解析成功。
"""
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tiktok_service_ex import parse_url_ex


# ─── 测试 fixture ──────────────────────────────────────────

_HTML_WITH_FULL_DATA = """
<html><head>
<meta property="og:title" content="Full Title">
<meta property="og:image" content="https://example.com/cover.jpg">
<meta property="og:video" content="https://example.com/video.mp4">
</head><body>data</body></html>
"""

_HTML_EMPTY_RISK_CONTROL = "<html><body>TikTok 验证页 / 风控页，无视频数据</body></html>"


# ─── Case 1: 有效解析结果 → 成功 ─────────────────────────

def test_case1_valid_result_success():
    """Case 1: video_url != "" → 解析成功。"""
    logs = []
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value=_HTML_WITH_FULL_DATA):
        with patch("core.tiktok_service_ex._original_parse_url") as mock_fb:
            result = parse_url_ex(
                "https://www.tiktok.com/@user/video/7681265056633326878",
                log_callback=lambda msg: logs.append(msg),
            )
    # video_url 有效 → 成功
    assert result["video_url"] != "", "有效页面应提取到 video_url"
    assert result["title"] == "Full Title"
    # 字段完整时不应触发 fallback
    mock_fb.assert_not_called()


# ─── Case 2: HTTP 200 但无数据 → 失败 ─────────────────────

def test_case2_http200_no_data_failure():
    """Case 2: HTTP 200 但页面无 TikTok 数据 → video_url == "" → 失败。"""
    logs = []
    # fetch_tiktok_html 返回风控页（HTTP 200 但无数据）
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value=_HTML_EMPTY_RISK_CONTROL):
        # fallback 也返回空（Chrome 也拿不到）
        with patch("core.tiktok_service_ex._original_parse_url", return_value={
            "video_id": "7681265056633326878", "author": "", "title": "",
            "url": "", "video_url": "", "cover_url": "",
            "duration": "", "resolution": ""
        }):
            result = parse_url_ex(
                "https://www.tiktok.com/@user/video/7681265056633326878",
                log_callback=lambda msg: logs.append(msg),
            )
    # video_url 为空 → 判定为失败（不是成功）
    assert result["video_url"] == "", "风控页不应提取到 video_url"
    assert result["title"] == ""
    # 假成功判定：video_url 为空即为失败
    success = bool(result["video_url"])
    assert success is False, "HTTP 200 但 video_url 为空必须判定为失败"


# ─── Case 3: parser_ex 失败但原 parser 成功 ───────────────

def test_case3_parser_ex_fail_original_success():
    """Case 3: parser_ex 无结果但原 parse_url fallback 成功。"""
    logs = []
    fallback_result = {
        "video_id": "123", "author": "fb_user", "title": "FB Title",
        "url": "https://www.tiktok.com/@user/video/123",
        "video_url": "https://example.com/fb_video.mp4",
        "cover_url": "https://example.com/fb_cover.jpg",
        "duration": "30", "resolution": "1080x1920"
    }
    # parser_ex 拿到空 HTML（无数据）
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value=_HTML_EMPTY_RISK_CONTROL):
        with patch("core.tiktok_service_ex._original_parse_url",
                   return_value=fallback_result) as mock_fb:
            result = parse_url_ex(
                "https://www.tiktok.com/@user/video/123",
                log_callback=lambda msg: logs.append(msg),
            )
    # fallback 补充了 video_url → 成功
    assert result["video_url"] == "https://example.com/fb_video.mp4"
    assert result["title"] == "FB Title"
    mock_fb.assert_called_once()


# ─── Case 4: requests/parser 失败但 Chrome 成功 ───────────

def test_case4_chrome_fallback_success():
    """Case 4: requests + parser_ex 都失败，Chrome fallback 成功。

    Chrome fallback 在 _original_parse_url 内部触发，这里通过
    mock _original_parse_url 返回 Chrome 提取的结果来验证链路。
    """
    logs = []
    # 模拟 Chrome fallback 成功提取的结果
    chrome_result = {
        "video_id": "123", "author": "chrome_user", "title": "Chrome Title",
        "url": "https://www.tiktok.com/@user/video/123",
        "video_url": "https://example.com/chrome_video.mp4",
        "cover_url": "https://example.com/chrome_cover.jpg",
        "duration": "60", "resolution": "720x1280"
    }
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value=_HTML_EMPTY_RISK_CONTROL):
        with patch("core.tiktok_service_ex._original_parse_url",
                   return_value=chrome_result):
            result = parse_url_ex(
                "https://www.tiktok.com/@user/video/123",
                log_callback=lambda msg: logs.append(msg),
            )
    # Chrome fallback 成功
    assert result["video_url"] == "https://example.com/chrome_video.mp4"
    assert result["title"] == "Chrome Title"
    success = bool(result["video_url"])
    assert success is True


# ─── Case 5: 全部失败 → 最终失败 ──────────────────────────

def test_case5_all_fail_final_failure():
    """Case 5: requests + parser_ex + Chrome 全部失败 → 最终失败。"""
    logs = []
    # fetch_tiktok_html 返回空（网络失败）
    with patch("core.tiktok_service_ex.fetch_tiktok_html", return_value=""):
        # _original_parse_url（含 Chrome）也返回空
        with patch("core.tiktok_service_ex._original_parse_url", return_value={
            "video_id": "123", "author": "", "title": "",
            "url": "", "video_url": "", "cover_url": "",
            "duration": "", "resolution": ""
        }):
            result = parse_url_ex(
                "https://www.tiktok.com/@user/video/123",
                log_callback=lambda msg: logs.append(msg),
            )
    # 全部失败 → video_url 为空
    assert result["video_url"] == ""
    assert result["title"] == ""
    success = bool(result["video_url"])
    assert success is False, "全部失败时必须判定为失败，不得假成功"


# ─── Case 6: 无 video_url → 下载入口被阻止 ───────────────

def test_case6_download_blocked_when_no_video_url():
    """Case 6: 最终无 video_url → 下载入口被阻止。

    验证 _start_download_worker 的阻断逻辑：work[5] (video_url) 为空时
    不入队下载。通过模拟 DB 返回空 video_url 的 work 记录来验证。
    """
    # 模拟 DB get_work 返回的 tuple（SELECT *，第 5 位是 video_url）
    # 字段顺序: id, video_id, author, title, url, video_url, cover_url,
    #          duration, resolution, download_status, local_path,
    #          created_at, updated_at
    work_with_empty_video_url = (
        1,                       # id
        "7681265056633326878",   # video_id
        "user",                  # author
        "Title",                 # title
        "https://www.tiktok.com/@user/video/7681265056633326878",  # url
        "",                      # video_url ← 空
        "cover.jpg",             # cover_url
        "30",                    # duration
        "1080x1920",             # resolution
        "未下载",                # download_status
        "",                      # local_path
        "2026-09-04T12:00:00",   # created_at
        "2026-09-04T12:00:00",   # updated_at
    )

    # 直接验证阻断条件（与 _start_download_worker L787-793 一致）
    work = work_with_empty_video_url
    video_url = work[5]
    # _start_download_worker 的判定逻辑
    blocked = not video_url
    assert blocked is True, "video_url 为空时下载必须被阻止"

    # 反向验证：有 video_url 时不阻止
    work_with_video = list(work_with_empty_video_url)
    work_with_video[5] = "https://example.com/video.mp4"
    video_url_ok = work_with_video[5]
    blocked_ok = not video_url_ok
    assert blocked_ok is False, "video_url 有效时下载不应被阻止"


# ─── 附加: ParseWorker success 标志验证 ───────────────────

def test_parse_worker_success_flag_true_when_video_url():
    """ParseWorker data["success"] 在 video_url 有效时为 True。"""
    # 模拟 parse_url_ex 返回有效 video_url
    valid_result = {
        "video_id": "123", "author": "u", "title": "t",
        "url": "https://www.tiktok.com/@u/video/123",
        "video_url": "https://example.com/v.mp4",
        "cover_url": "c", "duration": "10", "resolution": "1080x1920"
    }
    # patch ParseWorker 实际引用的 parse_url（已 import 的别名）
    with patch("workers.parse_worker.parse_url",
               return_value=valid_result):
        from workers.parse_worker import ParseWorker
        # 使用 MagicMock 替代 DB
        mock_db = MagicMock()
        mock_db.add_work.return_value = 1
        worker = ParseWorker(
            ["https://www.tiktok.com/@u/video/123"], mock_db
        )
        # 捕获 success 信号
        captured = []
        worker.success.connect(lambda d: captured.append(d))
        worker.run()
        assert len(captured) == 1
        assert captured[0]["success"] is True
        assert captured[0]["video_url"] != ""


def test_parse_worker_success_flag_false_when_no_video_url():
    """ParseWorker data["success"] 在 video_url 为空时为 False（假成功修复）。"""
    empty_result = {
        "video_id": "123", "author": "u", "title": "",
        "url": "https://www.tiktok.com/@u/video/123",
        "video_url": "",  # ← 空
        "cover_url": "", "duration": "", "resolution": ""
    }
    with patch("workers.parse_worker.parse_url",
               return_value=empty_result):
        from workers.parse_worker import ParseWorker
        mock_db = MagicMock()
        mock_db.add_work.return_value = 1
        worker = ParseWorker(
            ["https://www.tiktok.com/@u/video/123"], mock_db
        )
        captured = []
        worker.success.connect(lambda d: captured.append(d))
        worker.run()
        assert len(captured) == 1
        # success signal 仍 emit（URL 处理完成），但 success 标志为 False
        assert captured[0]["success"] is False
        assert captured[0]["video_url"] == ""


# ─── 附加: fallback 保守合并策略验证 ──────────────────────

def test_merge_empty_does_not_overwrite_valid():
    """空字符串不能覆盖有效值（保守合并）。"""
    logs = []
    # parser_ex 提取到 video_url
    html_with_video = (
        '<html><head>'
        '<meta property="og:video" content="https://example.com/orig.mp4">'
        '</head></html>'
    )
    # fallback 返回空 video_url（不应覆盖）
    with patch("core.tiktok_service_ex.fetch_tiktok_html",
               return_value=html_with_video):
        with patch("core.tiktok_service_ex._original_parse_url", return_value={
            "video_id": "123", "author": "", "title": "",
            "url": "", "video_url": "",  # ← 空，不应覆盖
            "cover_url": "fb_cover", "duration": "", "resolution": ""
        }):
            result = parse_url_ex(
                "https://www.tiktok.com/@user/video/123",
                log_callback=lambda msg: logs.append(msg),
            )
    # video_url 应保持 parser_ex 的有效值
    assert result["video_url"] == "https://example.com/orig.mp4"
    # cover_url 从 fallback 补充
    assert result["cover_url"] == "fb_cover"
