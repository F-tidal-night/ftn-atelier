# ============================================
# Update Engine 数据模型
# ============================================

from dataclasses import dataclass, field


@dataclass
class ProbeResult:
    """单源轻量探测结果（禁止下载完整 ZIP，只读响应头 + 前 1KB）。"""
    url: str = ""
    ok: bool = False
    status: int = None            # HTTP 状态码
    redirect: bool = False        # 是否发生重定向
    final_url: str = ""           # 重定向后的最终 URL
    content_type: str = ""        # Content-Type
    content_length: int = 0       # Content-Length（Range 响应时为分段长度）
    range_supported: bool = False # 是否支持 Range（返回 206）
    first_byte_ms: float = 0.0    # 首字节响应耗时（毫秒）
    is_zip: bool = False          # 前 4 字节是否为 PK\x03\x04
    error: str = ""               # 失败原因


@dataclass
class DownloadProgress:
    """下载器对外暴露的统一进度状态（前端只消费此结构，不判断镜像逻辑）。"""
    phase: str = "idle"           # probing | connecting | downloading | switching | verifying | done | error
    message: str = ""
    source: str = ""              # 当前使用的源
    received: int = 0             # 已下载字节
    total: int = 0                # 总字节
    speed_bps: float = 0.0        # 瞬时速度
    avg_speed_bps: float = 0.0    # 最近一段平均速度
    eta_sec: float = 0.0          # 预计剩余秒数
    error: str = ""

    @property
    def percent(self):
        if not self.total:
            return 0.0
        return min(100.0, self.received / self.total * 100.0)


@dataclass
class VerifyResult:
    """下载完成后的完整性校验结果；未通过绝不允许进入安装阶段。"""
    ok: bool = False
    size_ok: bool = False
    zip_ok: bool = False
    exe_ok: bool = False
    sha_ok: bool = False          # release 未提供 SHA-256 时视为 True（跳过）
    expected_size: int = 0
    actual_size: int = 0
    reason: str = ""


@dataclass
class DownloadTask:
    """一次下载任务的元信息（用于恢复/续传判断）。"""
    version: str = ""
    asset_url: str = ""
    asset_size: int = 0
    asset_sha256: str = ""
    dest_zip: str = ""
    part_path: str = ""
