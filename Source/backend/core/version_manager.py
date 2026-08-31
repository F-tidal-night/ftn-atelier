# ===========================================
# FTN Studio 版本管理器 (VersionManager)
#
# 对应蓝图「七、reForge版本管理」与 M5 里程碑：
#   - 基底隔离（Core/Engines/<基底>/<版本X>）
#   - 扫描已安装版本实例（支持多基底：reForge / Forge）
#   - 读取版本信息（git tag / commit / branch；目录名绝不作为版本号）
#   - 当前版本标记与切换
#   - 版本下载入口（空基底 → 提供下载路径）
#   - 更新保护清单（不覆盖用户数据/配置）
#
# 基底概念：见 core/base_registry.py。
#   主基底 = 当前主要使用的基底；适配功能只同步主基底。
# ============================================

import os
import re
import sys
import time
import json
import shutil
import tempfile
import zipfile
import subprocess
import threading
import urllib.request

from core.log_manager import log_manager

# Windows 下隐藏子进程控制台窗口（git 操作不闪黑窗）
_HIDE = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
from core.db import db
from core.base_registry import base_registry

# 引擎根目录（Core/Engines）
PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
ENGINES_ROOT = os.path.join(PROJECT_ROOT, "Core", "Engines")

# 更新保护路径清单（蓝图第八章：绝不覆盖用户数据/配置）
PROTECTED_PATHS = [
    "models", "outputs", "extensions", "embeddings",
    "config.json", "ui-config.json", "webui-user.bat",
    "styles.csv", "random_res_config",
]


def _protected_files(engine_dir):
    """需要主动备份的小文件（配置类）：保护清单中的文件 + 根目录 *.json。"""
    rels = [p for p in PROTECTED_PATHS if "." in p]
    out = list(rels)
    try:
        for name in os.listdir(engine_dir):
            if name.endswith(".json") and os.path.isfile(os.path.join(engine_dir, name)):
                if name not in out:
                    out.append(name)
    except OSError:
        pass
    return out


def _backup_protected(engine_dir):
    """checkout 前把受保护的小配置移出工作区（临时目录），避免被 git 覆盖/冲突。"""
    backup = tempfile.mkdtemp(prefix="ftn_protect_")
    rels = _protected_files(engine_dir)
    for rel in rels:
        src = os.path.join(engine_dir, rel)
        if os.path.isfile(src):
            try:
                shutil.move(src, os.path.join(backup, rel.replace(os.sep, "_")))
            except Exception:
                pass
    return backup, rels


def _restore_protected(engine_dir, backup, rels):
    """checkout 后把受保护配置原样放回（保护机制：更新/回退/转换绝不覆盖用户配置）。"""
    if not backup or not os.path.isdir(backup):
        return
    for rel in rels:
        src = os.path.join(backup, rel.replace(os.sep, "_"))
        if os.path.isfile(src):
            try:
                shutil.copy2(src, os.path.join(engine_dir, rel))
            except Exception:
                pass
    try:
        shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        pass

# 各基底的默认下载地址（实际以 base_registry 中该基底的 repo 为准，
# 此处保留作为兜底 + note 文案）。reForge 与 Forge 是不同仓库：
# reForge = Panchovix/stable-diffusion-webui-reForge；Forge = lllyasviel/stable-diffusion-webui-forge。
_BASE_DOWNLOAD = {
    "reforge": {
        "repo": "https://github.com/Panchovix/stable-diffusion-webui-reForge",
        "note": "Git 克隆 reForge 官方仓库（Panchovix/stable-diffusion-webui-reForge）到 Core/Engines 目录即可（建议英文纯路径）。",
    },
    "forge": {
        "repo": "https://github.com/lllyasviel/stable-diffusion-webui-forge",
        "note": "Git 克隆 Forge 仓库到 Core/Engines 目录即可（建议英文纯路径）。",
    },
}


def _repo_of(base_key):
    """返回某基底的官方下载仓库 URL：优先 base_registry 定义，退到 _BASE_DOWNLOAD。"""
    bdef = base_registry.get(base_key)
    if bdef and bdef.get("repo"):
        return bdef["repo"]
    return _BASE_DOWNLOAD.get(base_key, {}).get("repo", "")


def _repo_path(repo):
    """把仓库地址规整为 owner/name 形式（兼容已带 https://github.com/ 前缀的完整 URL）。"""
    s = str(repo or "").strip().rstrip("/")
    for pre in ("https://github.com/", "http://github.com/"):
        if s.startswith(pre):
            s = s[len(pre):]
            break
    return s


def _git_url_candidates(repo):
    """git URL 候选列表（统一走 core.mirrors：镜像优先 + 官方直连兜底 + 成功记忆）。"""
    from core.update import source_manager as mirrors
    return mirrors.url_candidates(repo)


def _fetch_all_tags(repo_url, timeout=25):
    """git ls-remote --tags 拉取仓库全部 tag 名（含 latest/previous 等浮动标记）。

    并发探测直连与镜像（最快成功源胜出，避免慢源拖死），都不通才抛异常。
    """
    from core.update import source_manager as mirrors

    def _fetch(url):
        return subprocess.check_output(
            ["git", "ls-remote", "--tags", "--refs", url],
            stderr=subprocess.DEVNULL, text=True, timeout=timeout,
            creationflags=_HIDE,
        )

    used, out = mirrors.pick_first_ok_parallel(_git_url_candidates(repo_url), _fetch, timeout=timeout + 5)
    if used is None:
        raise RuntimeError(f"拉取版本候选失败（GitHub 直连与镜像均不可用）：{out}")
    seen = set()
    tags = []
    for line in out.splitlines():
        m = re.search(r"refs/tags/([^}^{]+)$", line.strip())
        if not m:
            continue
        t = m.group(1).strip()
        if t not in seen:
            seen.add(t)
            tags.append(t)
    return tags


def _filter_version_tags(tags):
    """从 tag 列表过滤出语义化版本（数字 + 可选尾缀字母），按 新→旧 排序。
    latest / previous 等浮动 tag 不算版本，排除。
    """
    seen = set()
    vers = []
    for t in tags:
        norm = str(t).lstrip("vV").split("-")[0]
        # 版本 tag：数字 + 可选点分 + 可选尾缀字母（如 v1.7.0d、1.10.1RC）；
        # 纯字母/浮动 tag（如 latest）不算版本，排除。
        if not re.fullmatch(r"\d+(?:\.\d+)*[A-Za-z]*", norm):
            continue
        # 按「去 v 后版本串」去重，避免同时出现 v1.10.1 / 1.10.1
        if norm in seen:
            continue
        seen.add(norm)
        vers.append(t)
    return sorted(vers, key=lambda v: [int(x) for x in re.findall(r"\d+", v)], reverse=True)


def _fetch_tags(repo_url, timeout=25):
    """拉取仓库全部 tags，过滤出语义化版本，按 新→旧 排序（直连→镜像）。"""
    return _filter_version_tags(_fetch_all_tags(repo_url, timeout=timeout))


def _num_tuple(v):
    """版本串 → (major, minor) 数值元组，用于判断是否「大版本」跳变。"""
    nums = [int(x) for x in re.findall(r"\d+", str(v))]
    if len(nums) >= 2:
        return (nums[0], nums[1])
    if len(nums) == 1:
        return (nums[0], 0)
    return ()


_RESCUE_PREFIX = ".ftn-userdata-backup-"


def _prune_rescue_backups(parent_dir, keep=3):
    """救援备份（还原用户数据失败时生成）只保留最近 keep 份，更旧自动清理，防止堆积。
    备份名为 .ftn-userdata-backup-<epoch 秒>，按时间戳排序即可。"""
    try:
        entries = []
        for n in os.listdir(parent_dir):
            if not n.startswith(_RESCUE_PREFIX):
                continue
            ts = n[len(_RESCUE_PREFIX):]
            if not ts.isdigit():
                continue
            entries.append((int(ts), os.path.join(parent_dir, n)))
        entries.sort(key=lambda x: x[0])
        for _, p in entries[:-keep]:
            shutil.rmtree(p, ignore_errors=True)
            log_manager.warn("version", f"已清理过旧救援备份（仅保留最近 {keep} 份）：{p}")
    except Exception as e:
        log_manager.warn("version", f"救援备份清理失败（不影响使用）: {e}")


