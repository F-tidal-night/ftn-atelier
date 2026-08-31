# ============================================
# FTN Studio 模型资产管理器 (AssetManager)
#
# 对应蓝图 M4 AssetManager：
#   - 扫描 reForge 模型目录（全量/增量）
#   - 分类：checkpoint / embedding / lora / lora_plugin / vae
#   - 读取 safetensors metadata（基础模型、训练信息）
#   - 缩略图（同名 png 优先）
#   - 索引写入 SQLite（db.upsert_model）
#   - 搜索 / 查询 / 按分类统计
#
# 目录结构建立在 reForge 约定之上（非侵入扫描）：
#   models/Stable-diffusion  → checkpoint
#   models/Lora              → lora
#   models/Embedding         → embedding
#   models/VAE               → vae
# ============================================

import os
import re
import json
import struct
import time
import hashlib
import threading
from datetime import datetime

from core.log_manager import log_manager  # noqa
from core.status import status_manager
from core.db import db
from core import model_detect


# 目录名 → 模型类型
_DIR_TYPE_MAP = {
    "stable-diffusion": ("checkpoint", False),
    "lora": ("lora", False),
    "lora_plugin": ("lora_plugin", True),
    "embeddings": ("embedding", False),
    "embedding": ("embedding", False),
    "vae": ("vae", False),
    "textual_inversion": ("embedding", False),
}

# 支持的模型文件后缀
_MODEL_EXTS = (".safetensors", ".ckpt", ".pt", ".pth")

# vault: 预览图后缀
_PREVIEW_EXTS = (".png", ".jpg", ".jpeg", ".webp")


