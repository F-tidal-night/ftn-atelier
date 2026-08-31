# ============================================
# FTN Studio 网络模型下载管理器 (DownloadsManager)
#
# 对应蓝图「4. 网络下载功能」：
#   - CivitAI：通过 CivitAI API 搜索模型 → 选择版本 → 下载
#   - HuggingFace：通过 HF API 搜索模型库 → 选文件 → 下载
#   - 下载文件落入主引擎对应分类目录（models/Stable-diffusion、models/Lora …）并重新索引
#
# 设计要点：
#   - 搜索用公开只读 API（CivitAI / HF 均可匿名访问，速度/限额受官方限制）；
#     若配置了对应 API Key/Token 则附带鉴权头（提高限额）。
#   - 下载为流式后台任务，带 Content-Length 进度百分比；完成后触发模型增量扫描入库。
#   - 所有网络请求带短超时；单项失败绝不拖垮整轮。
# ============================================

import os
import re
import json
import time
import urllib.parse
import urllib.request
import threading

from core.log_manager import log_manager
from core.config_manager import config_manager
from core.selfcheck import FTN_APP_VERSION

# 模型类型 -> reForge 分类目录名（与 asset_manager._type_dir 保持一致）
_TYPE_DIR = {
    "checkpoint": "Stable-diffusion",
    "lora": "Lora",
    "lora_plugin": "Lora_plugin",
    "embedding": "Embedding",
    "vae": "VAE",
}
_VALID_TYPES = tuple(_TYPE_DIR.keys())

_UA = f"FTN-Atelier/{FTN_APP_VERSION} (network-download)"


class DownloadsManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    # =================================================
    # 凭据
    # =================================================
    def _api_keys(self):
        try:
            ak = config_manager.load().api_keys
            return {
                "civitai": (ak.civitai_api_key or "").strip(),
                "hf": (ak.huggingface_token or "").strip(),
            }
        except Exception:
            return {"civitai": "", "hf": ""}

    def _hf_base(self):
        """HF 请求基础地址：启用镜像且配置了端点时用镜像，否则官方。"""
        try:
            env = config_manager.load().env
            if env.use_hf_mirror:
                ep = (env.hf_endpoint or "").strip()
                if ep:
                    return ep.rstrip("/")
        except Exception:
            pass
        return "https://huggingface.co"

    def sources(self):
        keys = self._api_keys()
        return {
            "civitai": {"configured": bool(keys["civitai"])},
            "huggingface": {"configured": bool(keys["hf"])},
        }

    @staticmethod
    def _urlopen_json(url, headers=None, timeout=12):
        """GET 并解析 JSON；失败抛异常。"""
        h = {"User-Agent": _UA}
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    # =================================================
    # CivitAI 搜索
    # =================================================
    def civitai_search(self, query="", mtype="", limit=24):
        """CivitAI 模型搜索。type 映射到 CivitAI types 参数。"""
        try:
            params = {"limit": int(limit) or 24}
            if query and query.strip():
                params["query"] = query.strip()
            civ_type = _civit_type(mtype)
            if civ_type:
                params["types"] = civ_type
            url = "https://civitai.com/api/v1/models?" + urllib.parse.urlencode(params)
            keys = self._api_keys()
            headers = {}
            if keys["civitai"]:
                headers["Authorization"] = f"Bearer {keys['civitai']}"
            data = self._urlopen_json(url, headers=headers)
        except urllib.error.HTTPError as e:
            return _search_err("civitai", f"HTTP {e.code}", e.reason)
        except urllib.error.URLError as e:
            return _search_err("civitai", "网络错误", f"{e.reason}")
        except Exception as e:
            return _search_err("civitai", "解析失败", str(e))

        items = []
        for m in (data.get("items") or []):
            meta = m.get("modelVersions") or []
            best = _pick_civit_version(meta)
            versions = _civit_versions(meta)
            stats = m.get("stats") or {}
            items.append({
                "source": "civitai",
                "source_id": m.get("id"),
                "name": m.get("name") or "",
                "type": m.get("type") or "",
                "creator": (m.get("creator") or {}).get("username") or "",
                "image": _civit_preview(m),
                "description": _clean((m.get("description") or "")[:400]),
                "nsfw": bool(m.get("nsfw")),
                "download_url": best["url"] if best else "",
                "filename": best["filename"] if best else "",
                "size": best["size"] if best else 0,
                "base": best["base"] if best else "",
                "version_count": len(meta),
                "versions": versions,
                "downloads": stats.get("downloadCount") or 0,
                "likes": stats.get("thumbsUpCount") or 0,
            })
        return {"ok": True, "source": "civitai", "count": len(items), "items": items}

    # =================================================
    # HuggingFace 搜索
    # =================================================
    def hf_search(self, query="", limit=24):
        """HuggingFace 模型库搜索（浅列表，不含文件明细）。"""
        try:
            params = {"limit": int(limit) or 24}
            if query and query.strip():
                params["search"] = query.strip()
                params["sort"] = "downloads"
                params["direction"] = "-1"
            url = f"{self._hf_base()}/api/models?" + urllib.parse.urlencode(params)
            keys = self._api_keys()
            headers = {}
            if keys["hf"]:
                headers["Authorization"] = f"Bearer {keys['hf']}"
            data = self._urlopen_json(url, headers=headers)
            if isinstance(data, dict):
                data = data.get("items") or []
        except urllib.error.HTTPError as e:
            return _search_err("huggingface", f"HTTP {e.code}", e.reason)
        except urllib.error.URLError as e:
            return _search_err("huggingface", "网络错误", f"{e.reason}")
        except Exception as e:
            return _search_err("huggingface", "解析失败", str(e))

        items = []
        for m in (data or []):
            items.append({
                "source": "huggingface",
                "repo": m.get("id") or "",
                "name": (m.get("id") or "").split("/")[-1],
                "downloads": m.get("downloads") or 0,
                "likes": m.get("likes") or 0,
                "pipeline": (m.get("pipeline_tag") or "") or "",
                "tags": (m.get("tags") or [])[:8],
                "description": _clean((m.get("description") or "")[:300]),
            })
        return {"ok": True, "source": "huggingface", "count": len(items), "items": items}

    def hf_files(self, repo):
        """列出某 HF 模型库 main 分支顶层文件（含 LFS 大小）。"""
        repo = (repo or "").strip().strip("/")
        if not repo:
            return {"ok": False, "msg": "缺少模型库 id"}
        try:
            url = f"{self._hf_base()}/api/models/{urllib.parse.quote(repo, safe='/')}/tree/main"
            keys = self._api_keys()
            headers = {}
            if keys["hf"]:
                headers["Authorization"] = f"Bearer {keys['hf']}"
            data = self._urlopen_json(url, headers=headers)
        except urllib.error.HTTPError as e:
            return _search_err("huggingface", f"HTTP {e.code}", e.reason)
        except Exception as e:
            return _search_err("huggingface", "失败", str(e))

        files = []
        for f in data or []:
            if f.get("type") != "file":
                continue
            path = f.get("path") or ""
            size = f.get("size") or 0
            lfs = f.get("lfs") or {}
            if lfs.get("size"):
                size = lfs["size"]
            files.append({
                "path": path,
                "name": os.path.basename(path),
                "size": size,
                "extension": os.path.splitext(path)[1].lower(),
                "download_url": f"{self._hf_base()}/{repo}/resolve/main/{urllib.parse.quote(path)}",
            })
        # 按后缀优先级 + 大小排：safetensors > ckpt > pt > pth > 其他；大的在前
        def _score(f):
            return _ext_score(f["extension"])
        files.sort(key=lambda f: (_ext_score(f["extension"]), f["size"]), reverse=True)
        return {"ok": True, "repo": repo, "files": files}

    # =================================================
    # 下载（后台任务，流式 + 进度）
    # =================================================
    def start(self, source, url, filename, model_type):
        """启动后台下载任务。返回 {ok, task_id, target}。"""
        source = (source or "").lower()
        url = (url or "").strip()
        if source not in ("civitai", "huggingface"):
            return {"ok": False, "msg": f"未知下载来源: {source}"}
        if not url:
            return {"ok": False, "msg": "缺少下载地址"}
        if model_type not in _VALID_TYPES:
            return {"ok": False, "msg": f"未知模型分类: {model_type}"}

        # 目标目录：主引擎 models/<分类目录>
        from core.asset_manager import asset_manager
        dest_dir = asset_manager._type_dir_abs(model_type)
        if not dest_dir:
            return {"ok": False, "msg": "未配置主引擎模型目录，无法下载"}
        os.makedirs(dest_dir, exist_ok=True)

        fname = _clean_filename(filename or os.path.basename(urllib.parse.urlparse(url).path))
        if not fname:
            fname = f"download_{int(time.time())}.safetensors"
        out_path = _dedupe_path(os.path.join(dest_dir, fname))

        task_id = _new_task("download", _run_download_job,
                            source, url, out_path, model_type,
                            self._api_keys())
        return {
            "ok": True,
            "task_id": task_id,
            "target": out_path,
            "type": model_type,
            "type_label": _TYPE_DIR.get(model_type, model_type),
        }

    def status(self, task_id):
        return _task_status(task_id)


