# ============================================
# FTN Studio 环境检测链 module
#
# 一键检测运行环境，涵盖蓝图「启动前检测 Python / CUDA / 显存 / Git / 模型路径」。
# 与 selfcheck 的差异：这里是只读「信息展示」，不做修复、可重跑；
# 输出结构化快照供「疑难解答」页的环境检测分区展示。
# 设计原则：单项探测带超时，失败返回 status=warn/error，绝不抛异常拖垮整体。
# ============================================

import os
import re
import sys
import subprocess
import platform

# Windows 下隐藏子进程控制台窗口（环境探测不闪黑窗）
_HIDE = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0


class EnvDetect:
    """聚合一次环境快照。"""

    # ---- 基础 ----
    @staticmethod
    def _nvidia_smi():
        """定位 nvidia-smi：PATH 优先，兜底常见安装路径（打包环境 PATH 可能不完整）。"""
        import shutil
        p = shutil.which("nvidia-smi")
        if p:
            return p
        for cand in [
            r"C:\Windows\System32\nvidia-smi.exe",
            r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
        ]:
            if os.path.isfile(cand):
                return cand
        return "nvidia-smi"

    @staticmethod
    def _run(cmd, timeout=6):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                               creationflags=_HIDE)
            return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
        except Exception as e:
            return -1, "", str(e)

    def os_info(self):
        return {
            "key": "os",
            "label": "操作系统",
            "status": "ok",
            "value": platform.platform(),
        }

    def python_info(self):
        py = _sys_python
        try:
            code, out, err = self._run([py, "-V"])
            if code == 0 and out:
                return {"key": "python", "label": "Python", "status": "ok", "value": out}
        except Exception:
            pass
        # 兜底：当前进程解释器
        import sys
        return {
            "key": "python",
            "label": "Python",
            "status": "ok" if sys.version_info.major == 3 else "warn",
            "value": sys.version.split()[0],
            "hint": "（后端解释器）",
        }

    def git_info(self):
        code, out, err = self._run(["git", "--version"])
        if code == 0 and out:
            return {"key": "git", "label": "Git", "status": "ok", "value": out}
        return {
            "key": "git", "label": "Git", "status": "error",
            "value": "未检测到 Git",
            "hint": "影响版本下载/更新功能",
        }

    def gpu_info(self):
        """GPU 列表：从 /api/system/gpu 同款 nvidia-smi 查询，含显存与驱动。"""
        code, out, err = self._run(
            [self._nvidia_smi(), "--query-gpu=index,name,memory.total,driver_version", "--format=csv,noheader,nounits"]
        )
        gpus = []
        if code == 0 and out.strip():
            for ln in out.strip().splitlines():
                p = [x.strip() for x in ln.split(",")]
                if len(p) >= 4 and p[0].lstrip("-").isdigit():
                    gpus.append(f"#{p[0]} {p[1]} {p[2]}MB · 驱动 {p[3]}")
        if gpus:
            return {"key": "gpu", "label": "显卡", "status": "ok", "value": "；".join(gpus)}
        return {"key": "gpu", "label": "显卡", "status": "warn", "value": "未检测到 NVIDIA GPU"}

    def model_paths_info(self, cfg):
        """模型关键目录：主引擎各分类目录是否存在。"""
        from core.engine_registry import engine_registry
        primary = engine_registry.primary_engine()
        root = ((primary or {}).get("root") or "").strip()
        if not root:
            return {"key": "model_paths", "label": "模型路径", "status": "warn", "value": "未配置主引擎路径"}
        # 必检：models 根、底模目录、输出目录；Lora/Embedding 允许大小写任一存在
        required = ["models", "models/Stable-diffusion", "outputs"]
        missing = [s for s in required if not os.path.isdir(os.path.join(root, s))]
        models = os.path.join(root, "models")
        has_lora = any(os.path.isdir(os.path.join(models, n))
                       for n in ("Lora", "lora", "LoRA")) if os.path.isdir(models) else False
        has_emb = any(os.path.isdir(os.path.join(models, n))
                      for n in ("Embedding", "embeddings", "Embeddings")) if os.path.isdir(models) else False
        if missing:
            return {
                "key": "model_paths", "label": "模型路径", "status": "warn",
                "value": "缺失：" + "、".join(missing),
            }
        if not has_lora or not has_emb:
            tips = []
            if not has_lora:
                tips.append("Lora")
            if not has_emb:
                tips.append("Embedding")
            return {
                "key": "model_paths", "label": "模型路径", "status": "ok",
                "value": "各核心目录完整（" + "、".join(tips) + " 目录暂缺，添加模型时会自动创建）",
            }
        return {"key": "model_paths", "label": "模型路径", "status": "ok", "value": "各模型分类目录完整"}

    # ---- 聚合入口 ----
    def run(self, cfg=None):
        from core.config_manager import config_manager
        cfg = cfg or config_manager.load()
        items = [
            self.os_info(),
            self.python_info(),
            self.git_info(),
            self.gpu_info(),
            self.model_paths_info(cfg),
        ]
        ok_cnt = sum(1 for x in items if x["status"] == "ok")
        return {
            "items": items,
            "total": len(items),
            "ok_count": ok_cnt,
            "ok": ok_cnt == len(items),
        }


# 后端解释器路径（用于 python_info 调用；环境变量兜底）
_sys_python = os.environ.get("FTN_PYTHON") or "python"


env_detect = EnvDetect()
