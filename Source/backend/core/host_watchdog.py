# ============================================
# FTN Studio 宿主存活监控 (HostWatchdog)
#
# 问题场景：
#   Electron 被异常强杀（任务管理器、崩溃）时不触发 before-quit，
#   后端 FastAPI 进程可能残留 (孤儿进程)。
#
# 方案：
#   后端启动时，由 Electron 通过环境变量注入宿主 PID (FTN_HOST_PID)。
#   Watchdog 定期检查宿主进程是否存活；
#   若宿主消失，则判定为宿主异常退出，后端自动清理并自杀。
#
# 通过 Windows 系统 API 判断进程存活，无需额外依赖。
# ============================================

import os
import threading
import time
import ctypes
import sys

# Windows 进程查询：OpenProcess + WaitForSingleObject 判断是否存活
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_STILL_ACTIVE = 259  # STATUS_PENDING


def _is_process_alive_windows(pid):
    """判断 Windows 进程是否存活。"""
    kernel32 = ctypes.windll.kernel32
    # 尝试以受限信息权限打开进程
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE, False, pid)
    if not handle:
        # 打开失败：进程可能不存在或权限不足
        # 返回 False 以触发自杀（保守策略）
        return False
    try:
        # WaitForSingleObject 返回 WAIT_TIMEOUT 说明进程仍在运行
        result = kernel32.WaitForSingleObject(handle, 0)
        return result == 0x00000102  # WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


def is_process_alive(pid):
    """跨平台判断进程存活。"""
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            return _is_process_alive_windows(pid)
        except Exception:
            pass
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


class HostWatchdog:
    """宿主存活监控（后台线程，自动启动）。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self.host_pid = self._read_host_pid()
        self.interval = float(os.environ.get("FTN_HOST_CHECK_INTERVAL", "3"))
        self._stop = threading.Event()
        self._thread = None

    @staticmethod
    def _read_host_pid():
        """从环境变量读取宿主 (Electron) PID。"""
        raw = os.environ.get("FTN_HOST_PID", "")
        try:
            return int(raw) if raw else None
        except ValueError:
            return None

    @property
    def enabled(self):
        return self.host_pid is not None and self.host_pid > 0

    def start(self):
        """启动监控线程（仅当配置了宿主 PID 时）。"""
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def _watch(self):
        from core.log_manager import log_manager

        while not self._stop.is_set():
            if not is_process_alive(self.host_pid):
                log_manager.warn(
                    "backend",
                    f"检测到宿主进程 (pid={self.host_pid}) 已退出，FTN Studio 后端将自动清理退出",
                )
                # 触发退出（延迟一点确保日志写盘）
                threading.Timer(0.5, self._self_exit).start()
                break
            time.sleep(self.interval)

    def _self_exit(self):
        """宿主消失后，后端自我清理退出。"""
        # 兜底：先停掉由本程序拉起的引擎实例（避免异常退出时留下引擎孤儿进程）
        try:
            from core.runner import runner
            runner.stop_all()
        except Exception:
            pass
        try:
            from core.console_sessions import session_manager
            session_manager.list_sessions()
        except Exception:
            pass
        os._exit(0)

    def stop(self):
        """停止监控线程。"""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None


# 单例实例
watchdog = HostWatchdog()
