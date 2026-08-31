# ============================================
# 临时 GitHub 镜像探测脚本（仅测试用，不入库逻辑）
# 目标：https://github.com/F-tidal-night/ftn-atelier/releases/download/v1.0.0/FTN-Atelier-Portable-1.0.0.zip
# 对每个镜像：完整 GitHub URL 直接拼接 → HEAD/GET(Range 前 1KB) → 状态码/重定向/Content-Type/Content-Length/是否 ZIP
# 禁止下载完整文件：只读响应头 + 前 1024 字节后立即关闭。
# ============================================

import urllib.request
import urllib.error

TARGET = "https://github.com/F-tidal-night/ftn-atelier/releases/download/v1.0.0/FTN-Atelier-Portable-1.0.0.zip"
MIRRORS = [
    "https://gh-proxy.com/",
    "https://gh.3w.pm/",
    "https://gh.api.99988866.xyz/",
]


def probe(url, timeout=20):
    """只读响应头 + 前 1KB 后立即关闭；绝不下载完整文件。"""
    info = {
        "url": url,
        "status": None,
        "final_url": None,
        "redirect": False,
        "content_type": None,
        "content_length": None,
        "is_zip": None,
        "error": None,
    }
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "FTN-Atelier-mirror-probe",
            "Range": "bytes=0-1023",
            "Accept": "*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            info["status"] = resp.status
            info["final_url"] = resp.geturl()
            info["redirect"] = resp.geturl() != url.split("https://", 1)[-1] and "://" in resp.geturl()
            info["content_type"] = resp.headers.get("Content-Type")
            info["content_length"] = resp.headers.get("Content-Length")
            head = resp.read(1024)
            info["is_zip"] = head[:4] == b"PK\x03\x04"
    except urllib.error.HTTPError as e:
        info["status"] = e.code
        info["content_type"] = e.headers.get("Content-Type")
        info["error"] = f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
    return info


def main():
    results = []
    results.append(("direct(官方直连)", TARGET, probe(TARGET)))
    for m in MIRRORS:
        u = f"{m.rstrip('/')}/{TARGET}"
        results.append((m, u, probe(u)))

    for name, u, r in results:
        print("=" * 72)
        print(name)
        print("  url:", u)
        print("  status:", r["status"], "| redirect:", r["redirect"], "| final:", r["final_url"])
        print("  content-type:", r["content_type"], "| content-length:", r["content_length"])
        print("  is_zip(PK):", r["is_zip"], "| error:", r["error"])

    good = [
        name for name, u, r in results
        if r.get("status") is not None and 200 <= r["status"] < 400 and r.get("is_zip")
    ]
    print("=" * 72)
    print("可用镜像（状态 2xx/3xx 且确认 ZIP）:", good if good else "无")


if __name__ == "__main__":
    main()
