# ============================================
# Update Engine · Verifier（下载完成后的完整性校验）
#
# 校验顺序：文件大小 → ZIP 可打开 → 内含 FTN Atelier.exe → SHA-256（若 Release 提供）
# 未通过校验绝对不允许进入安装阶段。
# ============================================

import hashlib
import os
import zipfile

from core.update.models import VerifyResult


def _contains_exe(zip_path):
    """ZIP 顶层（或任意层级）是否含 FTN Atelier.exe。"""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
        return any(os.path.basename(n).lower() == "ftn atelier.exe" for n in names)
    except Exception:
        return False


def verify(task, part_path=None):
    """校验已下载文件（.part 或已 rename 的 .zip）。task: DownloadTask。"""
    path = part_path or task.part_path or task.dest_zip
    result = VerifyResult(expected_size=task.asset_size or 0)
    if not path or not os.path.isfile(path):
        result.reason = "文件不存在"
        return result
    result.actual_size = os.path.getsize(path)
    if task.asset_size and result.actual_size != task.asset_size:
        result.reason = f"大小不匹配：期望 {task.asset_size}，实际 {result.actual_size}"
        return result
    result.size_ok = True

    try:
        with zipfile.ZipFile(path, "r") as zf:
            if zf.testzip() is not None:
                result.reason = "ZIP 内容损坏（CRC 校验失败）"
                return result
        result.zip_ok = True
    except Exception as e:
        result.reason = f"ZIP 无法打开：{e}"
        return result

    if not _contains_exe(path):
        result.reason = "更新包缺少 FTN Atelier.exe"
        return result
    result.exe_ok = True

    if task.asset_sha256:
        try:
            # 兼容 "sha256:<hex>" 前缀（GitHub digest 格式）与纯 hex
            expected = str(task.asset_sha256).strip().lower()
            if expected.startswith("sha256:"):
                expected = expected[len("sha256:"):].strip()
            h = hashlib.sha256()
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
            result.sha_ok = h.hexdigest().lower() == expected
            if not result.sha_ok:
                result.reason = "SHA-256 不匹配"
                return result
        except Exception as e:
            result.reason = f"SHA-256 校验失败：{e}"
            return result
    else:
        result.sha_ok = True  # Release 未提供 SHA-256 → 跳过

    result.ok = True
    result.reason = "校验通过"
    return result
