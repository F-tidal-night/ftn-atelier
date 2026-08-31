# ============================================
# FTN Studio 引擎启动失败诊断
#
# 从引擎运行日志中匹配常见失败模式（端口占用 / 缺依赖 / OOM / 显卡驱动 /
# Python 缺失 / venv 缺失），给出可直接照做的修复指引。
# ============================================

import re

# (识别名, 正则, 修复建议)
DIAG_PATTERNS = [
    (
        "端口占用",
        r"address already in use|Address already in use|error while attempting to bind"
        r"|WinError 10048|Failed to listen|socket\.bind|Requested port|in use|taken",
        "目标端口被占用。程序会自动改空闲端口；若仍失败，请到「设置→启动参数」更换端口，"
        "或关闭占用该端口的程序（多开时按首页显示的端口判断）。",
    ),
    (
        "缺少依赖",
        r"ModuleNotFoundError|No module named|ImportError|ModuleNotFound",
        "缺少 Python 依赖。打包版请运行「重建运行时.bat」；源码版请执行 "
        "pip install -r Source\\backend\\requirements.txt，并确认主引擎 venv 完整。",
    ),
    (
        "显存/内存不足",
        r"CUDA out of memory|OutOfMemoryError|MemoryError|Killed|out of memory",
        "显存/内存不足。请降低分辨率或换小模型，或在「设置→启动参数」选择低显存模式 / CPU 模式。",
    ),
    (
        "显卡驱动/CUDA",
        r"No CUDA GPUs are available|CUDA driver version is insufficient|NVIDIA-SMI has failed"
        r"|torch\.cuda|CUDA driver",
        "未检测到可用 CUDA GPU 或驱动版本不匹配。请更新 NVIDIA 驱动；"
        "或到「设置→启动参数」勾选 CPU 模式（出图会慢）。",
    ),
    (
        "Python 解释器缺失",
        r"python\.exe[^\n]*(?:not found|No such file)|Error spawning|Failed to execute"
        r"|Cannot find Python",
        "未找到 Python 解释器。打包版应自带 runtime；源码运行请确认系统已安装 Python 3.10+ 并加入 PATH。",
    ),
    (
        "venv/实例损坏",
        r"venv[^\n]*(?:missing|not found)|No such file or directory[^\n]*python"
        r"|fatal: not a git repository",
        "主引擎虚拟环境缺失或版本实例损坏。请到「版本」页重新下载或修复该基底实例。",
    ),
]


def diagnose_log(text):
    """匹配日志文本，返回 [{key, title, suggestion}]（去重，最多 3 条）。"""
    if not text:
        return []
    hits = []
    for title, pattern, suggestion in DIAG_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            hits.append({"key": title, "title": title, "suggestion": suggestion})
    # 去重（按标题）
    seen, out = set(), []
    for h in hits:
        if h["key"] not in seen:
            seen.add(h["key"])
            out.append(h)
    return out[:3]


def diagnose_log_file(path, tail_bytes=200 * 1024):
    """读取日志文件末尾一段并诊断。"""
    try:
        with open(path, "rb") as f:
            size = f.seek(0, 2)
            f.seek(max(0, size - tail_bytes))
            raw = f.read()
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                return diagnose_log(raw.decode(enc))
            except (UnicodeDecodeError, LookupError):
                continue
    except Exception:
        pass
    return []
