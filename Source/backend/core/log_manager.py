# ============================================
# FTN Studio 统一日志系统 (LogManager)
#
# 职责：
# - 管理 reForge / Python后台 / 更新 / 错误日志
# - Windows 环境统一 UTF-8
# - 支持 GBK / ANSI / UTF-8 编码处理
# - 日志显示：时间、来源、等级、内容
# ============================================

import os
import sys
import time
import threading
from datetime import datetime

from core.paths import app_root

# 项目根目录（FTN Studio 根）
PROJECT_ROOT = app_root()
LOG_DIR = os.path.join(PROJECT_ROOT, "Logs")

# 日志等级常量
LEVELS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARN": 30,
    "ERROR": 40,
    "FATAL": 50,
}

_LEVEL_ORDER = {v: k for k, v in LEVELS.items()}


class LogManager:
    """统一日志管理器（线程安全）"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        self._log_lock = threading.Lock()
        self._level = "INFO"
        # 内存环形缓冲：供近期日志实时推送 / 疑难解答概括
        self._ring = []
        self._ring_max = 500
        self._file_handlers = {}
        # 监听日志回调（供 WebSocket 推送）
        self._listeners = []

    # ---------- 编码处理 ----------
    @staticmethod
    def _normalize_to_utf8(text: bytes) -> str:
        """将字节流尝试解码为 UTF-8，失败时降级为 GBK/ANSI。"""
        if isinstance(text, str):
            return text
        for enc in ("utf-8", "gbk", "ansi", "latin-1"):
            try:
                return text.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return text.decode("utf-8", errors="replace")

    # ---------- 写文件 ----------
    LOG_MAX_FILES = 30  # 每个 category 保留的最大日志文件数（超出自动删旧）

    def _prune_old_files(self, category: str):
        """保留每个日志类别最近的 LOG_MAX_FILES 个文件，删除更旧的。"""
        try:
            prefix = f"{category}."
            files = [
                f for f in os.listdir(LOG_DIR)
                if f.startswith(prefix) and f.endswith(".log")
            ]
            if len(files) <= self.LOG_MAX_FILES:
                return
            # 按日期排序（文件名含 YYYYMMDD），删最旧的
            files.sort()
            for old in files[:-self.LOG_MAX_FILES]:
                try:
                    os.remove(os.path.join(LOG_DIR, old))
                except Exception:
                    pass
        except Exception:
            pass

    def _get_file_handler(self, category: str):
        """按类别返回对应的日志文件句柄（按天分文件）。

        单条日志文件上限 FILE_MAX_SIZE（20MB），超限时静默截断（仅保留末尾，规避超量文件）。
        """
        today = datetime.now().strftime("%Y%m%d")
        key = f"{category}_{today}"
        if key not in self._file_handlers:
            fpath = os.path.join(LOG_DIR, f"{category}.{today}.log")
            fh = open(fpath, "a", encoding="utf-8")
            self._file_handlers[key] = fh
            self._prune_old_files(category)
        # 超量校验：超过 FILE_MAX_SIZE 则截断为末尾保留量（静默，不报错）
        try:
            size = os.path.getsize(os.path.join(LOG_DIR, f"{category}.{today}.log"))
            if size > self.FILE_MAX_SIZE:
                with self._log_lock:
                    self._truncate_large_file(category, today)
        except Exception:
            pass
        return self._file_handlers[key]

    # 单条日志文件上限 20MB；超限保留末尾 5MB（避免导出/读取超量）
    FILE_MAX_SIZE = 20 * 1024 * 1024
    FILE_KEEP_BYTES = 5 * 1024 * 1024

    def _truncate_large_file(self, category: str, today: str):
        """静默截断超大日志：仅保留文件末尾一段字节（以换行为界）。"""
        fpath = os.path.join(LOG_DIR, f"{category}.{today}.log")
        try:
            with open(fpath, "rb") as f:
                f.seek(-min(self.FILE_KEEP_BYTES, os.path.getsize(fpath)), os.SEEK_END)
                tail = f.read()
            # 以首个换行为界去除可能截断的半行
            nl = tail.find(b"\n")
            if nl != -1:
                tail = tail[nl + 1:]
            else:
                tail = b""
            # 重置句柄（先关再以 w 重写，避免双缓冲不一致）
            h = self._file_handlers.get(f"{category}_{today}")
            if h:
                try:
                    h.close()
                except Exception:
                    pass
            with open(fpath, "wb") as f:
                f.write(tail)
            if h:
                self._file_handlers[f"{category}_{today}"] = open(fpath, "a", encoding="utf-8")
        except Exception:
            pass

    # ---------- 日志源 / 文件查询 ----------
    def list_categories(self):
        """列出存在的日志类别（排除 backend 管理类）。"""
        cats = set()
        for f in os.listdir(LOG_DIR):
            if f.endswith(".log") and "." in f:
                cats.add(f.split(".")[0])
        return sorted(cats)

    def current_file(self, category: str):
        """返回某类别当前日志文件绝对路径。"""
        today = datetime.now().strftime("%Y%m%d")
        return os.path.join(LOG_DIR, f"{category}.{today}.log")

    @property
    def log_dir(self):
        return LOG_DIR

    # ---------- 订阅日志（WebSocket 推送） ----------
    def subscribe(self, callback):
        self._listeners.append(callback)

    def unsubscribe(self, callback):
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    # ---------- 核心记录方法 ----------
    def log(self, source: str, level: str, content: str):
        level = level.upper()
        if LEVELS.get(level, 20) < LEVELS.get(self._level, 20):
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        record = {
            "time": ts,
            "source": source,
            "level": level,
            "content": content,
        }
        line = f"[{ts}] [{level:>5}] [{source}] {content}"
        with self._log_lock:
            # 内存缓冲
            self._ring.append(record)
            if len(self._ring) > self._ring_max:
                self._ring = self._ring[-self._ring_max:]
            # 写文件
            try:
                cat = "backend" if source == "backend" else source
                self._get_file_handler(cat).write(line + "\n")
                self._get_file_handler(cat).flush()
            except Exception:
                pass
        # 推送监听器
        for cb in list(self._listeners):
            try:
                cb(record)
            except Exception:
                pass

    def debug(self, source, msg): self.log(source, "DEBUG", msg)
    def info(self, source, msg): self.log(source, "INFO", msg)
    def warn(self, source, msg): self.log(source, "WARN", msg)
    def error(self, source, msg): self.log(source, "ERROR", msg)

    # ---------- 近期日志查询 ----------
    def recent(self, limit=100, source=None, level=None):
        recs = self._ring
        if source:
            recs = [r for r in recs if r["source"] == source]
        if level:
            min_lv = LEVELS.get(level.upper(), 20)
            recs = [r for r in recs if LEVELS.get(r["level"], 20) >= min_lv]
        return recs[-limit:]

    # ---------- 疑难解答概括 ----------
    def error_summary(self, limit=20):
        errors = [r for r in self._ring if LEVELS.get(r["level"], 0) >= 30]
        return {
            "error_count": len(errors[-limit:]),
            "recent_errors": errors[-limit:],
        }

    # ---------- 疑难解答列表（至多 50 条，优先删旧与正常） ----------
    TROUBLESHOOT_MAX = 50

    def troubleshoot_logs(self):
        """返回疑难解答用日志与三档计数（正常 / 警告 / 错误）。

        返回结构：
          {
            "counts": { "normal": n, "warn": n, "error": n },
            "logs":   [ ...至多 50 条 WARN/ERROR（FATAL 并入错误）... ]
          }

        规则：
          - normal  = INFO / DEBUG（正常）
          - warn     = WARN
          - error    = ERROR + FATAL（致命并入错误档）
          - 列表只保留 WARN/ERROR/FATAL；超 50 优先删旧。
        """
        warn = [r for r in self._ring if LEVELS.get(r["level"], 0) == LEVELS["WARN"]]
        error = [r for r in self._ring if LEVELS.get(r["level"], 0) >= LEVELS["ERROR"]]
        normal = [r for r in self._ring if 0 < LEVELS.get(r["level"], 0) < LEVELS["WARN"]]
        # 附加引擎进程日志（*.run.log 尾部）——启动失败的 Traceback/ERROR 在疑难解答必须可见
        engine_rows = [r for r in self._engine_run_log_tail() if r["level"] in ("WARN", "ERROR")]
        warn = warn + [r for r in engine_rows if r["level"] == "WARN"]
        error = error + [r for r in engine_rows if r["level"] == "ERROR"]
        # 疑难列表：警告+错误（含致命），按时间排序保留最新上限条（旧优先删）
        troubles = sorted(warn + error, key=lambda r: r.get("time", ""))
        if len(troubles) > self.TROUBLESHOOT_MAX + 120:
            troubles = troubles[-(self.TROUBLESHOOT_MAX + 120):]
        # 正常日志单独返回（供三栏展示，控制条数避免过大）
        norm_sorted = sorted(normal, key=lambda r: r.get("time", ""))
        norm_out = norm_sorted[-20:] if len(norm_sorted) > 20 else norm_sorted
        return {
            "counts": {
                "normal": len(normal),
                "warn": len(warn),
                "error": len(error),
            },
            "logs": troubles,
            "normal_logs": norm_out,
            "engine_logs": len(engine_rows),
        }

    def _engine_run_log_tail(self, max_lines=30, max_files=12):
        """读取引擎进程日志（Logs/*.run.log）尾部，供疑难解答展示。"""
        rows = []
        try:
            files = [os.path.join(LOG_DIR, n) for n in os.listdir(LOG_DIR) if n.endswith(".run.log")]
            files.sort(key=os.path.getmtime, reverse=True)
            for p in files[:max_files]:
                src = os.path.basename(p)[: -len(".run.log")]
                try:
                    with open(p, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()[-max_lines:]
                except Exception:
                    continue
                for ln in lines:
                    s = ln.rstrip("\n")
                    if not s.strip():
                        continue
                    up = s.upper()
                    # ValueError / ModuleNotFoundError / Traceback / FATAL 等都要判为错误
                    if "TRACEBACK" in up or "FATAL" in up or "ERROR" in up:
                        lvl = "ERROR"
                    elif "WARN" in up:
                        lvl = "WARN"
                    else:
                        lvl = "INFO"
                    rows.append({
                        "time": "", "level": lvl,
                        "source": f"engine:{src}", "message": s[:500],
                    })
        except Exception:
            pass
        return rows

    # ---------- 关闭 ----------
    def close(self):
        for key, fh in list(self._file_handlers.items()):
            try:
                fh.close()
            except Exception:
                pass
        self._file_handlers.clear()


# 单例实例
log_manager = LogManager()
