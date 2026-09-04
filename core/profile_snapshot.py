"""Profile snapshot helper（Phase 5-B3.4）。

将登录态从 ``chrome_login_profile`` 快照到 ``chrome_home_auth_profile``，
使 ``HomeFetcher`` 能以登录态抓取主页（B3.2 auth 模式的填充机制）。

设计依据：B3.3 design review 推荐方案 A'（选择性目录复制）。

机制：
- 选择性复制：仅 Cookies + Local Storage + Local State（~5MB），跳过 Cache/History
- 触发时机：``LoginWorker.finished`` 之后（Chrome 已释放 profile 锁）
- 隔离：auth profile 是独立副本，不与登录 Chrome 共用，避免锁冲突/损坏/WAF 污染
- 失败恢复：snapshot 失败 → 调用方 fallback 匿名模式 + UI 提示

不触碰：
- ``core/tiktok_login.py``（A.4 冻结）
- ``workers/login_worker.py``（A.4 冻结）
- 不依赖 PySide6（纯 stdlib，可被任意线程调用）
"""
import os
import json
import shutil
import time


# FIX-EXE.1：profile/快照目录使用用户可写数据根目录（EXE 时 %LOCALAPPDATA%\TK_Studio）。
from core.paths import get_app_data_root
_PROJECT_ROOT = get_app_data_root()

# Profile 目录
LOGIN_PROFILE_DIR = os.path.join(_PROJECT_ROOT, "chrome_login_profile")
AUTH_PROFILE_DIR = os.path.join(_PROJECT_ROOT, "chrome_home_auth_profile")

# 选择性复制目标（相对于 profile 根目录）。
# 仅复制承载登录态的产物，跳过 Cache/History/GPUCache 等大体积无关数据。
_SNAPSHOT_TARGETS = [
    "Local State",                   # 顶层加密密钥（加密 cookie 需要）
    "Default/Cookies",               # SQLite cookie DB（sessionid 等）
    "Default/Network/Cookies",       # 新版 Chrome 网络 cookie
    "Default/Local Storage",          # localStorage（可能持有 token）
]

# 快照元数据文件（与 auth profile 并列）
_METADATA_FILE = os.path.join(_PROJECT_ROOT, "chrome_home_auth_profile.snapshot.json")


def snapshot_login_to_auth(log_callback=None):
    """将登录态从 login profile 快照到 auth profile。

    必须在 ``LoginWorker.shutdown()`` 完成后调用（Chrome 释放 profile 锁）。
    选择性复制保持 auth profile 体积小（~5MB）。

    流程：
    1. 校验 login profile 存在
    2. 清理旧 auth profile（避免残留陈旧文件）
    3. 选择性复制 ``_SNAPSHOT_TARGETS`` 中存在的文件/目录
    4. 写入快照元数据

    Args:
        log_callback: 可选日志回调 ``Callable[[str], None]``

    Returns:
        dict: ``{"success": bool, "error": str|None, "copied": list[str]}``
    """
    _log(log_callback, "B3.4: 开始快照 login profile → auth profile...")

    # 1. 校验源 profile
    if not os.path.isdir(LOGIN_PROFILE_DIR):
        msg = f"登录 profile 不存在：{LOGIN_PROFILE_DIR}（请先扫码登录）"
        _log(log_callback, f"快照失败：{msg}")
        return {"success": False, "error": msg, "copied": []}

    # 2. 清理旧 auth profile（避免残留陈旧文件混入新快照）
    try:
        if os.path.isdir(AUTH_PROFILE_DIR):
            shutil.rmtree(AUTH_PROFILE_DIR, ignore_errors=True)
            _log(log_callback, "已清理旧 auth profile")
    except Exception as e:
        _log(log_callback, f"清理旧 auth profile 警告：{e}（继续）")

    # 3. 选择性复制
    copied = []
    for rel in _SNAPSHOT_TARGETS:
        src = os.path.join(LOGIN_PROFILE_DIR, rel)
        dst = os.path.join(AUTH_PROFILE_DIR, rel)
        if not os.path.exists(src):
            # 不同 Chrome 版本结构可能不同，缺失则跳过
            continue
        try:
            _copy_path(src, dst)
            copied.append(rel)
        except Exception as e:
            _log(log_callback, f"复制 {rel} 失败：{e}")

    if not copied:
        msg = "未复制任何登录态产物（login profile 可能无 Cookies/Local Storage）"
        _log(log_callback, f"快照失败：{msg}")
        return {"success": False, "error": msg, "copied": []}

    # 4. 写入元数据
    try:
        _write_metadata(copied)
        _log(log_callback, f"快照完成：已复制 {len(copied)} 项 → {AUTH_PROFILE_DIR}")
    except Exception as e:
        _log(log_callback, f"元数据写入警告：{e}（快照仍可用）")

    return {"success": True, "error": None, "copied": copied}


def delete_auth_profile(log_callback=None):
    """删除 auth profile + 元数据（登出同步用）。

    在 ``on_logout_clicked`` 清除 login profile 后调用，确保 auth profile
    不残留过期登录态。

    Args:
        log_callback: 可选日志回调

    Returns:
        bool: True 表示清理完成（即使目录本就不存在）
    """
    _log(log_callback, "B3.4: 清理 auth profile 快照...")
    ok = True
    try:
        if os.path.isdir(AUTH_PROFILE_DIR):
            shutil.rmtree(AUTH_PROFILE_DIR, ignore_errors=True)
            _log(log_callback, "auth profile 已删除")
    except Exception as e:
        _log(log_callback, f"删除 auth profile 失败：{e}")
        ok = False
    try:
        if os.path.exists(_METADATA_FILE):
            os.remove(_METADATA_FILE)
    except Exception as e:
        _log(log_callback, f"删除快照元数据失败：{e}")
        ok = False
    return ok


def validate_snapshot():
    """检查 auth profile 快照是否存在且含元数据。

    用于 home auth 抓取前判断是否可复用登录态。

    Returns:
        dict: ``{"valid": bool, "metadata": dict|None, "path": str}``
    """
    if not os.path.isdir(AUTH_PROFILE_DIR):
        return {"valid": False, "metadata": None, "path": AUTH_PROFILE_DIR}
    if not os.path.exists(_METADATA_FILE):
        return {"valid": False, "metadata": None, "path": AUTH_PROFILE_DIR}
    try:
        with open(_METADATA_FILE, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return {"valid": True, "metadata": meta, "path": AUTH_PROFILE_DIR}
    except Exception:
        return {"valid": False, "metadata": None, "path": AUTH_PROFILE_DIR}


# ------------------------------------------------------------------
# 内部实现
# ------------------------------------------------------------------

def _copy_path(src, dst):
    """复制文件或目录树，自动创建父目录。"""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)


def _write_metadata(copied_artifacts):
    """写入快照元数据 JSON。"""
    meta = {
        "source_profile": "chrome_login_profile",
        "auth_profile": "chrome_home_auth_profile",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "method": "selective_copy",
        "copied_artifacts": list(copied_artifacts),
    }
    with open(_METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _log(callback, message):
    """安全调用日志回调。"""
    if callback:
        try:
            callback(message)
        except Exception:
            pass


__all__ = [
    "snapshot_login_to_auth",
    "delete_auth_profile",
    "validate_snapshot",
    "LOGIN_PROFILE_DIR",
    "AUTH_PROFILE_DIR",
]
