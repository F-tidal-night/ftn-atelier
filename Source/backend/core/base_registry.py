# ============================================
# FTN Studio 基底注册表 (BaseRegistry)
#
# 概念：「基底」= 引擎所使用的底层框架（reForge / Forge 等）。
# 一个基底可对应多个版本实例；主基底 = 当前主要使用的基底（引擎），
# 版本的显存模式 / 适配逻辑只跟随主基底。
#
# 职责：
#   - 定义常见基底及其中文名
#   - 每基底对应的显存模式选项（不同框架参数不同）
#   - 根据引擎根目录/入口推断其所属基底
#   - 持久化「主基底」选择（写在配置中）
# ============================================

import os
import re
import threading

from core.db import db
from core.log_manager import log_manager

# 常见基底定义
# vram_modes: 该基底特有的显存模式选项（value → label / 附加参数）
_BASE_DEFS = {
    "reforge": {
        "key": "reforge",
        "label": "reForge",
        "desc": "reForge（Stable Diffusion WebUI 续作，Panchovix 维护，默认主基底）",
        "repo": "https://github.com/Panchovix/stable-diffusion-webui-reForge",
        "vram_modes": [
            {"value": "auto", "label": "自动（reForge 默认）", "arg": "", "hint": "不附加显存参数，让引擎自动判断"},
            {"value": "low",  "label": "低占用", "arg": "--always-offload-from-vram", "hint": "--always-offload-from-vram"},
            {"value": "high", "label": "高占用", "arg": "--always-high-vram", "hint": "--always-high-vram"},
        ],
        # 入口脚本特征 → 判定基础
        "markers": ["webui.bat", "webui-user.bat", "modules/forge", "modules", "reforge"],
        # 静态兜底候选（「从 GitHub 实时拉取 tags」失败时使用，新→旧）
        "candidate_versions": ["1.11.0", "1.10.2", "1.10.1", "1.10.0", "1.9.4", "1.9.3"],
    },
    "forge": {
        "key": "forge",
        "label": "Forge",
        "desc": "Stable Diffusion WebUI Forge（lllyasviel 官方仓库）",
        "repo": "https://github.com/lllyasviel/stable-diffusion-webui-forge",
        "vram_modes": [
            {"value": "auto", "label": "自动（Forge 默认）", "arg": "", "hint": "不附加显存参数，让引擎自动判断"},
            {"value": "low",  "label": "低占用", "arg": "--always-offload-from-vram", "hint": "--always-offload-from-vram"},
            {"value": "high", "label": "高占用", "arg": "--always-high-vram", "hint": "--always-high-vram"},
        ],
        # 入口脚本特征 → 判定基础
        "markers": ["webui.bat", "webui-user.bat", "modules/forge", "modules", "launch.py"],
        # 静态兜底候选（「从 GitHub 实时拉取 tags」失败时使用，新→旧）
        "candidate_versions": ["1.11.0", "1.10.2", "1.10.1", "1.10.0", "1.9.4", "1.9.3"],
    },
}

# 主基底默认：reforge
DEFAULT_PRIMARY_BASE = "reforge"
_BASE_ORDER = ["reforge", "forge"]


