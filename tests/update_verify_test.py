# Update Engine · Verifier 回归测试
# 覆盖：大小校验 / ZIP 正常 / ZIP 损坏 / 缺少 FTN Atelier.exe / SHA-256 匹配与不匹配

import hashlib
import io
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Source", "backend")))

from core.update import verifier  # noqa: E402
from core.update.models import DownloadTask  # noqa: E402


def make_zip(path, files):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def main():
    base = tempfile.mkdtemp(prefix="ftn_verify_")
    try:
        good = os.path.join(base, "good.zip")
        make_zip(good, {"FTN Atelier.exe": b"MZ...", "other.dll": b"dd"})
        good_size = os.path.getsize(good)
        good_sha = hashlib.sha256(open(good, "rb").read()).hexdigest()

        task = DownloadTask(version="1.0.2", asset_url="https://x/y.zip", asset_size=good_size,
                            asset_sha256=good_sha, dest_zip=good, part_path=good)

        # 1) 全部通过
        r = verifier.verify(task)
        assert r.ok and r.size_ok and r.zip_ok and r.exe_ok and r.sha_ok
        print("[1] 完整校验通过 OK")

        # 2) 大小不匹配
        task2 = DownloadTask(version="1.0.2", asset_url="u", asset_size=good_size + 10, dest_zip=good, part_path=good)
        r2 = verifier.verify(task2)
        assert not r2.ok and not r2.size_ok and "大小不匹配" in r2.reason
        print("[2] 大小不匹配拒绝 OK")

        # 3) ZIP 损坏
        bad = os.path.join(base, "bad.zip")
        with open(bad, "wb") as f:
            f.write(b"this is not a zip at all, padding padding padding")
        task3 = DownloadTask(version="1.0.2", asset_url="u", asset_size=os.path.getsize(bad), dest_zip=bad, part_path=bad)
        r3 = verifier.verify(task3)
        assert not r3.ok and not r3.zip_ok
        print("[3] ZIP 损坏拒绝 OK")

        # 4) 缺少 FTN Atelier.exe
        noexe = os.path.join(base, "noexe.zip")
        make_zip(noexe, {"readme.txt": b"no exe"})
        task4 = DownloadTask(version="1.0.2", asset_url="u", asset_size=os.path.getsize(noexe), dest_zip=noexe, part_path=noexe)
        r4 = verifier.verify(task4)
        assert not r4.ok and r4.zip_ok and not r4.exe_ok and "FTN Atelier.exe" in r4.reason
        print("[4] 缺少 exe 拒绝 OK")

        # 5) SHA-256 不匹配
        task5 = DownloadTask(version="1.0.2", asset_url="u", asset_size=good_size,
                             asset_sha256="0" * 64, dest_zip=good, part_path=good)
        r5 = verifier.verify(task5)
        assert not r5.ok and not r5.sha_ok and "SHA-256" in r5.reason
        print("[5] SHA-256 不匹配拒绝 OK")

        # 6) Release 未提供 SHA-256 → 跳过（视为通过）
        task6 = DownloadTask(version="1.0.2", asset_url="u", asset_size=good_size,
                             asset_sha256="", dest_zip=good, part_path=good)
        r6 = verifier.verify(task6)
        assert r6.ok and r6.sha_ok
        print("[6] 无 SHA-256 时跳过 OK")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("\n=== Update Verifier 全部通过 ===")


if __name__ == "__main__":
    main()
