# Update Engine · Resume 回归测试
# 覆盖：.part 恢复 / meta 版本或 URL 不一致 / 大小超限 / 清理旧片段

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Source", "backend")))

from core.update import resume  # noqa: E402
from core.update.models import DownloadTask  # noqa: E402

URL = "https://github.com/x/y.zip"


def write_meta(part, version, url, size):
    with open(part + ".meta.json", "w", encoding="utf-8") as f:
        json.dump({"version": version, "asset_url": url, "asset_size": size}, f)


def main():
    base = tempfile.mkdtemp(prefix="ftn_resume_")
    try:
        part = os.path.join(base, "FTN-Atelier-1.0.2.zip.part")
        with open(part, "wb") as f:
            f.write(b"12345")
        task = DownloadTask(version="1.0.2", asset_url=URL, asset_size=100, dest_zip="x.zip", part_path=part)

        # 1) 版本/URL/大小一致 → 可续传
        write_meta(part, "1.0.2", URL, 100)
        p, start = resume.find_resume(base, task)
        assert p == part and start == 5
        print("[1] 一致 .part 可续传（start_byte=5）OK")

        # 2) 版本不一致 → 不续传
        write_meta(part, "1.0.1", URL, 100)
        p, start = resume.find_resume(base, task)
        assert p is None and start == 0
        print("[2] 版本不一致 → 拒绝续传 OK")

        # 3) URL 不一致 → 不续传
        write_meta(part, "1.0.2", "https://github.com/other/y.zip", 100)
        p, start = resume.find_resume(base, task)
        assert p is None
        print("[3] URL 不一致 → 拒绝续传 OK")

        # 4) 大小超限 → 不续传
        write_meta(part, "1.0.2", URL, 100)
        task2 = DownloadTask(version="1.0.2", asset_url=URL, asset_size=3, dest_zip="x.zip", part_path=part)
        p, start = resume.find_resume(base, task2)
        assert p is None
        print("[4] 大小超限 → 拒绝续传 OK")

        # 5) 无 meta → 不续传
        os.remove(part + ".meta.json")
        p, start = resume.find_resume(base, task)
        assert p is None
        print("[5] 缺 meta → 拒绝续传 OK")

        # 6) 清理旧片段：保留目标版本
        other = os.path.join(base, "FTN-Atelier-1.0.0.zip.part")
        open(other, "wb").close()
        resume.cleanup_stale(base, keep_version="1.0.2")
        assert os.path.exists(part) and not os.path.exists(other)
        print("[6] 清理旧片段（保留目标版本）OK")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("\n=== Update Resume 全部通过 ===")


if __name__ == "__main__":
    main()