class BaseRegistry:
    """基底注册表：基底定义 + 主基底管理 + 推断"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        pass

    # ---------- 基底定义 ----------
    def defs(self):
        """返回全部基底定义列表（按展示顺序）。"""
        return [_BASE_DEFS[k] for k in _BASE_ORDER if k in _BASE_DEFS]

    def get(self, key):
        return _BASE_DEFS.get(key)

    def labels(self):
        """key → label 映射。"""
        return {k: v["label"] for k, v in _BASE_DEFS.items()}

    def candidate_versions(self, key):
        """某基底可下载的候选稳定版本（未安装基底的多版本下载入口，按版本号 新→旧 排序）。

        支持 "1.10.2" / "v0.3.25" 等语义化版本；数字段逐位比较，绝不让 0.3.25 排在 0.3.7 之前。
        """
        d = _BASE_DEFS.get(key)
        vers = list((d or {}).get("candidate_versions", []))
        return sorted(vers, key=lambda s: self._semver_key(s), reverse=True)

    @staticmethod
    def _semver_key(s):
        """把版本字符串解析为可比较的数字列表（忽略前导 v / 尾部预发布段）。"""
        s = str(s).strip().lstrip("vV")
        s = s.split("-")[0]
        parts = re.findall(r"\d+", s)
        return [int(x) for x in parts] if parts else [0]

    # ---------- 主基底 ----------
    def primary(self):
        """当前主基底（持久化于 app_meta；默认 reforge）。"""
        key = db.get_meta("primary_base", DEFAULT_PRIMARY_BASE)
        if key not in _BASE_DEFS:
            key = DEFAULT_PRIMARY_BASE
        return key

    def set_primary(self, key):
        if key not in _BASE_DEFS:
            return {"ok": False, "msg": f"未知基底: {key}"}
        db.set_meta("primary_base", key)
        log_manager.info("backend", f"主基底已切换 → {key}({_BASE_DEFS[key]['label']})")
        return {"ok": True, "primary": key}

    # ---------- 引擎家族（类型识别；供主引擎切换与「不适用」门控） ----------
    FAMILY_LABELS = {
        "reforge": "reForge",
        "forge": "Forge",
        "a1111": "A1111 (SD WebUI)",
        "comfyui": "ComfyUI",
        "unknown": "未知类型",
        "other": "脚本/工具",
    }
    SUPPORTED_FAMILIES = ("reforge", "forge")

    @staticmethod
    def _reforge_content_marker(root):
        """reForge 与 Forge 结构同源（都有 modules_forge / webui.bat），
        靠源码品牌字符串区分：reForge 的 modules_forge/ldm_patched 源码含 "reforge"，
        Forge 不含。仅读少量小文件，绝不遍历模型/venv。"""
        for rel in (
            "modules_forge/initialization.py",
            "modules_forge/config.py",
            "ldm_patched/modules/args_parser.py",
        ):
            p = os.path.join(root, rel)
            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        head = f.read(16384)
                    if "reforge" in head.lower():
                        return True
                except Exception:
                    pass
        return False

    def family_of(self, root):
        """识别引擎家族：reforge / forge / comfyui / a1111 / unknown（空路径返回空）。

        仅用于类型识别与功能门控，不移动/修改任何文件。
        顺序：目录名关键词 → ComfyUI 结构 → Forge 专属结构（modules_forge）→ A1111 骨架 → unknown。
        """
        if not root or not os.path.isdir(root):
            return ""
        base = os.path.basename(root).strip().lower()
        if "reforge" in base:
            return "reforge"
        if "webui-forge" in base or base.endswith("forge"):
            return "forge"
        if "comfy" in base or os.path.isdir(os.path.join(root, "comfy")):
            return "comfyui"
        # Forge / reForge 特有结构（A1111 没有 modules_forge）：用内容品牌区分
        if os.path.isdir(os.path.join(root, "modules_forge")):
            return "reforge" if self._reforge_content_marker(root) else "forge"
        # A1111 骨架：launch.py + modules + webui.py
        if (os.path.exists(os.path.join(root, "launch.py"))
                and os.path.isdir(os.path.join(root, "modules"))
                and os.path.exists(os.path.join(root, "webui.py"))):
            return "a1111"
        if any(k in base for k in ("comfyui", "comfy-ui")):
            return "comfyui"
        if any(k in base for k in ("stable-diffusion-webui", "sd-webui", "automatic1111")):
            return "a1111"
        return "unknown"

    # ---------- 推断基底 ----------
    def infer(self, root):
        """根据引擎根目录 / 入口脚本推断所属基底。"""
        if not root or not os.path.isdir(root):
            return None
        base = os.path.basename(root).strip().lower()
        # 1) 「reforge / forge」为近亲（均含 forge 结构），先按目录名精确区分，
        #    避免 markers（webui.bat 等两者都有）把 forge 目录误判成 reforge。
        if "reforge" in base:
            return "reforge"
        if "webui-forge" in base or base.endswith("forge"):
            return "forge"
        # 2) Forge 家族结构（modules_forge）：目录名不含关键词时用源码品牌区分
        if os.path.isdir(os.path.join(root, "modules_forge")):
            return "reforge" if self._reforge_content_marker(root) else "forge"
        # 3) 其余：先按入口骨架探测
        for key in _BASE_ORDER:
            for m in _BASE_DEFS[key]["markers"]:
                if os.path.exists(os.path.join(root, m)):
                    return key
        # 4) 目录名含基底关键词
        keywords = {
            "reforge": ["reforge"],
            "forge": ["forge", "webui-forge"],
        }
        for key in _BASE_ORDER:
            if any(k in base for k in keywords.get(key, [])):
                return key
        return None

    # ---------- 主引擎状态（供首页告警） ----------
    def primary_health(self, engines):
        """返回主引擎是否为合法基底、以及主基底检测结果，供首页引擎名右侧告警。"""
        primary_base = self.primary()
        # 主引擎：跟随 engine_registry 标记的主引擎条目（primary_key，可指向任意引擎）
        from core.engine_registry import engine_registry
        primary_engine = engine_registry.primary_engine()
        # 若主引擎未设置根目录或无可用入口 → 主引擎有问题
        if not primary_engine or not primary_engine.get("root"):
            return {
                "ok": False,
                "warn": "主引擎未配置根目录 / 未检测到启动入口",
                "primary_base": primary_base,
                "primary_label": self.labels().get(primary_base, primary_base),
            }
        # 检测主引擎根目录所属基底
        inferred = self.infer(primary_engine.get("root"))
        if inferred is None:
            return {
                "ok": False,
                "warn": "主引擎根目录无法断定所属基底",
                "primary_base": primary_base,
                "primary_label": self.labels().get(primary_base, primary_base),
            }
        # 若推断出的基底与当前主基底不一致，提示
        if inferred != primary_base:
            return {
                "ok": True,
                "mismatch": True,
                "warn": f"主引擎实际为 {self.labels().get(inferred, inferred)}，与主基底({self.labels().get(primary_base, primary_base)})不一致",
                "inferred": inferred,
                "primary_base": primary_base,
                "primary_label": self.labels().get(primary_base, primary_base),
            }
        return {
            "ok": True,
            "primary_base": primary_base,
            "primary_label": self.labels().get(primary_base, primary_base),
        }


# 单例
base_registry = BaseRegistry()
