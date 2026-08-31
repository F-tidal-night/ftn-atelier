# Update Engine · Downloader 回归测试
# 覆盖：正常下载 / 连接失败切源 / 下载中断切源 / Range 续传 / Range 不支持 / .part 保留

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Source", "backend")))

from core.update import source_manager as sm  # noqa: E402
from core.update import probe as probe_mod  # noqa: E402
from core.update.models import DownloadTask, ProbeResult  # noqa: E402
from core.update.downloader import download_generator  # noqa: E402

URL = "https://github.com/x/y.zip"
DATA = bytes(range(256)) * 512  # 128KB


class FakeStream:
    def __init__(self, data, status=206, fail_after=None, raise_on_read=None):
        self._buf = bytearray(data)
        self._pos = 0
        self.status = status
        self.headers = {"Content-Range": f"bytes 0-{len(data) - 1}/{len(data)}"}
        self._reads = 0
        self._fail_after = fail_after
        self._raise_on_read = raise_on_read

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def geturl(self):
        return "https://example.com/file.zip"

    def read(self, n=-1):
        if self._raise_on_read is not None and self._reads >= self._raise_on_read:
            raise self._raise_on_read
        self._reads += 1
        if n is None or n < 0:
            out = bytes(self._buf[self._pos:])
            self._pos = len(self._buf)
            return out
        out = bytes(self._buf[self._pos:self._pos + n])
        self._pos += len(out)
        return out


