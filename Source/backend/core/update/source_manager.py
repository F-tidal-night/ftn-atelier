# ============================================
# Update Engine · SourceManager
#
# 唯一的下载源管理者：
#   GitHub 官方直连（永远保留、兜底）
#     + 配置镜像（设置→环境配置 env.git_mirror）
#     + 内置已验证镜像（GITHUB_MIRRORS）
#   → 生成候选 URL（去重、避免双重拼接）
#   → 运行时评分（最近成功/失败/吞吐，10 分钟 TTL，重启重置，绝不永久拉黑）
#
# 镜像可用性已实测（2026-08 探测）：
#   gh-proxy.com / gh.3w.pm 对 release 资产下载返回 206 + ZIP 头 ✅
#   gh.api.99988866.xyz SSL 握手失败，未收录。
# ============================================

import threading
import time

# 内置常用 GitHub 镜像（镜像优先，按探测顺序；均可到 设置→环境配置 修改/补充）
GITHUB_MIRRORS = [
    "https://gh-proxy.com/",
    "https://gh.3w.pm/",
    "https://ghfast.top/",
    "https://mirror.ghproxy.com/",
]

_STATUS_TTL = 10 * 60  # 评分缓存有效期：10 分钟

# 运行时评分：host -> {last_success, last_failure, bps}
_STATUS = {}
_LOCK = threading.Lock()


def configured_prefix():
    """唯一的镜像前缀配置来源：设置→环境配置 env.git_mirror（use_git_mirror 开关）。
    兼容旧前缀末尾自带 https://github.com 的情况（避免双重拼接）。"""
    try:
        from core.config_manager import config_manager
        env = config_manager.load().env
        prefix = (env.git_mirror or "").strip().rstrip("/")
        if not env.use_git_mirror or not prefix:
            return ""
        if prefix.endswith("https://github.com"):
            prefix = prefix[: -len("https://github.com")].rstrip("/")
        return prefix
    except Exception:
        return ""


def _dedup(candidates):
    seen = set()
    out = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def candidates_for(url):
    """候选源列表：[配置镜像] + [内置镜像] + [官方直连兜底]（去重、官方始终保留）。"""
    if not url or not url.startswith("http"):
        return [url] if url else []
    candidates = []
    cfg = configured_prefix()
    if cfg:
        candidates.append(f"{cfg}/{url}")
    for m in GITHUB_MIRRORS:
        candidates.append(f"{m.rstrip('/')}/{url}")
    candidates.append(url)  # GitHub 官方直连兜底
    return _dedup(candidates)


# 兼容旧调用名（同一模块内别名，逻辑不重复）
url_candidates = candidates_for


def api_candidates(owner, repo):
    """GitHub Release API 候选（releases/latest）。"""
    base = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    return candidates_for(base)


def _host_of(url):
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc or ""
    except Exception:
        return ""


def _now():
    return time.time()


def _prune():
    cutoff = _now() - _STATUS_TTL
    for k in [k for k, v in _STATUS.items() if max(v.get("last_success", 0), v.get("last_failure", 0)) < cutoff]:
        _STATUS.pop(k, None)
    if len(_STATUS) > 64:
        for k in sorted(_STATUS, key=lambda x: max(_STATUS[x].get("last_success", 0), _STATUS[x].get("last_failure", 0)))[: len(_STATUS) - 64]:
            _STATUS.pop(k, None)


def record_success(url, bps=None):
    """记录某源本次成功（含吞吐，用于评分排序）。"""
    host = _host_of(url)
    if not host:
        return
    with _LOCK:
        _prune()
        st = _STATUS.setdefault(host, {})
        st["last_success"] = _now()
        if bps:
            old = st.get("bps") or 0
            st["bps"] = old * 0.5 + bps * 0.5  # 简单指数平均
        st["fail_count"] = 0


def mark_success(url):
    """兼容旧调用：记录成功（无吞吐信息）。"""
    record_success(url)


def record_failure(url):
    """记录某源失败（不拉黑，只影响排序）。"""
    host = _host_of(url)
    if not host:
        return
    with _LOCK:
        _prune()
        st = _STATUS.setdefault(host, {})
        st["last_failure"] = _now()
        st["fail_count"] = st.get("fail_count", 0) + 1


