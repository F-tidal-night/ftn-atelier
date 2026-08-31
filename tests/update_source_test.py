# Update Engine · SourceManager 回归测试
# 覆盖：URL 拼接/去重/官方保留/配置镜像/内置镜像/成功记忆/失败不拉黑/评分排序/source_status

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Source", "backend")))

from core.update import source_manager as sm  # noqa: E402

URL = "https://github.com/F-tidal-night/ftn-atelier/releases/download/v1.0.2/FTN-Atelier-Portable-1.0.2.zip"


def main():
    sm.clear_success()
    # 1) 候选：配置 + 内置 + 官方兜底；去重；官方始终保留
    cands = sm.candidates_for(URL)
    assert URL in cands and cands[-1] == URL
    assert "https://gh-proxy.com/" + URL in cands
    assert "https://gh.3w.pm/" + URL in cands
    assert len(cands) == len(set(cands))
    # 配置镜像在最前（默认 env.git_mirror=ghproxy.com）
    assert cands[0].startswith("https://ghproxy.com/")
    print("[1] 候选生成/去重/官方兜底 OK")

    # 2) api_candidates
    api = sm.api_candidates("F-tidal-night", "ftn-atelier")
    assert api[-1] == "https://api.github.com/repos/F-tidal-night/ftn-atelier/releases/latest"
    print("[2] api_candidates OK")

    # 3) 成功记忆 + 评分排序（吞吐高的优先）
    assert sm.ranked_candidates(cands) == cands  # 无记忆 → 原顺序
    sm.record_success("https://gh.3w.pm/" + URL, bps=8 * 1024 * 1024)
    sm.record_success("https://gh-proxy.com/" + URL, bps=12 * 1024 * 1024)
    ranked = sm.ranked_candidates(cands)
    assert ranked[0] == "https://gh-proxy.com/" + URL, ranked  # 吞吐更高者优先
    assert ranked[1] == "https://gh.3w.pm/" + URL, ranked
    print("[3] 成功记忆 + 吞吐排序 OK")

    # 4) 失败不拉黑：失败源仍在候选，只是靠后
    sm.record_failure("https://gh.3w.pm/" + URL)
    ranked2 = sm.ranked_candidates(cands)
    assert "https://gh.3w.pm/" + URL in ranked2
    assert ranked2.index("https://gh.3w.pm/" + URL) > ranked2.index("https://gh-proxy.com/" + URL)
    print("[4] 失败不拉黑（仅排序靠后）OK")

    # 5) source_status 运行时评分信息
    st = {s["source"]: s for s in sm.source_status()}
    assert "gh-proxy.com" in st and st["gh-proxy.com"]["available"]
    assert st["gh.3w.pm"]["fail_count"] >= 1
    print("[5] source_status OK:", [s["source"] for s in sm.source_status()])

    # 6) clear_success 重置
    sm.clear_success()
    assert sm.ranked_candidates(cands) == cands
    print("[6] 重启重置（clear_success）OK")

    print("\n=== Update SourceManager 全部通过 ===")


if __name__ == "__main__":
    main()
