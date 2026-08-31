# ============================================
# FTN Atelier · GitHub 网络层唯一入口（薄转发）
#
# 实际逻辑统一实现在 core/update/source_manager.py（Update Engine 的 SourceManager），
# 本文件仅为兼容/集中导出：GitHub API / Release 查询 / Asset 下载 / 镜像候选生成 /
# 源选择 / 失败切换 全部经此入口访问，避免散落多份镜像逻辑。
# ============================================

from core.update.source_manager import (  # noqa: F401
    GITHUB_MIRRORS,
    configured_prefix,
    candidates_for,
    url_candidates,
    api_candidates,
    record_success,
    record_failure,
    mark_success,
    ranked_candidates,
    reorder,
    pick_first_ok,
    pick_first_ok_parallel,
    source_status,
    clear_success,
)
