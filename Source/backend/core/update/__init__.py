# FTN Atelier · Update Engine
#
# 更新系统统一入口。职责链：
#   selfcheck（检测新版本）
#     → UpdateService（编排：探测 → 下载(断点续传) → 校验）
#     → SourceManager（GitHub 官方 + 配置镜像 + 内置镜像，单一候选来源）
#     → Probe（并发轻量探测，选源）
#     → Downloader（流式 .part + Range 续传 + 自动切源 + 实时进度）
#     → Verifier（大小 / ZIP / exe / SHA-256）
#     → Electron（关闭 → 备份 → 替换 → 校验 → 回滚）
# 用户只负责发布 GitHub Release；镜像只是访问入口，无需人工维护。

from core.update.models import ProbeResult, DownloadProgress, VerifyResult  # noqa: E401
from core.update.source_manager import (  # noqa: E401
    GITHUB_MIRRORS,
    configured_prefix,
    candidates_for,
    api_candidates,
    pick_first_ok,
    pick_first_ok_parallel,
    mark_success,
    record_success,
    record_failure,
    reorder,
    ranked_candidates,
    clear_success,
    source_status,
)
from core.update.service import UpdateService  # noqa: E401

update_service = UpdateService()
