# ============================================
# Update Engine · Downloader
#
# 实际下载：流式写入 .part，支持 HTTP Range 断点续传，自动切换备用源。
# 原则：
#   - 只从选中的源下载（不同时下载多个 120MB 文件）
#   - 实时产出进度：已下载 / 总大小 / 百分比 / 瞬时速度 / 平均速度 / ETA
#   - 连接失败 / HTTP 错误 / 长时间无字节增长 / Range 失败 → 自动切换备用源
#   - 任何情况下都不删除已下载的 .part（断点续传的基础）
# ============================================

import os
import time
import urllib.error
import urllib.request
from collections import deque

from core.update.models import DownloadProgress
from core.update import source_manager
from core.update.probe import probe_sources

_UA = "FTN-Atelier-updater"
_CHUNK = 256 * 1024
_CONNECT_TIMEOUT = 20
_STALL_SECONDS = 40          # 下载中多少秒无字节增长视为异常
_SPEED_WINDOW = 5.0          # 平均速度采样窗口（秒）


def _stream_source_gen(url, part_path, start_byte, stall_seconds=_STALL_SECONDS):
    """从单个源流式下载（支持 Range 续传）。生成器，每写一块 yield (delta_bytes, inst_speed)。失败抛异常。"""
    headers = {"User-Agent": _UA}
    mode = "wb"
    if start_byte > 0:
        headers["Range"] = f"bytes={start_byte}-"
        mode = "ab"
    req = urllib.request.Request(url, headers=headers)
    last_byte_time = time.time()
    chunk_t = last_byte_time
    with urllib.request.urlopen(req, timeout=_CONNECT_TIMEOUT) as resp:
        # 请求了 Range 但服务端返回 200（不支持）→ 必须从头写，否则会损坏 .part
        if start_byte > 0 and resp.status == 200:
            raise RuntimeError(f"源不支持 Range（HTTP 200 全量响应）：{url}")
        with open(part_path, mode) as f:
            while True:
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                now = time.time()
                if now - last_byte_time > stall_seconds:
                    raise RuntimeError(f"下载无进展超过 {stall_seconds}s，切换备用源：{url}")
                last_byte_time = now
                inst = len(chunk) / max(now - chunk_t, 1e-6)
                chunk_t = now
                yield len(chunk), inst


def _progress_snapshot(phase, message, received, total, source, speed_bps=0.0, avg_bps=0.0, eta=0.0, error=""):
    p = DownloadProgress(
        phase=phase, message=message, source=source,
        received=received, total=total,
        speed_bps=speed_bps, avg_speed_bps=avg_bps, eta_sec=eta, error=error,
    )
    return p


def download_generator(task, start_byte=0, on_ready=None):
    """下载编排生成器：yield DownloadProgress，直到 done / error。

    task: DownloadTask（version/asset_url/asset_size/part_path）
    start_byte: 断点起始字节（由 Resume 提供；0 = 从头下载）
    on_ready: 可选回调（下载完成时返回最终 .part 路径）
    """
    total = task.asset_size or 0
    candidates = source_manager.ranked_candidates(source_manager.candidates_for(task.asset_url))

    # 1) 探测选源（阶段 2）
    yield _progress_snapshot("probing", "正在寻找可用下载源…", start_byte, total, "")
    probes = probe_sources(candidates, timeout=4)
    usable = [p for p in probes if p.ok]
    if not usable:
        yield _progress_snapshot(
            "error", "未找到可用的下载源（GitHub 直连与镜像均不可用）", start_byte, total, "", error="no source"
        )
        return

    # 2) 续传时优先支持 Range 的源；从头下载则按探测延迟排序
    if start_byte > 0:
        order = [p for p in usable if p.range_supported] + [p for p in usable if not p.range_supported]
    else:
        order = usable

    # 3) 写续传元信息（供下次恢复时比对版本/URL）
    meta_path = task.part_path + ".meta.json"
    try:
        import json
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "version": task.version,
                "asset_url": task.asset_url,
                "asset_size": task.asset_size,
                "part_size": start_byte,
            }, f, ensure_ascii=False)
    except Exception:
        pass

    received = start_byte
    last_err = None
    speed_samples = deque()

    for probe in order:
        url = probe.url
        # 源不支持 Range 且已有部分下载 → 不破坏 .part，跳过该源
        if start_byte > 0 and not probe.range_supported:
            yield _progress_snapshot(
                "switching",
                f"源不支持断点续传，跳过（已保留 {received // 1048576} MB）",
                received, total, url,
            )
            source_manager.record_failure(url)
            continue

        yield _progress_snapshot("connecting", f"正在连接下载源…", received, total, url)
        last_t, last_got = time.time(), received
        try:
            for delta, inst in _stream_source_gen(url, task.part_path, start_byte):
                received += delta
                now = time.time()
                speed_samples.append((now, inst))
                while speed_samples and now - speed_samples[0][0] > _SPEED_WINDOW:
                    speed_samples.popleft()
                avg = sum(s for _, s in speed_samples) / len(speed_samples) if speed_samples else inst
                eta = (total - received) / avg if avg > 0 and total > received else 0.0
                yield _progress_snapshot("downloading", "正在下载", received, total, url, inst, avg, eta)
            source_manager.record_success(url, bps=(received - start_byte) / max(time.time() - last_t, 0.001))
            if on_ready:
                on_ready(task.part_path)
            yield _progress_snapshot("done", "下载完成", received, total, url)
            return
        except Exception as e:
            last_err = e
            source_manager.record_failure(url)
            # 实时进度（失败前最后状态）
            inst = (received - last_got) / max(time.time() - last_t, 0.001)
            yield _progress_snapshot(
                "switching",
                f"当前下载源异常：{e}；已保留 {received // 1048576} MB，正在切换备用源…",
                received, total, url, speed_bps=inst,
            )
            # 失败后继续：start_byte 更新为已下载大小（后续源 Range 续传）
            start_byte = received
            if received > 0:
                # 重新探测剩余候选（可能仍支持 Range）
                continue
            continue

    yield _progress_snapshot(
        "error",
        f"所有下载源均失败（已保留 {received // 1048576} MB 可续传）：{last_err}",
        received, total, "", error=str(last_err or "unknown"),
    )
