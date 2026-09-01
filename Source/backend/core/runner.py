# ============================================
# FTN Studio 引擎进程管理器 (Runner)
#
# 对应蓝图「首页 / Reforge 控制」：
#   一键启动 / 关闭 reForge webui，管理其生命周期。
#
# 职责：
# - 根据 AppConfig（engine_paths + start_args）构建启动参数
# - 启动子进程（webui）→ 探测就绪 → 标记运行中
# - 停止：通过 API/信号关闭 → 回收进程 → 标记已停止
# - 状态机：stopped → starting → running → stopping → stopped
# - 实时日志推送（log_manager → WebSocket）
# - 状态广播（status_manager → WebSocket）
# - 启动互斥（status_manager.try_acquire）
#
# 说明：
#   若检测到真实 reForge 根目录则真实启动 webui；
#   否则进入「演示模式」，仅模拟进程与状态流转，
#   保证 UI / 进程管理框架可完整联调（最终可切真实环境验证）。
# ============================================

import os
import sys
import time
import subprocess
import threading
import json
import urllib.request

from core.status import status_manager
from core.log_manager import log_manager, LOG_DIR
from core.config_manager import config_manager
from core.base_registry import base_registry
from core.diagnose import diagnose_log_file


class EngineStatus(str):
    """引擎状态枚举值（字符串便于序列化）。"""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class Runner:
    """引擎（reForge webui）生命周期管理器。"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self.status = EngineStatus.STOPPED
        self.process = None         # subprocess.Popen
        self.pid = None
        self._kind = "webui"        # 当前主实例类型（webui / batdir / ftn_tag / exe）
        self._start_token = 0       # 启动代际令牌：旧 _wait_ready 线程据此识别过期并退出
        self._demo_start = None     # 实例级演示启动时间（避免命中类属性）
        self.log_path = None        # webui 输出日志文件
        self._log_fh = None
        self._log_reader = None
        self._stop_event = threading.Event()
        # 可重入锁：start() 持锁时可能嵌套调用 _start_extra 等锁内方法
        self._lock = threading.RLock()
        self._demo = False          # 是否为演示模式
        self.ready_url = None       # webui 可访问地址
        self.engine_key = None      # 当前运行的引擎 key（多启动模式）
        # 多开额外实例（设置→引擎路径→多开开关开启后叠加启动）：
        # 每个实例独立进程/日志源/关闭控制，仅主实例占用互斥锁语义
        self._extras = []           # [{key,label,num,pid,process,log_path,log_source,status,ready_url,demo,_log_fh,_demo_start}]
        self._diagnosis = []        # 主实例启动失败诊断（日志关键词匹配）
        self._stats_history = []    # 占用趋势采样（{ts,engine,instance,rss_mb,gpu_mb}）

    # =================================================
    # 定位实际启动项
    # =================================================
    @staticmethod
    def _hidden_flags():
        """Windows 下禁止子进程弹出独立控制台窗口（引擎集成到软件内显示，对齐绘世）。"""
        if sys.platform == "win32":
            return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        return 0

    @staticmethod
    def _port_in_use(port):
        """端口是否被占用（127.0.0.1 bind 探测）。"""
        if not port:
            return False
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", int(port)))
            return False
        except OSError:
            return True
        finally:
            try:
                s.close()
            except Exception:
                pass

    def _port_occupant(self, port):
        """返回占用指定端口的进程描述（含是否为本程序引擎实例）。"""
        pid = None
        try:
            out = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True, text=True, errors="replace", timeout=6,
                creationflags=Runner._hidden_flags(),
            )
            for ln in out.stdout.splitlines():
                parts = ln.split()
                if len(parts) >= 5 and parts[0] == "TCP" and parts[3] in ("LISTENING", "LISTEN"):
                    if parts[1].endswith(f":{port}"):
                        try:
                            pid = int(parts[4])
                        except ValueError:
                            pid = None
                        break
        except Exception:
            pass
        if not pid:
            return "其他程序"
        name = f"进程 {pid}"
        # 方式一：wmic（部分系统/权限下不可用）
        try:
            out = subprocess.run(
                ["wmic", "process", "get", "processid,name"],
                capture_output=True, text=True, errors="replace", timeout=6,
                creationflags=Runner._hidden_flags(),
            )
            for ln in out.stdout.splitlines()[1:]:
                parts = ln.split()
                if str(pid) in parts:
                    name = next(
                        (p for p in parts if p != str(pid) and not p.isdigit()),
                        f"进程 {pid}",
                    )
                    break
        except Exception:
            pass
        # 方式二：tasklist 兜底
        if name.startswith("进程"):
            try:
                out = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, errors="replace", timeout=6,
                    creationflags=Runner._hidden_flags(),
                )
                line = out.stdout.strip()
                if line.startswith('"'):
                    name = line.split('","')[0].strip('"') or f"进程 {pid}"
            except Exception:
                pass
        # 是否为该程序自己的引擎实例（进程树内）
        tree = set()
        for inst in self.engine_instances():
            if inst.get("pid"):
                tree |= self._wmic_tree([inst["pid"]])
        suffix = "（本程序引擎实例）" if pid in tree else ""
        return f"PID {pid}（{name}）{suffix}".strip()

    @staticmethod
    def _next_free_port(start, tries=30):
        """从 start 起找第一个空闲端口（最多 tries 次）。"""
        p = int(start or 7860)
        for _ in range(max(1, tries)):
            if not Runner._port_in_use(p):
                return p
            p += 1
        return None

    @staticmethod
    def _apply_free_port(engine_key, cmd, is_demo, port, is_bat):
        """端口被占用时自动改到空闲端口。

        - webui 引擎（launch.py 等）：改写 `--port=` 参数。
        - bat 引擎（webui.bat / 一键启动.bat 等）：尝试 COMMANDLINE_ARGS
          环境变量注入 `--port=<空闲>`（A1111 系启动器约定；脚本不支持则忽略）。
        返回 (cmd, port, spawn_env, ok)。
        """
        spawn_env = None
        if is_demo or not port or not Runner._port_in_use(port):
            return cmd, port, None, True
        free = Runner._next_free_port(port)
        if free is None:
            return cmd, port, None, False
        log_manager.warn(
            "runner",
            f"[{engine_key}] 端口 {port} 被占用，自动改用空闲端口 {free}",
        )
        cmd = [
            f"--port={free}" if str(a).startswith("--port=")
            else (str(free) if str(a) == str(port) else a)
            for a in cmd
        ]
        if is_bat:
            env = os.environ.copy()
            env["COMMANDLINE_ARGS"] = (
                env.get("COMMANDLINE_ARGS", "") + f" --port={free}"
            ).strip()
            spawn_env = env
        return cmd, free, spawn_env, True

    def _resolve_launch(self, engine_key="reforge"):
        """根据引擎 key 解析启动命令。返回 (commands, is_demo, kind, port, root)。"""
        conf = config_manager.load()

        # 通用引擎：从引擎注册表解析根目录 / 类型 / 入口（含用户新增的自定义引擎）
        from core.engine_registry import engine_registry
        edef = next((e for e in engine_registry.list_engines() if e.get("key") == engine_key), None)
        root_field = (edef or {}).get("root") or ""
        kind = (edef or {}).get("kind") or "webui"
        entry = (edef or {}).get("entry") or ""
        if not entry and root_field and os.path.isdir(root_field):
            entry = engine_registry._detect_entry(kind, root_field)
        if entry:
            log_manager.info("runner", f"[{engine_key}] 启动入口: {entry}")
            cmd = self._build_engine_cmd(engine_key, entry, conf, kind)
            port = 0 if kind == "exe" else conf.start_args.port
            return cmd, False, kind, port, root_field

        # 无真实环境：演示模式
        log_manager.warn("runner", f"[{engine_key}] 未检测到有效根目录，进入演示模式")
        return self._build_demo_cmd(conf, engine_key), True, "webui", conf.start_args.port, None

    def _build_engine_cmd(self, engine_key, entry, conf, kind="webui"):
        """按引擎类型构建启动命令。"""
        args = conf.start_args
        if kind == "exe":
            # 本地程序：直接拉起 exe（无端口、无参数）
            return [entry]
        if entry.lower().endswith(".bat"):
            return ["cmd", "/c", entry]
        if entry.lower().endswith(".py"):
            # 优先用引擎自带 venv 的 python（clone 版首次启动会自动创建）；
            # 不存在时才回退到 Atelier 运行时 python。
            root_dir = os.path.dirname(entry)
            venv_py = os.path.join(root_dir, "venv", "Scripts", "python.exe")
            cmd = [venv_py if os.path.exists(venv_py) else sys.executable, entry]
            if kind == "webui":
                if not args.open_browser:
                    cmd.append("--no-browser")
                if args.port:
                    cmd.append(f"--port={args.port}")
                if args.use_cpu:
                    cmd.append("--use-cpu")
                # 显存模式映射（按主基底决定参数，适配 reForge / Forge）
                vram_arg = self._vram_arg(args.vram_mode)
                if vram_arg:
                    cmd.append(vram_arg)
                # 显卡选择（device-id，从 0 起）
                try:
                    gpu_ids = list(getattr(args, "gpu_ids", None) or [])
                    if len(gpu_ids) >= 2:
                        cmd.append(f"--devices-id={','.join(str(int(x)) for x in gpu_ids)}")
                    elif len(gpu_ids) == 1:
                        cmd.append(f"--device-id={int(gpu_ids[0])}")
                    else:
                        gpu = int(args.gpu_index)
                        cmd.append(f"--device-id={gpu}")
                except Exception:
                    pass
                cmd.extend(args.custom_args)
            return cmd
        return [entry]

    def _engine_env(self):
        """引擎启动环境：注入 pip / HF 镜像（首次启动自动装依赖时国内可达）。"""
        env = os.environ.copy()
        try:
            from core.config_manager import config_manager
            e = config_manager.load().env
            if e.use_py_mirror and (e.pip_mirror or "").strip():
                env["PIP_INDEX_URL"] = e.pip_mirror.strip()
            if e.use_hf_mirror and (e.hf_endpoint or "").strip():
                env["HF_ENDPOINT"] = e.hf_endpoint.strip()
        except Exception:
            pass
        return env

    def _is_first_run(self, root, kind):
        """webui 引擎首次启动：根目录存在但无 venv（引擎会自动创建并安装依赖）。"""
        if kind != "webui" or not root or not os.path.isdir(root):
            return False
        return not os.path.exists(os.path.join(root, "venv", "Scripts", "python.exe"))

    def _vram_arg(self, vram_mode):
        """按主基底将显存模式值映射为对应启动参数（未知返回空串）。"""
        primary = base_registry.primary()
        bdef = base_registry.get(primary)
        if not bdef:
            return ""
        for m in bdef["vram_modes"]:
            if m["value"] == vram_mode:
                return m["arg"]
        return ""

    def _build_demo_cmd(self, conf, engine_key="reforge"):
        """构建演示模式「进程命令」（模拟日志）。"""
        return [sys.executable, "-c", self._DEMO_SCRIPT.format(engine=engine_key)]

    # =================================================
    # 生命周期
    # =================================================
    def start(self, engine_key="reforge"):
        """启动引擎（默认主引擎；支持自由多开）。

        产品定论：不做全局互斥，用户可任意叠加启动（主引擎 + N 个其他引擎，
        或同一引擎多开），每个实例独立进程 / 日志源 / 端口 / 关闭控制；
        端口冲突由本程序自动改空闲端口，用户按实例显示的占用/端口自行判断。
        """
        with self._lock:
            primary_busy = self.status in (EngineStatus.STARTING, EngineStatus.RUNNING)
            if primary_busy:
                # 自由多开：叠加启动为新实例
                return self._start_extra(engine_key)
            self.status = EngineStatus.STARTING
            self._stop_event.clear()
            self._start_token += 1
            token = self._start_token

        cmd, is_demo, kind, port, root = self._resolve_launch(engine_key)
        if kind == "ftn_tag":
            # 本地 HTML 工具：无需端口/进程，首页点击「启动」直接在浏览器打开
            with self._lock:
                self.status = EngineStatus.STOPPED
            return {"ok": False, "code": "local_html", "msg": "本地 HTML 工具无需启动进程：请在首页点击「启动」在浏览器中打开"}
        self._demo = is_demo
        self._kind = kind
        self.engine_key = engine_key
        first_run = self._is_first_run(root, kind)
        if first_run:
            log_manager.warn(
                "runner",
                f"[{engine_key}] 首次启动：未检测到虚拟环境，引擎将自动创建并安装依赖"
                "（已注入 pip/HF 镜像；需要联网且可能较久，进度见控制台）",
            )
        # 端口冲突自动处理：被占用 → 改到空闲端口（bat 引擎经 COMMANDLINE_ARGS 注入）
        is_bat = (
            len(cmd) >= 3
            and str(cmd[0]).lower() == "cmd"
            and str(cmd[2]).lower().endswith(".bat")
        )
        cmd, port, spawn_env, port_ok = self._apply_free_port(
            engine_key, cmd, is_demo, port, is_bat
        )
        if not port_ok:
            occupant = self._port_occupant(port)
            msg = f"端口 {port} 被 {occupant} 占用，且未找到空闲端口（隔离失败）。请到设置更换端口或关闭占用程序"
            log_manager.error("runner", f"[{engine_key}] {msg}")
            self.status = EngineStatus.ERROR
            return {
                "ok": False,
                "code": "port_busy",
                "port": port,
                "occupant": occupant,
                "msg": msg,
                "status": self.status,
            }
        start_args_port = getattr(config_manager.load().start_args, "port", 7860)
        # EXE 本地程序无端口：ready_url 置空，避免首页误显示端口
        self.ready_url = "" if kind == "exe" else f"http://127.0.0.1:{port or start_args_port}"

        log_manager.info("runner", f"正在启动引擎 [{engine_key}] {'(演示模式)' if is_demo else ''} ...")
        log_manager.info("runner", f"启动命令: {' '.join(cmd) if isinstance(cmd, list) else cmd}")

        try:
            self._open_log()
            work_dir = None
            # bat 命令：cwd 置为入口脚本所在目录；否则尝试首参数目录
            if isinstance(cmd[0], str) and (cmd[0].endswith(".bat") or cmd[0].endswith(".py")):
                work_dir = os.path.dirname(cmd[0]) or None
            elif root:
                work_dir = root
            base_env = self._engine_env()
            final_env = base_env
            if spawn_env is not None:
                final_env = base_env.copy()
                final_env.update(spawn_env)
            self.process = subprocess.Popen(
                cmd,
                cwd=work_dir,
                stdout=self._log_fh,
                stderr=subprocess.STDOUT,
                env=final_env,
                creationflags=self._hidden_flags(),
            )
        except Exception as e:
            log_manager.error("runner", f"启动进程失败: {e}")
            self.status = EngineStatus.ERROR
            return {"ok": False, "msg": f"启动失败: {e}"}

        self.pid = self.process.pid
        log_manager.info("runner", f"引擎进程已启动 (pid={self.pid})")
        # EXE 本地程序不做进程标记：退出/异常清理都不会误杀（用户期望它继续运行）
        if kind != "exe":
            self._register_engine(self.pid, engine_key, 1, root, "")

        # 启动日志读取线程 + 就绪探测线程
        self._start_log_reader()
        threading.Thread(target=self._wait_ready, args=(token,), daemon=True).start()

        return {
            "ok": True,
            "status": EngineStatus.STARTING,
            "pid": self.pid,
            "demo": is_demo,
            "engine": engine_key,
            "port": port or start_args_port,
            "first_run": first_run,
        }

    def _engine_label(self, engine_key):
        """引擎显示名。"""
        from core.engine_registry import engine_registry
        try:
            for e in engine_registry.list_engines():
                if e.get("key") == engine_key:
                    return e.get("label") or engine_key
        except Exception:
            pass
        return engine_key

    def _start_extra(self, engine_key):
        """多开：以额外实例方式叠加启动（独立进程/日志/就绪探测/关闭）。"""
        cmd, is_demo, kind, port, root = self._resolve_launch(engine_key)
        if kind == "ftn_tag":
            # 本地 HTML 工具不启动进程（首页直接打开），不支持多开
            return {"ok": False, "code": "local_html", "msg": "本地 HTML 工具无需启动进程"}
        label = self._engine_label(engine_key)
        first_run = self._is_first_run(root, kind)
        if first_run:
            log_manager.warn(
                "runner",
                f"[{engine_key}#{num}] 首次启动：未检测到虚拟环境，引擎将自动创建并安装依赖"
                "（已注入 pip/HF 镜像；需要联网且可能较久）",
            )
        with self._lock:
            nums = [x["num"] for x in self._extras if x["key"] == engine_key]
            num = (max(nums) + 1) if nums else 2
        log_source = f"{engine_key}-{num}"
        log_path = os.path.join(LOG_DIR, f"{engine_key}-{num}.run.log")
        # 端口偏移：多开实例避免端口冲突（--port=N 或位置参数）
        old_port = port
        if not is_demo and port:
            port = port + (num - 1)
        cmd = [
            f"--port={port}" if str(a).startswith("--port=")
            else (str(port) if str(a) == str(old_port) else a)
            for a in cmd
        ]
        # 端口占用兜底：偏移后若仍被其他程序占用 → 再找空闲端口
        is_bat = (
            len(cmd) >= 3
            and str(cmd[0]).lower() == "cmd"
            and str(cmd[2]).lower().endswith(".bat")
        )
        cmd, port, spawn_env, port_ok = self._apply_free_port(
            engine_key, cmd, is_demo, port, is_bat
        )
        if not port_ok:
            occupant = self._port_occupant(port)
            msg = f"端口 {port} 被 {occupant} 占用，且未找到空闲端口（隔离失败）。请到设置更换端口或关闭占用程序"
            log_manager.error("runner", f"[{engine_key}#{num}] {msg}")
            return {
                "ok": False,
                "code": "port_busy",
                "port": port,
                "occupant": occupant,
                "msg": msg,
            }
        inst = {
            "key": engine_key, "label": label, "num": num,
            "pid": None, "process": None, "log_path": log_path,
            "log_source": log_source, "status": "starting",
            "ready_url": "" if kind == "exe" else f"http://127.0.0.1:{port}",
            "demo": is_demo, "_log_fh": None, "_demo_start": None,
        }
        log_manager.info(
            "runner",
            f"[{engine_key}] 正在多开启动实例 #{num} {'(演示模式)' if is_demo else ''} ...",
        )
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            fh = open(log_path, "w", encoding="utf-8", errors="replace")
            inst["_log_fh"] = fh
            work_dir = None
            if isinstance(cmd[0], str) and (cmd[0].endswith(".bat") or cmd[0].endswith(".py")):
                work_dir = os.path.dirname(cmd[0]) or None
            elif root:
                work_dir = root
            base_env = self._engine_env()
            final_env = base_env
            if spawn_env is not None:
                final_env = base_env.copy()
                final_env.update(spawn_env)
            inst["process"] = subprocess.Popen(
                cmd, cwd=work_dir, stdout=fh, stderr=subprocess.STDOUT,
                env=final_env, creationflags=self._hidden_flags(),
            )
        except Exception as e:
            log_manager.error("runner", f"多开实例启动失败: {e}")
            try:
                if inst["_log_fh"]:
                    inst["_log_fh"].close()
            except Exception:
                pass
            return {"ok": False, "msg": f"多开启动失败: {e}"}
        inst["pid"] = inst["process"].pid
        if is_demo:
            inst["_demo_start"] = time.time()
        with self._lock:
            self._extras.append(inst)
        log_manager.info("runner", f"多开实例已启动 [{engine_key}#{num}] pid={inst['pid']}")
        if kind != "exe":
            self._register_engine(inst["pid"], engine_key, num, root, "")
        threading.Thread(target=self._tail_instance, args=(inst,), daemon=True).start()
        threading.Thread(target=self._wait_extra, args=(inst,), daemon=True).start()
        return {
            "ok": True, "status": EngineStatus.STARTING, "pid": inst["pid"],
            "demo": is_demo, "engine": engine_key, "instance": num, "port": port,
            "first_run": first_run,
        }

    def _tail_instance(self, inst):
        """跟随读取多开实例日志文件，转发到其独立日志源。"""
        path = inst.get("log_path")
        if not path:
            return
        pos = 0
        while True:
            with self._lock:
                alive = inst in self._extras
            if not alive:
                break
            # 活跃检测：运行中实例进程自行退出（例如被手动关闭）→ 整树清理并移除
            proc = inst.get("process")
            if proc and proc.poll() is not None and inst.get("status") == "running":
                code = proc.poll()
                log_manager.warn("runner", f"[{inst['key']}#{inst['num']}] 实例进程已退出 (exit={code})（可能被手动关闭）")
                if inst.get("pid"):
                    self._kill_tree(inst["pid"])
                self._remove_extra(inst, code)
                try:
                    import asyncio
                    asyncio.run(status_manager.broadcast_status())
                except Exception:
                    pass
                break
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    new_lines = f.read()
                    pos = f.tell()
                    for ln in new_lines.splitlines():
                        if ln.strip():
                            log_manager.info(inst["log_source"], ln)
            except (OSError, IOError):
                pass
            time.sleep(0.3)

    def _wait_extra(self, inst):
        """多开实例就绪探测 / 提前退出监控。"""
        port = 7860
        try:
            port = int(inst["ready_url"].rsplit(":", 1)[1].rstrip("/")) if inst.get("ready_url") else 7860
        except Exception:
            pass
        ready = False
        deadline = time.time() + 120
        while time.time() < deadline:
            proc = inst.get("process")
            if proc and proc.poll() is not None:
                code = proc.poll()
                log_manager.warn("runner", f"[{inst['key']}#{inst['num']}] 实例提前退出 (exit={code})")
                self._remove_extra(inst, code)
                return
            if inst.get("demo"):
                if time.time() > (inst.get("_demo_start") or 0) + 4:
                    ready = True
                    break
            else:
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
                    ready = True
                    break
                except Exception:
                    pass
            time.sleep(2)
        with self._lock:
            if ready:
                inst["status"] = "running"
                log_manager.info(
                    "runner",
                    f"[{inst['key']}#{inst['num']}] 多开实例就绪 {inst.get('ready_url')}",
                )
            else:
                inst["status"] = "error"
                log_manager.warn("runner", f"[{inst['key']}#{inst['num']}] 就绪探测超时")
                self._remove_extra(inst, None)

    def _remove_extra(self, inst, code=None):
        """移除多开实例并关闭其日志句柄。"""
        try:
            fh = inst.get("_log_fh")
            if fh:
                fh.close()
        except Exception:
            pass
        self._unregister_engine(inst.get("pid"))
        with self._lock:
            if inst in self._extras:
                self._extras.remove(inst)
        log_manager.info("runner", f"多开实例 [{inst['key']}#{inst['num']}] 已结束 (exit={code})")

    def _terminate_extra(self, inst):
        """终止单个多开实例进程（优雅 → 超时整树强杀）。"""
        proc = inst.get("process")
        if proc is None or proc.poll() is not None:
            return
        try:
            if inst.get("demo") or inst.get("kind") == "exe":
                # EXE 本地程序：无 /shutdown 接口，直接终止
                proc.terminate()
            else:
                port = None
                try:
                    port = int(inst["ready_url"].rsplit(":", 1)[1].rstrip("/")) if inst.get("ready_url") else None
                except Exception:
                    pass
                self._graceful_stop(proc, port=port)
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self._force_kill(proc)
            # 整树强杀兜底：cmd 已退出但 python 子进程可能仍是孤儿
            if inst.get("pid"):
                self._kill_tree(inst["pid"])
        except Exception as e:
            log_manager.error("runner", f"停止多开实例出错: {e}")
        try:
            fh = inst.get("_log_fh")
            if fh:
                fh.close()
        except Exception:
            pass

    def stop_instance(self, engine_key, num):
        """停止指定多开实例（控制台逐个关闭用，不影响其他实例）。"""
        with self._lock:
            inst = next(
                (x for x in self._extras if x["key"] == engine_key and x["num"] == num),
                None,
            )
        if inst is None:
            return {"ok": False, "msg": f"未找到引擎实例 {engine_key}#{num}"}
        log_manager.info("runner", f"正在停止多开实例 [{engine_key}#{num}]")
        self._terminate_extra(inst)
        self._remove_extra(inst, "stopped")
        return {"ok": True, "engine": engine_key, "instance": num}

    def _stop_extras_by_key(self, engine_key):
        """停止某引擎的全部多开实例（主实例不受影响）。"""
        with self._lock:
            targets = [x for x in self._extras if x["key"] == engine_key]
        stopped = 0
        for inst in targets:
            self._terminate_extra(inst)
            self._remove_extra(inst, "stopped")
            stopped += 1
        return {"ok": True, "engine": engine_key, "stopped": stopped}

    def stop_all(self):
        """停止全部引擎实例（主实例 + 所有多开），供退出/关闭前调用。
        EXE 本地程序不在此停止：关闭 FTN Atelier 不会关闭它们（退出时仅提示）。
        """
        with self._lock:
            primary_running = (
                self.status in (EngineStatus.RUNNING, EngineStatus.STARTING)
                and self._kind != "exe"
            )
            keys = sorted({x["key"] for x in self._extras if x.get("kind") != "exe"})
        results = []
        if primary_running:
            results.append(self._stop_primary())
        for k in keys:
            results.append(self._stop_extras_by_key(k))
        return {"ok": True, "stopped_count": len(results), "results": results}

    def engine_instances(self):
        """所有引擎实例快照（主实例 + 多开额外实例），供控制台会话列表使用。"""
        with self._lock:
            out = []
            if self.status in (EngineStatus.STARTING, EngineStatus.RUNNING, EngineStatus.STOPPING):
                port = None
                try:
                    port = int(self.ready_url.rsplit(":", 1)[1].rstrip("/")) if self.ready_url else None
                except Exception:
                    pass
                out.append({
                    "engine": self.engine_key,
                    "kind": self._kind,
                    "label": self._engine_label(self.engine_key),
                    "instance": 1,
                    "pid": self.pid,
                    "status": self.status,
                    "log_source": self.engine_key,
                    "demo": bool(self._demo),
                    "ready_url": self.ready_url,
                    "port": port,
                })
            for x in list(self._extras):
                port = None
                try:
                    port = int(x.get("ready_url", "").rsplit(":", 1)[1].rstrip("/")) if x.get("ready_url") else None
                except Exception:
                    pass
                out.append({
                    "engine": x["key"],
                    "kind": x.get("kind"),
                    "label": x.get("label") or self._engine_label(x["key"]),
                    "instance": x["num"],
                    "pid": x.get("pid"),
                    "status": x.get("status"),
                    "log_source": x.get("log_source"),
                    "demo": bool(x.get("demo")),
                    "ready_url": x.get("ready_url"),
                    "port": port,
                })
            return out

    # =================================================
    # 实例占用统计（内存/显存；bat 引擎可检测，html 无进程不检测）
    # =================================================
    @staticmethod
    def _wmic_tree(pids):
        """构建父子表，返回给定 pids 的全部后代（含自身）。wmic 失败时用 PowerShell 兜底。"""
        children = {}
        try:
            out = subprocess.run(
                ["wmic", "process", "get", "processid,parentprocessid"],
                capture_output=True, text=True, errors="replace", timeout=6,
                creationflags=Runner._hidden_flags(),
            )
            for ln in out.stdout.splitlines()[1:]:
                parts = ln.split()
                if len(parts) >= 2:
                    try:
                        # wmic 列顺序是 ParentProcessId, ProcessId（父在前、子在后）
                        ppid, pid = int(parts[0]), int(parts[1])
                        children.setdefault(ppid, []).append(pid)
                    except ValueError:
                        pass
        except Exception:
            pass
        if not children:
            # PowerShell 兜底（wmic 在部分系统/权限下不可用）
            try:
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId | ConvertTo-Csv -NoTypeInformation"],
                    capture_output=True, text=True, errors="replace", timeout=8,
                    creationflags=Runner._hidden_flags(),
                )
                lines = out.stdout.splitlines()
                for ln in lines[1:]:
                    parts = ln.strip().strip('"').split('","')
                    if len(parts) >= 2:
                        try:
                            pid, ppid = int(parts[0]), int(parts[1])
                            children.setdefault(ppid, []).append(pid)
                        except ValueError:
                            pass
            except Exception:
                pass
        result = set(pids)
        stack = list(pids)
        while stack:
            cur = stack.pop()
            for c in children.get(cur, []):
                if c not in result:
                    result.add(c)
                    stack.append(c)
        return result

    @staticmethod
    def _rss_mb(pid):
        """进程工作集内存（MB）；失败返回 None。"""
        try:
            import ctypes
            from ctypes import wintypes
            psapi = ctypes.WinDLL("psapi")
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            PROCESS_VM_READ = 0x0010

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            h = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, int(pid)
            )
            if not h:
                return None
            try:
                pmc = PROCESS_MEMORY_COUNTERS()
                if psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), ctypes.sizeof(pmc)):
                    return round(pmc.WorkingSetSize / 1048576, 1)
            finally:
                kernel32.CloseHandle(h)
        except Exception:
            pass
        return None

    @staticmethod
    def _gpu_mb_map():
        """nvidia-smi 计算应用：返回 (pid→显存MB, python 进程名→显存MB合计) 两组映射。"""
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-compute-apps=pid,process_name,used_gpu_memory", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, errors="replace", timeout=6,
                creationflags=Runner._hidden_flags(),
            )
        except Exception:
            return {}, {}
        pid_map, name_map = {}, {}
        for ln in out.stdout.splitlines():
            parts = [x.strip() for x in ln.split(",")]
            if len(parts) >= 3 and parts[0].isdigit():
                try:
                    used = float(parts[2])
                    pid_map[int(parts[0])] = used
                    nm = (parts[1] or "").lower()
                    if nm in ("python.exe", "python3.exe"):
                        name_map[nm] = name_map.get(nm, 0) + used
                except ValueError:
                    pass
        return pid_map, name_map

    @staticmethod
    def _total_mem_mb():
        """系统物理内存总量（MB）。"""
        try:
            class _MemStat(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = _MemStat()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return round(stat.ullTotalPhys / (1024 * 1024), 1)
        except Exception:
            return None

    @staticmethod
    def _total_gpu_mb():
        """NVIDIA 显存总量（MB，多卡求和）。"""
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, errors="replace", timeout=6,
                creationflags=Runner._hidden_flags(),
            )
            vals = [float(x.strip()) for x in out.stdout.splitlines() if x.strip().replace(".", "").isdigit()]
            return round(sum(vals), 1) if vals else None
        except Exception:
            return None

    def stats(self):
        """各引擎实例占用（整棵进程树汇总内存/显存）+ 采样历史（供趋势图）。"""
        gpu_pids, gpu_names = self._gpu_mb_map()
        out = []
        for inst in self.engine_instances():
            pid = inst.get("pid")
            if not pid:
                out.append({**inst, "rss_mb": None, "gpu_mb": None})
                continue
            tree = self._wmic_tree([pid])
            rss = sum(self._rss_mb(p) or 0 for p in tree)
            gpu = sum(gpu_pids.get(p, 0) for p in tree)
            if not gpu and tree:
                # 兜底：compute-apps 未按 pid 命中（驱动/进程归属差异）时，
                # 按 python 进程名汇总显存（多开时并入同引擎，可接受）
                gpu = gpu_names.get("python.exe", 0) + gpu_names.get("python3.exe", 0)
            out.append({
                **inst,
                "rss_mb": round(rss, 1) if rss else None,
                "gpu_mb": round(gpu, 1) if gpu else None,
            })
        # 采样入历史（供首页 5 分钟趋势），仅保留最近 120 点
        now = time.time()
        with self._lock:
            for x in out:
                self._stats_history.append({
                    "ts": now,
                    "engine": x.get("engine"),
                    "instance": x.get("instance"),
                    "rss_mb": x.get("rss_mb"),
                    "gpu_mb": x.get("gpu_mb"),
                })
            self._stats_history = self._stats_history[-120:]
            history = list(self._stats_history)
        return {
            "instances": out,
            "history": history[-60:],
            "total_mem_mb": self._total_mem_mb(),
            "total_gpu_mb": self._total_gpu_mb(),
        }

    def diagnose(self):
        """主实例启动失败诊断（日志关键词匹配出的修复建议）。"""
        with self._lock:
            return list(self._diagnosis)

    def stop(self, engine_key=None):
        """关闭引擎。

        - engine_key 为空：停止主实例及其同名多开实例（旧行为）。
        - 指定 engine_key 且不是主实例引擎：仅停止该引擎的多开实例。
        """
        target = engine_key or self.engine_key
        with self._lock:
            primary_is_target = self.engine_key == target
        if not primary_is_target:
            return self._stop_extras_by_key(target)
        primary_result = self._stop_primary()
        self._stop_extras_by_key(target)
        return primary_result

    def _stop_primary(self):
        """停止主实例（原有单实例关闭流程）。"""
        with self._lock:
            if self.status not in (EngineStatus.RUNNING, EngineStatus.STARTING):
                return {"ok": False, "msg": "引擎当前未在运行", "status": self.status}
            self.status = EngineStatus.STOPPING
        log_manager.info("runner", "正在停止引擎 ...")
        pid = self.pid
        try:
            # 演示模式直接终止；真实模式尝试优雅关闭
            if self.process and self.process.poll() is None:
                if self._demo or self._kind == "exe":
                    # EXE 本地程序：无 /shutdown 接口，直接终止
                    self.process.terminate()
                else:
                    self._graceful_stop(self.process, port=self._instance_port())
                # 等待退出
                try:
                    self.process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    self._force_kill(self.process)
            # 无论外层 cmd 是否已退出，整树强杀兜底：防止 python 子进程变孤儿
            if pid:
                self._kill_tree(pid)
        except Exception as e:
            log_manager.error("runner", f"停止引擎出错: {e}")

        return self._finalize_stop()

    @staticmethod
    def _force_kill(proc):
        """强杀进程：Windows 用 taskkill /T /F 整树终止，防止 cmd /c 子进程孤儿。"""
        if sys.platform == "win32" and proc and proc.poll() is None:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True, timeout=10,
                    creationflags=Runner._hidden_flags(),
                )
            except Exception:
                pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass

    @staticmethod
    def _kill_tree(root_pid):
        """整树强杀：确保 root_pid 的全部后代（含自身）都被终止。

        Windows 下 `cmd /c webui.bat` 的 python 子进程在外层 cmd 退出后会变成
        孤儿，只杀 cmd 不够。这里先用 taskkill /T 原生递归整树（根仍存活时
        无需枚举即可覆盖全部后代），再通过父子表枚举后代逐棵强杀兜底
        （根已退出、仅剩孤儿后代时仍能按 PPID 找到），并跑两轮覆盖新产生的子进程。
        """
        if not root_pid or sys.platform != "win32":
            return
        try:
            root = int(root_pid)
            # 方法一：根还活着 → taskkill /T /F 原生递归整树
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(root), "/T", "/F"],
                    capture_output=True, timeout=10,
                    creationflags=Runner._hidden_flags(),
                )
            except Exception:
                pass
            time.sleep(0.5)
            # 方法二：枚举后代（根已死时仍能按 PPID 找到孤儿），逐棵强杀，两轮
            for _ in range(2):
                tree = Runner._wmic_tree([root])
                if not tree:
                    return
                # 子进程优先、根最后，避免父进程先死后无法再枚举其余后代
                ordered = sorted(tree, key=lambda p: (p == root, p))
                for p in ordered:
                    try:
                        subprocess.run(
                            ["taskkill", "/PID", str(p), "/T", "/F"],
                            capture_output=True, timeout=10,
                            creationflags=Runner._hidden_flags(),
                        )
                    except Exception:
                        pass
                time.sleep(0.5)
        except Exception:
            pass

    def _graceful_stop(self, proc, port=None):
        """真实 webui 优雅关闭：先尝试 API（/shutdown，GET+POST）再终止。"""
        if port is None:
            port = config_manager.load().start_args.port
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/shutdown", timeout=3
            )
            time.sleep(2)
            if proc.poll() is not None:
                return
        except Exception:
            pass
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/shutdown",
                data=b"",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3)
            time.sleep(2)
            if proc.poll() is not None:
                return
        except Exception:
            pass
        proc.terminate()

    def _instance_port(self):
        """当前实例实际端口（从 ready_url 解析，兼容端口偏移后的多开实例）。"""
        try:
            if self.ready_url:
                return int(self.ready_url.rsplit(":", 1)[1].rstrip("/"))
        except Exception:
            pass
        return getattr(config_manager.load().start_args, "port", 7860)

    # =================================================
    # 引擎 PID 注册表（进程标记）
    #
    # 每次启动引擎都登记「根 PID + 引擎根目录」到 Database/engine_pids.json；
    # 停止/退出时移除标记。孤儿检测只处理注册表里标记过的 PID，并校验该 PID
    # 的进程命令行仍指向注册时的引擎根目录（防 PID 复用），绝不全局通杀。
    # =================================================
    @staticmethod
    def _pid_registry_path():
        try:
            from core.paths import app_root
            return os.path.join(app_root(), "Database", "engine_pids.json")
        except Exception:
            return os.path.join(LOG_DIR, "..", "Database", "engine_pids.json")

    def _registry_load(self):
        try:
            with open(self._pid_registry_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [x for x in data if isinstance(x, dict)]
        except Exception:
            pass
        return []

    def _registry_save(self, entries):
        try:
            p = self._pid_registry_path()
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(entries, f, ensure_ascii=False, indent=1)
            os.replace(tmp, p)
        except Exception:
            pass

    def _register_engine(self, pid, engine_key, num, root, entry=""):
        if not pid:
            return
        with self._lock:
            entries = [e for e in self._registry_load() if e.get("pid") != int(pid)]
            entries.append({
                "pid": int(pid),
                "key": engine_key,
                "num": int(num or 1),
                "root": root or "",
                "entry": entry or "",
                "started_at": time.time(),
            })
            self._registry_save(entries)

    def _unregister_engine(self, pid):
        if not pid:
            return
        with self._lock:
            entries = self._registry_load()
            before = len(entries)
            entries = [e for e in entries if e.get("pid") != int(pid)]
            if len(entries) != before:
                self._registry_save(entries)

    @staticmethod
    def _process_matches_root(pid, root):
        """校验 pid 进程仍存在且命令行/可执行路径指向 root（防 PID 复用误杀）。"""
        def _norm(s):
            return s.lower().replace("/", "\\")
        root_norm = _norm(root)
        try:
            out = subprocess.run(
                ["wmic", "process", "where", f"ProcessId={int(pid)}",
                 "get", "processid,commandline,executablepath", "/format:csv"],
                capture_output=True, text=True, errors="replace", timeout=6,
                creationflags=Runner._hidden_flags(),
            )
            if out.returncode == 0 and out.stdout and root_norm in _norm(out.stdout):
                return True
        except Exception:
            pass
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"$p = Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\"; "
                 "($p.CommandLine + ' ' + $p.ExecutablePath)"],
                capture_output=True, text=True, errors="replace", timeout=8,
                creationflags=Runner._hidden_flags(),
            )
            return root_norm in _norm(out.stdout or "")
        except Exception:
            pass
        return False

    def orphan_engine_roots(self):
        """注册表中「仍存活但已不被 runner 管理」的引擎进程 → {pid: root}。

        只处理本程序注册过的 PID（进程标记），且校验进程命令行仍指向注册时的
        引擎根目录，避免 PID 复用或路径相似造成的误杀。
        """
        with self._lock:
            tracked = set()
            for inst in self.engine_instances():
                if inst.get("pid"):
                    tracked |= self._wmic_tree([inst["pid"]])
            entries = self._registry_load()
        out = {}
        for e in entries:
            pid = e.get("pid")
            root = e.get("root") or ""
            if not pid or not root:
                continue
            if int(pid) in tracked:
                continue
            if not self._process_matches_root(pid, root):
                continue
            out[int(pid)] = root
        return out

    def _finalize_stop(self):
        with self._lock:
            self.status = EngineStatus.STOPPED
            pid = self.pid
            self.pid = None
            self.process = None
            self._reveal_log()
        self._stop_event.set()  # 停止日志/就绪线程的循环
        self._unregister_engine(pid)
        log_manager.info("runner", "引擎已停止")
        return {"ok": True, "status": EngineStatus.STOPPED}

    # =================================================
    # 就绪探测（starting → running）
    # =================================================
    def _wait_ready(self, token=None):
        """轮询探测引擎就绪；演示模式下延迟数秒模拟启动。

        token 为启动代际令牌：每次主引擎 start() 都会递增。旧引擎的
        _wait_ready 线程（可能因竞态晚醒）发现令牌不匹配时必须立即退出，
        绝不能碰新实例的 self.process / self.pid / self.status。
        """
        # 端口从 ready_url 解析（兼容 tag 库端口偏移）
        port = 7860
        try:
            port = int(self.ready_url.rsplit(":", 1)[1].rstrip("/")) if self.ready_url else 7860
        except Exception:
            pass

        def _stale():
            if token is None:
                return False
            with self._lock:
                return token != self._start_token

        ready = False
        deadline = time.time() + 120
        while time.time() < deadline and not self._stop_event.is_set():
            if _stale():
                return
            # 进程是否意外退出
            if self.process and self.process.poll() is not None:
                code = self.process.poll()
                if _stale():
                    return
                self._diagnosis = diagnose_log_file(self.log_path) if self.log_path else []
                log_manager.warn("runner", f"引擎进程提前退出 (exit={code})")
                for d in self._diagnosis:
                    log_manager.warn("runner", f"诊断[{d['title']}]: {d['suggestion']}")
                my_pid = self.pid
                if my_pid and not _stale():
                    self._kill_tree(my_pid)
                if _stale():
                    return
                self._finalize_stop()
                return
            if self._check_ready(port):
                ready = True
                break
            time.sleep(2)

        with self._lock:
            if _stale():
                return
            if self.status != EngineStatus.STARTING:
                return
            if ready:
                self.status = EngineStatus.RUNNING
                log_manager.info(
                    "runner",
                    f"引擎就绪，可访问 {self.ready_url} (运行中)",
                )
                import asyncio
                try:
                    asyncio.run(status_manager.broadcast_status())
                except Exception:
                    pass
            else:
                log_manager.warn("runner", "引擎就绪探测超时")
                self._diagnosis = diagnose_log_file(self.log_path) if self.log_path else []
                self.status = EngineStatus.ERROR

    def _check_ready(self, port):
        """探测 webui 是否可访问；演示模式用模拟端口。"""
        if self._demo:
            # 演示模式：探测 pid 存活 + 模拟 8 秒启动
            return (self.process is not None
                    and self.process.poll() is None
                    and time.time() > (self._demo_start or 0) + 4)
        # EXE 本地程序：进程存活即视为就绪（无端口可探测）
        if self._kind == "exe":
            return self.process is not None and self.process.poll() is None
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/", timeout=2
            )
            return True
        except Exception:
            return False

    # =================================================
    # 日志捕获
    # =================================================

    def _open_log(self):
        import os
        log_dir = LOG_DIR
        os.makedirs(log_dir, exist_ok=True)
        self.log_path = os.path.join(log_dir, f"{self.engine_key}.run.log")
        self._log_fh = open(self.log_path, "w", encoding="utf-8", errors="replace")
        if self._demo:
            self._demo_start = time.time()

    def _start_log_reader(self):
        """基于日志文件末尾跟随的读取线程（兼容 stdout 重定向到文件）。"""
        threading.Thread(target=self._tail_log, daemon=True).start()

    def _tail_log(self):
        """轮询读取日志文件新增内容，转发到 LogManager（WS 推送）。"""
        if not self.log_path:
            return
        pos = 0
        while not self._stop_event.is_set():
            # 活跃检测：运行中主实例进程自行退出（例如被手动关闭）→ 标记停止并整树清理
            with self._lock:
                running = self.status == EngineStatus.RUNNING
            if running and self.process and self.process.poll() is not None:
                code = self.process.poll()
                log_manager.warn("runner", f"引擎进程已退出 (exit={code})（可能被手动关闭）")
                if self.pid:
                    self._kill_tree(self.pid)
                self._finalize_stop()
                try:
                    import asyncio
                    asyncio.run(status_manager.broadcast_status())
                except Exception:
                    pass
                return
            try:
                with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    new_lines = f.read()
                    pos = f.tell()
                    for ln in new_lines.splitlines():
                        if ln.strip():
                            log_manager.info(self.engine_key, ln)
            except (OSError, IOError):
                pass
            time.sleep(0.3)

    def _reveal_log(self):
        """关闭日志文件句柄。"""
        if self._log_fh:
            try:
                self._log_fh.close()
            except Exception:
                pass
            self._log_fh = None

    # 演示模式模拟脚本（模拟 webui 启动时的典型日志输出）
    _DEMO_SCRIPT = r"""
import time, sys
print("Starting {engine} webui (demo mode)...")
for i, msg in enumerate(["Loading model", "Checking Skylib",
                         "Launching API server on 127.0.0.1:7860",
                         "Total progress: 100%", "Running on local URL: http://127.0.0.1:7860"]):
    print(msg)
    sys.stdout.flush()
    time.sleep(1)
time.sleep(3600)
"""

    # =================================================
    # 查询
    # =================================================
    def snapshot(self):
        """当前引擎状态快照。"""
        with self._lock:
            return {
                "status": self.status,
                "pid": self.pid,
                "demo": self._demo,
                "ready_url": self.ready_url,
                "engine": self.engine_key,
                "log_file": self.log_path,
                # 全部实例（主实例 + 多开额外实例），供首页/控制台按引擎显示运行状态
                "instances": self.engine_instances(),
            }


# 单例实例
runner = Runner()