def _civit_type(mtype):
    """FTN 模型分类 → CivitAI types 参数。留空返回 None（全部）。"""
    return {
        "checkpoint": "Checkpoint",
        "lora": "LORA",
        "lora_plugin": "LORA",
        "embedding": "TextualInversion",
        "vae": "VAE",
    }.get(mtype)


def _pick_civit_version(versions):
    """从 CivitAI modelVersions 中挑可下载版本：取带 downloadUrl 且为 safetensors 的最新一个。"""
    best = None
    for v in versions or []:
        dl = v.get("downloadUrl") or ""
        files = v.get("files") or []
        f = next((x for x in files if x.get("type") == "Model"), None)
        if not dl:
            continue
        fname = (f or {}).get("name") or ""
        size = (f or {}).get("sizeKB") or 0
        base = _base_of_meta(v.get("baseModel") or "", v.get("baseModelType") or "")
        cand = {
            "url": dl,
            "filename": fname,
            "size": size * 1024 if size else (f or {}).get("size", 0),
            "base": base,
            "_score": 1 if fname.lower().endswith(".safetensors") else 0,
        }
        if best is None or cand["_score"] > best["_score"]:
            best = cand
    return best


def _civit_versions(versions):
    """列出每个 modelVersion 的可下载文件（供下载时选择版本）。"""
    out = []
    for i, v in enumerate(versions or []):
        dl = v.get("downloadUrl") or ""
        files = v.get("files") or []
        f = next((x for x in files if x.get("type") == "Model"), None)
        if not dl:
            continue
        fname = (f or {}).get("name") or ""
        size = (f or {}).get("sizeKB") or 0
        out.append({
            "id": v.get("id") or i,
            "name": v.get("name") or f"版本 {i + 1}",
            "base": _base_of_meta(v.get("baseModel") or "", v.get("baseModelType") or ""),
            "filename": fname,
            "download_url": dl,
            "size": size * 1024 if size else (f or {}).get("size", 0),
        })
    return out


def _civit_preview(model):
    """CivitAI 暂无预览图信息时返回空——前端用占位。"""
    imgs = model.get("images") or []
    if imgs:
        url = imgs[0].get("url") or imgs[0].get("image") or ""
        return url
    return None


