# ============================================
# FTN Studio 后端服务入口 (FastAPI 常驻服务)
#
# 职责：
# - 提供 REST API 与 WebSocket
# - 作为 FTN Studio 核心服务常驻运行
# - 不随子进程启动立即结束
#
# 生命周期由 Electron 主进程管理：
#   启动：Electron 拉起本服务
#   关闭：Electron 调用 /api/shutdown 优雅退出
# ============================================

import os
import sys
import json
import asyncio
import platform
import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

# 确保项目根可导入业务模块
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from core.log_manager import log_manager  # noqa: E402
from core.status import status_manager  # noqa: E402
from core.host_watchdog import watchdog  # noqa: E402
from core.db import db  # noqa: E402
from core.config_manager import config_manager  # noqa: E402
from core.runner import runner  # noqa: E402
from core.asset_manager import asset_manager  # noqa: E402
from core.version_manager import version_manager  # noqa: E402
from core.engine_registry import engine_registry  # noqa: E402
from core.base_registry import base_registry  # noqa: E402
from core.selfcheck import selfcheck_manager, FTN_APP_VERSION  # noqa: E402
from core.env_detect import env_detect  # noqa: E402
from core.downloads import downloads_manager  # noqa: E402
from core.output_watcher import output_watcher  # noqa: E402
from core.console_sessions import session_manager  # noqa: E402
from core.paths import ensure_app_dirs  # noqa: E402

# 主事件循环引用（供线程安全地把日志推送协程调度到 WS 事件循环）
_MAIN_LOOP = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """捕获 uvicorn 主事件循环，供 log→WS 推送桥接使用。"""
    global _MAIN_LOOP
    _MAIN_LOOP = asyncio.get_running_loop()
    # 启动即补齐标准数据目录（新环境自检不再报「目录不完整」）
    ensure_app_dirs()
    yield


app = FastAPI(title="FTN Atelier Backend", version=FTN_APP_VERSION, lifespan=lifespan)

# CORS：允许 Electron 渲染进程与本地 Vite dev server 访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================
# 健康检查
# ============================================
@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "ftn-studio", "version": FTN_APP_VERSION}


# ============================================
# 系统信息
# ============================================
@app.get("/api/system")
async def system_info():
    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "arch": platform.machine(),
        "version": FTN_APP_VERSION,
        "pid": os.getpid(),
        "hostname": platform.node(),
    }


