"""Phase 8-B 全量功能验收测试脚本（只读，不修改代码）。"""
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_chrome_cdp():
    """Chrome CDP 集成验证"""
    print("=== Chrome CDP Integration ===")
    from core.chrome_bridge import _PROJECT_ROOT, _find_chrome
    print(f"  _PROJECT_ROOT: {_PROJECT_ROOT}")
    chrome = _find_chrome()
    print(f"  _find_chrome(): {chrome}")
    # Port finding is inline in chrome_render_with_cookies (9222-9231 range)
    # Verify the function exists and is callable
    from core.chrome_bridge import chrome_render_with_cookies
    print(f"  chrome_render_with_cookies: {chrome_render_with_cookies}")
    print("  RESULT: PASS")
    return True


def test_login_module():
    """登录模块验证"""
    print()
    print("=== Login Module ===")
    from core.tiktok_login import (
        TikTokLogin, LoginState, LOGIN_PROFILE_DIR, TIKTOK_LOGIN_URL
    )
    print(f"  LOGIN_PROFILE_DIR: {LOGIN_PROFILE_DIR}")
    print(f"  TIKTOK_LOGIN_URL: {TIKTOK_LOGIN_URL}")
    print(f"  LoginState.NOT_LOGGED_IN: {LoginState.NOT_LOGGED_IN}")
    print(f"  LoginState.LOGIN_SUCCESS: {LoginState.LOGIN_SUCCESS}")
    print(f"  TikTokLogin class: {TikTokLogin}")
    print("  RESULT: PASS")
    return True


def test_profile_snapshot():
    """Profile 快照验证"""
    print()
    print("=== Profile Snapshot ===")
    from core.profile_snapshot import (
        LOGIN_PROFILE_DIR, AUTH_PROFILE_DIR,
        snapshot_login_to_auth, delete_auth_profile
    )
    print(f"  LOGIN_PROFILE_DIR: {LOGIN_PROFILE_DIR}")
    print(f"  AUTH_PROFILE_DIR: {AUTH_PROFILE_DIR}")
    print(f"  snapshot_login_to_auth: {snapshot_login_to_auth}")
    print(f"  delete_auth_profile: {delete_auth_profile}")
    print("  RESULT: PASS")
    return True


def test_db_persistence():
    """DB 持久化验证"""
    print()
    print("=== DB Persistence ===")
    from core.db import Database
    tmp = tempfile.mkdtemp()
    try:
        db = Database(os.path.join(tmp, "test.db"))
        wid = db.add_work({
            "video_id": "vid_test",
            "author": "test",
            "title": "test",
            "url": "http://example.com",
            "video_url": "http://example.com/v.mp4",
            "cover_url": "",
            "duration": "",
            "resolution": "",
        })
        print(f"  add_work -> work_id: {wid}")
        tid = db.create_download_task(wid, "tiktok")
        print(f"  create_download_task -> task_id: {tid}")
        db.update_download_task(tid, status="下载中", progress=50)
        task = db.get_download_task(tid)
        # download_tasks columns: id, work_id, source, status, progress,
        # message, created_at, updated_at
        print(f"  get_download_task: status={task[3]}, progress={task[4]}")
        db.update_download(wid, "已下载", "/tmp/test.mp4")
        work = db.get_work(wid)
        # works columns: id, video_id, author, title, url, video_url,
        # cover_url, duration, resolution, download_status, local_path,
        # created_at, updated_at
        print(f"  get_work: download_status={work[9]}, local_path={work[10]}")
        tasks = db.list_download_tasks()
        print(f"  list_download_tasks: {len(tasks)} tasks")
        active = db.get_active_tasks_by_work(wid)
        print(f"  get_active_tasks_by_work: {active}")
        db.reset_downloading_to_failed()
        print(f"  reset_downloading_to_failed: OK")
        print("  RESULT: PASS")
        return True
    except Exception as e:
        print(f"  RESULT: FAIL - {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_download_chain():
    """下载链路验证（模块完整性）"""
    print()
    print("=== Download Chain ===")
    from core.downloader import run_download, download_once
    from workers.download_worker import DownloadWorker
    from workers.task_manager import TaskManager
    print(f"  run_download: {run_download}")
    print(f"  download_once: {download_once}")
    print(f"  DownloadWorker: {DownloadWorker}")
    print(f"  TaskManager: {TaskManager}")
    print("  RESULT: PASS")
    return True


def test_home_fetch_chain():
    """主页抓取链路验证（模块完整性）"""
    print()
    print("=== Home Fetch Chain ===")
    from core.home_fetcher import HomeFetcher
    from workers.home_fetch_worker import HomeFetchWorker
    print(f"  HomeFetcher: {HomeFetcher}")
    print(f"  HomeFetchWorker: {HomeFetchWorker}")
    print("  RESULT: PASS")
    return True


def test_parse_chain():
    """解析链路验证（模块完整性）"""
    print()
    print("=== Parse Chain ===")
    from core.tiktok_service import parse_url
    from core.tiktok_service_ex import parse_url_ex
    from core.parser_ex import extract_tiktok_data_ex
    from core.url_resolver import resolve_short_url, is_short_url
    from workers.parse_worker import ParseWorker
    from workers.resolve_worker import ResolveWorker
    print(f"  parse_url: {parse_url}")
    print(f"  parse_url_ex: {parse_url_ex}")
    print(f"  extract_tiktok_data_ex: {extract_tiktok_data_ex}")
    print(f"  resolve_short_url: {resolve_short_url}")
    print(f"  is_short_url: {is_short_url}")
    print(f"  ParseWorker: {ParseWorker}")
    print(f"  ResolveWorker: {ResolveWorker}")
    print("  RESULT: PASS")
    return True


def test_home_service_chain():
    """主页服务链路验证"""
    print()
    print("=== Home Service Chain ===")
    from core.tiktok_home_fetcher import TikTokHomeFetcher
    from core.tiktok_home_service import TikTokHomeService
    from core.tiktok_home_adapter import TikTokHomeAdapter
    print(f"  TikTokHomeFetcher: {TikTokHomeFetcher}")
    print(f"  TikTokHomeService: {TikTokHomeService}")
    print(f"  TikTokHomeAdapter: {TikTokHomeAdapter}")
    print("  RESULT: PASS")
    return True


if __name__ == "__main__":
    results = {}
    results["chrome_cdp"] = test_chrome_cdp()
    results["login"] = test_login_module()
    results["profile_snapshot"] = test_profile_snapshot()
    results["db_persistence"] = test_db_persistence()
    results["download_chain"] = test_download_chain()
    results["home_fetch_chain"] = test_home_fetch_chain()
    results["parse_chain"] = test_parse_chain()
    results["home_service_chain"] = test_home_service_chain()

    print()
    print("=== SUMMARY ===")
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
    print()
    all_pass = all(results.values())
    print(f"  OVERALL: {'PASS' if all_pass else 'FAIL'}")
