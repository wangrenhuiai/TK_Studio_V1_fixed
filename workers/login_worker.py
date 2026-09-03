"""登录 Worker（Qt 线程层）。

LoginWorker(QThread) 负责：
- 在后台线程启动可见 Chrome + CDP 登录会话
- 轮询登录状态（不阻塞 Qt 主线程）
- 通过 Qt Signal 向 GUI 报告 status_changed / login_success / login_failed / finished

此模块是 core 与 GUI 之间的桥接层，core/tiktok_login.py 不依赖 PySide6。
Worker 内部禁止任何 UI 操作，所有 UI 更新通过信号回到主线程。

生命周期与 DownloadWorker/ParseWorker 一致：
- 主线程创建 → start() → run() 在 Worker 线程执行
- finished 信号连接到 deleteLater（由调用方负责）
- cancel() 由主线程调用，置位 _cancel 标志，Worker 线程在下个检查点退出
"""
import time

from PySide6.QtCore import QThread, Signal

from core.tiktok_login import TikTokLogin, LoginState


# 登录轮询间隔（秒）
_POLL_INTERVAL = 3

# 登录超时（秒，5 分钟）
_LOGIN_TIMEOUT = 300


class LoginWorker(QThread):
    """TikTok 扫码登录后台 Worker。

    启动可见 Chrome 打开 TikTok 登录页，轮询登录状态，
    登录成功或超时后关闭 Chrome（Profile 保留）。

    Signals:
        status_changed(str): 登录状态变化（LoginState 常量）
        log(str): 日志消息
        login_success(): 登录成功
        login_failed(str): 登录失败/超时/取消（携带原因）
        finished(): Worker 结束（QThread 内置信号，run() 返回时自动发射）
    """

    status_changed = Signal(str)
    log = Signal(str)
    login_success = Signal()
    login_failed = Signal(str)

    def __init__(self, timeout=_LOGIN_TIMEOUT, poll_interval=_POLL_INTERVAL):
        super().__init__()
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._cancel = False
        self._login = TikTokLogin()

    def cancel(self):
        """请求取消登录。仅置位标志，由轮询循环检查后退出并清理 Chrome。"""
        self._cancel = True

    def run(self):
        """Worker 线程入口。

        流程：
        1. 启动可见 Chrome + CDP，打开 TikTok 登录页
        2. 轮询登录状态，每 _poll_interval 秒检查一次
        3. 登录成功 → 发射 login_success
        4. 超时/取消/失败 → 发射 login_failed
        5. finally: 关闭 Chrome 会话（Profile 保留），run() 返回时 QThread 自动发射 finished
    """
        log_cb = lambda msg: self.log.emit(msg)

        try:
            # 1. 启动登录会话
            try:
                initial_state = self._login.start_login_session(
                    log_callback=log_cb
                )
            except Exception as e:
                self.login_failed.emit(f"启动登录会话失败：{e}")
                return

            # 检查取消
            if self._cancel:
                self.login_failed.emit("用户取消登录")
                return

            self.status_changed.emit(initial_state)

            # 如果启动时已登录（Profile 复用），直接成功
            if initial_state == LoginState.LOGIN_SUCCESS:
                self.login_success.emit()
                return

            # 2. 轮询登录状态
            deadline = time.time() + self._timeout
            last_state = initial_state

            while time.time() < deadline and not self._cancel:
                time.sleep(self._poll_interval)

                if self._cancel:
                    break

                state = self._login.poll_login_state(log_callback=log_cb)

                # 状态变化时发射信号
                if state != last_state:
                    self.status_changed.emit(state)
                    last_state = state

                # 登录成功
                if state == LoginState.LOGIN_SUCCESS:
                    self.login_success.emit()
                    return

                # 登录失败
                if state == LoginState.LOGIN_FAILED:
                    self.login_failed.emit("登录失败（页面错误）")
                    return

            # 3. 超时或取消
            if self._cancel:
                self.status_changed.emit(LoginState.UNKNOWN)
                self.login_failed.emit("用户取消登录")
            else:
                self.status_changed.emit(LoginState.TIMEOUT)
                self.login_failed.emit("登录超时（5 分钟未完成扫码）")

        except Exception as e:
            self.login_failed.emit(f"登录异常：{e}")

        finally:
            # 4. 关闭 Chrome 会话（Profile 保留），run() 返回后 QThread 自动发射 finished
            try:
                self._login.shutdown(log_callback=log_cb)
            except Exception:
                pass