def _recent_success_hosts():
    cutoff = _now() - _STATUS_TTL
    with _LOCK:
        _prune()
        return {
            h for h, st in _STATUS.items()
            if st.get("last_success", 0) > st.get("last_failure", 0) and st.get("last_success", 0) >= cutoff
        }


def ranked_candidates(candidates):
    """把「近期成功且吞吐高」的源提前；近期失败的在最后；官方直连始终保留在列表中。
    不产生任何黑名单——失败源之后仍可再次尝试。"""
    if not candidates:
        return candidates
    now = _now()
    with _LOCK:
        _prune()
        score = {}
        for h, st in _STATUS.items():
            if now - st.get("last_success", 0) < _STATUS_TTL and st.get("last_success", 0) > st.get("last_failure", 0):
                score[h] = st.get("bps") or 1
        fails = {
            h for h, st in _STATUS.items()
            if st.get("last_failure", 0) >= st.get("last_success", 0) and now - st.get("last_failure", 0) < _STATUS_TTL
        }
    def _key(c):
        h = _host_of(c)
        if h in score:
            return (0, -score[h])          # 成功源，吞吐高者优先
        if h in fails:
            return (2, 0)                   # 近期失败 → 靠后（但仍保留）
        return (1, 0)                       # 未测过 → 中间
    return sorted(candidates, key=_key)


def reorder(candidates):
    """兼容旧调用：按成功记忆排序（ranked_candidates 的子集语义）。"""
    return ranked_candidates(candidates)


def source_status():
    """SourceManager 运行时评分信息（host 级）。"""
    out = []
    with _LOCK:
        _prune()
        for h, st in sorted(_STATUS.items()):
            out.append({
                "source": h,
                "available": st.get("last_success", 0) > st.get("last_failure", 0),
                "throughput_bps": round(st.get("bps") or 0),
                "last_success": st.get("last_success"),
                "last_failure": st.get("last_failure"),
                "fail_count": st.get("fail_count", 0),
            })
    return out


def pick_first_ok(candidates, fetcher):
    """逐候选调用 fetcher(url)：成功 → 记录成功并返回 (url, result)；
    全部失败 → 返回 (None, last_error)。失败源会 record_failure（不拉黑）。"""
    last_err = None
    for url in ranked_candidates(candidates):
        try:
            result = fetcher(url)
            record_success(url)
            return url, result
        except Exception as e:
            record_failure(url)
            last_err = e
            continue
    return None, last_err


def pick_first_ok_parallel(candidates, fetcher, timeout=8):
    """并发请求所有候选，第一个成功即返回（避免被某个慢/失效源拖死）。

    fetcher(url) 失败应抛异常，且内部自行控制单候选超时；
    典型场景：VPN 下官方直连快、无 VPN 时镜像快——并发可保证总是用最快的源。
    全失败返回 (None, last_error)。成功源会被记忆（下次串行时优先）。"""
    if not candidates:
        return None, RuntimeError("无候选源")
    results = {}
    lock = threading.Lock()
    done = threading.Event()

    def _run(i, url):
        try:
            r = fetcher(url)
            with lock:
                results[i] = ("ok", r)
                results.setdefault("url", url)
                results.setdefault("result", r)
                results["n"] = results.get("n", 0) + 1
                if results.get("n", 0) >= len(candidates):
                    done.set()
        except Exception as e:
            record_failure(url)
            with lock:
                results[i] = ("err", e)
                results["n"] = results.get("n", 0) + 1
                if results.get("n", 0) >= len(candidates):
                    done.set()

    for i, c in enumerate(candidates):
        threading.Thread(target=_run, args=(i, c), daemon=True).start()

    deadline = time.time() + timeout + 5
    while time.time() < deadline:
        with lock:
            if "url" in results:
                record_success(results["url"])
                return results["url"], results["result"]
            if results.get("n", 0) >= len(candidates):
                break
        time.sleep(0.05)

    with lock:
        errs = [v[1] for k, v in results.items() if isinstance(v, tuple) and v[0] == "err"]
    return None, (errs[-1] if errs else RuntimeError("所有候选源均失败"))


def clear_success():
    """清空评分缓存（测试用）。"""
    with _LOCK:
        _STATUS.clear()