# ============================================
# GPU 自动检测（nvidia-smi）
# ============================================
@app.get("/api/system/gpu")
async def system_gpu():
    gpus = []
    try:
        import subprocess
        out = subprocess.run(
            [env_detect._nvidia_smi(), "--query-gpu=index,name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
        if out.returncode == 0 and out.stdout.strip():
            for line in out.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    gpus.append({
                        "index": int(parts[0]),
                        "name": parts[1],
                        "vram": parts[2] + " MB",
                    })
    except Exception:
        gpus = []
    return {"gpus": gpus, "detected": bool(gpus)}


# ============================================
# 环境检测链（Python / Git / CUDA / 显卡 / 模型路径 一键检测）
# ============================================
@app.get("/api/system/env")
async def system_env():
    """聚合环境快照，供疑难解答页「环境检测」分区展示（只读，不修复）。"""
    return env_detect.run()


# ============================================
# 运行状态（启动模式互斥查询）
# ============================================
@app.get("/api/status")
async def status():
    return status_manager.snapshot()


# ============================================
# 全局配置（AppConfig 可视化编辑的数据源）
# ============================================
@app.get("/api/config")
async def get_config():
    return config_manager.load().model_dump()


@app.put("/api/config")
async def update_config(payload: dict):
    app_config = config_manager.update(payload)
    log_manager.info("backend", "配置已更新")
    return app_config.model_dump()


@app.post("/api/config/reset")
async def reset_config():
    config = config_manager.reset()
    log_manager.info("backend", "配置已重置为默认")
    return config.model_dump()


# ============================================
# 首页自定义头图
# ============================================
@app.get("/api/hero")
async def hero_image():
    """返回首页头图（读 preference.hero_image，缺省返回 204 由前端渐变兜底）。"""
    conf = config_manager.load()
    hero = conf.preference.hero_image
    if not hero:
        return JSONResponse(status_code=204, content=None)
    # 网络 URL 直接返回
    if hero.startswith(("http://", "https://")):
        return JSONResponse({"url": hero})
    if os.path.isfile(hero):
        # 禁止缓存：裁剪/更换头图后同 URL 必须立即取到新图
        return FileResponse(hero, headers={"Cache-Control": "no-store"})
    return JSONResponse(status_code=204, content=None)


# ============================================
# 数据库健康 / 统计
# ============================================
@app.get("/api/stats")
async def stats():
    try:
        meta_rows = db.query("SELECT COUNT(*) as c FROM app_meta")
        model_rows = db.query("SELECT COUNT(*) as c FROM models")
        return {
            "db": "ok",
            "path": db.DATABASE_PATH,
            "meta_count": meta_rows[0]["c"] if meta_rows else 0,
            "model_count": model_rows[0]["c"] if model_rows else 0,
        }
    except Exception as e:
        return {"db": "error", "detail": str(e)}


# ============================================
# 近期日志查询（疑难解答数据源）
# ============================================
@app.get("/api/logs/recent")
async def recent_logs(limit: int = 100, source: str = None, level: str = None):
    return log_manager.recent(limit=limit, source=source, level=level)


# ============================================
# 疑难解答日志（至多50条，优先删旧与正常）
# ============================================
@app.get("/api/logs/troubleshoot")
async def troubleshoot_logs():
    return log_manager.troubleshoot_logs()


# ============================================
# 日志源（客户端 + 各引擎）分区查询 / 导出
# ============================================
@app.get("/api/logs/sources")
async def logs_sources():
    """返回可查看的日志源：客户端 + 各 bat/脚本类引擎（html/tag 库无进程日志）。"""
    sources = [{"name": "backend", "label": "客户端", "path": log_manager.current_file("backend")}]
    for e in engine_registry.list_engines():
        if e.get("kind") in ("batdir", "webui"):
            sources.append({"name": e["key"], "label": e["label"], "path": log_manager.current_file(e["key"])})
    return {"sources": sources, "log_dir": log_manager.log_dir}


@app.get("/api/logs/file")
async def logs_file(category: str, lines: int = 500):
    """读取某类别日志文件内容（用于控制台/疑难解答分区展示，不做行内强校验）。"""
    p = log_manager.current_file(category)
    if not os.path.isfile(p):
        return {"category": category, "exists": False, "content": ""}
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        # 行数限制：若末行不完整（被截断），保留最近完整行
        content = "".join(all_lines[-lines:])
        return {"category": category, "exists": True, "content": content}
    except Exception as e:
        return {"category": category, "exists": True, "content": "", "error": str(e)}


# ============================================
# 引擎（reForge）控制 / 状态
# ============================================
@app.get("/api/engine/status")
async def engine_status():
    return runner.snapshot()


@app.post("/api/engine/start")
async def engine_start(engine: str = "reforge"):
    result = runner.start(engine_key=engine)
    return result


@app.post("/api/engine/stop")
async def engine_stop(engine: str = None):
    """停止指定引擎的全部实例；engine 为空则停止主实例及其同名实例。"""
    result = runner.stop(engine_key=engine)
    return result


@app.post("/api/engine/stop-all")
async def engine_stop_all():
    """停止全部引擎实例（主实例 + 所有多开），供退出/关闭前兜底清理。"""
    result = runner.stop_all()
    return result


@app.get("/api/engine/stats")
async def engine_stats():
    """各引擎实例占用（内存/显存，整棵进程树汇总）。bat 引擎可检测；html 无进程不检测。"""
    return runner.stats()


@app.get("/api/engine/diagnose")
async def engine_diagnose():
    """主实例启动失败诊断（日志关键词 → 修复建议）。"""
    return {"ok": True, "diagnosis": runner.diagnose()}


# ============================================
# 控制台多窗口 / CMD 多开
# ============================================
@app.get("/api/console/sessions")
async def console_sessions_list():
    """返回控制台会话列表：运行中的 CMD/PowerShell 会话 + 实时引擎会话。"""
    return {"ok": True, "sessions": session_manager.list_sessions()}


@app.post("/api/console/sessions/{sid}/stop")
async def console_sessions_stop(sid: str):
    """关闭指定引擎会话（走 runner 生命周期，只终止对应实例）。"""
    if sid.startswith("engine:"):
        parts = sid.split(":")
        key = parts[1] if len(parts) > 1 else "reforge"
        num = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        if num is not None and num > 1:
            return runner.stop_instance(key, num)
        return runner.stop(engine_key=key)
    return {"ok": False, "msg": "未知会话"}


# ============================================
# 模型资产管理 (M4)
# ============================================
@app.get("/api/models/stats")
async def models_stats():
    return asset_manager.stats()


@app.get("/api/models")
async def models_list(type: str = "all", q: str = None, limit: int = 300):
    return asset_manager.list(model_type=type, query=q, limit=limit)


@app.post("/api/models/scan")
async def models_scan(demo: bool = False, full: bool = True):
    result = asset_manager.scan(full=full, demo=demo)

    return result


@app.post("/api/models/auto-scan")
async def models_auto_scan():
    """模型页加载时的自动检测：索引为空或距上次自动检测超时则后台增量扫描。"""
    return asset_manager.ensure_auto_scan()


@app.get("/api/models/folder")
async def models_folder(type: str = "all"):
    """返回当前分类对应的模型文件夹（打开文件夹按钮用）。"""
    return asset_manager.category_dir(model_type=type)


@app.get("/api/models/{model_id}/lora")
async def models_lora_detail(model_id: str):
    """LoRA 详情：safetensors metadata（SafetensorsMetadataProvider）+ 手动覆盖合并。"""
    return asset_manager.lora_detail(model_id)


@app.post("/api/models/{model_id}/lora/override")
async def models_lora_override(model_id: str, payload: dict):
    """保存 LoRA 手动覆盖字段（base_model / 推荐权重 / 触发词 / 备注）。"""
    return asset_manager.lora_override(model_id, payload)
@app.get("/api/models/{model_id}/dir")
async def models_dir(model_id: str):
    """返回模型所在文件夹（打开文件管理器用）。"""
    return asset_manager.model_dir(model_id)
@app.post("/api/models/add")
async def models_add(payload: dict):
    """剪切式添加模型：把源文件 move 到当前分类目录并重新索引。"""
    paths = payload.get("paths") or payload.get("path")
    model_type = payload.get("type", "checkpoint")
    return asset_manager.add_models(paths, model_type)


# ============================================
# 版本管理 (M5)
# ============================================
@app.get("/api/versions")
async def versions_snapshot():
    return version_manager.snapshot()


@app.post("/api/versions/active")
async def versions_set_active(engine_id: str):
    return version_manager.set_active(engine_id)


@app.get("/api/versions/protected")
async def versions_protected():
    return version_manager.protected_paths()


@app.post("/api/versions/download")
async def versions_download(payload: dict):
    """真实 git clone 下载某基底的某个版本为独立实例（后台任务）。"""
    return version_manager.download(
        base_key=payload.get("base_key", ""),
        version=payload.get("version", ""),
        write_to=payload.get("write_to"),
    )


@app.get("/api/versions/download/status/{task_id}")
async def versions_download_status(task_id: str):
    return version_manager.download_status(task_id)


@app.post("/api/versions/{engine_id}/update")
async def versions_update(engine_id: str, payload: dict):
    """真实 git 更新指定版本实例到新版本（默认该基底最新可用版本）。"""
    return version_manager.update_version(engine_id, payload.get("target_version"))


@app.post("/api/versions/{engine_id}/rollback")
async def versions_rollback(engine_id: str, payload: dict):
    """真实 git 回退指定版本实例到旧版本。"""
    return version_manager.rollback_version(engine_id, payload.get("to_version", ""))


@app.post("/api/versions/preview-switch")
async def versions_preview_switch(payload: dict):
    """切换前预览：venv 策略 + 配置文件迁移差异（供二次确认）。"""
    return version_manager.preview_switch(payload.get("engine_id", ""))


@app.post("/api/versions/takeover")
async def versions_takeover(payload: dict):
    """接管外部 ZIP：备份用户数据 → 安装最新版 → 记录 → 由 Atelier 管理更新。"""
    return version_manager.takeover_external(payload.get("engine_id", ""))


@app.post("/api/versions/managed-update")
async def versions_managed_update(payload: dict):
    """Atelier Managed 实例在线更新（下载→备份→替换→失败回滚）。"""
    return version_manager.managed_update(
        payload.get("engine_id", ""),
        payload.get("target"),
    )


@app.get("/api/versions/{engine_id}/managed-candidates")
async def versions_managed_candidates(engine_id: str):
    """Atelier Managed 实例的新旧版本候选（选择式更新/回退）。"""
    return version_manager.managed_candidates(engine_id)


@app.get("/api/versions/{engine_id}/git-candidates")
async def versions_git_candidates(engine_id: str):
    """git（clone 版）实例的更新/回退候选：更新=分支最新 commit；回退=正式 tag + previous。"""
    return version_manager.git_candidates(engine_id)


@app.post("/api/versions/{engine_id}/bind")
async def versions_bind_external(engine_id: str, payload: dict):
    """外部 ZIP 实例手动绑定版本身份（commit/tag 由用户提供，仅作展示）。"""
    return version_manager.bind_external(
        engine_id,
        commit=payload.get("commit", ""),
        tag=payload.get("tag", ""),
        branch=payload.get("branch", ""),
    )


@app.post("/api/versions/{engine_id}/env-install")
async def versions_env_install(engine_id: str):
    """对实例执行环境安装/修复（venv + PyTorch + 依赖 + CLIP 修复，走国内镜像）。"""
    return version_manager.env_install(engine_id)


@app.get("/api/versions/{engine_id}/env-check")
async def versions_env_check(engine_id: str):
    """检查实例环境状态（venv / PyTorch / skimage / numpy 对齐）。"""
    return version_manager.env_check(engine_id)


@app.post("/api/update/download")
async def update_download(payload: dict = None):
    """下载最新版 FTN Atelier 更新包（GitHub Release 资产 zip，后台任务）。
    可传入最近一次检测的 asset_url / expected_version 复用结果，避免重复请求 GitHub。"""
    payload = payload or {}
    return version_manager.update_download(
        asset_url=payload.get("asset_url"),
        expected_version=payload.get("expected_version"),
        asset_size=payload.get("asset_size") or 0,
        asset_sha256=payload.get("asset_sha256") or "",
    )


@app.get("/api/versions/{base_key}/venv-strategy")
async def versions_venv_strategy(base_key: str, target: str = None):
    """某基底的环境策略：复用共享 venv 或重建（venv 共享）。"""
    return version_manager.venv_strategy(base_key, target)


# ============================================
# 基底管理（多基底 / 主基底切换 / 版本下载）
# ============================================
@app.get("/api/bases")
async def bases_snapshot():
    """返回基底定义 + 当前主基底。"""
    return {
        "defs": base_registry.defs(),
        "labels": base_registry.labels(),
        "primary": base_registry.primary(),
        "health": base_registry.primary_health(engine_registry.list_engines()),
    }


@app.post("/api/bases/primary")
async def bases_set_primary(payload: dict):
    return base_registry.set_primary(payload.get("base"))


@app.get("/api/bases/{base_key}/download")
async def bases_download_info(base_key: str):
    return version_manager.download_info(base_key)


@app.get("/api/bases/{base_key}/candidates")
async def bases_download_candidates(base_key: str):
    """某基底的可下载候选稳定版本列表（GitHub 实时拉取 + 本机已装垫底）。"""
    defb = base_registry.get(base_key)
    if not defb:
        return {"ok": False, "msg": f"未知基底: {base_key}"}
    cands = version_manager.download_candidates(base_key, limit=6)
    return {
        "ok": True,
        "base": base_key,
        "label": cands.get("label", base_key),
        "desc": defb.get("desc", ""),
        "repo": cands.get("repo", ""),
        "note": version_manager.download_info(base_key).get("note", ""),
        "fetched": cands.get("fetched", False),
        "fetch_error": cands.get("fetch_error"),
        "versions": cands.get("versions", []),
    }


# ============================================
# 主引擎（主基底）健康告警（首页引擎名旁）
# ============================================
@app.get("/api/engine/primary-health")
async def engine_primary_health():
    return base_registry.primary_health(engine_registry.list_engines())


# ============================================
# 启动自检 / 修复 / 版本更新检测
# ============================================
@app.get("/api/selfcheck/run")
async def selfcheck_run():
    """启动前自检。返回每项状态 status:ok|warn|error + 是否可修复。"""
    return {"os": platform.system(), "app_version": FTN_APP_VERSION, **selfcheck_manager.run()}


@app.post("/api/selfcheck/fix")
async def selfcheck_fix(payload: dict):
    """尝试修复指定自检项（key）。"""
    key = (payload or {}).get("key", "")
    res = selfcheck_manager.fix(key)
    return {"key": key, "ok": res.get("ok"), "msg": res.get("msg"), "ok_after": selfcheck_manager.run()}


@app.post("/api/selfcheck/start")
async def selfcheck_start():
    """异步自检：后台逐项执行，返回 task_id（前端轮询状态让进度条逐步推进）。"""
    return {"ok": True, "task_id": selfcheck_manager.start_async()}


@app.get("/api/selfcheck/status/{task_id}")
async def selfcheck_status(task_id: str):
    return selfcheck_manager.status(task_id)


@app.get("/api/selfcheck/update")
async def selfcheck_update():
    """检测 FTN Atelier 是否有新版本。"""
    res = selfcheck_manager.check_update()
    return res


# ============================================
# 网络下载（CivitAI / HuggingFace 搜索 + 下载）
# ============================================
@app.get("/api/downloads/sources")
async def downloads_sources():
    """返回各下载来源是否已配置凭据。"""
    return downloads_manager.sources()


@app.get("/api/downloads/civitai/search")
async def downloads_civitai_search(query: str = "", type: str = "", limit: int = 24):
    """CivitAI 模型搜索。"""
    return downloads_manager.civitai_search(query=query, mtype=type, limit=limit)


@app.get("/api/downloads/hf/search")
async def downloads_hf_search(query: str = "", limit: int = 24):
    """HuggingFace 模型库搜索。"""
    return downloads_manager.hf_search(query=query, limit=limit)


@app.get("/api/downloads/hf/files")
async def downloads_hf_files(repo: str = ""):
    """列出某 HF 模型库 main 分支文件。"""
    return downloads_manager.hf_files(repo=repo)


@app.post("/api/downloads/start")
async def downloads_start(payload: dict):
    """启动后台下载任务，写落到主引擎对应分类目录并重新索引。"""
    if not _plugins_supported():
        return {"ok": False, "msg": "当前主引擎类型不受支持（仅支持启动/停止/重启），模型下载不适用"}
    return downloads_manager.start(
        source=payload.get("source", ""),
        url=payload.get("url", ""),
        filename=payload.get("filename", ""),
        model_type=payload.get("type", "checkpoint"),
    )


@app.get("/api/downloads/status/{task_id}")
async def downloads_status(task_id: str):
    return downloads_manager.status(task_id)


# ============================================
# 首页快捷文件夹（跟随主引擎根目录 + 自定义覆盖）
# ============================================
@app.get("/api/quickfolders")
async def quick_folders():
    return config_manager.quick_folders(engine_registry)


@app.put("/api/quickfolders")
async def quick_folders_update(payload: dict):
    """更新首页快捷文件夹配置（改名 / 重新指定路径）。"""
    folders = payload.get("folders")
    if not folders or not isinstance(folders, list):
        return {"ok": False, "msg": "参数错误"}
    conf = config_manager.load()
    conf.home_folders = folders
    config_manager.save(conf)
    return {"ok": True, **config_manager.quick_folders(engine_registry)}


# ============================================
# 插件管理（当前实例 extensions）
# ============================================
def _plugins_supported():
    """主引擎家族不受支持（非 reforge/forge 且已配置路径）→ 插件功能不适用。"""
    from core.engine_registry import engine_registry
    fam = engine_registry.primary_family()
    return not fam or fam in ("reforge", "forge")


_PLUGIN_NOT_SUPPORTED_NOTE = "当前主引擎类型不受支持（仅支持启动/停止/重启），插件管理不适用"


@app.get("/api/plugins")
async def plugins_list():
    if not _plugins_supported():
        return {"demo": False, "plugs": [], "extensions_dir": "",
                "not_supported": True, "note": _PLUGIN_NOT_SUPPORTED_NOTE}
    return version_manager.plugins()


@app.post("/api/plugins/{key}/enabled")
async def plugins_set_enabled(key: str, payload: dict):
    return version_manager.plugin_set_enabled(key, bool(payload.get("enabled")))


# ---- 插件市场（内置库 + 比对） ----
@app.get("/api/plugins/market")
async def plugins_market(query: str = None, group: str = None, base_filter: str = None):
    if not _plugins_supported():
        return {"demo": False, "no_engine": True, "groups": ["全部"], "items": [],
                "not_supported": True, "note": _PLUGIN_NOT_SUPPORTED_NOTE}
    return version_manager.plugin_market(
        query=query or "", group=group or "", base_filter=base_filter or "",
    )


@app.post("/api/plugins/install")
async def plugins_install(payload: dict):
    if not _plugins_supported():
        return {"ok": False, "msg": _PLUGIN_NOT_SUPPORTED_NOTE}
    return version_manager.plugin_install(
        repo_url=payload.get("repo_url", ""), key=payload.get("key"),
    )


@app.post("/api/plugins/update")
async def plugins_update(payload: dict):
    if not _plugins_supported():
        return {"ok": False, "msg": _PLUGIN_NOT_SUPPORTED_NOTE}
    return version_manager.plugin_update(payload.get("key", ""))


@app.post("/api/plugins/uninstall")
async def plugins_uninstall(payload: dict):
    if not _plugins_supported():
        return {"ok": False, "msg": _PLUGIN_NOT_SUPPORTED_NOTE}
    return version_manager.plugin_uninstall(payload.get("key", ""))


@app.post("/api/plugins/url-install")
async def plugins_url_install(payload: dict):
    if not _plugins_supported():
        return {"ok": False, "msg": _PLUGIN_NOT_SUPPORTED_NOTE}
    return version_manager.plugin_url_install(
        repo_url=payload.get("repo_url", ""), key=payload.get("key"),
    )


@app.post("/api/plugins/update-all")
async def plugins_update_all():
    """一键更新全部已装插件（后台任务 + 进度轮询）。"""
    if not _plugins_supported():
        return {"ok": False, "msg": _PLUGIN_NOT_SUPPORTED_NOTE}
    return version_manager.plugin_update_all()


@app.get("/api/plugins/task/{task_id}")
async def plugins_task_status(task_id: str):
    return version_manager.task_status(task_id)


# ============================================
# 数据迁移（配置 / 引擎注册 / 模型索引 导出导入）
# ============================================
@app.get("/api/data/export")
async def data_export():
    """导出：配置 + 引擎注册 + 模型索引（换机迁移用）。"""
    try:
        cfg = config_manager.load().model_dump()
        # 导出不携带凭据（防分享泄露）
        cfg["api_keys"] = {"civitai_api_key": "", "huggingface_token": ""}
        custom = db.get_meta("engine_custom", None) or {}
        models = db.query("SELECT * FROM models") or []
        return {"ok": True, "data": {"config": cfg, "engine_custom": custom, "models": models}}
    except Exception as e:
        return {"ok": False, "msg": f"导出失败：{e}"}


@app.post("/api/data/import")
async def data_import(payload: dict):
    """导入并覆盖：配置 / 引擎注册 / 模型索引。"""
    data = payload.get("data") or payload
    imported = []
    try:
        if data.get("config"):
            from core.models.app_config import AppConfig
            config_manager.save(AppConfig.model_validate(data["config"]))
            imported.append("配置")
        if data.get("engine_custom"):
            db.set_meta("engine_custom", data["engine_custom"])
            imported.append("引擎注册")
        if isinstance(data.get("models"), list):
            models = data["models"]
            db.execute("DELETE FROM models")
            for row in models:
                db.upsert_model(row)
            if models:
                imported.append(f"模型索引 {len(models)} 条")
        if not imported:
            return {"ok": False, "msg": "导入数据中无可用内容"}
        log_manager.info("backend", "已导入数据：" + "、".join(imported))
        return {"ok": True, "msg": "已导入：" + "、".join(imported)}
    except Exception as e:
        return {"ok": False, "msg": f"导入失败：{e}"}


# ============================================
# 引擎注册表 (可编辑引擎)
# ============================================
@app.get("/api/engines")
async def engines_list():
    return engine_registry.list_engines()


@app.get("/api/changelog")
async def changelog():
    """版本更新日志（随包分发，Source/backend/更新说明.md）。"""
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "更新说明.md")
        with open(p, "r", encoding="utf-8") as f:
            return {"ok": True, "content": f.read()}
    except Exception as e:
        return {"ok": False, "content": "", "error": str(e)}


@app.post("/api/engines")
async def engines_add(payload: dict):
    return engine_registry.add_engine(
        key=payload.get("key"), label=payload.get("label", ""),
        kind=payload.get("kind", "webui"),
        desc=payload.get("desc", ""), root=payload.get("root", ""),
    )


@app.post("/api/engines/detect")
async def engines_detect(payload: dict):
    """新增引擎自动识别：选目录或启动文件 → 返回类型/入口/家族。"""
    return engine_registry.detect_engine(
        root=payload.get("root") or "",
        entry=payload.get("entry") or "",
    )


@app.delete("/api/engines/{key}")
async def engines_remove(key: str):
    return engine_registry.remove_engine(key)


@app.post("/api/engines/{key}/rename")
async def engines_rename(key: str, payload: dict):
    return engine_registry.rename_engine(key, payload.get("label", ""))


@app.post("/api/engines/{key}/path")
async def engines_set_path(key: str, payload: dict):
    return engine_registry.set_path(key, payload.get("root", ""))


@app.post("/api/engines/{key}/path/clear")
async def engines_clear_path(key: str):
    return engine_registry.clear_path(key)


@app.post("/api/engines/{key}/primary")
async def engines_set_primary(key: str):
    return engine_registry.set_primary(key)


@app.post("/api/engines/{key}/entry")
async def engines_set_entry(key: str, payload: dict):
    return engine_registry.set_entry(key, payload.get("entry", ""))


@app.post("/api/engines/{key}/entry/redetect")
async def engines_re_detect_entry(key: str):
    return engine_registry.re_detect_entry(key)


@app.post("/api/engines/{key}/multi")
async def engines_set_multi(key: str, enabled: bool = False):
    return engine_registry.set_multi(key, enabled)


# ============================================
# 输出目录自动整理（不分日期）
# ============================================
@app.get("/api/outputs/auto-organize")
async def outputs_auto_organize():
    """查询输出目录自动整理开关状态。"""
    conf = config_manager.load()
    return {"enabled": conf.output_auto_organize}


@app.post("/api/outputs/auto-organize")
async def outputs_set_auto_organize(payload: dict):
    """开/关输出目录自动整理。开启时启动后台线程，关闭时停止。"""
    enabled = bool((payload or {}).get("enabled"))
    conf = config_manager.load()
    conf.output_auto_organize = enabled
    config_manager.save(conf)
    if enabled:
        output_watcher.start()
    else:
        output_watcher.stop()
    log_manager.info("backend", f"输出目录自动整理已{'开启' if enabled else '关闭'}")
    return {"ok": True, "enabled": enabled}


@app.post("/api/outputs/organize-now")
async def outputs_organize_now():
    """立即整理一次（不依赖定时轮询）。"""
    return {"ok": True, "result": output_watcher.organize_once()}


# ============================================
# 优雅关闭（供 Electron 调用）
# ============================================
@app.get("/api/shutdown")
async def shutdown():
    log_manager.info("backend", "收到关闭指令，开始优雅退出")
    # 先停止全部引擎实例（主实例 + 多开），再清理控制台会话
    try:
        eng_result = runner.stop_all()
        log_manager.info("backend", f"已停止引擎实例 {eng_result.get('stopped_count', 0)} 个")
    except Exception as e:
        log_manager.warn("backend", f"停止引擎实例失败: {e}")
    # 延迟触发退出，确保响应先返回
    async def _do_exit():
        await asyncio.sleep(0.3)
        os._exit(0)

    asyncio.create_task(_do_exit())
    return {"status": "shutting_down"}


# ============================================
# WebSocket：实时日志 / 状态 / 进度 / 通知
# ============================================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await status_manager.register(websocket)
    log_manager.info("backend", "WebSocket 客户端已连接")

    # 订阅后端日志，实时推送给该客户端（收尾处主动取消订阅）
    # 每连接待发上限：会话日志可能大量刷屏，超限丢弃防止拖垮事件循环
    _push_pending = {"n": 0}

    async def _push_log(record: dict):
        try:
            await websocket.send_json({"type": "log", "record": record})
        except Exception:
            pass
        finally:
            _push_pending["n"] -= 1

    # 同步桥：log_manager 的回调是同步调用，这里把协程调度回主事件循环执行，
    # 否则协程从未被 await，实时日志推送不会真正发出。
    def _push_log_sync(record: dict):
        if _MAIN_LOOP is None:
            return
        if _push_pending["n"] >= 3000:
            return
        _push_pending["n"] += 1
        _MAIN_LOOP.call_soon_threadsafe(
            lambda: asyncio.ensure_future(_push_log(record))
        )

    log_manager.subscribe(_push_log_sync)

    try:
        # 发送欢迎/订阅确认
        await websocket.send_json({"type": "subscribed", "service": "ftn-studio"})
        while True:
            # 心跳检测，同时接收客户端消息（可扩展为控制命令）
            data = await websocket.receive_text()
            # M0 阶段：仅记录收到的消息，后续扩展为命令分发
            if data:
                await status_manager.push({"type": "echo", "data": data})
    except WebSocketDisconnect:
        await status_manager.unregister(websocket)
        log_manager.info("backend", "WebSocket 客户端已断开")
    except Exception:
        await status_manager.unregister(websocket)
    finally:
        # 释放日志订阅，避免重复/泄漏
        log_manager.unsubscribe(_push_log_sync)


if __name__ == "__main__":
    port = int(os.environ.get("FTN_BACKEND_PORT", "19000"))
    host = os.environ.get("FTN_BACKEND_HOST", "127.0.0.1")
    # 若存在宿主(Electron)PID，启动宿主存活监控，异常退出时后端自清理
    watchdog.start()
    # 输出目录自动整理（配置开启时才起线程）
    output_watcher.start()
    log_manager.info("backend", f"FTN Studio 后端启动中，监听 {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
