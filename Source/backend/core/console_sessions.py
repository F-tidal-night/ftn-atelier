# ============================================
# FTN Studio 控制台会话聚合（ConsoleSessionManager）
#
# 产品定论（对齐绘世）：
#   控制台不做「手动新建会话」，而是自动识别引擎启动带出的 cmd
#   进程并挂载进软件——每启动一个引擎实例自动新增一个标签，
#   名字与引擎对应（reForge / reForge #2 / WD1.4 ...），
#   关闭仅终止对应实例。引擎进程本身以 CREATE_NO_WINDOW 隐藏
#   （不弹独立 cmd 窗口），输出集成到软件内查看。
#
# 本模块只负责把 runner 的引擎实例快照转成控制台会话视图：
# - 仅「有 cmd 的引擎」进入控制台（webui.bat / 一键启动.bat /
#   launch.py 等脚本启动）；ftn_tag（html 工具）无 cmd，不占会话。
# - 实际运行才出现，不占位、不锁名。
# ============================================

import threading


class ConsoleSessionManager:
    """控制台会话视图（线程安全，单例）。"""

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._lock = threading.RLock()

    def list_sessions(self):
        """返回控制台会话列表（= 全部引擎实例，自动挂载，不占位）。"""
        return self._engine_sessions()

    def _engine_sessions(self):
        """引擎进程会话：由 runner 全部实例实时合成。

        仅「有 cmd 窗的引擎」进入控制台：bat / webui 脚本引擎；
        html（ftn_tag）与本地程序（exe）无 cmd 窗，不占会话。
        """
        from core.runner import runner
        from core.engine_registry import engine_registry
        try:
            insts = runner.engine_instances()
        except Exception:
            return []
        kinds = {}
        try:
            for e in engine_registry.list_engines():
                kinds[e.get("key")] = e.get("kind")
        except Exception:
            pass
        out = []
        for x in insts:
            key = x.get("engine")
            if kinds.get(key) in ("ftn_tag", "exe"):
                continue  # html / 本地 exe 无 cmd 窗，不进控制台
            num = x.get("instance") or 1
            label = x.get("label") or key
            out.append({
                "id": f"engine:{key}" if num == 1 else f"engine:{key}:{num}",
                "kind": "engine",
                "title": label if num == 1 else f"{label} #{num}",
                "engine_key": key,
                "pid": x.get("pid"),
                "status": x.get("status"),
                "exit_code": None,
                "log_source": x.get("log_source") or key,
                "command": "",
                "cwd": "",
                "started_at": None,
                "ended_at": None,
                "demo": bool(x.get("demo")),
            })
        return out


# 单例
session_manager = ConsoleSessionManager()
