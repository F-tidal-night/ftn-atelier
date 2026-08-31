# ============================================
# FTN Studio 应用数据根目录（统一入口）
#
# 开发/便携运行：以源码目录为根（Logs/Database/Data/Core/Backup 同在源码根）。
# 打包运行：Electron 主进程注入 FTN_APP_DIR（%APPDATA%/FTN Atelier），
# 数据写入用户目录，避免写进 Program Files 等只读位置。
# ============================================

import os


def app_root():
    """返回应用数据根目录。优先取环境变量 FTN_APP_DIR，否则用源码目录。"""
    env = (os.environ.get("FTN_APP_DIR") or "").strip()
    if env and os.path.isabs(env):
        return env
    return os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
    )


def ensure_app_dirs():
    """启动时补齐标准数据目录（Core/Engines、Data、Backup、Logs、Database）。"""
    root = app_root()
    for rel in ["Core", os.path.join("Core", "Engines"), "Data", "Backup", "Logs", "Database"]:
        try:
            os.makedirs(os.path.join(root, rel), exist_ok=True)
        except Exception:
            pass
    return root
