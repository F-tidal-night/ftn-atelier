# ============================================
# FTN Studio 输出目录自动整理（方案B：监听/迁移）
#
# 需求：输出「不分日期」——取消 reForge 默认的日期子目录，
#       生成图直接落在 outputs/<mode>-images/ 根。
#
# 约束：不修改 reForge 源码 → reForge 没有「关掉日期目录」的启动参数，
#       因此采用「监听 + 迁移」方案：
#         1. 监听主引擎 outputs/ 下的 <mode>-images/<日期> 子目录
#         2. 把新增图片 move 到对应 <mode>-images/ 根
#         3. 迁移后删除空日期目录
#
# 仅追踪图片类文件（.png/.jpg/.jpeg/.webp/.gif），不移动目录/配置。
# 后台线程轮询（默认 3s），优雅中线程可安全停止。
# ============================================

import os
import time
import shutil
import threading

from core.log_manager import log_manager

# 需要整理的输出模式目录（reForge 约定；以「-images」结尾）
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
# 合法日期子目录名（仅当子目录名是 8 位数字「20260829」形态才整理，避免误动）
_POLL_INTERVAL = 3.0


def _is_date_dir(name):
    """判断是否为日期子目录：纯 8 位数字（yyyyMMdd）。"""
    return len(name) == 8 and name.isdigit()


class OutputWatcher:
    """后台线程：扫描并整理 outputs 输出目录（把日期子目录内容上提）。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self._thread = None
        self._stop = threading.Event()
        self.running = False
        self._last_organize = None

    # ---------- 生命周期 ----------
    def start(self):
        """启动后台整理线程（仅当配置开启自动整理时）。"""
        if self.running:
            return
        from core.config_manager import config_manager
        if not config_manager.load().output_auto_organize:
            return
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(
            target=self._loop, name="output-watcher", daemon=True
        )
        self._thread.start()
        log_manager.info("backend", "输出目录自动整理已启动（不分日期：日期子目录自动上提）")

    def stop(self):
        self._stop.set()
        self.running = False

    # ---------- 主循环 ----------
    def _loop(self):
        while not self._stop.is_set():
            self.organize_once()
            self._stop.wait(_POLL_INTERVAL)

    # ---------- 核心整理逻辑 ----------
    def _output_roots(self):
        """返回 [(mode_images_dir, engine_label)]，基于主引擎根目录。"""
        roots = []
        from core.base_registry import base_registry
        from core.engine_registry import engine_registry
        from core.config_manager import config_manager
        try:
            engines = engine_registry.list_engines()
            primary_base = base_registry.primary()
            primary = next((e for e in engines if e.get("key") == primary_base), None)
            if primary is None:
                primary = next((e for e in engines if e.get("primary")), None)
            root = (primary or {}).get("root", "") or ""
            if not root or not os.path.isdir(root):
                return roots
            outputs_dir = os.path.join(root, "outputs")
            if not os.path.isdir(outputs_dir):
                return roots
            # 收集所有 <mode>-images 目录
            for entry in os.listdir(outputs_dir):
                full = os.path.join(outputs_dir, entry)
                if os.path.isdir(full) and entry.endswith("-images"):
                    roots.append((full, entry))
            return roots
        except Exception:
            return roots

    def organize_once(self):
        """执行一次整理：把各 <mode>-images/<日期> 的内容上提到根，删空日期目录。

        返回本次迁移统计（供手动触发接口展示）。
        """
        moved, removed, skipped = [], [], []
        for mode_dir, mode in self._output_roots():
            if self._stop.is_set():
                break
            try:
                for entry in os.listdir(mode_dir):
                    sub = os.path.join(mode_dir, entry)
                    if not (os.path.isdir(sub) and _is_date_dir(entry)):
                        continue
                    # 遍历日期目录内的图片，逐个 move 到 mode 根
                    for fn in os.listdir(sub):
                        src = os.path.join(sub, fn)
                        if not (os.path.isfile(src) and fn.lower().endswith(_IMAGE_EXTS)):
                            continue
                        dst = os.path.join(mode_dir, fn)
                        dst = self._dedupe(dst)
                        try:
                            shutil.move(src, dst)
                            moved.append({"from": src, "to": dst})
                        except Exception as e:
                            skipped.append({"file": fn, "error": str(e)})
                    # 日期目录内已空则删除
                    try:
                        if not os.listdir(sub):
                            os.rmdir(sub)
                            removed.append(sub)
                    except Exception:
                        pass
            except Exception:
                pass
        if moved:
            self._last_organize = time.time()
            log_manager.info(
                "backend",
                f"输出目录自动整理：迁移 {len(moved)} 个文件，删除 {len(removed)} 个空日期目录",
            )
        return {"moved": moved, "removed": removed, "skipped": skipped}

    @staticmethod
    def _dedupe(dst):
        """同名冲突追加序号。"""
        if not os.path.exists(dst):
            return dst
        stem, ext = os.path.splitext(dst)
        n = 1
        new = f"{stem} ({n}){ext}"
        while os.path.exists(new):
            n += 1
            new = f"{stem} ({n}){ext}"
        return new


# 单例
output_watcher = OutputWatcher()