class AssetManager:
    """模型扫描、索引与查询"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._scan_lock = threading.Lock()
        self._hash_lock = threading.Lock()
        self._hash_thread = None
        self.scanning = False
        self.last_scan = None
        self._cancel = threading.Event()

    # =================================================
    # 定位模型根目录
    # =================================================
    def _primary_not_supported(self):
        """主引擎家族不受支持（已配置路径但非 reforge/forge）→ 模型功能不适用。
        只识别类型，不移动/修改任何文件。"""
        from core.engine_registry import engine_registry
        fam = engine_registry.primary_family()
        return bool(fam) and fam not in ("reforge", "forge")

    def _resolve_roots(self):
        """从配置解析出模型根目录（只扫描主引擎）。

        模型只归属主引擎（主基底）——需求：模型只主管引擎。
        通过 engine_registry 找到主基底对应的引擎根目录，扫描其 models/。若主基底引擎未注册，
        回退到 engine_registry 标记为 primary 的引擎。
        """
        from core.base_registry import base_registry
        from core.engine_registry import engine_registry
        primary_base = base_registry.primary()
        # 主引擎根目录：跟随 engine_registry 标记的主引擎（primary_key，可指向任意引擎）
        primary = engine_registry.primary_engine()
        root = (primary or {}).get("root", "")
        if root and os.path.isdir(root):
            models_dir = os.path.join(root, "models")
            if os.path.isdir(models_dir):
                # 只扫描已知分类目录（Stable-diffusion/Lora/Embedding/VAE…），
                # 未知目录（hypernetworks/CLIP 等）不扫，避免误判为底模
                roots = []
                for sub, (mtype, _is_plugin) in _DIR_TYPE_MAP.items():
                    d = os.path.join(models_dir, sub)
                    if os.path.isdir(d):
                        roots.append((d, mtype))
                if roots:
                    return roots
        # 兜底：仍走固定 reForge 配置（老配置兼容）
        from core.config_manager import config_manager
        conf = config_manager.load()
        reforge = conf.engine_paths.reforge
        if reforge and os.path.isdir(reforge):
            models_dir = os.path.join(reforge, "models")
            if os.path.isdir(models_dir):
                return [(models_dir, None)]
        return []

    # =================================================
    # 扫描
    # =================================================
    def scan(self, full=True, demo=False):
        """全量 / 增量扫描。demo 用于无真实引擎时生成示例数据。"""
        with self._scan_lock:
            if self.scanning:
                return {"ok": False, "msg": "扫描已在进行中"}
            self.scanning = True
            self._cancel.clear()

        try:
            started = time.time()
            if demo:
                rows = self._scan_demo()
            elif self._primary_not_supported():
                return self._scan_result(
                    started, 0, 0, scanned=0,
                    note="当前主引擎类型不受支持（仅支持启动/停止/重启），模型管理不适用",
                )
            else:
                roots = self._resolve_roots()
                if not roots:
                    return self._scan_result(started, 0, 0, scanned=0, note="未配置主引擎模型目录")
                rows, skipped = self._walk_roots(roots, full)
            stats = self._index(rows, force_update=bool(full and not demo))
            pruned = 0
            if full and not demo:
                # 全量扫描 = 以当前扫描结果重建索引：清除已失效/过期记录（防重复与残留计数）
                pruned = self._prune_missing({r["file_path"].lower() for r in rows})
                # 同路径大小写变体去重（Windows 不区分大小写；老库可能残留双行）
                try:
                    db.execute(
                        "DELETE FROM models WHERE id NOT IN "
                        "(SELECT MIN(id) FROM models GROUP BY LOWER(file_path))"
                    )
                except Exception:
                    pass
            # 后台补齐内容指纹（扫描不阻塞；hash 完成前不判重）
            self._start_hash_worker()
            note = None
            if not full:
                note = f"快速扫描完成：{skipped} 个文件未变化已跳过"
            elif pruned:
                note = f"扫描完成，已清理 {pruned} 条失效/过期记录"
            return self._scan_result(
                started, stats["new"], stats["updated"], scanned=stats["total"],
                note=note, pruned=pruned,
            )
        finally:
            self.scanning = False

    def _walk_roots(self, roots, full):
        """只扫各类型目录【顶层文件】（不递归子目录——插件/子文件夹不再混入）。

        增量（full=False）：预取已索引文件的 size/mtime，未变化的文件跳过，
        避免对几十 GB 模型库反复读 safetensors 头。
        """
        rows = []
        seen = set()
        skipped = 0
        skip_map = {}
        if not full:
            try:
                for r in db.query("SELECT file_path, file_size, mtime FROM models"):
                    skip_map[str(r["file_path"]).lower()] = (r.get("file_size"), r.get("mtime"))
            except Exception:
                pass
        for root_dir, base_type in roots:
            if self._cancel.is_set():
                break
            try:
                names = os.listdir(root_dir)
            except OSError:
                continue
            for fn in names:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in _MODEL_EXTS:
                    continue
                full_path = os.path.join(root_dir, fn)
                if not os.path.isfile(full_path):
                    continue
                key = full_path.lower()
                if key in seen:
                    continue
                seen.add(key)
                if not full:
                    try:
                        st = os.stat(full_path)
                        old = skip_map.get(key)
                        if old and old[0] == st.st_size and abs((old[1] or 0) - st.st_mtime) <= 1:
                            skipped += 1
                            continue
                    except OSError:
                        pass
                rows.append(self._build_row(full_path, root_dir, forced_type=base_type))
        return rows, skipped

    def _prune_missing(self, seen_paths):
        """全量扫描后清理失效记录：文件已不存在、或不在本次扫描范围内（残留/重复来源）。"""
        try:
            rows = db.query("SELECT id, file_path FROM models")
        except Exception:
            return 0
        drop = []
        for r in rows:
            fp = r.get("file_path") or ""
            if fp.lower() not in seen_paths:
                drop.append(r["id"])
        for rid in drop:
            try:
                db.execute("DELETE FROM models WHERE id = ?", (rid,))
            except Exception:
                pass
        return len(drop)

    # =================================================
    # 内容指纹（SHA256）后台计算
    #   扫描先完成；hash 后台补齐；hash 未完成前不判重。
    # =================================================
    def _start_hash_worker(self):
        with self._hash_lock:
            t = self._hash_thread
            if t and t.is_alive():
                return
            self._hash_thread = threading.Thread(target=self._hash_loop, daemon=True)
            self._hash_thread.start()

    def _hash_loop(self):
        while True:
            try:
                rows = db.query(
                    "SELECT id, file_path FROM models WHERE file_path NOT LIKE 'demo://%' "
                    "AND (sha256 IS NULL OR sha256 = '' OR sha256 = 'missing') "
                    "ORDER BY file_size LIMIT 4"
                )
            except Exception:
                return
            if not rows:
                return
            for r in rows:
                fp = r["file_path"]
                try:
                    if os.path.isfile(fp):
                        h = model_detect.sha256_file(fp)
                        db.execute("UPDATE models SET sha256=? WHERE id=?", (h, r["id"]))
                    else:
                        db.execute("UPDATE models SET sha256='missing' WHERE id=?", (r["id"],))
                except Exception:
                    try:
                        db.execute("UPDATE models SET sha256='missing' WHERE id=?", (r["id"],))
                    except Exception:
                        pass
            time.sleep(0.1)

    def _build_row(self, file_path, dir_path, forced_type=None):
        """构造一条模型记录。"""
        st = os.stat(file_path)
        dirname = os.path.basename(dir_path)
        name = os.path.splitext(os.path.basename(file_path))[0]
        # 类型：路径分类优先（reForge 目录约定）；检测层负责架构/base_model/格式
        model_type = forced_type or _DIR_TYPE_MAP.get(dirname.lower(), ("checkpoint", False))[0]
        det = model_detect.detect(file_path, forced_category=model_type)
        # 训练 tag 自动检测已取消：改为用户在详情自行备注
        preview = self._find_preview(file_path)
        now = time.time()
        return {
            "id": _stable_id(file_path),
            "name": name,
            "type": model_type,
            "file_path": file_path,
            "file_size": st.st_size,
            "mtime": st.st_mtime,
            "preview_path": preview or "",
            "source_type": "reforge",
            "source_path": dir_path,
            "engine": "reforge",
            "metadata": det.get("metadata"),
            "tags": "[]",
            "base_model": det.get("base_model", ""),
            "architecture": det.get("architecture", ""),
            "format": det.get("format", ""),
            "sha256": det.get("sha256", ""),
            "detection_source": det.get("detection_source", ""),
            "confidence": det.get("confidence", ""),
            "created_time": now,
            "updated_time": now,
        }

    def _index(self, rows, force_update=False):
        """批量 upsert；返回新增/更新/总数统计。

        force_update（全量扫描）：即使 size/mtime 未变化也刷新检测字段；
        但未变化文件的 sha256 保留缓存，避免后台重复计算。
        """
        new_c = updated_c = 0
        for row in rows:
            existing = db.get_model_by_path(row["file_path"])
            if existing:
                row["id"] = existing["id"]
                row["updated_time"] = time.time()
                changed = (
                    existing.get("file_size") != row["file_size"]
                    or abs((existing.get("mtime") or 0) - row["mtime"]) > 1
                )
                if not changed and existing.get("sha256"):
                    row["sha256"] = existing["sha256"]
                if changed or force_update:
                    updated_c += 1
                    db.upsert_model(row)
            else:
                new_c += 1
                db.upsert_model(row)
        return {"new": new_c, "updated": updated_c, "total": len(rows)}

    def _scan_result(self, started, new_c, updated_c, scanned, note=None, pruned=0):
        self.last_scan = time.time()
        log_manager.info(
            "asset",
            f"模型扫描完成: 新增 {new_c}, 更新 {updated_c}, 遍历 {scanned}, 耗时 {time.time()-started:.1f}s",
        )
        return {
            "ok": True,
            "new": new_c,
            "updated": updated_c,
            "scanned": scanned,
            "note": note or "扫描完成",
            "pruned": pruned,
            "elapsed": round(time.time() - started, 1),
        }

    # =================================================
    # safetensors / 缩略图
    # =================================================
    def _read_safetensors_meta(self, path):
        """读取 safetensors 头部：__metadata__ 中的基础模型、训练信息与标签。"""
        info = {"json": None, "base_model": "", "tags": []}
        if not path.lower().endswith(".safetensors"):
            return info
        try:
            with open(path, "rb") as f:
                nbytes = struct.unpack("<Q", f.read(8))[0]
                header = json.loads(f.read(nbytes))
            meta = header.get("__metadata__", {})
            if not meta:
                return info
            info["json"] = json.dumps(meta, ensure_ascii=False, default=str)[:4000]
            # 基础模型
            bm = (
                meta.get("ss_sd_model_name")
                or meta.get("ss_base_model_version")
                or (meta.get("ss_sd_model_hash") and "sd")
                or ""
            )
            if bm:
                info["base_model"] = str(bm)
            # 触发词
            tw = meta.get("ss_tag_frequency")
            if tw:
                try:
                    tf = json.loads(tw) if isinstance(tw, str) else tw
                    words = list(tf.keys()) if isinstance(tf, dict) else []
                    info["tags"] = words[:24]
                except Exception:
                    pass
        except Exception:
            pass
        return info

    def _find_preview(self, model_path):
        """查找同名预览图（png 优先）。"""
        base, _ = os.path.splitext(model_path)
        for ext in _PREVIEW_EXTS:
            p = base + ext
            if os.path.exists(p):
                return p
        return None

    # =================================================
    # 演示数据（无真实环境时）
    # =================================================
    def _scan_demo(self):
        """生成一组示例模型数据，供 UI 联调。"""
        names = [
            ("majicMIX realistic", "checkpoint", "SD"),
            ("anime pastel dream", "checkpoint", "SDXL"),
            ("detail enhancer", "lora", "SD"),
            ("hand fix lora", "lora_plugin", "SDXL"),
            ("embedding easynegative", "embedding", "SD"),
            ("vae fp16 fix", "vae", "SD"),
        ]
        rows = []
        for name, mtype, base in names:
            fake = f"demo://{name.replace(' ', '_')}.safetensors"
            now = time.time()
            rows.append({
                "id": _stable_id(fake),
                "name": name,
                "type": mtype,
                "file_path": fake,
                "file_size": len(name) * 1000000,
                "mtime": now,
                "preview_path": "",
                "source_type": "reforge",
                "source_path": f"models/{_type_dir(mtype)}",
                "engine": "reforge",
                "metadata": None,
                "tags": json.dumps(["示例", "demo"] if mtype == "lora" else [], ensure_ascii=False),
                "base_model": base,
                "created_time": now,
                "updated_time": now,
            })
        return rows

    # =================================================
    # 查询 / 统计
    # =================================================
    def stats(self):
        if self._primary_not_supported():
            return {
                "total": 0,
                "by_type": {},
                "last_scan": self.last_scan,
                "scanning": False,
                "not_supported": True,
                "note": "当前主引擎类型不受支持（仅支持启动/停止/重启），模型管理不适用",
            }
        rows = db.query(
            "SELECT type, COUNT(*) as c FROM models GROUP BY type"
        )
        total = sum(r["c"] for r in rows)
        by_type = {r["type"]: r["c"] for r in rows}
        return {
            "total": total,
            "by_type": by_type,
            "last_scan": self.last_scan,
            "scanning": self.scanning,
            "not_supported": False,
        }

    def list(self, model_type=None, query=None, tags=None, limit=300):
        if self._primary_not_supported():
            return []
        sql = "SELECT * FROM models WHERE 1=1"
        params = []
        if model_type and model_type != "all":
            sql += " AND type = ?"
            params.append(model_type)
        if query:
            sql += " AND (name LIKE ? OR file_path LIKE ?)"
            like = f"%{query}%"
            params += [like, like]
        sql += " LIMIT ?"
        params.append(limit)
        rows = db.query(sql, params)
        # tags/base_model 从 JSON 还原
        for r in rows:
            r["type_label"] = _TYPE_LABEL.get(r["type"], r["type"])
        # 重复标记：仅 sha256 明确相同才归为副本（hash 未完成的不判重）
        groups = {}
        for r in rows:
            h = r.get("sha256") or ""
            if h and h != "missing":
                groups.setdefault(h, []).append(r)
        for group in groups.values():
            if len(group) > 1:
                group.sort(key=lambda x: x.get("file_path") or "")
                for i, r in enumerate(group):
                    r["copies"] = len(group)
                    r["dup"] = i > 0
        return rows

    def get_by_id(self, model_id):
        """按 id 取单条模型记录（含类型中文标签）。"""
        row = db.query_one("SELECT * FROM models WHERE id = ?", (model_id,))
        if row:
            row["type_label"] = _TYPE_LABEL.get(row["type"], row["type"])
        return row

    # =================================================
    # 打开所在文件夹 / 添加模型（剪切至模型目录）
    # =================================================
    def model_dir(self, model_id):
        """返回某模型的所在文件夹（打开文件管理器用）。

        直接落在该模型文件所属目录（天然处于对应分类目录下）。
        """
        row = self.get_by_id(model_id)
        if not row:
            return {"ok": False, "msg": "模型不存在"}
        fp = row.get("file_path") or ""
        if not fp or fp.startswith("demo://"):
            return {"ok": False, "msg": "演示数据无真实文件", "demo": True}
        folder = os.path.dirname(fp)
        if not os.path.isdir(folder):
            return {"ok": False, "msg": "模型所在目录不存在（文件可能已移动）"}
        return {"ok": True, "path": folder, "name": row.get("name"), "type": row.get("type")}

    def _type_dir_abs(self, model_type):
        """某分类对应的绝对目录（主引擎 models/<分类目录>）。"""
        try:
            roots = self._resolve_roots()
            root = roots[0][0] if roots else ""
        except Exception:
            root = ""
        return os.path.join(root, _type_dir(model_type)) if root else ""

    def add_models(self, paths, model_type):
        """剪切式添加模型：把源文件 move 到对应分类目录下并重新索引。

        paths: 源文件绝对路径（一个或多个）。
        model_type: 目标分类（checkpoint/lora/lora_plugin/embedding/vae）。
        目标目录若不存在则自动创建；同名冲突自动追加序号。
        """
        import shutil

        if isinstance(paths, str):
            paths = [paths]
        paths = [p for p in (paths or []) if p]
        VALID = ("checkpoint", "lora", "lora_plugin", "embedding", "vae")
        if not paths:
            return {"ok": False, "msg": "未选择要添加的模型文件"}
        if model_type not in VALID:
            return {"ok": False, "msg": f"未知模型分类: {model_type}"}

        dest_dir = self._type_dir_abs(model_type)
        if not dest_dir:
            return {"ok": False, "msg": "未配置主引擎模型目录，无法添加"}
        if self._primary_not_supported():
            return {"ok": False, "msg": "当前主引擎类型不受支持（仅支持启动/停止/重启），模型管理不适用"}
        os.makedirs(dest_dir, exist_ok=True)

        moved, errors = [], []
        for src in paths:
            src = os.path.abspath(src)
            if not os.path.isfile(src):
                errors.append(f"{os.path.basename(src)}: 文件不存在")
                continue
            fname = os.path.basename(src)
            # 已在目标目录内则直接复用，否则剪切过去（同名自动加序号）
            if os.path.dirname(src) == dest_dir:
                dst = src
            else:
                stem, ext = os.path.splitext(fname)
                dst = os.path.join(dest_dir, fname)
                n = 1
                while os.path.exists(dst):
                    dst = os.path.join(dest_dir, f"{stem} ({n}){ext}")
                    n += 1
                try:
                    shutil.move(src, dst)
                except Exception as e:
                    errors.append(f"{fname}: {e}")
                    continue
            # 重新索引（删除旧路径条目，写入新条目）
            self._drop_index(src)
            row = self._build_row(dst, dest_dir)
            row["type"] = model_type  # 强制目标分类
            db.upsert_model(row)
            moved.append({"path": dst, "name": row["name"], "type": model_type})

        if not moved and errors:
            return {"ok": False, "msg": "；".join(errors)}
        return {
            "ok": True,
            "moved": moved,
            "errors": errors,
            "count": len(moved),
            "type": model_type,
            "type_label": _TYPE_LABEL.get(model_type, model_type),
            "note": f"已剪切 {len(moved)} 个文件至「{_TYPE_LABEL.get(model_type, model_type)}」分类并加入索引",
        }

    @staticmethod
    def _drop_index(old_path):
        """按旧路径删除索引条目（用于文件被移动后清理脏记录）。"""
        try:
            old = db.get_model_by_path(old_path)
            if old:
                db.delete_model(old["id"])
        except Exception:
            pass

    # =================================================
    # LoRA 详情（SafetensorsMetadataProvider + 手动覆盖）
    # =================================================
    def _load_override(self, model_id):
        """读取用户手动覆盖（base_model / 推荐权重 / 触发词 / 备注）。"""
        try:
            val = db.get_meta(f"lora_override:{model_id}", "{}")
            return json.loads(val) if isinstance(val, str) else {}
        except Exception:
            return {}

    def _save_override(self, model_id, payload):
        """保存用户手动覆盖字段。"""
        cur = self._load_override(model_id)
        for k in ("base_model", "recommended_weight", "trigger_words", "custom_notes"):
            if k in payload:
                cur[k] = payload[k]
        db.set_meta(f"lora_override:{model_id}", json.dumps(cur, ensure_ascii=False))
        return cur

    def lora_detail(self, model_id):
        """构造统一 LoRA 详情：safetensors 读取 + 手动覆盖合并。"""
        row = self.get_by_id(model_id)
        if not row:
            return {"ok": False, "msg": "模型不存在"}
        if row["type"] not in ("lora", "lora_plugin"):
            return {"ok": False, "msg": "该模型不是 LoRA", "type": row["type"]}

        over = self._load_override(model_id)

        file_path = row.get("file_path") or ""
        meta = None
        if file_path.startswith("demo://") or not file_path.lower().endswith(".safetensors"):
            meta = self._lora_fallback(row)
        else:
            try:
                from core.lora_provider import SafetensorsMetadataProvider
                meta = SafetensorsMetadataProvider(file_path).load()
            except Exception:
                meta = self._lora_fallback(row)

        d = meta.model_dump()
        # 手动覆盖优先
        if over.get("base_model"):
            d["base_model"] = over["base_model"]
        if over.get("recommended_weight") is not None:
            d["recommended_weight"] = over["recommended_weight"]
        if over.get("trigger_words") is not None:
            d["trigger_words"] = over["trigger_words"]
        d["custom_notes"] = over.get("custom_notes", "")

        # 回填索引侧信息
        try:
            d["tags"] = json.loads(row.get("tags") or "[]")
        except Exception:
            pass
        d["preview_path"] = row.get("preview_path") or d.get("preview_path")
        d["id"] = model_id
        d["title_name"] = row["name"]
        # 架构（检测层结果，与 base_model 分离：架构 vs 具体模型）
        d["architecture"] = row.get("architecture") or ""
        d["detection_source"] = row.get("detection_source") or ""
        d["asset"] = {
            "name": row["name"],
            "type": row["type"],
            "type_label": row.get("type_label"),
            "file_size": row.get("file_size"),
            "mtime": row.get("mtime"),
        }
        d["override"] = over
        d["can_read_safetensors"] = bool(file_path and file_path.lower().endswith(".safetensors")
                                         and not file_path.startswith("demo://"))

        # 尽力而为：配置了 CivitAI Key 且确为真实 LoRA 时补拉在线信息（失败不影响主结果）
        if not file_path.startswith("demo://") and row["type"] in ("lora", "lora_plugin"):
            d = self._enrich_civitai(row, d)

        return {"ok": True, "lora": d}

    def _enrich_civitai(self, row, d):
        """用 CivitAI 在线信息补全 LoRA 详情（有 Key 才尝试，断网/缺失静默跳过）。"""
        try:
            from core.config_manager import config_manager
            from core.lora_provider import CivitaiMetadataProvider
            key = (config_manager.load().api_keys.civitai or "").strip()
            if not key:
                return d
            online = CivitaiMetadataProvider(row["name"], api_key=key, timeout=6).load()
            if not d.get("base_model") and online.base_model:
                d["base_model"] = online.base_model
            if not d.get("trigger_words") and online.trigger_words:
                d["trigger_words"] = online.trigger_words
            if d.get("recommended_weight") is None and online.recommended_weight is not None:
                d["recommended_weight"] = online.recommended_weight
            d["online"] = {
                "id": online.id,
                "name": online.name,
                "trigger_words": online.trigger_words,
                "recommended_weight": online.recommended_weight,
                "base_model": online.base_model,
            }
            if online.training_info.comment and not d.get("custom_notes"):
                d["custom_notes"] = ("（来自 CivitAI）" + online.training_info.comment)[:800]
        except Exception:
            pass
        return d

    def _lora_fallback(self, row):
        """真实文件缺失/非 safetensors 时，用索引信息构造详情。"""
        from core.models.lora_metadata import LoraMetadata, LoraSource, TrainingInfo
        try:
            tags = json.loads(row.get("tags") or "[]")
        except Exception:
            tags = []
        return LoraMetadata(
            id=row["id"],
            name=row["name"],
            file_path=row.get("file_path") or "",
            tags=tags if isinstance(tags, list) else [],
            base_model=row.get("base_model") or None,
            training_info=TrainingInfo(),
            source=LoraSource.MANUAL if row.get("file_path", "").startswith("demo://") else LoraSource.SAFETENSORS,
        )

    def lora_override(self, model_id, payload):
        """保存 LoRA 手动覆盖字段并返回合并后的详情。"""
        row = self.get_by_id(model_id)
        if not row:
            return {"ok": False, "msg": "模型不存在"}
        if row["type"] not in ("lora", "lora_plugin"):
            return {"ok": False, "msg": "该模型不是 LoRA"}

        allowed = {"base_model", "recommended_weight", "trigger_words", "custom_notes"}
        clean = {k: v for k, v in (payload or {}).items() if k in allowed}
        if "recommended_weight" in clean and clean["recommended_weight"] == "":
            clean["recommended_weight"] = None
        if "trigger_words" in clean and isinstance(clean["trigger_words"], str):
            clean["trigger_words"] = [x.strip() for x in clean["trigger_words"].split(",") if x.strip()]
        self._save_override(model_id, clean)
        return self.lora_detail(model_id)


# ---------- 工具 ----------
def _stable_id(path):
    """按路径生成稳定 id（含 config_manager 直读避免循环导入）。"""
    return "m-" + hashlib.md5(path.encode("utf-8")).hexdigest()[:12]


def _type_dir(mtype):
    return {
        "checkpoint": "Stable-diffusion",
        "lora": "Lora",
        "lora_plugin": "Lora_plugin",
        "embedding": "Embedding",
        "vae": "VAE",
    }.get(mtype, "Stable-diffusion")


_TYPE_LABEL = {
    "checkpoint": "Checkpoint",
    "lora": "LoRA",
    "lora_plugin": "插件 LoRA",
    "embedding": "Embedding",
    "vae": "VAE",
}


# 单例
asset_manager = AssetManager()
