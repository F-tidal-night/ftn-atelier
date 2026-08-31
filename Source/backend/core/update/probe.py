# ============================================
# Update Engine · Probe
#
# 对候选源做「轻量探测」：GET + Range 前 1KB，记录：
#   HTTP 状态码 / 重定向 / 最终 URL / Content-Type / Content-Length / Range 支持
#   首字节响应时间 / 是否确认是 ZIP（前 4 字节 PK\x03\x04）
# 禁止实际下载完整 ZIP。
# 注意：「谁最先响应」≠「谁下载最快」，探测结果只用于选源，不直接代表最终速度。
# ============================================

import threading
import time
import urllib.request

from core.update.models import ProbeResult
from core.update import source_manager

_UA = "FTN-Atelier-updater"


def probe_single(url, timeout=4):
    """单源探测：GET + Range bytes=0-1023，读 1KB 后立即关闭。"""
    result = ProbeResult(url=url)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _UA, "Range": "bytes=0-1023", "Accept": "*/*"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result.status = resp.status
            result.final_url = resp.geturl()
            result.redirect = bool(resp.geturl()) and resp.geturl() != url
            result.content_type = resp.headers.get("Content-Type") or ""
            # 完整大小优先取 Content-Range 的 total；否则取 Content-Length
            cr = resp.headers.get("Content-Range") or ""
            if cr and "/" in cr:
                try:
                    result.content_length = int(cr.rsplit("/", 1)[-1])
                except ValueError:
                    pass
            if not result.content_length:
                try:
                    result.content_length = int(resp.headers.get("Content-Length") or 0)
                except ValueError:
                    pass
            result.range_supported = resp.status == 206
            head = resp.read(1024)
            result.is_zip = head[:4] == b"PK\x03\x04"
            result.first_byte_ms = (time.time() - t0) * 1000.0
            result.ok = True
    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
        result.first_byte_ms = (time.time() - t0) * 1000.0
    if result.ok:
        source_manager.record_success(url)
    else:
        source_manager.record_failure(url)
    return result


def probe_sources(candidates, timeout=4):
    """并发探测所有候选，返回按可用性 + 首字节耗时排序的 [ProbeResult]。"""
    if not candidates:
        return []
    results = [None] * len(candidates)

    def _run(i, url):
        results[i] = probe_single(url, timeout=timeout)

    threads = [threading.Thread(target=_run, args=(i, u), daemon=True) for i, u in enumerate(candidates)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout + 3)
    out = [r for r in results if r is not None]
    out.sort(key=lambda r: (not r.ok, r.first_byte_ms if r.ok else 999999))
    return out
