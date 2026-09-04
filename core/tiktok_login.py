"""TikTok 扫码登录模块。

通过 Chrome DevTools Protocol (CDP) 启动可见 Chrome 窗口，
打开 TikTok 官方登录页，让用户使用手机扫码完成登录。
登录态通过 Cookie 名称存在性 + 页面状态组合检测，
持久化保存在独立 Profile 中，重启后可复用。

设计原则：
- 不逆向 TikTok 登录协议，让 Chrome 自己完成网页登录
- 独立持久化 Profile（chrome_login_profile/），不删除
- 不复制用户真实 Chrome Profile 数据
- 日志只记录 Cookie 名称/存在性，禁止输出 Cookie value/token
- 不依赖 PySide6（纯 Python，可被 Worker 或脚本调用）
"""
import os
import re
import json
import time
import subprocess
import urllib.request


# 项目根目录（core/tiktok_login.py 的上一级）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 持久化登录 Profile 目录（与 chrome_cdp_profile/ 隔离，不混用下载 cookie）
LOGIN_PROFILE_DIR = os.path.join(_PROJECT_ROOT, "chrome_login_profile")

# TikTok 官方登录页
TIKTOK_LOGIN_URL = "https://www.tiktok.com/login/qrcode"

# TikTok 主页（用于检测登录后状态）
TIKTOK_HOME_URL = "https://www.tiktok.com/"

# 登录相关 Cookie 名称集合（只检测名称存在性，不读取 value）
LOGIN_COOKIE_NAMES = {
    "sessionid",
    "sessionid_ss",
    "sid_tt",
    "sid_guard",
    "passport_auth_status",
    "passport_auth_status_ss",
    "passport_csrf_token",
    "uid_tt",
    "uid_tt_ss",
}

# 最可靠的登录成功指标：sessionid 存在
_REQUIRED_LOGIN_COOKIE = "sessionid"


class LoginState:
    """登录状态分级常量。

    使用字符串常量而非 bool，便于 UI 和 Worker 扩展。
    """
    UNKNOWN = "unknown"
    LOGIN_PAGE = "login_page"          # 在登录页，尚未出现二维码
    QR_WAITING = "qr_waiting"          # 二维码已显示，等待扫码
    QR_SCANNED = "qr_scanned"          # 已扫码，等待手机确认
    LOGIN_SUCCESS = "login_success"    # 登录成功
    LOGIN_FAILED = "login_failed"      # 登录失败（页面错误等）
    TIMEOUT = "timeout"                # 超时
    NOT_LOGGED_IN = "not_logged_in"    # 检查持久化 Profile 时未发现登录态


def _find_chrome():
    """查找本机 Chrome 可执行文件路径（与 chrome_bridge 一致的逻辑）。"""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    return next((x for x in candidates if os.path.exists(x)), None)


