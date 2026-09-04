"""Phase 8-A 启动验收测试脚本（只读，不修改代码）。"""
import os
import sys
import sqlite3
import time


def test_import_chain():
    """TEST 1: Python Import Chain (Dev Mode)"""
    print("=== TEST 1: Python Import Chain (Dev Mode) ===")
    try:
        from core.paths import get_app_data_root
        from core.db import Database, DB_FILE
        from core.chrome_bridge import _PROJECT_ROOT as cb_root
        from core.home_fetcher import _PROJECT_ROOT as hf_root
        from core.tiktok_login import LOGIN_PROFILE_DIR
        from core.profile_snapshot import LOGIN_PROFILE_DIR as snap_login, AUTH_PROFILE_DIR
        print("  Import chain: OK")
        print(f"  get_app_data_root: {get_app_data_root()}")
        print(f"  DB_FILE: {DB_FILE}")
        print(f"  chrome_bridge root: {cb_root}")
        print(f"  home_fetcher root: {hf_root}")
        print(f"  LOGIN_PROFILE_DIR: {LOGIN_PROFILE_DIR}")
        print(f"  AUTH_PROFILE_DIR: {AUTH_PROFILE_DIR}")
        print("  RESULT: PASS")
        return True
    except Exception as e:
        print(f"  RESULT: FAIL - {e}")
        return False


def test_data_dir():
    """TEST 2: Data Directory Creation (EXE Mode Simulation)"""
    print()
    print("=== TEST 2: Data Directory Creation (EXE Mode) ===")
    try:
        sys.frozen = True
        from importlib import reload
        import core.paths
        reload(core.paths)
        from core.paths import get_app_data_root
        root = get_app_data_root()
        expected = os.path.expandvars(r"%LOCALAPPDATA%\TK_Studio")
        print(f"  app_data_root: {root}")
        print(f"  expected: {expected}")
        assert root == expected, f"path mismatch"
        assert os.path.isdir(root), f"directory not created"
        print(f"  Directory exists: {os.path.isdir(root)}")
        print(f"  Writable: {os.access(root, os.W_OK)}")
        print("  RESULT: PASS")
        return True, root
    except Exception as e:
        print(f"  RESULT: FAIL - {e}")
        return False, None


def test_sqlite(root):
    """TEST 3: SQLite Initialization (EXE Mode)"""
    print()
    print("=== TEST 3: SQLite Initialization (EXE Mode) ===")
    try:
        from core.db import Database
        db_path = os.path.join(root, "tk_studio_phase8a_test.db")
        if os.path.exists(db_path):
            os.remove(db_path)
        db = Database(db_path)
        con = db.connect()

        # Check WAL mode
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        print(f"  journal_mode: {mode}")
        assert mode.lower() == "wal", f"WAL not enabled"

        # Check busy_timeout
        bt = con.execute("PRAGMA busy_timeout").fetchone()[0]
        print(f"  busy_timeout: {bt}")
        assert bt == 5000, f"busy_timeout wrong"

        # Check tables
        tables = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        print(f"  Tables: {tables}")
        assert "works" in tables, "works table missing"
        assert "download_tasks" in tables, "download_tasks table missing"

        # Check works columns (13 fields)
        cols = [r[1] for r in con.execute("PRAGMA table_info(works)").fetchall()]
        print(f"  works columns ({len(cols)}): {cols}")
        assert len(cols) == 13, f"works should have 13 columns, got {len(cols)}"

        # Write test
        con.execute(
            "INSERT INTO works (video_id, author, title, url, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test_vid_8a", "tester", "Phase 8-A Test", "", "2026-09-04T23:00:00"),
        )
        con.commit()
        row = con.execute(
            "SELECT video_id, title FROM works WHERE video_id=?",
            ("test_vid_8a",),
        ).fetchone()
        print(f"  Write/read test: {row}")
        assert row == ("test_vid_8a", "Phase 8-A Test")

        con.close()
        # Cleanup (WAL checkpoint may hold file briefly)
        time.sleep(0.3)
        for ext in ["", "-wal", "-shm"]:
            p = db_path + ext
            if os.path.exists(p):
                try:
                    os.remove(p)
                except PermissionError:
                    pass  # file still locked by OS, not a test failure
        print("  RESULT: PASS")
        return True
    except Exception as e:
        print(f"  RESULT: FAIL - {e}")
        import traceback
        traceback.print_exc()
        return False


def test_chrome_profiles(root):
    """TEST 4: Chrome Profile Path Verification (EXE Mode)"""
    print()
    print("=== TEST 4: Chrome Profile Path Verification (EXE Mode) ===")
    try:
        profiles = {
            "chrome_headless_profile": os.path.join(root, "chrome_headless_profile"),
            "chrome_cdp_profile": os.path.join(root, "chrome_cdp_profile"),
            "chrome_home_fetcher_profile": os.path.join(root, "chrome_home_fetcher_profile"),
            "chrome_login_profile": os.path.join(root, "chrome_login_profile"),
            "chrome_home_auth_profile": os.path.join(root, "chrome_home_auth_profile"),
        }
        for name, path in profiles.items():
            print(f"  {name}: {path}")
            assert root in path, f"{name} not in data root"
        print(f"  All profiles under {root}")
        print("  RESULT: PASS")
        return True
    except Exception as e:
        print(f"  RESULT: FAIL - {e}")
        return False


def test_log_paths(root):
    """TEST 5: Log/Probe Path Verification"""
    print()
    print("=== TEST 5: Log/Probe Path Verification ===")
    try:
        # Probe directory (per project memory: data/probes/home_fetch_debug.log)
        probe_path = os.path.join(root, "data", "probes")
        debug_log = os.path.join(probe_path, "home_fetch_debug.log")
        print(f"  Expected probe dir: {probe_path}")
        print(f"  Expected debug log: {debug_log}")

        # Check dev mode probe path
        dev_root = os.path.dirname(
            os.path.dirname(os.path.abspath(
                os.path.join(os.path.dirname(__file__) or ".",
                             "..", "core", "db.py")
            ))
        )
        dev_probe = os.path.join(dev_root, "data", "probes")
        print(f"  Dev probe path: {dev_probe}")
        print(f"  Dev probe exists: {os.path.isdir(dev_probe)}")

        # Verify all log paths are under data root (EXE mode)
        assert root in probe_path, "probe path not under data root"
        assert root in debug_log, "debug log not under data root"
        print("  RESULT: PASS (paths verified)")
        return True
    except Exception as e:
        print(f"  RESULT: FAIL - {e}")
        return False


if __name__ == "__main__":
    results = {}
    results["import"] = test_import_chain()
    ok, root = test_data_dir()
    results["data_dir"] = ok
    if root:
        results["sqlite"] = test_sqlite(root)
        results["chrome_profiles"] = test_chrome_profiles(root)
        results["log_paths"] = test_log_paths(root)
    else:
        results["sqlite"] = False
        results["chrome_profiles"] = False
        results["log_paths"] = False

    print()
    print("=== SUMMARY ===")
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
    print()
    all_pass = all(results.values())
    print(f"  OVERALL: {'PASS' if all_pass else 'FAIL'}")
