# ============================================
# FTN Studio 引擎注册表 (EngineRegistry)
#
# 需求：「可编辑引擎」——引擎可增/删/改名/重排，
#   但 reForge 为主引擎：可改名、禁止删除。
#
# 默认引擎：
#   reforge  → webui（webui.bat / launch.py）
#   wd       → WD1.4 反推 tag webui（一键启动.bat）
#   lora     → lora-scripts 训练器（A启动脚本.bat）
#   tag      → FTN-tag 库（前端 html 工具）
#
# 引擎启动入口按 kind 探测：
#   webui  → webui.bat / webui-user.bat / launch.py
#   batdir → 一键启动.bat / A启动脚本.bat（关键目录扫描）
#   ftn_tag→ index.html / 启动.bat
#
# 自定义（增删改名重排）持久化到 db meta：engine_custom
# ============================================

import os
import json
import re
import time
import threading

from core.db import db
from core.log_manager import log_manager

# 默认引擎定义：仅保留「主引擎」一个（生图 WebUI）。
# WD1.4 / LoRA 训练器 / FTN-tag 库等不再预置，需要时由用户「新增引擎」添加；
# 主引擎可改名、禁止删除，始终存在。
_DEFAULT_ENGINES = [
    {"key": "reforge", "label": "主引擎", "default_label": "主引擎",
     "path_field": "reforge", "kind": "webui", "primary": True, "multi": False,
     "desc": "主引擎（生图 WebUI，可指向 reForge / Forge 等）"},
]