def patch_env(m1_behavior, m2_behavior):
    """m1/m2_behavior: ('ok', data) | ('fail', exc) | ('partial', data, fail_after, exc)"""
    orig_cands = sm.candidates_for
    orig_probe = probe_mod.probe_sources
    orig_urlopen = probe_mod.urllib.request.urlopen
    sm.candidates_for = lambda url: ["https://m1/x.zip", "https://m2/x.zip"]
    probe_mod.probe_sources = lambda cands, timeout=4: [
        ProbeResult(url=cands[0], ok=True, status=206, range_supported=True, is_zip=True),
        ProbeResult(url=cands[1], ok=True, status=206, range_supported=True, is_zip=True),
    ]

    def _open(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "m1" in url:
            b = m1_behavior
        else:
            b = m2_behavior
        kind = b[0]
        if kind == "ok":
            return FakeStream(b[1])
        if kind == "fail":
            raise b[1]
        if kind == "partial":
            return FakeStream(b[1], fail_after=b[2], raise_on_read=b[3])
        raise AssertionError(f"unexpected url: {url}")

    probe_mod.urllib.request.urlopen = _open
    return orig_cands, orig_probe, orig_urlopen


def main():
    base = tempfile.mkdtemp(prefix="ftn_dl_")
    try:
        # 1) 正常下载
        sm.clear_success()
        part = os.path.join(base, "u.zip.part")
        task = DownloadTask(version="1.0.2", asset_url=URL, asset_size=len(DATA), dest_zip=os.path.join(base, "u.zip"), part_path=part)
        o1, o2, o3 = patch_env(("ok", DATA), ("ok", DATA))
        try:
            phases = []
            for prog in download_generator(task, start_byte=0):
                phases.append(prog.phase)
            assert "downloading" in phases and "done" in phases
            assert os.path.isfile(part) and os.path.getsize(part) == len(DATA)
        finally:
            sm.candidates_for, probe_mod.probe_sources, probe_mod.urllib.request.urlopen = o1, o2, o3
        print("[1] 正常下载 + 进度状态 OK")

        # 2) 连接失败 → 自动切源
        sm.clear_success()
        part2 = os.path.join(base, "u2.zip.part")
        task2 = DownloadTask(version="1.0.2", asset_url=URL, asset_size=len(DATA), dest_zip="x.zip", part_path=part2)
        o1, o2, o3 = patch_env(("fail", ConnectionError("m1 down")), ("ok", DATA))
        try:
            done = False
            for prog in download_generator(task2, start_byte=0):
                if prog.phase == "switching":
                    assert "切换" in prog.message
                if prog.phase == "done":
                    done = True
            assert done and os.path.getsize(part2) == len(DATA)
        finally:
            sm.candidates_for, probe_mod.probe_sources, probe_mod.urllib.request.urlopen = o1, o2, o3
        print("[2] 连接失败自动切源 OK")

        # 3) 下载中断（读到一半断流）→ 保留 .part → 从断点继续
        sm.clear_success()
        part3 = os.path.join(base, "u3.zip.part")
        half = DATA[:len(DATA) // 2]
        task3 = DownloadTask(version="1.0.2", asset_url=URL, asset_size=len(DATA), dest_zip="x.zip", part_path=part3)
        o1, o2, o3 = patch_env(("partial", half, 3, RuntimeError("stream broke")), ("ok", DATA))
        try:
            done = False
            for prog in download_generator(task3, start_byte=0):
                if prog.phase == "switching":
                    assert "已保留" in prog.message or "保留" in prog.message
                if prog.phase == "done":
                    done = True
            assert done, "应切到备用源完成"
            assert os.path.getsize(part3) == len(DATA)
            assert os.path.exists(part3 + ".meta.json")
        finally:
            sm.candidates_for, probe_mod.probe_sources, probe_mod.urllib.request.urlopen = o1, o2, o3
        print("[3] 下载中断 → .part 保留 → 备用源续传完成 OK")

        # 4) Range 续传：start_byte>0，m2 成功（带 Range 头）
        sm.clear_success()
        part4 = os.path.join(base, "u4.zip.part")
        with open(part4, "wb") as f:
            f.write(DATA[:len(DATA) // 3])
        seen_range = []

        def _open_range(req, timeout=None):
            hdrs = getattr(req, "headers", {}) or {}
            seen_range.append(hdrs.get("Range"))
            return FakeStream(DATA[len(DATA) // 3:], status=206)

        o1, o2, o3 = patch_env(("fail", ConnectionError("m1")), ("ok", b""))
        probe_mod.urllib.request.urlopen = _open_range
        task4 = DownloadTask(version="1.0.2", asset_url=URL, asset_size=len(DATA), dest_zip="x.zip", part_path=part4)
        try:
            done = False
            for prog in download_generator(task4, start_byte=len(DATA) // 3):
                if prog.phase == "done":
                    done = True
            assert done
            assert seen_range and seen_range[-1] == f"bytes={len(DATA) // 3}-", seen_range
            assert os.path.getsize(part4) == len(DATA)
        finally:
            sm.candidates_for, probe_mod.probe_sources, probe_mod.urllib.request.urlopen = o1, o2, o3
        print("[4] Range 断点续传 OK")

        # 5) Range 不支持：源返回 200 → 不破坏 .part，跳过
        sm.clear_success()
        part5 = os.path.join(base, "u5.zip.part")
        with open(part5, "wb") as f:
            f.write(b"partial")
        probe_mod.probe_sources = lambda cands, timeout=4: [
            ProbeResult(url=cands[0], ok=True, status=200, range_supported=False, is_zip=True),
        ]
        orig_url = probe_mod.urllib.request.urlopen
        probe_mod.urllib.request.urlopen = lambda req, timeout=None: (_ for _ in ()).throw(AssertionError("不应发起下载"))
        task5 = DownloadTask(version="1.0.2", asset_url=URL, asset_size=1000, dest_zip="x.zip", part_path=part5)
        try:
            states = [p.phase for p in download_generator(task5, start_byte=7)]
            assert states[-1] == "error", states
            assert os.path.getsize(part5) == 7, "不允许破坏已下载 .part"
        finally:
            probe_mod.probe_sources, probe_mod.urllib.request.urlopen = o2, orig_url
        print("[5] Range 不支持 → 保留 .part、拒绝损坏续传 OK")
    finally:
        shutil.rmtree(base, ignore_errors=True)
        sm.clear_success()
    print("\n=== Update Downloader 全部通过 ===")


if __name__ == "__main__":
    main()
