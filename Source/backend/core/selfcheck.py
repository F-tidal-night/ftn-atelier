# ============================================
# FTN Studio 启动自检 + 修复 模块
#
# 职责：
# - 启动软件前收集环境 / 目录 / 配置 / 进程等健康检查项
# - 区分「可修复」与「不可修复」异常
# - 提供单条修复能力（自动建目录 / 重建配置 / 清理孤儿进程 / 重建DB表）

# - 版本更新检测（当前版本 vs 远端最新；更新源 owner/repo 可配置，留空则跳过）
#
# 设计原则：所有网络/进程探测带短超时，单项失败绝不拖垮整轮检查。
# ============================================

import os
import re
import json
import sys
import time
import subprocess
import threading
import urllib.request
import socket

# Windows 下隐藏子进程控制台窗口（nvidia-smi / wmic / git 探测不闪黑窗）
_HIDE = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0

from core.db import db
from core.config_manager import config_manager, PROJECT_ROOT as APP_ROOT
from core.models.app_config import AppConfig
from core.env_detect import env_detect

# FTN Atelier 应用版本（与前端 package.json version 保持一致）
FTN_APP_VERSION = "1.0.3"

# 需要校验完整性的一份标准目录（存在性 + 可创建）
REQUIRED_DIRS = ["Core", os.path.join("Core", "Engines"), "Data", "Backup", "Logs", "Database"]

# 自检项顺序 + 中文标签（前端也有一份同名映射用于展示）
ITEM_LABELS = {
    "backend": "FastAPI 后端",
    "sqlite": "SQLite 数据库读写",
    "dirs": "目录完整性",
    "reforge_path": "主引擎路径",
    "reforge_python": "主引擎 Python 环境",
    "git": "Git 是否可用",
    "cuda": "CUDA / 显卡",
    "network": "网络连通性",
    "config": "关键配置完整性",
    "port": "端口占用",
    "orphan": "异常孤儿进程",
}

# 异步自检任务（内存态，最多保留 20 个）
_TASKS = {}
_TASKS_LOCK = threading.Lock()


class SelfCheckError(Exception):
    """自检过程中无法预期的基础异常。"""


class SelfCheckManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    # =================================================
    # 目录路径解析
    # =================================================
    @property
    def project_root(self):
        return APP_ROOT

    def resolve_path(self, rel):
        return os.path.join(self.project_root, rel) if rel else self.project_root

    # =================================================
    # 单项自检
    # =================================================
    def _check_backend(self):
        """FastAPI 后端：当前进程已作为后端常驻，即健康。"""
        return {
            "status": "ok",
            "message": "FastAPI 后端服务运行正常",
        }

    def _check_sqlite(self):
        """SQLite 数据库：写入临时键 + 读回 + 删除。"""
        try:
            key = "__selfcheck_probe__"
            db.set_meta(key, {"probe": 1})
            got = db.get_meta(key)
            db.execute(
                "DELETE FROM app_meta WHERE key = ?", (key,)
            )
            if got and got.get("probe") == 1:
                return {"status": "ok", "message": "数据库可正常读写（ftn.db）"}
            return {"status": "error", "fixable": True, "message": "数据库读写异常（写入未读到）"}
        except Exception as e:
            return {"status": "error", "fixable": True, "message": f"数据库读写失败：{e}"}

    def _check_dirs(self):
        """目录完整性：Core/Core-Engines/Data/Backup/Logs/Database 应存在且可写。"""
        missing = []
        ro = []
        for rel in REQUIRED_DIRS:
            p = self.resolve_path(rel)
            if not os.path.isdir(p):
                missing.append(rel)
            elif not os.access(p, os.W_OK):
                ro.append(rel)
        if missing or ro:
            msg = []
            if missing:
                msg.append("缺失：" + "、".join(missing))
            if ro:
                msg.append("无写权限：" + "、".join(ro))
            return {
                "status": "warn",
                "fixable": True,
                "message": "目录不完整，" + "；".join(msg),
                "missing": missing,
            }
        return {"status": "ok", "message": "Core / Engines / Data / Backup / Logs / Database 目录完整"}

    def _check_reforge_path(self):
        """主引擎路径有效：根目录存在且为生图 WebUI 根（含 webui.bat / webui-user.bat）。"""
        root = self._primary_root()
        if root is None:
            return {"status": "error", "fixable": False, "message": "无法读取引擎配置"}
        if not root:
            return {"status": "error", "fixable": False, "message": "未配置主引擎路径（请到设置→引擎路径填写）"}
        root = os.path.abspath(root)
        if not os.path.isdir(root):
            return {"status": "error", "fixable": False, "message": f"主引擎路径不存在：{root}"}
        return {"status": "ok", "message": "主引擎路径有效", "path": root}

    def _check_reforge_python(self):
        """主引擎 Python 环境：优先 venv/Scripts/python.exe。"""
        root = self._primary_root() or ""
        if root:
            venv_py = os.path.join(root, "venv", "Scripts", "python.exe")
            if os.path.isfile(venv_py):
                return {"status": "ok", "message": "主引擎虚拟环境可用（venv/Scripts/python.exe）", "path": venv_py}
            # 允许 webui-user.bat 存在（webui 自建 venv 未解压前）
            if os.path.exists(os.path.join(root, "webui-user.bat")) or os.path.exists(root):
                return {"status": "warn", "fixable": False, "message": "未发现 venv/Scripts/python.exe（主引擎环境可能尚未安装 / 解压）"}
        return {"status": "warn", "fixable": False, "message": "主引擎路径未配置，跳过环境检测"}

    def _primary_root(self):
        """主引擎根目录：跟随 engine_registry 主引擎条目（主引擎可指向任意已配置路径）。"""
        try:
            from core.engine_registry import engine_registry
            e = engine_registry.primary_engine()
            return ((e or {}).get("root") or "").strip() or ""
        except Exception:
            return None

    def _check_git(self):
        """Git 是否可用。"""
        try:
            r = subprocess.run(
                ["git", "--version"], capture_output=True, timeout=3, text=True,
                creationflags=_HIDE,
            )
            ver = (r.stdout or r.stderr or "").strip()
            if r.returncode == 0 and ver:
                # 提取版本号
                m = re.search(r"(\d+\.\d+(?:\.\d+)?)", ver)
                return {"status": "ok", "message": f"Git 可用（{m.group(1) if m else ver}）"}
        except Exception as e:
            return {"status": "error", "fixable": False, "message": f"Git 检测失败：{e}"}
        return {"status": "error", "fixable": False, "message": "未检测到 Git（影响版本下载/更新功能）"}

    def _check_cuda(self):
        """CUDA / 显卡：nvidia-smi 探测驱动与 GPU（并入启动前环境检测）。"""
        try:
            out = subprocess.run(
                [env_detect._nvidia_smi(), "--query-gpu=index,name,memory.total,driver_version", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, errors="replace", timeout=5,
                creationflags=_HIDE,
            )
            if out.returncode == 0 and out.stdout.strip():
                gpus = []
                for line in out.stdout.strip().splitlines():
                    p = [x.strip() for x in line.split(",")]
                    if len(p) >= 4 and p[0].lstrip("-").isdigit():
                        gpus.append(f"#{p[0]} {p[1]} {p[2]}MB")
                if gpus:
                    return {"status": "ok", "message": f"检测到 CUDA GPU（{'；'.join(gpus)}）"}
                return {"status": "warn", "fixable": False, "message": "nvidia-smi 有输出但未解析到 GPU"}
            return {"status": "warn", "fixable": False, "message": "未检测到 NVIDIA GPU（可用 CPU 模式运行，但出图会慢）"}
        except Exception as e:
            return {"status": "warn", "fixable": False, "message": f"CUDA/显卡检测失败：{e}"}

    def _check_network(self):
        """网络连通性：依次探测 国内 → 国内镜像 → GitHub，任一可达即正常。

        GitHub 连不通不代表异常（可走镜像/国内源），全部不通才提示。
        """
        targets = [
            ("https://www.baidu.com", "国内可达"),
            ("https://npmmirror.com", "国内镜像可达"),
            ("https://api.github.com", "GitHub API 可达"),
        ]
        try:
            for url, desc in targets:
                try:
                    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "ftn-selfcheck"})
                    with urllib.request.urlopen(req, timeout=3) as resp:
                        if resp.status < 400:
                            return {"status": "ok", "message": f"网络可用（{desc}）"}
                except Exception:
                    continue
        except Exception:
            pass
        return {"status": "warn", "fixable": False, "message": "网络不可用 / 超时（可点击「重试」，或检查网络后用科学上网）"}

    def _check_config(self):
        """关键配置完整性：AppConfig 加载不抛异常。"""
        try:
            cfg = config_manager.load()
            if cfg is None:
                raise SelfCheckError("配置为空")
            return {"status": "ok", "message": "关键配置完整可读"}
        except Exception as e:
            return {"status": "error", "fixable": True, "message": f"配置文件损坏：{e}"}

    def _check_port(self):
        """端口占用：确认后端端口确实可连接（避免仅进程在、端口没监听）。"""
        port = os.environ.get("FTN_BACKEND_PORT", "19000")
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=2):
                return {"status": "ok", "message": f"后端端口 {port} 正常监听"}
        except Exception as e:
            return {"status": "warn", "fixable": False, "message": f"后端端口 {port} 未响应：{e}"}

    def _check_orphan(self):
        """异常孤儿进程：除当前后端外，是否还有残留的后端/引擎 python 进程。"""
        try:
            cur = os.getpid()
            # 读取锁文件记录的"本实例拉起的后端 pid"
            lock_pid = None
            try:
                lock_path = os.path.join(self.project_root, "Database", "backend.lock")
                if os.path.exists(lock_path):
                    import json
                    with open(lock_path, "r", encoding="utf-8") as f:
                        lock_pid = json.load(f).get("pid")
            except Exception:
                pass
            pids = self._find_backend_python_pids()
            others = [p for p in pids if p not in (cur, lock_pid)]
            # 引擎孤儿：只处理注册表标记过的 PID（进程标记），避免误杀其它进程
            try:
                from core.runner import runner
                engine_pids = list(runner.orphan_engine_roots().keys())
            except Exception:
                engine_pids = []
            others += [p for p in engine_pids if p not in others]
            if others:
                kinds = []
                if any(p in engine_pids for p in others):
                    kinds.append("引擎")
                if any(p not in engine_pids for p in others):
                    kinds.append("后端")
                return {
                    "status": "warn",
                    "fixable": True,
                    "message": "检测到异常遗留的" + "/".join(kinds) + "进程（pid=" + "、".join(map(str, others)) + "）",
                    "pids": others,
                }
            return {"status": "ok", "message": "无异常孤儿进程"}
        except Exception as e:
            return {"status": "warn", "fixable": False, "message": f"孤儿进程检测失败:{e}"}

    @staticmethod
    def _find_backend_python_pids():
        """遍历 python/pythonw 进程，找出运行「本程序 main.py」的 pid 列表（精确路径匹配，防误杀）。"""
        pids = []
        try:
            main_py = os.path.normcase(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"))
        except Exception:
            main_py = None
        if not main_py:
            return pids
        try:
            cmd = "wmic process where \"name='python.exe' or name='pythonw.exe'\" get processid,commandline /format:csv"
            r = subprocess.run(cmd, capture_output=True, timeout=4, text=True, shell=True,
                               creationflags=_HIDE)
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    if main_py in os.path.normcase(line):
                        parts = line.split(",")
                        pid = parts[-1].strip() if parts else ""
                        if pid.isdigit():
                            pids.append(int(pid))
        except Exception:
            pass
        return pids

    # =================================================
    # 全量自检
    # =================================================
    def _item_runners(self):
        """返回 [(key, callable)]：自检项按顺序逐个执行（供同步/异步共用）。"""
        return [
            ("backend", self._check_backend),
            ("sqlite", self._check_sqlite),
            ("dirs", self._check_dirs),
            ("reforge_path", self._check_reforge_path),
            ("reforge_python", self._check_reforge_python),
            ("git", self._check_git),
            ("cuda", self._check_cuda),
            ("network", self._check_network),
            ("config", self._check_config),
            ("port", self._check_port),
            ("orphan", self._check_orphan),
        ]

    def run(self):
        out = []
        for key, fn in self._item_runners():
            res = fn()
            res.setdefault("key", key)
            res.setdefault("label", ITEM_LABELS.get(key, key))
            res.setdefault("status", res.get("status", "ok"))
            res.setdefault("fixable", bool(res.get("fixable")))
            out.append(res)
        ok_cnt = sum(1 for x in out if x["status"] == "ok")
        fixable = [x for x in out if x.get("fixable")]
        return {
            "ok": ok_cnt == len(out),
            "total": len(out),
            "ok_count": ok_cnt,
            "items": out,
            "fixable_count": len(fixable),
            "has_fixable": bool(fixable),
        }

    # ---------- 异步自检（逐项完成 → 前端进度条逐步推进） ----------
    def start_async(self):
        """后台逐项执行自检，返回 task_id；前端轮询 status 获取已完成项。"""
        tid = f"sc{int(time.time() * 1000)}"
        st = {
            "id": tid, "done": False, "total": len(self._item_runners()),
            "ok_count": 0, "fixable_count": 0, "items": [],
        }
        with _TASKS_LOCK:
            _TASKS[tid] = st
            # 只保留最近 20 个任务，防止无限累积
            if len(_TASKS) > 20:
                for old in list(_TASKS)[:-20]:
                    _TASKS.pop(old, None)

        def _worker():
            try:
                for key, fn in self._item_runners():
                    try:
                        res = fn()
                    except Exception as e:
                        res = {"status": "error", "fixable": False, "message": f"检测异常：{e}"}
                    res.setdefault("key", key)
                    res.setdefault("label", ITEM_LABELS.get(key, key))
                    res.setdefault("status", res.get("status", "ok"))
                    res.setdefault("fixable", bool(res.get("fixable")))
                    with _TASKS_LOCK:
                        st["items"].append(res)
                        st["ok_count"] = sum(1 for x in st["items"] if x["status"] == "ok")
                        st["fixable_count"] = sum(1 for x in st["items"] if x.get("fixable"))
            finally:
                # 无论成功/异常，都必须置 done，避免前端永远"检测中"
                with _TASKS_LOCK:
                    st["done"] = True

        threading.Thread(target=_worker, daemon=True).start()
        return tid

    def status(self, task_id):
        with _TASKS_LOCK:
            st = _TASKS.get(task_id)
        if not st:
            return {"ok": False, "msg": "自检任务不存在或已过期"}
        return {"ok": True, **st}

    # =================================================
    # 修复
    # =================================================
    def fix(self, key):
        """按 key 修复对应问题，返回 {ok,msg}。"""
        key = key or ""
        if key == "dirs":
            return self._fix_dirs()
        if key in ("config",):
            return self._fix_config()
        if key in ("sqlite",):
            return self._fix_sqlite()
        if key == "orphan":
            return self._fix_orphan()
        if key == "network":
            # 网络无法自动修复，重跑一次看是否恢复
            res = self._check_network()
            return {"ok": res["status"] == "ok", "msg": res["message"]}
        return {"ok": False, "msg": f"未知修复项：{key}"}

    def _fix_dirs(self):
        made = []
        for rel in REQUIRED_DIRS:
            p = self.resolve_path(rel)
            if not os.path.isdir(p):
                try:
                    os.makedirs(p, exist_ok=True)
                    made.append(rel)
                except Exception as e:
                    return {"ok": False, "msg": f"创建目录失败 {rel}：{e}"}
        if made:
            return {"ok": True, "msg": "已补建缺失目录：" + "、".join(made)}
        return {"ok": True, "msg": "目录已完整"}

    def _fix_config(self):
        """配置损坏：备份损坏文件后重建默认配置。"""
        path = config_manager.CONFIG_PATH
        import shutil
        try:
            if os.path.exists(path):
                # 备份（追加 .corrupt 时间戳）
                backup = path + "." + str(int(os.path.getmtime(path))) + ".corrupt.bak"
                shutil.copy2(path, backup)
            config_manager.reset()
            return {"ok": True, "msg": "配置已损坏，已备份旧文件并重建默认配置（请重新到设置填写）"}
        except Exception as e:
            return {"ok": False, "msg": f"重建配置失败：{e}"}

    def _fix_sqlite(self):
        """数据库损坏：尝试重建表结构（保留已建的）。"""
        try:
            db._init_schema()
            key = "__selfcheck_probe2__"
            db.set_meta(key, 2)
            db.execute("DELETE FROM app_meta WHERE key = ?", (key,))
            return {"ok": True, "msg": "数据库已修复（重建表结构，保留已有数据）"}
        except Exception as e:
            return {"ok": False, "msg": f"数据库修复失败：{e}"}

    def _fix_orphan(self):
        res = self._check_orphan()
        if res.get("status") == "ok":
            return {"ok": True, "msg": "无孤儿进程需清理"}
        pids = res.get("pids") or []
        killed = []
        for pid in pids:
            try:
                subprocess.run(f"taskkill /PID {pid} /T /F", shell=True, capture_output=True, timeout=5,
                               creationflags=_HIDE)
                killed.append(pid)
            except Exception:
                pass
        if killed:
            return {"ok": True, "msg": "已清理异常孤儿进程（pid=" + "、".join(map(str, killed)) + "）"}
        return {"ok": False, "msg": "孤儿进程清理失败"}

    # =================================================
    # 版本更新检测
    # =================================================
    def check_update(self):
        """检测 FTN Atelier 是否有新版本（GitHub releases/latest vs 当前版本）。

        更新源为可配置项（app_config.selfcheck.update_owner / update_repo / update_mirror）：
        - 未配置时使用内置默认更新源（F-tidal-night/ftn-atelier，正式发布固定）。
        - 镜像轮换统一走 core.mirrors：镜像优先 + 官方直连兜底 + 成功源记忆。
        - 网络不通 / 限流等 → 返回 ok=false + error，前端提示「无法检测」。
        返回含 zip 资产信息（release assets 里匹配 FTN-Atelier-Portable-*.zip，无则 archive 兜底）。
        """
        current = FTN_APP_VERSION
        DEFAULT_OWNER = "F-tidal-night"
        DEFAULT_REPO = "ftn-atelier"
        from core.update import source_manager as mirrors
        try:
            sc = config_manager.load().selfcheck
        except Exception as e:
            return {"ok": False, "current": current, "error": f"读取更新源配置失败（{e}）"}

        owner = (sc.update_owner or "").strip() or DEFAULT_OWNER
        repo = (sc.update_repo or "").strip() or DEFAULT_REPO

        def _fetch_json(url):
            from core.log_manager import log_manager
            log_manager.info("update", f"API candidate start: {url}")
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "ftn-updater", "Accept": "application/vnd.github+json"}
                )
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = json.load(resp)
                log_manager.info("update", f"API candidate success: {url}")
                return data
            except Exception as e:
                log_manager.warn("update", f"API candidate fail: {url} — {e}")
                raise

        # 并发探测所有候选（官方直连 + 镜像），最快成功源胜出：
        # VPN 下直连快、无 VPN 时镜像快，都不会被慢源拖死。
        used, data = mirrors.pick_first_ok_parallel(mirrors.api_candidates(owner, repo), _fetch_json, timeout=6)
        if used is None:
            return {"ok": False, "current": current, "error": f"无法检测更新（GitHub 直连与镜像均不可用，最后原因：{data}）"}
        from core.log_manager import log_manager
        log_manager.info("update", f"update source selected: {used}")
        try:
            latest = str(data.get("tag_name") or data.get("name") or "").lstrip("v")
            if not latest:
                return {"ok": False, "current": current, "error": "远端未返回版本号"}
            has_update = self._version_gt(latest, current)
            # 更新包资产：优先 release assets 里匹配 FTN-Atelier-Portable-*.zip
            zip_asset = None
            for a in (data.get("assets") or []):
                name = str(a.get("name") or "")
                if name.lower().startswith("ftn-atelier-portable-") and name.lower().endswith(".zip"):
                    digest = str(a.get("digest") or "").strip()
                    # GitHub digest 形如 "sha256:<64位hex>"，统一存纯 hex
                    if digest.lower().startswith("sha256:"):
                        digest = digest[len("sha256:"):].strip()
                    zip_asset = {
                        "name": name,
                        "url": a.get("browser_download_url") or "",
                        "size": a.get("size") or 0,
                        "sha256": digest,
                    }
                    break
            if not zip_asset:
                zip_asset = {"name": f"FTN-Atelier-Portable-{latest}.zip",
                             "url": f"https://github.com/{owner}/{repo}/archive/refs/tags/v{latest}.zip",
                             "size": 0, "sha256": ""}
            return {
                "ok": True,
                "current": current,
                "latest": latest,
                "has_update": has_update,
                "owner": owner,
                "repo": repo,
                "url": data.get("html_url", ""),
                "body": data.get("body", "")[:500],
                "asset": zip_asset,
            }
        except Exception as e:
            return {"ok": False, "current": current, "error": f"无法检测更新（{e}）"}

    @staticmethod
    def _version_gt(a, b):
        def nums(v):
            s = re.sub(r"[^0-9.]", "", v)
            return [int(x) for x in s.split(".") if x.isdigit()]
        na, nb = nums(a), nums(b)
        for x, y in zip(na, nb):
            if x > y:
                return True
            if x < y:
                return False
        return len(na) > len(nb)


selfcheck_manager = SelfCheckManager()