class VersionManager:
    """版本管理：多基底版本隔离 + 更新保护 + 插件"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._demo = None       # None=待判定；True/False 惰性缓存
        # 打包正式版（Electron 注入 FTN_PACKAGED=1）：彻底关闭演示数据
        self._packaged = (os.environ.get("FTN_PACKAGED") or "").strip() == "1"

    @property
    def is_demo(self):
        """是否无真实引擎实例（演示模式）。

        打包正式版（FTN_PACKAGED=1）一律返回 False——不注入任何演示版本，
        未安装的基底如实显示「未装 + 下载此版本」。
        """
        if self._packaged:
            return False
        if self._demo is None:
            self._demo = True
            if os.path.isdir(ENGINES_ROOT):
                entries = [e for e in os.listdir(ENGINES_ROOT)
                           if not e.startswith('.') and e != '.gitkeep']
                if entries:
                    self._demo = False
        return self._demo

    # =================================================
    # 版本读取
    # =================================================
    def _read_version(self, engine_dir):
        """读取版本身份：repository + branch + commit（tag 仅作友好名称）。

        安装来源三类（不互相伪造）：
          atelier_managed：.ftn/engine.json 记录（Atelier 安装/接管，记录 commit）
          git           ：存在 .git，读取 branch / commit / tag
          external      ：用户自带的 ZIP/目录（无 .git、无安装记录）→ 版本 Unknown；
                          用户可在 UI 手动绑定 commit/tag（.ftn/bind.json，仅作展示）
        install_path 的目录名绝不当作版本；-main/-master 仅作 branch 推断。
        """
        git_tag, git_commit, git_branch = "", "", ""
        date = ""
        install_source = "external"
        branch = ""
        user_bound = False
        dirname = os.path.basename(engine_dir)
        if os.path.exists(os.path.join(engine_dir, ".git")):
            install_source = "git"
            git_tag = self._git_tag(engine_dir)
            git_commit = self._git_commit(engine_dir)
            git_branch = self._git_branch(engine_dir)
            date = self._git_commit_date(engine_dir)
        else:
            record = self._read_managed_record(engine_dir)
            if record and record.get("install_source") == "atelier_managed":
                install_source = "atelier_managed"
                branch = record.get("branch") or ""
                git_commit = record.get("commit") or ""
                git_tag = record.get("tag") or ""
                date = str(record.get("installed_at") or "")[:10]
            else:
                # 用户手动绑定优先于目录名推断（-main/-master 仅作 branch 兜底）
                bind = self._read_user_bind(engine_dir)
                if bind and (bind.get("commit") or bind.get("tag")):
                    git_commit = str(bind.get("commit") or "").strip()
                    git_tag = str(bind.get("tag") or "").strip()
                    branch = str(bind.get("branch") or "").strip()
                    date = str(bind.get("date") or "")[:10]
                    user_bound = True
                elif dirname.endswith("-main"):
                    branch = "main"
                elif dirname.endswith("-master"):
                    branch = "master"
        version = git_tag or git_commit
        return {
            "version": version,
            "git_tag": git_tag,
            "git_commit": git_commit,
            "git_branch": git_branch,
            "install_source": install_source,
            "branch": branch,
            "date": date,
            "user_bound": user_bound,
            "dir_name": dirname,
            "repository": _repo_of(_base_of_path(engine_dir) or "reforge"),
        }

    # ---------- Atelier Managed 安装记录 ----------
    def _read_managed_record(self, engine_dir):
        try:
            with open(os.path.join(engine_dir, ".ftn", "engine.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _write_managed_record(self, engine_dir, record):
        ftn_dir = os.path.join(engine_dir, ".ftn")
        os.makedirs(ftn_dir, exist_ok=True)
        with open(os.path.join(ftn_dir, "engine.json"), "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

    def _read_user_bind(self, engine_dir):
        """读取外部 ZIP 实例的手动版本身份绑定（.ftn/bind.json）。"""
        try:
            with open(os.path.join(engine_dir, ".ftn", "bind.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def bind_external(self, engine_id, commit="", tag="", branch=""):
        """外部 ZIP 实例手动绑定版本身份（commit/tag 由用户提供，仅作展示，不伪造 .git）。

        能可靠匹配（用户知道来源 commit/tag）就绑定；匹配不了保持 Unknown。
        """
        if not os.path.isdir(engine_id):
            return {"ok": False, "msg": f"实例目录不存在: {engine_id}"}
        if os.path.isdir(os.path.join(engine_id, ".git")):
            return {"ok": False, "msg": "该实例是 git 安装，版本身份自动读取，无需手动绑定"}
        rec = self._read_managed_record(engine_id)
        if rec and rec.get("install_source") == "atelier_managed":
            return {"ok": False, "msg": "该实例由 Atelier 管理，自动记录 commit，无需手动绑定"}
        commit = str(commit or "").strip()
        tag = str(tag or "").strip()
        branch = str(branch or "").strip()
        if not commit and not tag:
            return {"ok": False, "msg": "请填写 commit 或 tag 至少一项（用于识别该 ZIP 的来源版本）"}
        ftn_dir = os.path.join(engine_id, ".ftn")
        os.makedirs(ftn_dir, exist_ok=True)
        bind = {
            "commit": commit,
            "tag": tag,
            "branch": branch,
            "date": time.strftime("%Y-%m-%d"),
            "bound_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(os.path.join(ftn_dir, "bind.json"), "w", encoding="utf-8") as f:
            json.dump(bind, f, ensure_ascii=False, indent=2)
        log_manager.info("version", f"外部实例已手动绑定版本身份: {os.path.basename(engine_id)}")
        return {"ok": True, "msg": "已绑定版本身份（仅作展示，不改变安装来源；可在详情重新绑定）"}

    def _git_commit_date(self, engine_dir):
        """git 实例当前 commit 的日期（YYYY-MM-DD），读不到返回空。"""
        try:
            out = subprocess.check_output(
                ["git", "-C", engine_dir, "log", "-1", "--format=%cs"],
                stderr=subprocess.DEVNULL, text=True, timeout=5,
                creationflags=_HIDE,
            ).strip()
            return out if len(out) == 10 else ""
        except Exception:
            return ""

    def _git_tag(self, engine_dir):
        """Git tag（无 tag 时返回空，纯 commit 哈希不算 tag）。"""
        try:
            out = subprocess.check_output(
                ["git", "-C", engine_dir, "describe", "--tags", "--always", "--dirty"],
                stderr=subprocess.DEVNULL, text=True, timeout=5,
                creationflags=_HIDE,
            ).strip()
            if not out:
                return ""
            # 纯 commit 哈希（如 abcdef1）不是 tag
            if re.fullmatch(r"[0-9a-f]{7,40}", out):
                return ""
            return out
        except Exception:
            return ""

    def _git_commit(self, engine_dir):
        try:
            out = subprocess.check_output(
                ["git", "-C", engine_dir, "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL, text=True, timeout=5,
                creationflags=_HIDE,
            ).strip()
            return out or ""
        except Exception:
            return ""

    def _git_branch(self, engine_dir):
        try:
            out = subprocess.check_output(
                ["git", "-C", engine_dir, "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL, text=True, timeout=5,
                creationflags=_HIDE,
            ).strip()
            return out or ""
        except Exception:
            return ""

    def _scan_path_for_base(self, base_key):
        """扫描基底目录 Core/Engines/<基底>/ 下所有版本实例。"""
        base_dir = os.path.join(ENGINES_ROOT, base_key)
        rows = []
        if not os.path.isdir(base_dir):
            return rows
        for node in sorted(os.listdir(base_dir)):
            d = os.path.join(base_dir, node)
            if not os.path.isdir(d) or node.startswith("."):
                continue
            try:
                info = self._read_version(d)
                size = _dir_size_cached(d)
                try:
                    mtime = os.path.getmtime(d)
                except OSError:
                    mtime = 0
                rows.append({
                    "id": d,
                    "name": node,
                    "version": info["version"],
                    "git_tag": info["git_tag"],
                    "git_commit": info["git_commit"],
                    "git_branch": info["git_branch"],
                    "install_source": info["install_source"],
                    "branch": info["branch"],
                    "path": d,
                    "size": size,
                    "dir_name": info["dir_name"],
                    "install_path": d,
                    "repository": _repo_of(base_key),
                    "engine_name": base_registry.labels().get(base_key, base_key),
                    "base": base_key,
                    "updated_time": mtime,
                })
            except Exception as e:
                log_manager.warn("version", f"扫描版本实例失败（已跳过）: {d} — {e}")
                continue
        return rows

    # =================================================
    # 版本列表（按基底分组 + 新旧排序 + active 居中）
    # =================================================
    def list_versions(self):
        """列出所有版本实例，按基底分组。返回 { base_key: [rows...] }。"""
        groups = {}
        if self.is_demo:
            rows = self._demo_versions()
            for r in rows:
                groups.setdefault(r["base"], []).append(r)
        else:
            for b in base_registry.defs():
                rows = self._scan_path_for_base(b["key"])
                groups[b["key"]] = rows
            # 注册过的外部引擎根目录（主引擎 + 用户自建，不在 Core/Engines 下）→ 也识别为已装实例；
            # 基底按目录实际内容推断（reForge/Forge 用目录名+源码品牌），绝不盲目跟主基底。
            seen = {r.get("path") for rows in groups.values() for r in rows}
            for ext in self._external_engines():
                if ext and ext["path"] not in seen:
                    groups.setdefault(ext["base"], []).append(ext)
                    seen.add(ext["path"])
        # 每个基底内部：新旧排序
        for k, rows in groups.items():
            rows.sort(key=lambda r: self._ver_key(r["version"]), reverse=True)
        return groups

    def _external_engines(self):
        """注册过的、根目录在 Core/Engines 之外的引擎（主引擎或用户自建）→ 已装实例行。

        基底按目录实际内容推断（base_registry.infer，目录名 + 源码品牌），
        推断不出才回退到当前主基底；绝不因为主基底是 forge 就把 reForge 误判成 forge。
        """
        out = []
        try:
            from core.engine_registry import engine_registry
            seen = set()
            for eng in engine_registry.list_engines():
                root = (eng or {}).get("root") or ""
                if not root or not os.path.isdir(root) or root in seen:
                    continue
                seen.add(root)
                # 根目录在 Core/Engines 之内的，已由 _scan_path_for_base 覆盖，跳过
                try:
                    rel = os.path.relpath(root, ENGINES_ROOT)
                    if rel != "." and not rel.startswith(".."):
                        continue
                except Exception:
                    pass
                # 版本页只面向 reForge / Forge：外部引擎按实际家族归组，
                # 其它家族（ComfyUI / A1111 / 未知）不进版本页，避免误导；
                # 绝不盲目跟主基底（例如主基底是 forge 时不能把 reForge 归到 forge）。
                fam = base_registry.family_of(root)
                if fam not in ("reforge", "forge"):
                    continue
                base = fam
                info = self._read_version(root)
                out.append({
                    "id": root,
                    "name": info["dir_name"] or os.path.basename(root.rstrip("/\\")),
                    "version": info["version"],
                    "git_tag": info["git_tag"],
                    "git_commit": info["git_commit"],
                    "git_branch": info["git_branch"],
                    "install_source": info["install_source"],
                    "branch": info["branch"],
                    "path": root,
                    # 外部引擎目录可能几十 GB，不做全量遍历（体积显示为 0）
                    "size": 0,
                    "dir_name": info["dir_name"],
                    "install_path": root,
                    "repository": _repo_of(base),
                    "engine_name": base_registry.labels().get(base, base),
                    "base": base,
                    "external": True,
                    "updated_time": os.path.getmtime(root),
                })
        except Exception as e:
            log_manager.warn("version", f"外部引擎识别失败: {e}")
        return out

    def _ver_key(self, v):
        m = re.findall(r"\d+", v)
        return [int(x) for x in m] if m else [0]

    def _demo_versions(self):
        """演示：仅主基底 reForge 生成若干版本（含历史与更新版本）。
        其他基底（Forge）保持「未安装」状态（未装 → 下载入口），
        避免把演示数据误当成已安装实例。
        """
        demo = []
        reforge_rows = [
            ("reForge-1.10.1", "1.10.1", "2026-06-01"),
            ("reForge-1.10.2", "1.10.2", "2026-07-15"),
            ("reForge-1.11.0", "1.11.0", "2026-08-20"),
        ]
        for i, (name, ver, date) in enumerate(reforge_rows):
            demo.append({
                "id": name, "name": name, "version": ver,
                "path": f"Core/Engines/reforge/{name}",
                "size": 2.4e9 + i * 3e8, "dir_name": name,
                "base": "reforge",
                "updated_time": time.mktime(time.strptime(date, "%Y-%m-%d")),
            })
        # 注：Forge 不做演示版本，一律显示「未装」。
        return demo

    def _annotate_active(self, groups):
        """标记 active 版本（全局唯一）。"""
        active = db.get_meta("active_engine", None)
        all_rows = [r for rows in groups.values() for r in rows]
        # active 缺失或指向已不存在/已移除的实例 → 回退到“最新版本”行，
        # 避免整页没有一个「当前」导致界面看不懂
        if not self.is_demo and all_rows and (
            active is None or active not in {r["id"] for r in all_rows}
        ):
            top = max(all_rows, key=lambda r: self._ver_key(r["version"]))
            active = top["id"]
        for rows in groups.values():
            for r in rows:
                r["active"] = r["id"] == active

    def set_active(self, engine_id):
        rows = [r for rows in self.list_versions().values() for r in rows]
        ids = [r["id"] for r in rows]
        if engine_id not in ids:
            return {"ok": False, "msg": f"未找到引擎实例: {engine_id}", "ids": ids}
        db.set_meta("active_engine", engine_id)
        log_manager.info("version", f"当前引擎已切换 → {engine_id}")
        return {"ok": True, "active": engine_id}

    def current(self):
        groups = self.list_versions()
        self._annotate_active(groups)
        for rows in groups.values():
            for r in rows:
                if r.get("active"):
                    return r
        return None

    # =================================================
    # 基底快照（供版本页布局 / 首页告警）
    # =================================================
    def snapshot(self):
        groups = self.list_versions()
        self._annotate_active(groups)

        primary = base_registry.primary()
        cur = self.current()
        # 横幅显示「当前主引擎」应为实际在用引擎的基底（外部引擎可能与其基底分组不同，
        # 不盲目跟随配置的主基底——例如主基底是 forge、实际用的是外部 reForge）
        primary_label = base_registry.labels().get(
            (cur or {}).get("base") or primary,
            base_registry.labels().get(primary, primary),
        )
        defs = base_registry.defs()
        bases = []
        for d in defs:
            rows = groups.get(d["key"], [])
            dl = _BASE_DOWNLOAD.get(d["key"], {})
            bases.append({
                "key": d["key"],
                "label": d["label"],
                "desc": d.get("desc", ""),
                "installed": len(rows) > 0,
                "version_count": len(rows),
                "download_url": _repo_of(d["key"]),
                "download_note": dl.get("note", ""),
                "active_version": next((r["id"] for r in rows if r.get("active")), None),
                "versions": rows,
            })

        return {
            "demo": self.is_demo,
            "engines_root": ENGINES_ROOT,
            "primary_base": primary,
            "primary_label": primary_label,
            "bases": bases,
            "current": cur,
        }

    # =================================================
    # 版本切换预览（venv 策略 + 配置文件迁移差异，供前端二次确认）
    # =================================================
    def preview_switch(self, engine_id):
        try:
            groups = self.list_versions()
            target = None
            for rows in groups.values():
                for r in rows:
                    if r["id"] == engine_id:
                        target = r
                        break
            if not target:
                return {"ok": False, "msg": f"未找到版本实例: {engine_id}"}
            cur = self.current()
            venv = {"strategy": "unknown", "reason": ""}
            try:
                venv = self.venv_strategy(target["base"], target.get("version"))
            except Exception as e:
                venv = {"ok": False, "strategy": "unknown", "reason": str(e)}
            # 配置文件迁移差异（仅文件类保护项；目录类数据不提示迁移）
            configs = []
            for rel in PROTECTED_PATHS:
                if "." not in rel:
                    continue
                cur_p = os.path.join(cur["path"], rel) if cur else None
                tgt_p = os.path.join(target["path"], rel)
                cfg = {
                    "name": rel,
                    "in_current": bool(cur_p and os.path.exists(cur_p)),
                    "in_target": os.path.exists(tgt_p),
                    "changed": False,
                }
                if cfg["in_current"] and cfg["in_target"]:
                    try:
                        a, b = os.stat(cur_p), os.stat(tgt_p)
                        cfg["changed"] = a.st_size != b.st_size or abs(a.st_mtime - b.st_mtime) > 1
                    except OSError:
                        pass
                configs.append(cfg)
            return {
                "ok": True,
                "engine_id": engine_id,
                "base": target.get("base"),
                "version": target.get("version"),
                "venv": venv,
                "configs": configs,
                "current": {"id": cur["id"], "version": cur.get("version")} if cur else None,
            }
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    # =================================================
    # 更新保护路径（版本页展示；更新时永不覆盖）
    # =================================================
    def protected_paths(self):
        return {"items": list(PROTECTED_PATHS)}

    # =================================================
    # 下载（版本下载）
    # =================================================
    def download_info(self, base_key):
        """返回某基底下载信息；若该基底已有版本则提示已存在。"""
        dl = _BASE_DOWNLOAD.get(base_key, {})
        return {
            "ok": True,
            "base": base_key,
            "label": base_registry.labels().get(base_key, base_key),
            "repo": _repo_of(base_key),
            "url": _repo_of(base_key),
            "note": dl.get("note", "请选择纯英文路径进行版本下载（避免中文路径导致依赖编译失败）。"),
        }

    def download_candidates(self, base_key, limit=6, fetch=True):
        """某基底的可下载候选稳定版本列表。

        Forge / reForge 没有稳定语义版本号，以 Git Commit 为真实版本：
          - 「main（最新）」：滚动更新仓库，main 分支即最新，永远置顶；
          - 官方正式 tag（如 v1.7.0d）；
          - Forge 的 previous 浮动标记（上一版，可下载可回退）。
        本机已安装版本过滤掉与候选重复的项后垫底显示。
        GitHub 拉取失败时仅保留「main」入口（能否下载取决于网络），不再展示无法下载的假版本号。

        返回: {ok, base, label, repo, limit, fetched, fetch_error,
               remote(实时版本,仅 fetch 成功时), versions(候选+已装合并), installed}
        """
        label = base_registry.labels().get(base_key, base_key)
        repo = _repo_of(base_key)
        info = {
            "ok": True, "base": base_key, "label": label, "repo": repo,
            "limit": limit, "fetched": False, "fetch_error": None,
            "versions": [], "installed": [],
        }
        remote = []
        if fetch and repo:
            try:
                all_tags = _fetch_all_tags(repo)
                info["fetched"] = True
                remote = ["main"]
                for t in _filter_version_tags(all_tags):
                    if t not in remote:
                        remote.append(t)
                if "previous" in all_tags and "previous" not in remote:
                    remote.append("previous")
            except Exception as e:
                info["fetch_error"] = str(e)
        if not remote:
            remote = ["main"]
        info["remote"] = [v for v in remote]

        # 候选：最新 limit 个置顶
        top = remote[:limit]
        top_low = {str(v).lower() for v in top}

        # 本机已安装版本：过滤与候选重复项后垫底
        installed = []
        for r in self._scan_path_for_base(base_key):
            v = r.get("version", "")
            if not str(v).strip():
                continue  # 未知版本不进入候选/已装列表
            if str(v).lower() in top_low:
                continue
            if v not in installed:
                installed.append(v)

        info["versions"] = top + installed
        info["installed"] = installed
        return info

    def git_candidates(self, engine_id):
        """git 实例（clone 版）的新旧候选：
        更新 = 所属分支远端最新 commit（滚动更新）；回退 = 仓库正式 tag + previous（如有）。
        """
        if not os.path.isdir(engine_id):
            return {"ok": False, "msg": f"实例目录不存在: {engine_id}"}
        if not os.path.isdir(os.path.join(engine_id, ".git")):
            return {"ok": False, "msg": "该实例不是 git 安装（ZIP 请用「接管为 Atelier 管理」或手动绑定）"}
        base = _base_of_path(engine_id) or base_registry.infer(engine_id)
        repo = _repo_of(base)
        if not repo:
            return {"ok": False, "msg": "无法确定该实例所属仓库，无法检测候选"}
        branch = self._git_branch(engine_id) or "main"
        cur_commit = self._git_commit(engine_id) or ""
        update, rollback = [], []
        try:
            head = self._gh_commit_sha(repo, f"refs/heads/{branch}")
            if head and cur_commit and head != cur_commit:
                update.append({"type": "latest", "label": f"{branch} @ {head[:7]}", "target": ""})
        except Exception as e:
            log_manager.warn("version", f"git_candidates 取分支 commit 失败: {e}")
        raw = []
        try:
            raw = _fetch_all_tags(repo)
        except Exception as e:
            log_manager.warn("version", f"git_candidates 拉取 tags 失败: {e}")
        for t in _filter_version_tags(raw):
            rollback.append({"type": "tag", "label": t, "target": t})
        if "previous" in raw:
            rollback.append({"type": "tag", "label": "previous（上一版）", "target": "previous"})
        return {
            "ok": True,
            "repo": repo,
            "branch": branch,
            "current": {"branch": branch, "commit": cur_commit},
            "update": update,
            "rollback": rollback,
        }

    # =================================================
    # 真实版本下载 / 更新 / 回退（git 操作，后台任务）
    # =================================================
    def download(self, base_key, version, write_to=None):
        """按版本号从官方仓库真实 git clone 到 Core/Engines/<base>/ 成为新实例（后台任务）。"""
        base = base_registry.get(base_key)
        if not base:
            return {"ok": False, "msg": f"未知基底: {base_key}"}
        repo = _repo_of(base_key)
        if not repo:
            return {"ok": False, "msg": f"{base_key} 未配置官方仓库地址"}
        label = base.get("label", base_key)
        dest = write_to or os.path.join(ENGINES_ROOT, base_key, f"{label}-{version}")
        if os.path.isdir(dest):
            return {"ok": False, "msg": f"目标目录已存在: {dest}\n（若需更新请使用更新功能）"}
        task_id = _new_task("download", _run_clone_job, base_key, version, dest)
        return {"ok": True, "task_id": task_id, "dest": dest}

    def download_status(self, task_id):
        return _task_status(task_id)

    def update_download(self, asset_url=None, expected_version=None, asset_size=0, asset_sha256=""):
        """下载最新版 FTN Atelier 更新包（GitHub Release 资产 zip）到 Data/updates/，后台任务。

        可传入前端最近一次检测的 asset_url / expected_version 复用结果，避免重复请求 GitHub；
        未传入时重新执行 check_update。下载由 Update Engine 编排（探测/断点续传/校验）。"""
        from core.update import update_service
        from core.update.models import DownloadTask
        url = (asset_url or "").strip()
        latest = str(expected_version or "").strip()
        size = int(asset_size or 0)
        sha = str(asset_sha256 or "").strip()
        if not url or not latest:
            from core.selfcheck import selfcheck_manager
            info = selfcheck_manager.check_update()
            if not info.get("ok"):
                return {"ok": False, "msg": info.get("error") or "检测更新失败"}
            asset = info.get("asset") or {}
            url = asset.get("url") or ""
            latest = str(info.get("latest") or "")
            size = int(asset.get("size") or 0)
            sha = str(asset.get("sha256") or "")
        if not url:
            return {"ok": False, "msg": "未找到更新包下载地址"}
        updates_dir = os.path.join(PROJECT_ROOT, "Data", "updates")
        try:
            os.makedirs(updates_dir, exist_ok=True)
        except Exception:
            pass
        # 自动清理历史安装包/临时文件（保留当前目标版本，断点续传与失败重试不受影响）
        try:
            from core.update import resume as resume_mod
            resume_mod.cleanup_updates_dir(updates_dir, keep_version=latest)
        except Exception:
            pass
        dest = os.path.join(updates_dir, f"FTN-Atelier-{latest}.zip")
        task = DownloadTask(
            version=latest, asset_url=url, asset_size=size, asset_sha256=sha,
            dest_zip=dest, part_path=dest + ".part",
        )
        task_id = _new_task("update-download", update_service.start_download, task)
        return {"ok": True, "task_id": task_id, "dest": dest, "latest": latest}

    def env_install(self, engine_id):
        """对实例执行「环境安装/修复」：venv + PyTorch + requirements + CLIP 修复。
        用于下载后补装（含之前安装被 CLIP 构建失败中断的实例）。"""
        if not os.path.isdir(engine_id):
            return {"ok": False, "msg": f"实例目录不存在: {engine_id}"}
        task_id = _new_task("env-install", _install_engine_env, engine_id)
        return {"ok": True, "task_id": task_id, "dest": engine_id}

    def env_check(self, engine_id):
        """检查实例环境：venv / PyTorch / scikit-image / numpy 版本对齐，返回逐项状态。"""
        if not os.path.isdir(engine_id):
            return {"ok": False, "msg": f"实例目录不存在: {engine_id}"}
        venv_py = os.path.join(engine_id, "venv", "Scripts", "python.exe")
        items = []
        if not os.path.exists(venv_py):
            items.append({"name": "虚拟环境", "ok": False, "msg": "未创建 venv（首次需安装环境）"})
            return {"ok": False, "items": items}
        items.append({"name": "虚拟环境", "ok": True, "msg": "venv 存在"})
        checks = [("PyTorch", "import torch")]
        req = ""
        for n in ("requirements_versions.txt", "requirements.txt"):
            if os.path.exists(os.path.join(engine_id, n)):
                req = os.path.join(engine_id, n)
                break
        if req and "scikit-image" in open(req, encoding="utf-8", errors="replace").read():
            checks.append(("scikit-image", "import numpy; import skimage"))
        for name, code in checks:
            ok = _run_import(venv_py, code)
            items.append({
                "name": name, "ok": ok,
                "msg": "可正常导入" if ok else "导入失败（依赖不完整或二进制不兼容）",
            })
        pin = _extract_numpy_pin(req) if req else ""
        if pin:
            try:
                r = subprocess.run(
                    [venv_py, "-c", "import numpy; print(numpy.__version__)"],
                    capture_output=True, text=True, timeout=30, creationflags=_HIDE,
                )
                cur = (r.stdout or "").strip()
                want = pin.split("==")[-1].split(",")[0].strip()
                ok = bool(cur) and cur == want
                items.append({
                    "name": "numpy 版本", "ok": ok,
                    "msg": f"当前 {cur or '未知'}，要求 {pin}" if not ok else f"已对齐 {pin}",
                })
            except Exception as e:
                items.append({"name": "numpy 版本", "ok": False, "msg": f"读取失败：{e}"})
        return {"ok": all(i["ok"] for i in items), "items": items}

    def update_version(self, engine_id, target_version=None):
        """对 git 实例真实更新：
        未指定目标 → 更新到所属分支（如 main）远端最新 commit（滚动更新，commit 即版本）；
        指定 tag（如 v1.7.0d / previous）→ fetch + checkout 到该 tag。
        """
        if not os.path.isdir(engine_id):
            return {"ok": False, "msg": f"实例目录不存在: {engine_id}"}
        if not os.path.isdir(os.path.join(engine_id, ".git")):
            return {"ok": False, "msg": "该实例来自 ZIP 下载（无 git 仓库），无法在线更新，请重新下载"}
        base = _base_of_path(engine_id) or base_registry.infer(engine_id)
        if not base:
            return {"ok": False, "msg": "无法确定该实例所属基底，无法执行更新"}
        repo = _repo_of(base)
        if not repo:
            return {"ok": False, "msg": f"{base} 未配置官方仓库地址，无法执行更新"}
        target = (target_version or "").strip()
        if target and target not in ("main", "latest"):
            tag = _resolve_remote_tag(repo, target)
            task_id = _new_task("update", _update_rollback_job, engine_id, tag, "更新")
            return {"ok": True, "task_id": task_id, "target": tag, "tag": tag}
        branch = self._git_branch(engine_id) or "main"
        task_id = _new_task("update", _update_branch_job, engine_id, branch, "更新")
        return {"ok": True, "task_id": task_id, "target": f"{branch}（最新）", "branch": branch}

    def rollback_version(self, engine_id, to_version):
        """对指定版本实例目录真实 git checkout 到旧版本（回退）。"""
        if not os.path.isdir(engine_id):
            return {"ok": False, "msg": f"实例目录不存在: {engine_id}"}
        if not os.path.isdir(os.path.join(engine_id, ".git")):
            return {"ok": False, "msg": "该实例来自 ZIP 下载（无 git 仓库），无法回退，请重新下载"}
        base = _base_of_path(engine_id) or base_registry.infer(engine_id)
        if not base:
            return {"ok": False, "msg": "无法确定该实例所属基底，无法执行回退"}
        repo = _repo_of(base)
        if not repo:
            return {"ok": False, "msg": f"{base} 未配置官方仓库地址，无法执行回退"}
        tag = _resolve_remote_tag(repo, to_version)
        task_id = _new_task("rollback", _update_rollback_job, engine_id, tag)
        return {"ok": True, "task_id": task_id, "tag": tag}

    # =================================================
    # Atelier Managed：接管外部 ZIP / 在线更新（ZIP 安装来源）
    #   流程：远端 commit → 下载 ZIP → 临时解压校验 → 备份用户数据 →
    #         替换程序文件 → 还原用户数据 → 写入 .ftn/engine.json；
    #         任何失败自动回滚旧程序目录（绝不留半成品）。
    # =================================================
    def _gh_commit_sha(self, repo, ref):
        """获取远端指定 ref（refs/heads/main / refs/tags/v1.1.0）的 commit SHA：
        用 git ls-remote（统一镜像轮换：镜像优先 + 官方直连兜底 + 成功记忆），
        不依赖 GitHub REST API / JSON（api.github.com 常被墙或被镜像返回 HTML）。"""
        from core.update import source_manager as mirrors

        def _fetch(url):
            out = subprocess.check_output(
                ["git", "ls-remote", url, ref],
                stderr=subprocess.DEVNULL, text=True, timeout=15,
                creationflags=_HIDE,
            ).strip()
            sha = out.split()[0] if out else ""
            if re.fullmatch(r"[0-9a-fA-F]{40}", sha):
                return sha
            raise RuntimeError(f"未从 {url} 解析到 commit（输出: {out[:80] or '空'}）")

        # 并发探测（直连 + 镜像），最快成功源胜出，避免被慢源拖死
        used, sha = mirrors.pick_first_ok_parallel(
            mirrors.url_candidates(f"https://github.com/{_repo_path(repo)}"), _fetch, timeout=18
        )
        if used is None:
            raise RuntimeError(f"获取远端 commit 失败（GitHub 直连与镜像均不可用）：{sha}")
        return sha

    def _zip_url(self, repo, ref):
        return f"https://github.com/{_repo_path(repo)}/archive/{ref}.zip"

    def _url_candidates(self, url):
        """候选列表（统一走 core.mirrors：镜像优先 + 官方直连兜底 + 成功记忆）。"""
        from core.update import source_manager as mirrors
        return mirrors.url_candidates(url)

    def _download_zip(self, repo, ref, dest_zip):
        """下载引擎 ZIP：镜像优先 + 官方直连兜底 + 成功记忆；
        单候选连接超时 20s，下载中 40s 无进展自动切换（防止慢源拖死）。"""
        from core.update import source_manager as mirrors
        last_err = None
        for url in mirrors.reorder(mirrors.url_candidates(self._zip_url(repo, ref))):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "ftn-updater"})
                with urllib.request.urlopen(req, timeout=20) as resp, open(dest_zip + ".part", "wb") as f:
                    got = 0
                    last_p, last_t = -1, time.time()
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        if got != last_p:
                            last_p, last_t = got, time.time()
                        elif time.time() - last_t > 40:
                            raise RuntimeError(f"下载速度过慢（40s 无进展），切换镜像：{url}")
                os.replace(dest_zip + ".part", dest_zip)
                mirrors.mark_success(url)
                return
            except Exception as e:
                last_err = e
                try:
                    os.remove(dest_zip + ".part")
                except OSError:
                    pass
                continue
        raise RuntimeError(f"下载引擎 ZIP 失败（GitHub 直连与镜像均不可用）：{last_err}")

    def _install_job(self, engine_dir, repo, ref, label, ref_kind="branch"):
        """后台任务：下载 ZIP（分支/tag）→ 备份 → 替换 → 还原 → 记录；
        失败自动回滚，用户数据绝不清除；成功后旧程序备份保留到 Backup/engine-backups（最近 2 份）。"""
        prev_rec = self._read_managed_record(engine_dir) or {}
        ref_name = ref.split("/")[-1]
        yield f"{label}：获取远端 {ref_name} 的 commit...", 3
        commit = self._gh_commit_sha(repo, ref)
        if not commit:
            raise RuntimeError(f"无法获取远端 {ref_name} 的 commit")
        yield f"{label}：下载 ZIP（{ref_name}）...", 18
        # 临时目录与引擎同盘：models/outputs 可能几十 GB，跨盘 move 会变成“复制+删除”，慢且占双倍磁盘
        try:
            tmp = tempfile.mkdtemp(prefix="ftn_install_", dir=os.path.dirname(engine_dir) or None)
        except OSError:
            tmp = tempfile.mkdtemp(prefix="ftn_install_")
        try:
            zip_path = os.path.join(tmp, "engine.zip")
            self._download_zip(repo, ref, zip_path)
            yield f"{label}：解压并校验...", 42
            extract = os.path.join(tmp, "src")
            os.makedirs(extract)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(extract)
            # 找包含启动文件的目录：GitHub ZIP 是单根目录；镜像/二次打包可能平铺，逐个候选探测
            inner = extract
            for n in sorted(os.listdir(extract)):
                cand = os.path.join(extract, n)
                if (os.path.isdir(cand)
                        and (os.path.isfile(os.path.join(cand, "launch.py"))
                             or os.path.isfile(os.path.join(cand, "webui.py")))):
                    inner = cand
                    break
            if not (os.path.isfile(os.path.join(inner, "launch.py"))
                    or os.path.isfile(os.path.join(inner, "webui.py"))):
                raise RuntimeError("下载包内容校验失败（缺少启动文件）")

            yield f"{label}：备份用户数据（模型/输出/配置等）...", 58
            backup = os.path.join(tmp, "userdata")
            os.makedirs(backup)
            user_rels = (
                ["models", "outputs", "extensions", "embeddings",
                 "localizations", "random_res_config", "venv"]
                + _protected_files(engine_dir)
            )
            for rel in user_rels:
                src = os.path.join(engine_dir, rel)
                if os.path.exists(src):
                    shutil.move(src, os.path.join(backup, rel.replace(os.sep, "_")))

            yield f"{label}：替换程序文件...", 72
            old_backup = os.path.join(tmp, "old_program")
            install_err = None
            try:
                shutil.move(engine_dir, old_backup)
                os.makedirs(engine_dir)
                for name in os.listdir(inner):
                    shutil.move(os.path.join(inner, name), os.path.join(engine_dir, name))
            except Exception as e:
                install_err = str(e)

            if install_err:
                # 替换失败：先恢复旧程序目录，再统一还原用户数据
                if os.path.isdir(engine_dir):
                    shutil.rmtree(engine_dir, ignore_errors=True)
                if os.path.isdir(old_backup):
                    shutil.move(old_backup, engine_dir)

            yield f"{label}：还原用户数据...", 88
            restore_err = None
            for rel in user_rels:
                src = os.path.join(backup, rel.replace(os.sep, "_"))
                dst = os.path.join(engine_dir, rel)
                if os.path.exists(src):
                    try:
                        if os.path.exists(dst):
                            shutil.rmtree(dst, ignore_errors=True)
                        shutil.move(src, dst)
                    except Exception as e:
                        restore_err = restore_err or str(e)

            if restore_err:
                # 用户数据还原失败：把备份挪出临时目录（绝不随 tmp 删除），并提示人工找回
                rescue = os.path.join(os.path.dirname(engine_dir), f".ftn-userdata-backup-{int(time.time())}")
                try:
                    shutil.move(backup, rescue)
                    _prune_rescue_backups(os.path.dirname(engine_dir), keep=3)
                except Exception:
                    rescue = backup
                raise RuntimeError(f"还原用户数据失败，备份保留在：{rescue}（{restore_err}）")

            if install_err:
                raise RuntimeError(f"替换程序文件失败，已自动回滚：{install_err}")

            yield f"{label}：写入安装记录（.ftn/engine.json）...", 95
            record = {
                "engine": _base_of_path(engine_dir) or "reforge",
                "repository": repo,
                "commit": commit,
                "install_source": "atelier_managed",
                "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            if ref_kind == "tag":
                record["tag"] = ref_name
                record["branch"] = prev_rec.get("branch") or ""
            else:
                record["branch"] = ref_name
                record["tag"] = prev_rec.get("tag") or ""
            self._write_managed_record(engine_dir, record)

            # 旧程序备份：保留到 Backup/engine-backups（最近 2 份），不随临时目录删除
            keep_path = ""
            try:
                backup_root = os.path.join(PROJECT_ROOT, "Backup", "engine-backups")
                os.makedirs(backup_root, exist_ok=True)
                stamp = time.strftime("%Y%m%d-%H%M%S")
                keep_path = os.path.join(backup_root, f"{os.path.basename(engine_dir)}-{stamp}")
                if os.path.isdir(old_backup):
                    shutil.move(old_backup, keep_path)
                    # 只保留最近 2 份，更旧自动清理
                    prefix = os.path.basename(engine_dir) + "-"
                    cands = sorted(
                        (os.path.join(backup_root, n) for n in os.listdir(backup_root)
                         if n.startswith(prefix) and os.path.isdir(os.path.join(backup_root, n))),
                        key=os.path.getmtime,
                    )
                    for stale in cands[:-2]:
                        shutil.rmtree(stale, ignore_errors=True)
            except Exception as e:
                log_manager.warn("version", f"保留旧版本备份失败（已清理）: {e}")
                shutil.rmtree(old_backup, ignore_errors=True)
            if keep_path:
                yield f"{label}完成：{ref_name} @ {commit[:7]}（旧程序已备份至 Backup/engine-backups，保留最近 2 份）", 100
            else:
                yield f"{label}完成：{ref_name} @ {commit[:7]}", 100
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def takeover_external(self, engine_id):
        """接管外部 ZIP：备份用户数据 → 安装最新版 → 记录 → 由 Atelier 管理更新。"""
        if not os.path.isdir(engine_id):
            return {"ok": False, "msg": f"实例目录不存在: {engine_id}"}
        info = self._read_version(engine_id)
        if info["install_source"] != "external":
            return {"ok": False, "msg": "仅外部 ZIP / 目录可接管"}
        # 基底解析：Core/Engines 内取路径首段；外部目录按内容/目录名推断，兜底 reforge
        base = _base_of_path(engine_id)
        if not base_registry.get(base):
            base = base_registry.infer(engine_id) or "reforge"
        repo = _repo_of(base)
        if not repo:
            return {"ok": False, "msg": f"未知基底仓库: {base}"}
        branch = info.get("branch") or "main"
        task_id = _new_task("takeover", self._install_job, engine_id, repo,
                            f"refs/heads/{branch}", "接管", "branch")
        return {"ok": True, "task_id": task_id, "branch": branch}

    def _managed_repo(self, engine_id, rec):
        """解析 Atelier Managed 实例的仓库：记录优先，其次按基底推断。"""
        repo = rec.get("repository") or ""
        if not repo:
            base = _base_of_path(engine_id)
            if not base_registry.get(base):
                base = base_registry.infer(engine_id) or "reforge"
            repo = _repo_of(base)
        return repo

    def managed_candidates(self, engine_id):
        """Atelier Managed 实例的新旧版本候选：最新分支 commit + 仓库 tags（对齐 clone 版的选择式更新）。"""
        if not os.path.isdir(engine_id):
            return {"ok": False, "msg": f"实例目录不存在: {engine_id}"}
        rec = self._read_managed_record(engine_id)
        if not rec or rec.get("install_source") != "atelier_managed":
            return {"ok": False, "msg": "该实例不是 Atelier 管理"}
        repo = self._managed_repo(engine_id, rec)
        branch = rec.get("branch") or "main"
        cur = {
            "branch": branch,
            "commit": rec.get("commit") or "",
            "tag": rec.get("tag") or "",
        }
        update, rollback = [], []
        try:
            head = self._gh_commit_sha(repo, f"refs/heads/{branch}")
            if head and cur["commit"] and head != cur["commit"]:
                update.append({"type": "latest", "label": f"{branch} @ {head[:7]}", "target": "latest"})
        except Exception as e:
            log_manager.warn("version", f"managed_candidates 取分支 commit 失败: {e}")
        tags = []
        try:
            tags = _fetch_tags(repo)
        except Exception as e:
            log_manager.warn("version", f"managed_candidates 拉取 tags 失败: {e}")
        cur_ver = _num_tuple(cur["tag"])
        for t in tags:
            tv = _num_tuple(t)
            if cur_ver and tv:
                if tv > cur_ver:
                    update.append({"type": "tag", "label": t, "target": t})
                elif tv < cur_ver:
                    rollback.append({"type": "tag", "label": t, "target": t})
            elif not cur_ver:
                rollback.append({"type": "tag", "label": t, "target": t})
        return {
            "ok": True,
            "repo": repo,
            "current": cur,
            "update": update,
            "rollback": rollback,
        }

    def managed_update(self, engine_id, target=None):
        """Atelier Managed 实例更新：target 为空/latest → 分支最新；否则按指定 tag 安装。"""
        if not os.path.isdir(engine_id):
            return {"ok": False, "msg": f"实例目录不存在: {engine_id}"}
        rec = self._read_managed_record(engine_id)
        if not rec or rec.get("install_source") != "atelier_managed":
            return {"ok": False, "msg": "该实例不是 Atelier 管理，无法用此方式更新"}
        repo = self._managed_repo(engine_id, rec)
        if not repo:
            return {"ok": False, "msg": "未配置仓库地址，无法更新"}
        target = (target or "").strip()
        if not target or target == "latest":
            branch = rec.get("branch") or "main"
            ref, kind, shown = f"refs/heads/{branch}", "branch", branch
        else:
            ref, kind, shown = f"refs/tags/{target}", "tag", target
        task_id = _new_task("managed-update", self._install_job, engine_id, repo, ref, "更新", kind)
        return {"ok": True, "task_id": task_id, "target": shown, "ref": ref}

    # =================================================
    # venv 共享策略（多版本间环境复用 / 重建）
    # =================================================
    # 共享 venv 全局目录：Core/SharedVenvs/<base>/（key 由依赖指纹标记）
    SHARED_VENV_ROOT = os.path.join(ENGINES_ROOT, "_shared_venv")

    def venv_strategy(self, base_key, target_version=None):
        """计算某基底（可选到目标版本）的环境策略：复用共享 venv 或重建。

        规则（对齐蓝图"小版本复用，大版本重建询问"）：
          1. venv_share 关闭 → 每个版本实例独立 venv（rebuild）。
          2. venv_share 开启且该基底存在可用共享 venv（指纹匹配） → reuse。
          3. 目标/当前版本发生「大版本依赖变化」（pyvenv/requirements 指纹差异较大）→ rebuild 并提示。
          4. 无任何共享 venv → rebuild（首次下载将创建）。
        """
        from core.config_manager import config_manager
        share = config_manager.load().venv_share if hasattr(config_manager.load(), "venv_share") else True
        if not share:
            return {"ok": True, "share": False, "strategy": "rebuild",
                    "reason": "已关闭多版本共享 venv（每个实例独立环境）"}

        # 共享 venv 目录：Core/SharedVenvs/<base>/
        base_dir = os.path.join(self.SHARED_VENV_ROOT, base_key or "")
        has_shared = os.path.isdir(base_dir) and any(
            os.path.isdir(os.path.join(base_dir, n)) for n in os.listdir(base_dir)
        )
        if not has_shared:
            return {"ok": True, "share": True, "strategy": "rebuild",
                    "reason": "尚无该基底的共享 venv，首次将创建共享环境",
                    "shared_dir": base_dir}

        # 版本跨度判断：target 相对当前 active 版本大版本（major.minor）是否跳变
        reason = "复用现有共享 venv"
        strategy = "reuse"
        cur = self.current() or {}
        cur_ver = cur.get("version") or ""
        if target_version and cur_ver:
            a = _num_tuple(target_version)
            b = _num_tuple(cur_ver)
            if a and b and (a[0], a[1]) != (b[0], b[1]):
                # major.minor 变化 → 依赖很可能大改 → 建议重建
                strategy = "rebuild"
                reason = f"版本大跨度（{cur_ver} → {target_version}），依赖可能显著变化，建议重建环境"
        return {
            "ok": True, "share": True, "strategy": strategy, "reason": reason,
            "shared_dir": base_dir, "current_version": cur_ver,
        }

    # =================================================
    # 插件管理（当前实例 extensions 目录）
    # =================================================
    PLUGIN_DISABLE_FILE = ".ftn_disabled"

    def plugins(self):
        """列出当前实例 extensions 目录下的插件（含 git 来源去重标记）。"""
        cur = self.current()
        if not cur or self.is_demo:
            return {"demo": True, "plugs": [], "extensions_dir": ""}
        ext_dir = os.path.join(cur["path"], "extensions")
        plugs = []
        remotes = {}
        if os.path.isdir(ext_dir):
            for name in sorted(os.listdir(ext_dir)):
                d = os.path.join(ext_dir, name)
                if not os.path.isdir(d) or name.startswith("."):
                    continue
                disabled = os.path.exists(os.path.join(d, self.PLUGIN_DISABLE_FILE))
                remote = ""
                if os.path.exists(os.path.join(d, ".git")):
                    ok, out = _exec_git_quiet(["remote", "get-url", "origin"], d)
                    remote = out.strip() if ok else ""
                remotes[name] = remote
                plugs.append({
                    "key": name,
                    "name": name,
                    "path": d,
                    "enabled": not disabled,
                    "has_git": os.path.exists(os.path.join(d, ".git")),
                    "remote": remote,
                })
        # 重复插件：相同 git remote 出现在多个目录 → 全部标记 dup
        by_remote = {}
        for name, remote in remotes.items():
            if remote:
                by_remote.setdefault(remote, []).append(name)
        dup_names = {n for names in by_remote.values() if len(names) > 1 for n in names}
        for p in plugs:
            p["dup"] = p["name"] in dup_names
        return {"demo": False, "plugs": plugs, "extensions_dir": ext_dir}

    def plugin_update_all(self):
        """一键更新全部已装插件（后台任务，返回 task_id）。"""
        def _job():
            res = self.plugins()
            targets = [p for p in res.get("plugs", []) if p.get("has_git")]
            if not targets:
                yield "当前没有可更新的插件", 100
                return
            updated, failed, skipped = [], [], []
            total = len(targets)
            for i, p in enumerate(targets):
                yield f"正在更新 {p['name']}（{i + 1}/{total}）...", round(i / total * 100)
                r = self.plugin_update(p["key"])
                if r.get("ok"):
                    updated.append(p["name"])
                else:
                    failed.append({"name": p["name"], "msg": r.get("msg", "")})
            yield f"更新完成：成功 {len(updated)}，失败 {len(failed)}", 100
            return {"updated": updated, "failed": failed}

        tid = _new_task("plugins-update-all", _job)
        return {"ok": True, "task_id": tid}

    def task_status(self, task_id):
        return _task_status(task_id)

    def plugin_set_enabled(self, plugin_key, enabled):
        res = self.plugins()
        if res["demo"]:
            return {"ok": False, "msg": "演示模式无真实插件"}
        target = None
        for p in res["plugs"]:
            if p["key"] == plugin_key:
                target = p
                break
        if not target:
            return {"ok": False, "msg": f"插件不存在: {plugin_key}"}
        marker = os.path.join(target["path"], self.PLUGIN_DISABLE_FILE)
        try:
            if enabled:
                if os.path.exists(marker):
                    os.remove(marker)
            else:
                open(marker, "w").close()
            log_manager.info("version", f"插件{'启用' if enabled else '禁用'}: {plugin_key}")
            return {"ok": True, "key": plugin_key, "enabled": enabled}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    # ---- 上面是原有方法，以下是新增：插件市场 / 安装 / 更新 / URL / 卸载 ----

    def _git_describe(self, dir):
        """读取 git 仓库当前版本/哈希，用于插件版本比对。"""
        try:
            out = subprocess.check_output(
                ["git", "-C", dir, "describe", "--tags", "--always", "--dirty"],
                stderr=subprocess.DEVNULL, text=True, timeout=5,
                creationflags=_HIDE,
            ).strip()
            return out or ""
        except Exception:
            return ""

    def _extensions_dir(self):
        """当前主引擎 extensions 目录。返回 (ext_dir, primary_base, engine_dir) 或 None。"""
        if self.is_demo:
            return None
        primary = base_registry.primary()
        # 外部主引擎（不在 Core/Engines）优先用其自身目录
        cur = self.current()
        if cur and os.path.isdir(os.path.join(cur["path"], "extensions")):
            return os.path.join(cur["path"], "extensions"), primary, cur["path"]
        base_dir = os.path.join(ENGINES_ROOT, primary)
        if os.path.isdir(base_dir):
            for node in os.listdir(base_dir):
                d = os.path.join(base_dir, node)
                if os.path.isdir(d):
                    ext = os.path.join(d, "extensions")
                    if os.path.isdir(ext):
                        return ext, primary, d
        return None

    def plugin_market(self, query="", group="", base_filter=""):
        """返回插件市场：内置库 + 已装状态比对 + 主基底适配判断。"""
        from core.plugin_library import library, groups as lib_groups
        primary = base_registry.primary()
        pri_label = base_registry.labels().get(primary, primary)
        installed = {}
        env = self._extensions_dir()
        if env:
            ext_dir = env[0]
            if os.path.isdir(ext_dir):
                for name in os.listdir(ext_dir):
                    d = os.path.join(ext_dir, name)
                    if os.path.isdir(d):
                        installed[name.lower()] = d

        items = []
        for p in library():
            if query and query.lower() not in (p["name"].lower() + p["key"].lower()):
                continue
            if group and group != "全部" and group != p["group"]:
                continue
            if base_filter and base_filter != "全部":
                if base_filter == "通用":
                    if p["base"] != "通用":
                        continue
                elif p["base"] != base_filter and p["base"] != "通用":
                    continue
            key_l = p["key"].lower()
            # 匹配已安装目录（key 或 name）
            match_dir = None
            for k, d in installed.items():
                if k == key_l or p["name"].lower() in k or k in p["key"].lower():
                    match_dir = d
                    break
            status = "download"
            local_ver = ""
            if match_dir:
                status = "installed"
                local_ver = self._git_describe(match_dir)
            fits = (p["base"] == "通用" or p["base"] == primary)
            items.append({
                **p,
                "primary_base": primary,
                "primary_label": pri_label,
                "installed": bool(match_dir),
                "status": status,
                "local_version": local_ver,
                "fits": fits,
            })
        groups_out = ["全部"] + lib_groups()
        return {
            "demo": self.is_demo,
            "no_engine": bool(env is None or self.is_demo),
            "primary_base": primary,
            "primary_label": pri_label,
            "extensions_dir": env[0] if env else "",
            "groups": groups_out,
            "items": items,
        }

    def _exec_git(self, args, cwd):
        try:
            out = subprocess.check_output(["git"] + args, cwd=cwd,
                                          stderr=subprocess.STDOUT, text=True, timeout=600,
                                          creationflags=_HIDE)
            return True, (out or "").strip()
        except subprocess.CalledProcessError as e:
            return False, (e.output or str(e)).strip()
        except Exception as e:
            return False, str(e)

    def plugin_install(self, repo_url, key=None):
        env = self._extensions_dir()
        if not env:
            return {"ok": False, "msg": "当前无主引擎实例，无法安装插件（或处于演示模式）"}
        ext_dir, primary_base = env[0], env[1]
        if not repo_url or "github.com" not in repo_url.lower():
            return {"ok": False, "msg": "请提供有效的 Git 仓库 URL"}
        target_name = key or repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        target = os.path.join(ext_dir, target_name)
        if os.path.exists(target):
            return {"ok": False, "msg": f"已存在同名插件: {target_name}，请改用「更新」"}
        os.makedirs(ext_dir, exist_ok=True)
        ok, out = False, ""
        for url in _git_url_candidates(repo_url):
            ok, out = self._exec_git(["clone", "--depth", "1", url, target], ext_dir)
            if ok:
                break
            try:
                if os.path.isdir(target):
                    is_partial = os.path.isdir(os.path.join(target, ".git")) or not os.listdir(target)
                    if is_partial:
                        shutil.rmtree(target, ignore_errors=True)
            except Exception:
                pass
        if not ok:
            return {"ok": False, "msg": f"安装失败（GitHub 直连与常用镜像均不可用，可到 设置→环境配置 更换镜像）：{(out or '')[:200]}"}
        log_manager.info("version", f"已安装插件 {target_name} → {primary_base}")
        return {"ok": True, "msg": f"已安装插件 {target_name}（{primary_base}）", "key": target_name}

    def plugin_update(self, plugin_key):
        env = self._extensions_dir()
        if not env:
            return {"ok": False, "msg": "当前无主引擎实例"}
        ext_dir = env[0]
        target = os.path.join(ext_dir, plugin_key)
        if not os.path.isdir(target):
            return {"ok": False, "msg": f"插件不存在: {plugin_key}"}
        ok, out = self._exec_git(["pull", "--ff-only"], target)
        if not ok:
            return {"ok": False, "msg": f"更新失败：{out[:200]}"}
        log_manager.info("version", f"已更新插件 {plugin_key}")
        return {"ok": True, "msg": f"已更新插件 {plugin_key}", "detail": out}

    def plugin_url_install(self, repo_url, key=None):
        env = self._extensions_dir()
        if not env:
            return {"ok": False, "msg": "当前无主引擎实例，无法安装插件"}
        if not repo_url or "github.com" not in repo_url.lower():
            return {"ok": False, "msg": "请提供有效的 Git 仓库 URL"}
        ext_dir, primary_base = env[0], env[1]
        target_name = key or repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        target = os.path.join(ext_dir, target_name)
        if os.path.isdir(target):
            if not os.path.exists(os.path.join(target, ".git")):
                return {"ok": False, "msg": f"{target_name} 已存在但无 Git 记录，无法比对版本，可手动替换目录"}
            remote_ver = self._git_remote_version(repo_url)
            local_ver = self._git_describe(target)
            if remote_ver and local_ver:
                cmp = self._compare_version(remote_ver, local_ver)
                if cmp > 0:
                    return {"ok": True, "code": "update", "action": "update",
                            "msg": f"检测到 {target_name} 存在新版（本地 {local_ver} → 远程 {remote_ver}）。是否更新？",
                            "key": target_name, "remote": remote_ver, "local": local_ver}
                elif cmp < 0:
                    return {"ok": True, "code": "rollback", "action": "rollback",
                            "msg": f"检测到 {target_name} 为旧版（本地 {local_ver} > 远程 {remote_ver}）。是否回退？",
                            "key": target_name, "remote": remote_ver, "local": local_ver}
                else:
                    return {"ok": True, "code": "same", "key": target_name, "msg": f"{target_name} 已是最新版本（{local_ver}）"}
            return {"ok": True, "code": "update_unknown", "key": target_name, "msg": f"{target_name} 已存在。是否执行 git pull 更新？"}
        # 无同名 → 直接安装
        return self.plugin_install(repo_url, key)

    def _git_remote_version(self, repo_url):
        """探测插件仓库远程版本（git ls-remote tags，统一镜像轮换：镜像优先 + 官方兜底）。"""
        for url in _git_url_candidates(repo_url):
            try:
                out = subprocess.check_output(
                    ["git", "ls-remote", "--tags", "--refs", url],
                    stderr=subprocess.DEVNULL, text=True, timeout=15,
                    creationflags=_HIDE,
                )
                tags = re.findall(r"refs/tags/([^}^{]+)$", out, re.MULTILINE)
                if not tags:
                    return ""
                ver_tags = [t for t in tags if re.search(r"\d", t)]
                if not ver_tags:
                    return tags[-1]
                return max(ver_tags, key=self._ver_key)
            except Exception:
                continue
        return ""

    def _compare_version(self, a, b):
        ka, kb = self._ver_key(a), self._ver_key(b)
        return (ka > kb) - (ka < kb)

    def plugin_uninstall(self, plugin_key):
        env = self._extensions_dir()
        if not env:
            return {"ok": False, "msg": "当前无主引擎实例"}
        ext_dir = env[0]
        target = os.path.join(ext_dir, plugin_key)
        if not os.path.isdir(target):
            return {"ok": False, "msg": f"插件不存在: {plugin_key}"}
        import shutil
        try:
            backup = target + ".uninstalled"
            if os.path.exists(backup):
                shutil.rmtree(backup, ignore_errors=True)
            shutil.move(target, backup)
            log_manager.info("version", f"已卸载插件 {plugin_key}（移至 .uninstalled 备份）")
            return {"ok": True, "msg": f"已卸载插件 {plugin_key}（备份为 .uninstalled）"}
        except Exception as e:
            return {"ok": False, "msg": f"卸载失败: {e}"}


# =================================================
# 后台任务执行器（下载 / 更新 / 回退 的 git 操作）
# =================================================
_tasks = {}
_tasks_lock = threading.Lock()


def _parse_clone_pct(line):
    """从 git clone 输出解析进度百分比（0-100）。"""
    m = re.search(r"([\d.]+)%\s*\(?(\d+)\s*/\s*(\d+)\)?", line)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _stream_git(args, cwd, progress=False):
    """流式执行 git（Popen 逐行读取），作为生成器产出 (行文本, 进度或None)。

    进度仅在 clone 阶段解析。命令失败时抛出 RuntimeError。
    """
    if not os.path.isdir(cwd):
        raise RuntimeError(f"工作目录不存在: {cwd}")
    try:
        proc = subprocess.Popen(
            ["git"] + args, cwd=cwd, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", bufsize=1,
            creationflags=_HIDE,
        )
    except FileNotFoundError:
        raise RuntimeError("未检测到 git 命令，请先安装 Git 并加入 PATH")
    for line in proc.stdout:
        line = line.rstrip("\n")
        pct = _parse_clone_pct(line) if progress else None
        yield line, pct
    proc.stdout.close()
    code = proc.wait()
    if code != 0:
        raise RuntimeError(f"git 操作失败（code={code}），详情见上方输出")


def _stamp_ver(v):
    """内部版本号 → git tag（reForge/Forge 的 tag 可能带或不带 v 前缀，保持一致处理）。"""
    v = str(v).strip()
    if v.lower().startswith("v"):
        return v
    return "v" + v


def _resolve_remote_tag(repo, version):
    """探测给定版本在远程仓库中真实存在的 tag（兼顾带 v / 不带 v 两种写法）。

    远程仓库 tag 可能是 "1.11.0" 也可能是 "v1.11.0"。逐个探测，返回真实存在者；
    直连与镜像都不通 / 都查不到则返回加了 v 前缀的经典写法（由 git clone 自行处理）。
    """
    if not repo:
        return _stamp_ver(version)
    cands = [str(version).strip()]
    if not cands[0].lower().startswith("v"):
        cands.append("v" + cands[0])
    existing = set()
    for url in _git_url_candidates(repo):
        try:
            out = subprocess.check_output(
                ["git", "ls-remote", "--tags", "--refs", url],
                stderr=subprocess.DEVNULL, text=True, timeout=15,
                creationflags=_HIDE,
            )
        except Exception:
            continue
        for line in out.splitlines():
            m = re.search(r"refs/tags/([^}^{]+)$", line.strip())
            if m:
                existing.add(m.group(1).strip())
        if existing:
            break
    for c in cands:
        if c in existing:
            return c
    return cands[0]


def _base_of_path(engine_dir):
    """由实例目录路径推断基底 key：Core/Engines/<base>/<name>；目录在 Core/Engines 之外返回 None。"""
    try:
        rel = os.path.relpath(engine_dir, ENGINES_ROOT)
        if rel == "." or rel.startswith(".."):
            return None
        return rel.split(os.sep)[0] or None
    except Exception:
        return None


def _run_clone_job(base_key, version, dest):
    """生成器：真实 git clone 某版本实例。产出 (msg, 进度)。"""
    base = base_registry.get(base_key)
    dl = _BASE_DOWNLOAD.get(base_key, {})
    repo = _repo_of(base_key)
    tag = _resolve_remote_tag(repo, version)
    label = base.get("label", base_key) if base else base_key
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        free = shutil.disk_usage(os.path.dirname(dest)).free
        if free < 6 * 1024 ** 3:
            yield (f"警告：目标盘剩余空间不足 6GB（当前约 {free // (1024**3)}GB），"
                   "环境安装（PyTorch 等）可能需要 5GB 以上，建议清理磁盘"), None
    except Exception:
        pass
    yield f"克隆 {label} {version}（tag={tag}）...", 5
    yield "从官方仓库浅克隆（--depth 1，直连→镜像自动轮换）...", 5
    last_err = None
    cloned = False
    for url in _git_url_candidates(repo):
        if last_err is not None:
            yield f"当前地址不可用，尝试下一镜像：{url}", None
        try:
            for line, pct in _stream_git(
                ["clone", "--progress", "--depth", "1", "--branch", tag, url, dest],
                os.path.dirname(dest), progress=True,
            ):
                yield line, (5 + pct * 0.15 if pct is not None else None)
            cloned = True
            break
        except Exception as e:
            last_err = e
            # 清理半成品目标目录（任务开始前 dest 不存在；仅删空目录或刚 clone 的部分内容）
            try:
                if os.path.isdir(dest):
                    is_partial = os.path.isdir(os.path.join(dest, ".git")) or not os.listdir(dest)
                    if is_partial:
                        shutil.rmtree(dest, ignore_errors=True)
            except Exception:
                pass
            continue
    if not cloned:
        raise RuntimeError(
            f"git clone 失败（GitHub 直连与常用镜像均不可用，可到 设置→环境配置 更换 Git 镜像前缀）：{last_err}"
        )
    yield "校验版本...", 21
    ver = None
    try:
        out = subprocess.check_output(
            ["git", "-C", dest, "describe", "--tags", "--always"],
            stderr=subprocess.DEVNULL, text=True, timeout=5,
            creationflags=_HIDE).strip()
        ver = out or None
    except Exception:
        ver = None
    _ensure_model_dirs(dest)
    for msg, pct in _install_engine_env(dest):
        yield msg, (25 + (pct or 0) * 0.70 if pct is not None else None)
    _promote_download_if_needed(dest)
    yield f"下载完成（{label} {ver or version}）", 100


_COMMON_MODEL_DIRS = ["Stable-diffusion", "Lora", "Embedding", "VAE", "ControlNet"]


def _ensure_model_dirs(root):
    """补齐引擎 models/ 下的常用分类目录（clone 仓库可能缺 Lora/Embedding 等），
    保证下载后「添加模型」/「扫描」开箱即用。"""
    models = os.path.join(root, "models")
    if not os.path.isdir(models):
        return
    for sub in _COMMON_MODEL_DIRS:
        try:
            os.makedirs(os.path.join(models, sub), exist_ok=True)
        except Exception:
            pass


def _find_system_python():
    """探测可用于创建 venv 的系统 Python（py 启动器兼容）。"""
    for name in ("python", "py"):
        exe = shutil.which(name)
        if not exe:
            continue
        try:
            r = subprocess.run(
                [exe, "--version"], capture_output=True, text=True, timeout=10,
                creationflags=_HIDE,
            )
            if r.returncode == 0:
                return exe
        except Exception:
            continue
    return ""


def _extract_launch_default(engine_dir, key, default=""):
    """从引擎 modules/launch_utils.py 提取环境安装默认参数（TORCH/CLIP 等），读不到用 default。"""
    try:
        lu = os.path.join(engine_dir, "modules", "launch_utils.py")
        if os.path.exists(lu):
            txt = open(lu, encoding="utf-8", errors="replace").read()
            m = re.search(re.escape(key) + r"', ?f?\"([^\"]+)\"", txt, re.IGNORECASE)
            if m:
                return m.group(1)
    except Exception:
        pass
    return default


def _import_ok(python, mod):
    try:
        r = subprocess.run(
            [python, "-c", f"import {mod}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
            creationflags=_HIDE,
        )
        return r.returncode == 0
    except Exception:
        return False


def _run_import(python, code):
    """执行一段 import 校验代码（如 'import numpy; import torch'），成功返回 True。"""
    try:
        r = subprocess.run(
            [python, "-c", code],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120,
            creationflags=_HIDE,
        )
        return r.returncode == 0
    except Exception:
        return False


def _extract_numpy_pin(req_path):
    """从 requirements 文件提取 numpy 固定版本约束（如 numpy==1.26.2），没有返回空。"""
    try:
        for ln in open(req_path, encoding="utf-8", errors="replace"):
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            low = s.lower()
            if low.startswith("numpy") and ("==" in s or ">=" in s or "<=" in s):
                return s.split("#")[0].strip()
    except Exception:
        pass
    return ""


def _run_pip_proc(args, desc, timeout=3600):
    """执行 pip/环境安装命令；失败抛 RuntimeError 并带输出尾部（便于定位）。"""
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
    try:
        r = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=_HIDE, env=env,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{desc}超时（超过 60 分钟），请检查网络后重试")
    except Exception as e:
        raise RuntimeError(f"{desc}执行失败：{e}")
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-8:]
        raise RuntimeError(f"{desc}失败：{' / '.join(tail)}")
    return r


def _install_engine_env(engine_dir):
    """生成器：下载后自动安装引擎环境（venv + PyTorch + requirements + CLIP 修复）。

    产出阶段进度消息；失败抛 RuntimeError（任务转 error 并提示修复方向）。
    关键修复：CLIP 走 --no-build-isolation + setuptools 69.5.1，
    避开新版 setuptools 移除 pkg_resources 导致的构建失败（启动时静默下载环境的根因）。
    """
    root = engine_dir
    venv_py = os.path.join(root, "venv", "Scripts", "python.exe")
    try:
        if not os.path.exists(venv_py):
            sys_py = _find_system_python()
            if not sys_py:
                raise RuntimeError(
                    "未检测到系统 Python，无法自动创建引擎环境。"
                    "请安装 Python 3.10 并加入 PATH 后重试「下载」；或使用已内置环境的引擎目录。"
                )
            yield "创建虚拟环境（python -m venv）...", 10
            _run_pip_proc([sys_py, "-m", "venv", os.path.join(root, "venv")], "创建虚拟环境")
        yield "准备 pip / setuptools（修复旧包兼容）...", 15
        _run_pip_proc(
            [venv_py, "-m", "pip", "install", "--upgrade", "pip", "setuptools==69.5.1", "wheel"],
            "准备 pip/setuptools",
        )
        if not _import_ok(venv_py, "torch"):
            idx = _extract_launch_default(
                root, "torch_index_url", "https://download.pytorch.org/whl/cu121"
            )
            torch_cmd = _extract_launch_default(root, "torch_command", "")
            if torch_cmd:
                args = torch_cmd.replace("{torch_index_url}", idx).split()[1:]  # 已含 install 前缀
            else:
                args = ["install", "torch", "--extra-index-url", idx]
            yield f"安装 PyTorch（{idx}，约 2-3GB，需要较久）...", 25
            try:
                _run_pip_proc([venv_py, "-m", "pip"] + args, "安装 PyTorch")
            except RuntimeError:
                # 官方索引不可达（国内常见）→ 换阿里镜像重试一次
                cu = idx.rstrip("/").rsplit("/", 1)[-1] or "cu121"
                alt_idx = f"https://mirrors.aliyun.com/pytorch-wheels/{cu}"
                yield f"官方索引不可用，改用阿里镜像重试（{alt_idx}）...", 26
                if torch_cmd:
                    alt_args = torch_cmd.replace("{torch_index_url}", alt_idx).split()[1:]
                else:
                    alt_args = ["install", "torch", "--extra-index-url", alt_idx]
                _run_pip_proc([venv_py, "-m", "pip"] + alt_args, "安装 PyTorch（阿里镜像）")
        req = ""
        for n in ("requirements_versions.txt", "requirements.txt"):
            if os.path.exists(os.path.join(root, n)):
                req = os.path.join(root, n)
                break
        if req:
            yield f"安装依赖（{os.path.basename(req)}，走国内镜像）...", 60
            _run_pip_proc([venv_py, "-m", "pip", "install", "-r", req], "安装依赖")
            # 兼容性对齐：按 requirements 固定 numpy（避免 pip 解析出 numpy 2.x 与
            # scikit-image 等 C 扩展二进制不兼容——启动时报 numpy.dtype size changed）
            pin = _extract_numpy_pin(req)
            if pin:
                yield f"对齐依赖版本（{pin}）...", 88
                _run_pip_proc([venv_py, "-m", "pip", "install", pin], "对齐 numpy 版本")
        for key, mod, default in (
            ("clip_package", "clip", "https://github.com/openai/CLIP/archive/d50d76daa670286dd6cacf3bcd80b5e4823fc8e1.zip"),
            ("openclip_package", "open_clip", "https://github.com/mlfoundations/open_clip/archive/bb6e834e9c70d9c27d0dc3ecedeebeaeb1ffad6b.zip"),
        ):
            if _import_ok(venv_py, mod):
                continue
            url = _extract_launch_default(root, key, default)
            yield f"安装 {mod}（修复隔离构建兼容）...", 85
            _run_pip_proc(
                [venv_py, "-m", "pip", "install", "--no-build-isolation", url],
                f"安装 {mod}",
            )
        # 导入自检：确保核心依赖可导入（二进制兼容），失败则按约束重装一次
        checks = ["import numpy; import torch"]
        if req and "scikit-image" in open(req, encoding="utf-8", errors="replace").read():
            checks.append("import numpy; import skimage")
        for code in checks:
            if _run_import(venv_py, code):
                continue
            pin2 = _extract_numpy_pin(req) if req else ""
            if pin2:
                yield f"检测到依赖二进制不兼容，重装 {pin2} 修复...", 90
                _run_pip_proc([venv_py, "-m", "pip", "install", "--force-reinstall", pin2], "重装 numpy")
            if not _run_import(venv_py, code):
                raise RuntimeError(
                    "引擎依赖导入校验失败（可能是 numpy 等二进制不兼容）。"
                    "请对实例点「修复环境」重试，或删除后重新下载。"
                )
        _SIZE_CACHE.clear()
        yield "引擎环境就绪（依赖已安装，首次启动将快速进入）", 92
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"自动安装引擎环境失败：{e}")


def _promote_download_if_needed(dest):
    """下载完成且主引擎未配置路径时：自动激活该实例并设为主引擎（含同步主基底）。

    已有主引擎时不打扰（新下载归类为非主引擎，用户自行「切换至此」）。
    """
    try:
        from core.engine_registry import engine_registry
        from core.base_registry import base_registry
        primary = engine_registry.primary_engine()
        if primary and primary.get("root"):
            return
        vm = VersionManager()
        vm.set_active(dest)
        key = (primary or {}).get("key") or "reforge"
        engine_registry.set_path(key, dest)
        fam = base_registry.family_of(dest)
        if fam in base_registry.SUPPORTED_FAMILIES:
            base_registry.set_primary(fam)
        log_manager.info("version", f"下载完成，自动设为主引擎：{dest}（家族 {fam}）")
    except Exception as e:
        log_manager.warn("version", f"下载后自动设为主引擎失败（不影响已下载实例，可手动设置）: {e}")


def _download_update_job(url, dest, label):
    """生成器：流式下载 FTN Atelier 更新包 zip（镜像优先+官方直连兜底+成功记忆，Content-Length 进度）。
    单候选连接超时 20s；下载中 40s 无进度增长自动切换下一候选（防止慢源拖死）。"""
    from core.update import source_manager as mirrors
    last_err = None
    for cand in mirrors.reorder(mirrors.url_candidates(url)):
        try:
            req = urllib.request.Request(cand, headers={"User-Agent": "FTN-Atelier-updater"})
            with urllib.request.urlopen(req, timeout=20) as resp, open(dest + ".part", "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                got = 0
                last_got, last_t = -1, time.time()
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if got != last_got:
                        last_got, last_t = got, time.time()
                    elif time.time() - last_t > 40:
                        raise RuntimeError(f"下载速度过慢（40s 无进展），切换镜像：{cand}")
                    if total:
                        pct = min(95, int(got / total * 100))
                        yield f"下载更新包 {label}：{got // 1048576}MB / {total // 1048576}MB", pct
                    else:
                        yield f"下载更新包 {label}：{got // 1048576}MB", None
            os.replace(dest + ".part", dest)
            mirrors.mark_success(cand)
            yield f"更新包已下载：{dest}", 100
            return
        except Exception as e:
            last_err = e
            try:
                os.remove(dest + ".part")
            except OSError:
                pass
            continue
    raise RuntimeError(f"更新包下载失败（GitHub 直连与镜像均不可用）：{last_err}")


def _update_rollback_job(engine_dir, tag, log_prefix="更新"):
    """生成器：对实例目录 git fetch + checkout 到目标 tag（更新 / 回退共用）。

    浅克隆（下载时 --depth 1）首次切换到其它 tag 时，先 --unshallow 补全历史，
    保证能真实切换到官方任意 tag（对齐 StabilityMatrix / 绘世的做法）。
    fetch 走 直连→镜像 轮换，任一地址可用即可。
    """
    backup, rels = _backup_protected(engine_dir)
    try:
        yield "获取远程仓库信息...", 5
        is_shallow = os.path.isfile(os.path.join(engine_dir, ".git", "shallow"))
        base = _base_of_path(engine_dir) or base_registry.infer(engine_dir)
        repo = _repo_of(base)
        fetch_err = None
        fetched = False
        for i, url in enumerate(_git_url_candidates(repo)):
            if i:
                yield f"当前地址不可用，尝试下一镜像：{url}", None
            try:
                if is_shallow:
                    yield "浅克隆：展开历史以支持版本切换（git fetch --unshallow）...", 8
                    for line, pct in _stream_git(["fetch", "--unshallow", "--tags", url], engine_dir):
                        yield line, (8 + (pct or 0) * 0.40 if pct is not None else None)
                else:
                    for line, pct in _stream_git(["fetch", "--tags", url], engine_dir):
                        yield line, (8 + (pct or 0) * 0.40 if pct is not None else None)
                fetched = True
                break
            except Exception as e:
                fetch_err = e
                continue
        if not fetched:
            raise RuntimeError(f"获取远程仓库失败（GitHub 直连与常用镜像均不可用）：{fetch_err}")
        yield f"{log_prefix}到 {tag} ...", 60
        for line, pct in _stream_git(["checkout", tag, "--"], engine_dir):
            yield line, (60 + (pct or 0) * 0.30 if pct else None)
        yield "刷新元数据...", 92
        try:
            subprocess.check_output(["git", "-C", engine_dir, "fsck", "--no-progress"],
                                    stderr=subprocess.DEVNULL, timeout=60,
                                    creationflags=_HIDE)
        except Exception:
            pass
        ver = None
        try:
            out = subprocess.check_output(
                ["git", "-C", engine_dir, "describe", "--tags", "--always"],
                stderr=subprocess.DEVNULL, text=True, timeout=5,
                creationflags=_HIDE).strip()
            ver = out or None
        except Exception:
            ver = None
        yield f"完成：当前指向 {ver or tag}", 100
    finally:
        # 保护机制：无论成功/失败，都把用户配置原样放回
        _restore_protected(engine_dir, backup, rels)


def _update_branch_job(engine_dir, branch, log_prefix="更新"):
    """生成器：git 实例更新到所属分支远端最新 commit。

    fetch origin（浅克隆先 --unshallow）→ checkout --detach origin/<branch>，
    以 commit 为准（滚动更新仓库没有语义版本号）。fetch 走 直连→镜像 轮换。
    """
    backup, rels = _backup_protected(engine_dir)
    try:
        yield "获取远程仓库最新提交...", 5
        is_shallow = os.path.isfile(os.path.join(engine_dir, ".git", "shallow"))
        base = _base_of_path(engine_dir) or base_registry.infer(engine_dir)
        repo = _repo_of(base)
        fetch_err = None
        fetched = False
        for i, url in enumerate(_git_url_candidates(repo)):
            if i:
                yield f"当前地址不可用，尝试下一镜像：{url}", None
            try:
                if is_shallow:
                    yield "浅克隆：展开历史以支持更新（git fetch --unshallow）...", 8
                    for line, pct in _stream_git(["fetch", "--unshallow", "--tags", url], engine_dir):
                        yield line, (8 + (pct or 0) * 0.40 if pct is not None else None)
                else:
                    for line, pct in _stream_git(["fetch", "--tags", url], engine_dir):
                        yield line, (8 + (pct or 0) * 0.40 if pct is not None else None)
                fetched = True
                break
            except Exception as e:
                fetch_err = e
                continue
        if not fetched:
            raise RuntimeError(f"获取远程仓库失败（GitHub 直连与常用镜像均不可用）：{fetch_err}")
        yield f"{log_prefix}到 {branch} 最新提交...", 60
        for line, pct in _stream_git(["checkout", "--detach", f"origin/{branch}", "--"], engine_dir):
            yield line, (60 + (pct or 0) * 0.30 if pct else None)
        yield "刷新元数据...", 92
        try:
            subprocess.check_output(["git", "-C", engine_dir, "fsck", "--no-progress"],
                                    stderr=subprocess.DEVNULL, timeout=60,
                                    creationflags=_HIDE)
        except Exception:
            pass
        ver = None
        try:
            out = subprocess.check_output(
                ["git", "-C", engine_dir, "describe", "--tags", "--always"],
                stderr=subprocess.DEVNULL, text=True, timeout=5,
                creationflags=_HIDE).strip()
            ver = out or None
        except Exception:
            ver = None
        yield f"{log_prefix}完成：{branch} @ {ver or 'latest'}", 100
    finally:
        # 保护机制：无论成功/失败，都把用户配置原样放回
        _restore_protected(engine_dir, backup, rels)


def _exec_git_quiet(args, cwd):
    """静默执行 git，返回 (ok, output)。"""
    try:
        out = subprocess.check_output(["git"] + args, cwd=cwd,
                                      stderr=subprocess.STDOUT, text=True, timeout=60,
                                      creationflags=_HIDE)
        return True, (out or "").strip()
    except subprocess.CalledProcessError as e:
        return False, (e.output or str(e)).strip()
    except Exception as e:
        return False, str(e)


def _new_task(name, job_fn, *args, **kwargs):
    """启动一个后台任务，返回 task_id。"""
    tid = f"{name}-{int(time.time() * 1000)}"
    st = {"id": tid, "name": name, "status": "running",
          "progress": 0, "log": [], "error": None, "result": None}
    with _tasks_lock:
        _tasks[tid] = st

    def _run():
        last = 0
        try:
            for item in job_fn(*args, **kwargs):
                if isinstance(item, tuple) and len(item) >= 2 \
                        and isinstance(item[1], (int, float)):
                    msg, pct = item[0], float(item[1])
                    if pct is not None:
                        last = max(last, pct)
                        st["progress"] = last
                    st["log"].append(msg)
                else:
                    st["log"].append(str(item))
            st["progress"] = 100
            st["status"] = "done"
        except Exception as e:
            st["status"] = "error"
            st["error"] = str(e)
            st["log"].append(f"错误: {e}")
        with _tasks_lock:
            _tasks[tid] = st

    threading.Thread(target=_run, daemon=True).start()
    return tid


def _task_status(task_id):
    with _tasks_lock:
        st = _tasks.get(task_id)
    if not st:
        return {"ok": False, "msg": "任务不存在或已过期"}
    return {"ok": True, **st}


_SIZE_CACHE = {}


def _dir_size_cached(path):
    """目录大小缓存：目录 mtime 不变则复用上次结果，避免版本列表每次刷新都全量遍历
    （实例环境可达 6GB+，全遍历会阻塞接口、造成页面长时间「加载中」）。"""
    try:
        mt = os.path.getmtime(path)
    except OSError:
        mt = 0
    hit = _SIZE_CACHE.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    size = _dir_size(path)
    if len(_SIZE_CACHE) > 256:
        _SIZE_CACHE.clear()
    _SIZE_CACHE[path] = (mt, size)
    return size


def _dir_size(path):
    total = 0
    try:
        for dirpath, _, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total


# 单例
version_manager = VersionManager()
