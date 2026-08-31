# ============================================
# 统一镜像 / 多源轮换 回归测试
# 覆盖：候选生成与去重、官方直连兜底、成功源记忆排序、失败不拉黑、全失败报错、
#       镜像列表含实测可用的 gh-proxy.com / gh.3w.pm
# ============================================

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Source", "backend")))

from core.update import source_manager as mirrors  # noqa: E402


def main():
    mirrors.clear_success()
    URL = "https://github.com/F-tidal-night/ftn-atelier/releases/download/v1.0.0/x.zip"

    # 1) 候选生成：配置镜像 + 内置 + 官方直连兜底；去重；官方始终保留
    cands = mirrors.url_candidates(URL)
    assert URL in cands, cands
    assert cands[-1] == URL, cands          # 官方直连兜底在最后
    assert "https://gh-proxy.com/" + URL in cands, cands
    assert "https://gh.3w.pm/" + URL in cands, cands  # 实测可用镜像已收录
    assert len(cands) == len(set(cands)), cands
    print("[1] url_candidates OK:", cands)

    # 2) API 候选
    api = mirrors.api_candidates("F-tidal-night", "ftn-atelier")
    assert api[-1] == "https://api.github.com/repos/F-tidal-night/ftn-atelier/releases/latest"
    assert len(api) == len(set(api))
    print("[2] api_candidates OK")

    # 3) 成功源记忆：mark 后 reorder 把该源提前
    assert mirrors.reorder(cands) == cands  # 无记忆 → 原顺序
    mirrors.mark_success("https://gh.3w.pm/" + URL)
    re = mirrors.reorder(cands)
    assert re[0] == "https://gh.3w.pm/" + URL, re
    assert URL in re and len(re) == len(cands)
    print("[3] 成功源记忆排序 OK:", re[0])

    # 4) pick_first_ok：失败自动切换，成功记忆；全失败返回错误
    mirrors.clear_success()
    calls = []

    def fetcher_switch(url):
        calls.append(url)
        if len(calls) == 1:
            raise RuntimeError("first mirror down")
        return "DATA-" + url[:40]

    used, result = mirrors.pick_first_ok(cands, fetcher_switch)
    assert used and result.startswith("DATA-"), (used, result)
    assert calls[0] == cands[0], calls          # 第一个候选（配置镜像）失败
    assert calls[1] == cands[1], calls          # 自动切到第二个候选
    assert used == cands[1], used
    print("[4] pick_first_ok 失败切换 OK:", used)

    # 5) 全失败：不拉黑 + 明确错误
    mirrors.clear_success()

    def fetcher_all_fail(url):
        raise RuntimeError("all down")

    used2, err2 = mirrors.pick_first_ok(cands, fetcher_all_fail)
    assert used2 is None and err2 is not None
    # 失败后镜像仍在候选（不拉黑）
    assert any("gh-proxy.com" in c for c in mirrors.url_candidates(URL))
    print("[5] 全失败明确报错 + 失败镜像不拉黑 OK")

    # 6) 官方直连始终保留（即使配置/内置变化）
    for _ in range(3):
        mirrors.mark_success("https://gh-proxy.com/" + URL)
    re2 = mirrors.reorder(cands)
    assert URL in re2
    print("[6] 官方直连始终保留 OK")

    # 7) 并行轮换：最快成功源胜出，慢源不阻塞
    import time

    def fetcher_fast_first(url):
        time.sleep(0.2)
        return "DATA-" + url[:30]

    t0 = time.time()
    used3, result3 = mirrors.pick_first_ok_parallel(cands[:3], fetcher_fast_first, timeout=6)
    assert used3 and result3.startswith("DATA-")
    assert time.time() - t0 < 2, "并行应快速返回"
    print("[7] 并行轮换（最快源胜出，不阻塞）OK:", used3)

    # 8) 并行全失败 → 明确错误
    mirrors.clear_success()

    def fetcher_all_fail_parallel(url):
        raise RuntimeError("down")

    used4, err4 = mirrors.pick_first_ok_parallel(cands, fetcher_all_fail_parallel, timeout=3)
    assert used4 is None and err4 is not None
    print("[8] 并行全失败明确报错 OK")

    mirrors.clear_success()
    print("\n=== 镜像轮换回归全部通过 ===")


if __name__ == "__main__":
    main()