def _base_of_meta(base_model, base_model_type=""):
    """CivitAI baseModel/baseModelType → FTN 架构（SD1 / SD2 / SDXL / Flux / SD3）。"""
    s = (str(base_model or "") + " " + str(base_model_type or "")).lower()
    if "xl" in s or "sdxl" in s or "pony" in s or "illustrious" in s or "noobai" in s:
        return "SDXL"
    if "flux" in s:
        return "Flux"
    if "sd3" in s or "stable-diffusion-3" in s:
        return "SD3"
    if "2" in s and ("sd 2" in s or "2." in s):
        return "SD2"
    if "1" in s and ("sd 1" in s or "1." in s or "v1" in s):
        return "SD1"
    return base_model or "Unknown"


def _ext_score(ext):
    """文件后缀下载优先级：safetensors>ckpt>pt>pth>其他。"""
    return {
        ".safetensors": 5,
        ".ckpt": 4,
        ".pt": 3,
        ".pth": 3,
        ".bin": 2,
        ".onnx": 2,
        ".sft": 2,
    }.get(ext, 0)


def _clean_filename(name):
    """清理不可用于文件名的字符。"""
    name = re.sub(r'[\\/:*?"<>|]+', "_", name or "").strip()
    name = name.replace(" ", "_")
    return name


def _dedupe_path(path):
    """同名冲突追加序号，保证不覆盖已有文件。"""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


def _clean(s):
    import html as _html
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)   # 去掉 <p>/<br> 等标签
    s = _html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _search_err(source, kind, detail):
    return {
        "ok": False,
        "source": source,
        "error": f"{kind}：{detail}",
        "items": [],
    }


# =================================================
# 后台任务执行器（流式下载 + 进度）
# =================================================
_tasks = {}
_tasks_lock = threading.Lock()
_BLOCK = 1 << 16


def _run_download_job(source, url, out_path, model_type, api_keys):
    """生成器：流式下载到 out_path，完成后增量扫描入库。产出 (msg, 进度)。"""
    head = {"User-Agent": _UA}
    if source == "civitai" and api_keys.get("civitai"):
        head["Authorization"] = f"Bearer {api_keys['civitai']}"
    elif source == "huggingface" and api_keys.get("hf"):
        head["Authorization"] = f"Bearer {api_keys['hf']}"

    yield "发起下载请求...", 1
    try:
        req = urllib.request.Request(url, headers=head)
        with urllib.request.urlopen(req, timeout=20) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            tmp = out_path + ".part"
            with open(tmp, "wb") as fh:
                while True:
                    chunk = resp.read(_BLOCK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    pct = (done * 100.0 / total) if total else None
                    if pct is not None:
                        yield f"已下载 {_fmt_size(done)} / {_fmt_size(total)}", min(99, round(pct, 1))
                    else:
                        yield f"已下载 {_fmt_size(done)}", 20
            os.replace(tmp, out_path)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"下载失败（HTTP {e.code} {e.reason}）")
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络错误：{getattr(e, 'reason', e)}（请检查网络或使用科学上网）")
    except OSError as e:
        _safe_remove(out_path + ".part")
        raise RuntimeError(f"写入失败：{e}")
    except Exception as e:
        _safe_remove(out_path + ".part")
        raise RuntimeError(str(e))

    size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
    yield f"下载完成：{os.path.basename(out_path)}（{_fmt_size(size)}），正在加入模型库...", 100

    _safe_remove(out_path + ".part")
    try:
        from core.asset_manager import asset_manager
        asset_manager.scan(full=False)
        yield f"已加入模型库（模型管理页可查看）", 100
    except Exception as e:
        log_manager.error("download", f"下载后入库失败: {e}")
        yield f"文件已下载，但入库失败（{e}），可手动「刷新」模型库", 100


def _fmt_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"


def _safe_remove(p):
    try:
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass


def _new_task(name, job_fn, *args, **kwargs):
    """启动后台任务，返回 task_id。"""
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


downloads_manager = DownloadsManager()
