# Update Engine · Probe 回归测试
# 覆盖：HTTP 200 / 重定向 / Content-Type / Content-Length / Range / ZIP / 超时

import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Source", "backend")))

from core.update import probe  # noqa: E402
from core.update import source_manager as sm  # noqa: E402


class FakeResp:
    def __init__(self, status=206, headers=None, data=b"PK\x03\x04xxxx", geturl=None, delay=0.0):
        self.status = status
        self.headers = headers or {"Content-Type": "application/octet-stream", "Content-Range": "bytes 0-1023/1000"}
        self._data = data
        self._url = geturl or "https://example.com/file.zip"
        self._delay = delay

    def __enter__(self):
        if self._delay:
            time.sleep(self._delay)
        return self

    def __exit__(self, *a):
        return False

    def geturl(self):
        return self._url

    def read(self, n=-1):
        return self._data[:n] if n >= 0 else self._data


def fake_urlopen(resp, error=None):
    orig = probe.urllib.request.urlopen

    def _open(req, timeout=None):
        if error:
            raise error
        return resp

    probe.urllib.request.urlopen = _open
    return orig


def main():
    sm.clear_success()
    URL = "https://github.com/x/y.zip"

    # 1) 206 + Range + ZIP
    orig = fake_urlopen(FakeResp(status=206, headers={"Content-Type": "application/octet-stream", "Content-Range": "bytes 0-1023/126767724"}))
    try:
        r = probe.probe_single(URL)
        assert r.ok and r.status == 206 and r.range_supported and r.is_zip
        assert r.content_length == 126767724  # 从 Content-Range 取完整大小
        assert r.content_type == "application/octet-stream"
    finally:
        probe.urllib.request.urlopen = orig
    print("[1] 206 / Range / Content-Length / ZIP 识别 OK")

    # 2) 重定向
    orig = fake_urlopen(FakeResp(status=302, geturl="https://cdn.example.com/real.zip", headers={"Content-Type": "text/html"}))
    try:
        r = probe.probe_single(URL)
        assert r.redirect and r.final_url == "https://cdn.example.com/real.zip"
    finally:
        probe.urllib.request.urlopen = orig
    print("[2] 重定向记录 OK")

    # 3) HTTP 错误 / 超时
    import urllib.error
    orig = fake_urlopen(None, error=urllib.error.HTTPError(URL, 404, "nf", {}, None))
    try:
        r = probe.probe_single(URL)
        assert not r.ok and "HTTP" in r.error
    finally:
        probe.urllib.request.urlopen = orig
    orig = fake_urlopen(None, error=TimeoutError("slow"))
    try:
        r = probe.probe_single(URL)
        assert not r.ok and "TimeoutError" in r.error
    finally:
        probe.urllib.request.urlopen = orig
    print("[3] HTTP 错误 / 超时 OK")

    # 4) probe_sources 并发排序（快源在前）
    orig = probe.urllib.request.urlopen

    def _slow_open(req, timeout=None):
        return FakeResp(status=206, data=b"PK\x03\x04", delay=0.2)

    def _fast_open(req, timeout=None):
        return FakeResp(status=206, data=b"PK\x03\x04", delay=0.0)

    try:
        probe.urllib.request.urlopen = _slow_open
        slow = probe.probe_sources(["https://m1/x.zip"])
        probe.urllib.request.urlopen = _fast_open
        fast = probe.probe_sources(["https://m2/x.zip"])
        assert fast[0].first_byte_ms < slow[0].first_byte_ms
    finally:
        probe.urllib.request.urlopen = orig
    print("[4] 并发探测 + 延迟排序 OK")

    sm.clear_success()
    print("\n=== Update Probe 全部通过 ===")


if __name__ == "__main__":
    main()