class TikTokLogin:
    """TikTok 扫码登录管理器。

    生命周期：
        start_login_session()  → 启动可见 Chrome + CDP，打开登录页
        poll_login_state()     → 轮询检测登录状态（可多次调用）
        check_existing_login() → 独立 headless 检查持久化登录态
        shutdown()             → 关闭本次 Chrome 会话（Profile 保留）

    线程安全：本类实例方法不可跨线程并发调用；
    在 LoginWorker 中由 Worker 线程独占访问。
    """

    def __init__(self):
        self._proc = None
        self._ws = None
        self._cdp = None
        self._port = None
        self._active = False
        # headless 登录态检查（check_existing_login）的临时进程句柄，
        # 仅供 abort_check() 在程序退出时快速回收，不影响可见登录会话。
        self._check_proc = None

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def start_login_session(self, log_callback=None, initial_wait=12):
        """启动可见 Chrome，打开 TikTok 登录页。

        启动后 Chrome 窗口可见，用户可看到二维码并扫码。
        Profile 持久化保存在 LOGIN_PROFILE_DIR，下次可复用。

        Args:
            log_callback: 日志回调
            initial_wait: 打开登录页后等待秒数（让二维码加载）

        Returns:
            str: 初始 LoginState（通常为 LOGIN_PAGE 或 QR_WAITING）

        Raises:
            RuntimeError: Chrome 找不到 / CDP 连接失败 / 页面加载失败
        """
        self._log(log_callback, "启动 TikTok 登录会话...")

        chrome_path = _find_chrome()
        if not chrome_path:
            raise RuntimeError("未找到 Chrome 可执行文件")

        os.makedirs(LOGIN_PROFILE_DIR, exist_ok=True)
        self._log(log_callback, f"使用持久化 Profile：{LOGIN_PROFILE_DIR}")

        try:
            self._proc, self._ws, self._cdp, self._port = self._start_visible_chrome(
                chrome_path, LOGIN_PROFILE_DIR, startup_url=TIKTOK_LOGIN_URL
            )
            self._active = True

            # 启用 CDP 域
            self._cdp("Page.enable")
            self._cdp("Network.enable")

            # 导航到登录页
            self._log(log_callback, f"打开登录页：{TIKTOK_LOGIN_URL}")
            self._cdp("Page.navigate", {"url": TIKTOK_LOGIN_URL})
            time.sleep(initial_wait)

            # 检测初始状态
            state = self._classify_state(log_callback)
            self._log(log_callback, f"初始登录状态：{state}")
            return state

        except Exception:
            # 启动失败时立即清理
            self.shutdown(log_callback)
            raise

    def poll_login_state(self, log_callback=None):
        """轮询当前登录状态。

        必须在 start_login_session() 之后调用。

        Returns:
            str: LoginState 常量
        """
        if not self._active:
            return LoginState.NOT_LOGGED_IN

        return self._classify_state(log_callback)

    def check_existing_login(self, log_callback=None):
        """用 headless Chrome 快速检查持久化 Profile 是否已登录。

        不弹出可见窗口，适合程序启动时调用。
        启动临时 headless 会话检查 Cookie，不影响后续可见登录会话。

        Args:
            log_callback: 日志回调

        Returns:
            bool: True 表示已登录（sessionid 存在），False 表示未登录
        """
        self._log(log_callback, "检查持久化登录态（headless）...")

        if not os.path.exists(LOGIN_PROFILE_DIR):
            self._log(log_callback, "Profile 目录不存在，未登录")
            return False

        chrome_path = _find_chrome()
        if not chrome_path:
            raise RuntimeError("未找到 Chrome 可执行文件")

        proc = None
        ws = None
        cdp = None
        try:
            proc, ws, cdp, _ = self._start_headless_chrome(
                chrome_path, LOGIN_PROFILE_DIR
            )
            self._check_proc = proc
            cdp("Page.enable")
            cdp("Network.enable")
            cdp("Page.navigate", {"url": TIKTOK_HOME_URL})
            time.sleep(8)

            present = self._get_login_cookie_names(cdp)
            logged_in = _REQUIRED_LOGIN_COOKIE in present
            self._log(
                log_callback,
                f"持久化登录态检查：{'已登录' if logged_in else '未登录'} "
                f"(sessionid: {'present' if _REQUIRED_LOGIN_COOKIE in present else 'absent'})"
            )
            return logged_in

        except Exception as e:
            self._log(log_callback, f"登录态检查失败：{e}")
            return False
        finally:
            self._check_proc = None
            self._cleanup_session(proc, ws, log_callback, cdp)

    def logout(self, log_callback=None):
        """清除持久化 Profile 的登录态。

        删除整个 Profile 目录，下次启动 Chrome 会重新开始。
        如果有活动会话，先关闭。

        Args:
            log_callback: 日志回调

        Returns:
            bool: True 表示清除成功
        """
        self._log(log_callback, "登出：清除持久化 Profile...")

        # 先关闭活动会话
        if self._active:
            self.shutdown(log_callback)

        try:
            import shutil
            if os.path.exists(LOGIN_PROFILE_DIR):
                shutil.rmtree(LOGIN_PROFILE_DIR, ignore_errors=True)
                self._log(log_callback, "Profile 目录已删除")
            else:
                self._log(log_callback, "Profile 目录不存在，无需清除")
            return True
        except Exception as e:
            self._log(log_callback, f"登出失败：{e}")
            return False

    def shutdown(self, log_callback=None):
        """关闭本次 Chrome 会话（Profile 保留）。

        无论成功/失败/取消/超时都应调用，确保无僵尸 Chrome。
        Profile 不删除，下次 start_login_session 可复用登录态。
        """
        if not self._active and not self._proc and not self._ws:
            return

        self._cleanup_session(self._proc, self._ws, log_callback, self._cdp)
        self._proc = None
        self._ws = None
        self._cdp = None
        self._port = None
        self._active = False

    def abort_check(self):
        """终止进行中的 headless 登录态检查（check_existing_login）。

        用于程序退出时快速回收 headless Chrome（典型 <2s），
        避免等待 check 自然完成（~10s）。不影响可见登录会话。
        """
        proc = self._check_proc
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _start_visible_chrome(self, chrome_path, profile_dir,
                              startup_url="about:blank"):
        """启动可见 Chrome（无 --headless），返回 (proc, ws, cdp_func, port)。

        用户可看到 Chrome 窗口，用于扫码登录。
        FIX-A.3-2：启动 URL 直接使用登录页（替代 about:blank），
        使正确的页面 target 从启动即存在。
        """
        return self._start_chrome(chrome_path, profile_dir, headless=False,
                                  startup_url=startup_url)

    def _start_headless_chrome(self, chrome_path, profile_dir):
        """启动 headless Chrome，返回 (proc, ws, cdp_func, port)。

        用于 check_existing_login() 的静默检查。
        """
        return self._start_chrome(chrome_path, profile_dir, headless=True)

    def _start_chrome(self, chrome_path, profile_dir, headless=True,
                      startup_url="about:blank"):
        """启动 Chrome + CDP 会话。

        复用 chrome_bridge.py 的端口扫描和 CDP 连接模式，
        但使用独立 LOGIN_PROFILE_DIR，且可选择 headless/visible。

        FIX-A.3-2：CDP target 不再盲选 /json 的 pages[0]。非 headless Chrome
        会加载组件扩展，pages[0] 可能是 chrome-extension:// 后台页，导致
        Page.navigate 导航失败、可见标签页停在 about:blank、二维码不显示。
        现按 type=="page" 过滤，优先 http(s) 页面，再优先 tiktok.com 页面；
        无 http 页面时（headless 启动于 about:blank）回退首个 page target，
        保持 check_existing_login 原行为。
        """
        # 端口扫描：9222-9231
        port = None
        for candidate in range(9222, 9232):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{candidate}/json/version", timeout=0.3
                ):
                    continue
            except Exception:
                port = candidate
                break

        if port is None:
            raise RuntimeError("无可用 CDP 端口（9222-9231 均被占用）")

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        cmd = [
            chrome_path,
            "--disable-gpu",
            "--disable-extensions",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--autoplay-policy=no-user-gesture-required",
            "--remote-allow-origins=*",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--profile-directory=Default",
        ]
        # visible 模式不加 --headless；headless 检查时加 --headless=new + CREATE_NO_WINDOW
        if headless:
            cmd.insert(1, "--headless=new")
        else:
            # 可见窗口时不要 CREATE_NO_WINDOW（否则窗口不显示）
            creationflags = 0
        # FIX-A.3-2：可见登录会话的启动 URL 直接使用登录页
        cmd.append(startup_url)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

        # FIX2 异常安全：Popen 成功后，若 CDP endpoint 探测 / WebSocket / CDP
        # 初始化在 return 前抛异常，proc 句柄会滞留本函数局部变量，
        # 调用方元组解包不完成、finally 拿不到 proc，将留下 Chrome 孤儿
        # 并锁住 login profile（FIX1 诊断确认的泄漏路径）。
        # 因此 return 前的任何异常都必须先回收 Chrome 进程，再向上传递原异常。
        try:
            # 等待 CDP endpoint 就绪
            # FIX-A.3-2：按 target 类型与 URL 过滤，避免连到扩展后台页
            endpoint = None
            for _ in range(50):
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/json", timeout=0.5
                    ) as resp:
                        pages = json.loads(resp.read().decode("utf-8", "ignore"))
                    page_targets = [
                        p for p in pages if p.get("type") == "page"
                    ]
                    http_pages = [
                        p for p in page_targets
                        if str(p.get("url") or "").startswith("http")
                    ]
                    pool = http_pages or page_targets or pages
                    tiktok_pages = [
                        p for p in pool
                        if "tiktok.com" in (p.get("url") or "")
                    ]
                    chosen = (tiktok_pages or pool)[0]
                    endpoint = chosen.get("webSocketDebuggerUrl")
                    if endpoint:
                        break
                except Exception:
                    pass
                time.sleep(0.2)

            if not endpoint:
                raise RuntimeError("Chrome CDP endpoint 启动失败")

            import websocket
            ws = websocket.create_connection(endpoint, timeout=15)
            seq = [0]

            def cdp(method, params=None):
                """发送 CDP 命令并等待响应。"""
                seq[0] += 1
                ident = seq[0]
                ws.send(json.dumps({
                    "id": ident, "method": method, "params": params or {}
                }))
                deadline = time.time() + 30
                while time.time() < deadline:
                    raw = ws.recv()
                    msg = json.loads(raw)
                    if msg.get("id") == ident:
                        if "error" in msg:
                            raise RuntimeError(f"CDP 错误 {method}: {msg['error']}")
                        return msg.get("result", {})
                raise RuntimeError(f"CDP 超时：{method}")

            return proc, ws, cdp, port
        except Exception:
            # 回收已启动的 Chrome：terminate → wait → 必要时 kill → wait
            try:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    try:
                        proc.kill()
                        proc.wait(timeout=2)
                    except Exception:
                        pass
            except Exception:
                pass
            raise

    def _classify_state(self, log_callback=None):
        """组合检测当前登录状态。

        检测维度：
        A. Cookie：sessionid 等登录相关 cookie 是否存在
        B. 页面 URL：是否仍在 /login 页
        C. 页面内容：是否有用户头像等已登录标识

        只记录 Cookie 名称/存在性，不输出 value。
        """
        try:
            # A. Cookie 检查
            present_cookies = self._get_login_cookie_names(self._cdp)
            has_sessionid = _REQUIRED_LOGIN_COOKIE in present_cookies

            # 安全日志：只记录名称和存在性
            cookie_summary = ", ".join(
                f"{name}: present" for name in sorted(present_cookies)
            ) or "(none)"
            self._log(log_callback, f"Login cookies: {cookie_summary}")

            # B. 如果 sessionid 存在，判定为登录成功
            if has_sessionid:
                self._log(log_callback, "登录状态：login_success")
                return LoginState.LOGIN_SUCCESS

            # C. 页面状态检查（URL + 内容）
            page_info = self._get_page_info(self._cdp)
            current_url = page_info.get("url", "")
            body_text = page_info.get("body_text", "")

            self._log(log_callback, f"页面 URL：{_truncate(current_url, 80)}")

            # 判断是否在登录页
            is_login_page = "/login" in current_url.lower()

            if is_login_page:
                # 检查是否有二维码（QR code canvas 或 img）
                # TikTok 登录页通常有二维码图片元素
                has_qr = self._has_qr_code(self._cdp)
                if has_qr:
                    self._log(log_callback, "登录状态：qr_waiting")
                    return LoginState.QR_WAITING
                else:
                    self._log(log_callback, "登录状态：login_page")
                    return LoginState.LOGIN_PAGE

            # 不在登录页且没有 sessionid —— 可能正在跳转或未登录
            # 检查是否有用户头像等已登录标识
            if self._has_user_avatar(self._cdp):
                # 页面显示用户内容但 cookie 尚未同步 —— 视为成功
                self._log(log_callback, "登录状态：login_success (page indicator)")
                return LoginState.LOGIN_SUCCESS

            # 默认：仍在登录流程中
            self._log(log_callback, "登录状态：qr_waiting (default)")
            return LoginState.QR_WAITING

        except Exception as e:
            self._log(log_callback, f"状态检测异常：{e}")
            return LoginState.LOGIN_FAILED

    def _get_login_cookie_names(self, cdp):
        """获取当前存在的登录相关 Cookie 名称集合（不含 value）。"""
        try:
            result = cdp("Network.getAllCookies")
            cookies = result.get("cookies", [])
            present = set()
            for item in cookies:
                name = item.get("name", "")
                if name in LOGIN_COOKIE_NAMES:
                    present.add(name)
            return present
        except Exception:
            return set()

    def _get_page_info(self, cdp):
        """获取当前页面 URL 和 body 文本（不输出敏感内容）。"""
        info = {"url": "", "body_text": ""}
        try:
            eval_result = cdp("Runtime.evaluate", {
                "expression": (
                    "JSON.stringify({"
                    "url: window.location.href,"
                    "body: (document.body && document.body.innerText) ? "
                    "document.body.innerText.substring(0, 500) : ''"
                    "})"
                ),
                "returnByValue": True
            })
            value = (eval_result.get("result") or {}).get("value", "")
            if value:
                try:
                    parsed = json.loads(value)
                    info["url"] = parsed.get("url", "")
                    info["body_text"] = parsed.get("body", "")
                except Exception:
                    pass
        except Exception:
            pass
        return info

    def _has_qr_code(self, cdp):
        """检测页面是否有二维码元素（canvas/img with QR-related class/id）。"""
        try:
            eval_result = cdp("Runtime.evaluate", {
                "expression": (
                    "(() => {"
                    "  const qr = document.querySelector("
                    "    'canvas[id*=\"qr\"], img[id*=\"qr\"], "
                    "    div[class*=\"qrcode\"], div[class*=\"qr-code\"], "
                    "    canvas[class*=\"qr\"], img[src*=\"qrcode\"],"
                    "    div[data-e2e=\"qr-code\"], div[role=\"img\"]"
                    "  );"
                    "  return qr !== null;"
                    "})()"
                ),
                "returnByValue": True
            })
            return (eval_result.get("result") or {}).get("value", False)
        except Exception:
            return False

    def _has_user_avatar(self, cdp):
        """检测页面是否显示用户头像（已登录标识）。"""
        try:
            eval_result = cdp("Runtime.evaluate", {
                "expression": (
                    "(() => {"
                    "  const avatar = document.querySelector("
                    "    'img[alt*=\"avatar\"], img[data-e2e=\"avatar\"], "
                    "    div[data-e2e=\"user-avatar\"], "
                    "    img[src*=\"avatar\"]"
                    "  );"
                    "  return avatar !== null;"
                    "})()"
                ),
                "returnByValue": True
            })
            return (eval_result.get("result") or {}).get("value", False)
        except Exception:
            return False

    def _cleanup_session(self, proc, ws, log_callback=None, cdp=None):
        """清理单个 CDP 会话。优先正常关闭 Chrome，确保 Profile 数据完成落盘。"""
        # 1. 优先通过 CDP 请求 Chrome 正常关闭
        #    给 Chrome 机会完成 Cookie / Profile 数据持久化。
        try:
            if cdp:
                try:
                    cdp("Browser.close")
                except Exception:
                    pass
        except Exception:
            pass

        # 2. 关闭 WebSocket
        try:
            if ws:
                ws.close()
        except Exception:
            pass

        # 3. 等待 Chrome 正常退出
        #    只有无法正常退出时才使用 terminate / kill。
        try:
            if proc:
                proc.wait(timeout=8)
        except Exception:
            try:
                if proc:
                    proc.terminate()
                    proc.wait(timeout=3)
            except Exception:
                try:
                    if proc:
                        proc.kill()
                        proc.wait(timeout=2)
                except Exception:
                    pass

        if log_callback:
            self._log(log_callback, "Chrome 会话已关闭（Profile 已保留）")

    def _log(self, callback, message):
        """安全调用日志回调。"""
        if callback:
            try:
                callback(message)
            except Exception:
                pass


def _truncate(text, max_len=80):
    """截断文本用于日志显示。"""
    if not text:
        return ""
    return text[:max_len] + ("..." if len(text) > max_len else "")