class EngineRegistry:
    """引擎注册表：增删改名重排 + 入口脚本检测"""

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

    # ---------- 自定义持久化 ----------
    def _read_custom(self):
        c = db.get_meta("engine_custom", None)
        if not c:
            return {"removed": [], "renamed": {}, "added": [], "order": [], "multi": {}, "entries": {}, "primary_key": ""}
        if "entries" not in c:
            c["entries"] = {}
        if "multi" not in c:
            c["multi"] = {}
        if "primary_key" not in c:
            c["primary_key"] = ""
        return c

    def _write_custom(self, c):
        db.set_meta("engine_custom", c)

    # ---------- 引擎列表快照 ----------
    def list_engines(self):
        """返回引擎条目（含根目录路径 + 检测出的入口脚本）。"""
        from core.config_manager import config_manager
        conf = config_manager.load()
        paths = conf.engine_paths

        custom = self._read_custom()
        removed = set(custom.get("removed", []))
        entry_overrides = custom.get("entries", {})
        pk = custom.get("primary_key") or _DEFAULT_ENGINES[0]["key"]

        entries = []
        # 默认引擎（主引擎永在；其余可删）
        for d in _DEFAULT_ENGINES:
            if d["key"] in removed:
                continue
            root = getattr(paths, d["path_field"], "") or ""
            label = custom.get("renamed", {}).get(d["key"], d["label"])
            entry = entry_overrides.get(d["key"]) or (self._detect_entry(d["kind"], root) if root else "")
            entries.append({
                "key": d["key"], "label": label,
                "default_label": d["default_label"],
                "kind": d["kind"], "primary": d["key"] == pk,
                "multi": self._multi_override(d["key"], d.get("multi", False)),
                "desc": d["desc"], "root": root,
                "family": self._family_of(d["kind"], root),
                "entry": entry,
                "entry_overridden": bool(entry_overrides.get(d["key"])),
            })
        # 用户新增引擎
        for a in custom.get("added", []):
            root = paths.extra.get(a["key"], "") or ""
            entry = entry_overrides.get(a["key"]) or (self._detect_entry(a["kind"], root) if root else "")
            entries.append({
                "key": a["key"],
                "label": custom.get("renamed", {}).get(a["key"], a.get("label", a["key"])),
                "default_label": a["key"], "kind": a.get("kind", "webui"),
                "primary": a["key"] == pk, "multi": self._multi_override(a["key"], a.get("multi", False)),
                "desc": a.get("desc", ""),
                "root": root, "entry": entry,
                "family": self._family_of(a.get("kind", "webui"), root),
                "entry_overridden": bool(entry_overrides.get(a["key"])),
            })
        # 排序
        order = custom.get("order", [])
        if order:
            by_key = {e["key"]: e for e in entries}
            ordered = [by_key[k] for k in order if k in by_key]
            rest = [e for e in entries if e["key"] not in set(order)]
            entries = ordered + rest
        # 兜底：primary_key 指向的条目不存在时，回退到默认主引擎
        if not any(e.get("primary") for e in entries):
            for e in entries:
                if e["key"] == _DEFAULT_ENGINES[0]["key"]:
                    e["primary"] = True
                    break
        # 主引擎永远置顶（其余保持自定义顺序，稳定排序）
        entries.sort(key=lambda e: 0 if e.get("primary") else 1)
        return entries

    # ---------- 主引擎 ----------
    def primary_engine(self):
        """返回当前主引擎条目（primary_key 指向；缺失时回退默认 reforge）。"""
        custom = self._read_custom()
        pk = custom.get("primary_key") or _DEFAULT_ENGINES[0]["key"]
        engines = self.list_engines()
        e = next((x for x in engines if x.get("key") == pk), None)
        if e is None:
            e = next((x for x in engines if x.get("primary")), None)
        return e

    def _family_of(self, kind, root):
        """引擎家族：webui 类按目录结构识别（reforge/forge/comfyui/a1111/unknown）；
        脚本/工具类固定 other；未配置路径返回空。"""
        if not root or not os.path.isdir(root):
            return ""
        if kind != "webui":
            return "other"
        from core.base_registry import base_registry
        return base_registry.family_of(root)

    def primary_family(self):
        """当前主引擎家族（"" = 未配置路径；other = 脚本/工具；unknown = 无法识别）。"""
        e = self.primary_engine()
        if not e or not e.get("root"):
            return ""
        return e.get("family") or ""

    def set_primary(self, key):
        """把某引擎设为主引擎：记录 primary_key，并按家族同步主基底。

        reforge / forge（支持家族）：直接切换并同步主基底；
        其它家族（A1111 / ComfyUI / unknown / other）：允许切换，进入「仅启动/停止/重启」的
        受限模式——主引擎切换只改变默认行为，绝不移动/修改/删除任何模型与用户数据。
        """
        e = next((x for x in self.list_engines() if x.get("key") == key), None)
        if not e:
            return {"ok": False, "msg": f"未找到引擎: {key}"}
        if not e.get("root") or not os.path.isdir(e.get("root") or ""):
            return {"ok": False, "msg": f"「{e.get('label')}」尚未配置有效根目录，无法设为主引擎"}
        from core.base_registry import base_registry
        family = e.get("family") or base_registry.family_of(e["root"])
        limited = family not in base_registry.SUPPORTED_FAMILIES
        custom = self._read_custom()
        custom["primary_key"] = key
        self._write_custom(custom)
        if limited:
            fam_txt = base_registry.FAMILY_LABELS.get(family, family or "未知类型")
            msg = (f"已将「{e.get('label')}」设为主引擎（{fam_txt}）。"
                   "该类型暂未适配：仅支持启动/停止/重启，模型/插件/版本下载等功能将显示「不适用」，"
                   "不会改动你的模型与数据。")
            log_manager.warn("engine", f"主引擎已切换（受限）→ {key}（家族 {family}）")
            return {"ok": True, "engine": key, "family": family, "limited": True, "msg": msg}
        base = base_registry.infer(e.get("root")) or "reforge"
        br = base_registry.set_primary(base)
        log_manager.info("engine", f"主引擎已切换 → {key}（基底 {base}）")
        return {"ok": True, "engine": key, "family": family, "limited": False, "primary": base, **br}

    # ---------- 入口脚本检测 ----------
    def _detect_entry(self, kind, root):
        """按 kind 探测启动入口脚本路径。"""
        if not root or not os.path.isdir(root):
            return ""
        import glob
        try:
            if kind == "webui":
                for c in ["webui.bat", "webui-user.bat", "launch.py", "webui.py"]:
                    if os.path.exists(os.path.join(root, c)):
                        return os.path.join(root, c)
            elif kind == "batdir":
                # 深一层扫描关键 bat
                for base, dirs, files in os.walk(root):
                    for f in files:
                        if f.lower() in ("一键启动.bat", "a启动脚本.bat", "启动.bat", "webui.bat"):
                            return os.path.join(base, f)
                        if f.lower().endswith(".bat") and base.count(os.sep) - root.count(os.sep) <= 1:
                            return os.path.join(base, f)
                    if base.count(os.sep) - root.count(os.sep) >= 2:
                        break
            elif kind == "ftn_tag":
                for c in ["index.html", "启动.bat"]:
                    if os.path.exists(os.path.join(root, c)):
                        return os.path.join(root, c)
                # HTML 工具：顶层任意 .html/.htm 也视为入口（index.html 只是常见命名）
                try:
                    for fn in os.listdir(root):
                        if fn.lower().endswith((".html", ".htm")):
                            return os.path.join(root, fn)
                except Exception:
                    pass
            elif kind == "exe":
                # 本地程序：顶层 .exe，无则一级子目录兜底；
                # 优先与目录同名的主程序，其次体积最大，最后第一个
                cands = []
                try:
                    for fn in os.listdir(root):
                        if fn.lower().endswith(".exe"):
                            p = os.path.join(root, fn)
                            if os.path.isfile(p):
                                cands.append(p)
                    if not cands:
                        for sub in os.listdir(root):
                            subp = os.path.join(root, sub)
                            if os.path.isdir(subp):
                                for fn in os.listdir(subp):
                                    if fn.lower().endswith(".exe"):
                                        p = os.path.join(subp, fn)
                                        if os.path.isfile(p):
                                            cands.append(p)
                except Exception:
                    pass
                if not cands:
                    return ""
                base = os.path.basename(root).strip().lower()
                same = [p for p in cands if os.path.splitext(os.path.basename(p))[0].lower() in (base, base.split("-")[0], base.split("_")[0])]
                if same:
                    return same[0]
                try:
                    return max(cands, key=lambda p: os.path.getsize(p))
                except Exception:
                    return cands[0]
        except Exception:
            pass
        return ""

    def detect_engine(self, root="", entry=""):
        """新增引擎自动识别：优先按用户选的启动文件判定类型，
        否则按根目录探测；同时识别家族。返回可直接用于新增的字段。"""
        from core.base_registry import base_registry
        root = (root or "").strip().rstrip("/\\")
        entry = (entry or "").strip()
        if entry and os.path.isfile(entry):
            root = root or os.path.dirname(entry)
        if not root or not os.path.isdir(root):
            return {"ok": False, "msg": "请选择引擎根目录或启动文件"}

        kind = ""
        if entry:
            ename = os.path.basename(entry).lower()
            if ename.endswith(".py"):
                kind = "webui"
            elif ename.endswith(".bat"):
                # webui.bat / webui-user.bat 属于 WebUI；其它 bat 视为启动脚本
                kind = "webui" if ename in ("webui.bat", "webui-user.bat") else "batdir"
            elif ename.endswith((".html", ".htm")) or ename in ("启动.bat",):
                kind = "ftn_tag"
            elif ename.endswith(".exe"):
                kind = "exe"
            else:
                entry = ""  # 未知文件类型：回退到按目录探测
        if not entry or not kind:
            # 顺序：webui → exe → html → batdir
            # （exe 应用目录常含 html 文档，必须 exe 优先；html/exe 都优先于 bat 兜底）
            for k in ("webui", "exe", "ftn_tag", "batdir"):
                e = self._detect_entry(k, root)
                if e:
                    kind, entry = k, e
                    break
        if not kind or not entry:
            return {
                "ok": False,
                "msg": "未能自动识别该目录的启动方式，请直接选择启动文件（.bat / .py / index.html）",
            }

        family = base_registry.family_of(root)
        return {
            "ok": True,
            "root": root,
            "entry": entry,
            "kind": kind,
            "kind_label": {"webui": "WebUI 引擎", "batdir": "启动脚本", "ftn_tag": "HTML 工具", "exe": "本地程序 (EXE)"}.get(kind, kind),
            "family": family,
            "family_label": base_registry.FAMILY_LABELS.get(family, family or "未知"),
        }

    # ---------- 编辑操作 ----------
    def add_engine(self, key, label, kind="webui", desc="", root=""):
        custom = self._read_custom()
        key = (key or "").strip() or self._auto_key(label, custom)
        keys = {e["key"] for e in _DEFAULT_ENGINES} | {a["key"] for a in custom.get("added", [])}
        if key in keys:
            return {"ok": False, "code": "dup", "msg": f"引擎代号已存在: {key}"}
        custom.setdefault("added", []).append({
            "key": key, "label": label, "kind": kind, "desc": desc,
        })
        # 路径写入 extra
        self._set_path(key, root)
        self._write_custom(custom)
        log_manager.info("engine", f"新增引擎 {key}({label})")
        return {"ok": True, "key": key}

    @staticmethod
    def _auto_key(label, custom):
        """由名称自动生成内部代号（对用户不可见）：拉丁字符转小写短横线，
        中文/特殊字符回退时间戳；冲突自动追加序号。"""
        base = re.sub(r"[^A-Za-z0-9]+", "-", str(label or "").strip().lower()).strip("-")
        if len(base) < 2:
            base = f"engine-{int(time.time() * 1000)}"
        keys = {e["key"] for e in _DEFAULT_ENGINES} | {a["key"] for a in custom.get("added", [])}
        cand = base
        n = 2
        while cand in keys:
            cand = f"{base}-{n}"
            n += 1
        return cand

    def remove_engine(self, key):
        """删除引擎（当前主引擎禁止删除）。"""
        primary = self.primary_engine()
        if primary and key == primary["key"]:
            return {"ok": False, "code": "protected", "msg": f"主引擎「{primary.get('label')}」不可删除，仅可改名"}
        custom = self._read_custom()
        removed = custom.setdefault("removed", [])
        if key not in removed:
            removed.append(key)
        if custom.get("primary_key") == key:
            custom["primary_key"] = ""
        custom["added"] = [a for a in custom.get("added", []) if a["key"] != key]
        self._write_custom(custom)
        log_manager.info("engine", f"删除引擎 {key}")
        return {"ok": True}

    def rename_engine(self, key, new_label):
        custom = self._read_custom()
        renamed = custom.setdefault("renamed", {})
        renamed[key] = new_label
        self._write_custom(custom)
        log_manager.info("engine", f"引擎改名 {key} → {new_label}")
        return {"ok": True}

    def reorder(self, keys):
        custom = self._read_custom()
        custom["order"] = list(keys)
        self._write_custom(custom)
        return {"ok": True}

    def set_multi(self, key, enabled):
        """开关某引擎是否允许多开。"""
        custom = self._read_custom()
        overrides = custom.setdefault("multi", {})
        overrides[key] = bool(enabled)
        self._write_custom(custom)
        log_manager.info("engine", f"引擎 {key} 多开开关 → {bool(enabled)}")
        return {"ok": True, "key": key, "multi": bool(enabled)}

    def _multi_override(self, key, default):
        """读取某引擎多开开关（有覆盖用覆盖，否则默认）。"""
        custom = self._read_custom()
        return custom.get("multi", {}).get(key, default)

    # ---------- 配置路径 ----------
    def _set_path(self, key, root):
        from core.config_manager import config_manager
        conf = config_manager.load()
        fld = next((d["path_field"] for d in _DEFAULT_ENGINES if d["key"] == key), None)
        if fld:
            setattr(conf.engine_paths, fld, root or "")
        else:
            conf.engine_paths.extra[key] = root or ""
        config_manager.save(conf)

    def set_path(self, key, root):
        self._set_path(key, root)
        return {"ok": True, "key": key, "root": root}

    def clear_path(self, key):
        """清空某引擎的根目录路径（主引擎不可删，用清空路径代替删除）。
        同时清除启动入口覆盖，避免残留指向旧路径的失效入口文件。
        """
        self._set_path(key, "")
        custom = self._read_custom()
        custom.setdefault("entries", {}).pop(key, None)
        self._write_custom(custom)
        log_manager.info("engine", f"引擎 {key} 路径已清空（含启动入口覆盖）")
        return {"ok": True, "key": key, "root": ""}

    def set_entry(self, key, entry_path):
        """手动指定/更改某引擎的启动入口文件，并持久化。"""
        custom = self._read_custom()
        if not entry_path:
            custom["entries"].pop(key, None)
        else:
            custom["entries"][key] = entry_path
        self._write_custom(custom)
        log_manager.info("engine", f"引擎 {key} 启动入口 → {entry_path or '(自动检测)'}")
        return {"ok": True, "key": key, "entry": entry_path or "", "entry_overridden": bool(entry_path)}

    def re_detect_entry(self, key):
        """清除入口覆盖，并根据当前根目录重新自动检测。"""
        custom = self._read_custom()
        custom["entries"].pop(key, None)
        self._write_custom(custom)
        e = next((x for x in self.list_engines() if x["key"] == key), None)
        return {"ok": True, "key": key, "entry": (e or {}).get("entry", ""), "entry_overridden": False}

    def reset(self):
        db.set_meta("engine_custom", {"removed": [], "renamed": {}, "added": [], "order": [], "multi": {}, "entries": {}, "primary_key": ""})
        return {"ok": True}


# 单例
engine_registry = EngineRegistry()
