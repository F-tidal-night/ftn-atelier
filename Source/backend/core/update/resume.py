# ============================================
# Update Engine · Resume（断点续传 / 崩溃恢复）
#
# 规则：
#   - 只认 Data/updates/FTN-Atelier-{version}.zip.part（文件名版本一致）
#   - 必须同时有 .part.meta.json，且 version / asset_url / asset_size 与本次任务一致
#   - 文件状态有效（大小 >= 0 且 <= asset_size）才允许续传
#   - 程序崩溃 / 断网 / 重启后再次进入更新流程时自动接管
# ============================================

import json
import os
import shutil


def find_resume(updates_dir, task):
    """查找可续传的 .part。返回 (part_path, start_byte) 或 (None, 0)。
    task: DownloadTask（version / asset_url / asset_size / part_path）。"""
    if not task.part_path or not os.path.isfile(task.part_path):
        return None, 0
    meta_path = task.part_path + ".meta.json"
    if not os.path.isfile(meta_path):
        return None, 0
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return None, 0
    # 版本与资源一致才续传
    if str(meta.get("version") or "") != str(task.version or ""):
        return None, 0
    if str(meta.get("asset_url") or "") != str(task.asset_url or ""):
        return None, 0
    if task.asset_size and meta.get("asset_size") not in (None, task.asset_size):
        return None, 0
    size = os.path.getsize(task.part_path)
    if size < 0 or (task.asset_size and size > task.asset_size):
        return None, 0
    return task.part_path, size


def cleanup_stale(updates_dir, keep_version=None):
    """清理与当前任务无关的旧 .part / .meta（保留目标版本；失败不影响）。兼容旧调用。"""
    try:
        for n in os.listdir(updates_dir or ""):
            if not n.endswith(".part") and not n.endswith(".part.meta.json"):
                continue
            keep = bool(keep_version) and f"-{keep_version}.zip.part" in n
            if not keep:
                try:
                    os.remove(os.path.join(updates_dir, n))
                except OSError:
                    pass
    except Exception:
        pass


def cleanup_updates_dir(updates_dir, keep_version=None, keep_backups=3, keep_scripts=2, max_log_bytes=2 * 1024 * 1024):
    """Data/updates 目录自动清理，避免安装包/临时文件越积越多。

    规则：
      - 保留「当前目标版本」的 .zip / .part / .part.meta.json（断点续传 + 失败重试的基础）；
      - 清理其它历史版本的 .zip / .part / meta；
      - apply-*.ps1 保留最近 keep_scripts 个（诊断用）；
      - pending.json 保留最近 1 个（每次更新会覆盖写入）；
      - backup-* 保留最近 keep_backups 个（程序文件备份；Core/Data/Database/Logs 从不在此目录内，不受影响）；
      - updater-electron.log 超过 max_log_bytes 时重置（日志是追加写入，防止无限增长）。
    """
    try:
        entries = os.listdir(updates_dir or "")
    except Exception:
        return

    def _safe_remove(p, is_dir=False):
        try:
            if is_dir:
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
        except OSError:
            pass

    keep_ver = f"-{keep_version}.zip" if keep_version else None

    def _is_keep_package(n):
        if not keep_ver:
            return False
        return n == f"FTN-Atelier{keep_ver}" or n == f"FTN-Atelier{keep_ver}.part" or n == f"FTN-Atelier{keep_ver}.part.meta.json"

    # 1) 历史版本安装包 / 断点文件
    for n in entries:
        if n.endswith(".zip") or n.endswith(".part") or n.endswith(".part.meta.json"):
            if not _is_keep_package(n):
                _safe_remove(os.path.join(updates_dir, n))

    # 2) apply-*.ps1 保留最近 keep_scripts
    scripts = sorted(
        (n for n in os.listdir(updates_dir) if n.startswith("apply-") and n.endswith(".ps1")),
        key=lambda x: os.path.getmtime(os.path.join(updates_dir, x)),
    )
    for n in scripts[:-keep_scripts] if keep_scripts else scripts:
        _safe_remove(os.path.join(updates_dir, n))

    # 3) pending.json 保留最近 1 个（正常只有一个，防异常堆积）
    pendings = sorted(
        (n for n in os.listdir(updates_dir) if n == "pending.json"),
        key=lambda x: os.path.getmtime(os.path.join(updates_dir, x)),
    )
    for n in pendings[:-1]:
        _safe_remove(os.path.join(updates_dir, n))

    # 4) backup-* 保留最近 keep_backups（失败回滚的程序文件备份）
    backups = sorted(
        (n for n in os.listdir(updates_dir) if n.startswith("backup-")),
        key=lambda x: os.path.getmtime(os.path.join(updates_dir, x)),
    )
    for n in backups[:-keep_backups] if keep_backups else backups:
        _safe_remove(os.path.join(updates_dir, n), is_dir=True)

    # 5) 追加型日志防无限增长
    try:
        log_path = os.path.join(updates_dir, "updater-electron.log")
        if os.path.isfile(log_path) and os.path.getsize(log_path) > max_log_bytes:
            os.remove(log_path)
    except OSError:
        pass
