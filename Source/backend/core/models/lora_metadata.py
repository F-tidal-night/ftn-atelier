# ============================================
# FTN Studio LoRA 元数据统一数据结构 LoraMetadata
#
# 对应蓝图「二、LoraMetadataProvider设计」：
#   所有 LoRA 信息最终转换为本统一数据结构。
#
# 前端只依赖 LoraMetadata，禁止直接读取来源原始数据。
# 各 Provider（Safetensors/Kohya/Civitai/Manual）负责将
# 不同来源转换为本结构。
# ============================================

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TrainingInfo(BaseModel):
    """训练信息（合并自 ss_training_comment / 相关 metadata）。"""

    comment: Optional[str] = None       # ss_training_comment 训练备注
    slogan: Optional[str] = None        # 训练标语（可选）
    resolution: Optional[str] = None    # 训练分辨率
    network_dim: Optional[int] = None   # Network Dim
    network_alpha: Optional[int] = None # Network Alpha
    clip_skip: Optional[int] = None     # Clip Skip
    optimizer: Optional[str] = None     # 优化器
    lr_scheduler: Optional[str] = None  # 学习率调度器
    raw: Dict[str, Any] = Field(default_factory=dict)  # 来源原始字段备份


class LoraSource(str, Enum):
    """LoRA 信息来源（未来扩展）。"""

    SAFETENSORS = "safetensors"  # 从文件 metadata 读取
    KOHYA = "kohya"              # kohya 训练目录
    CIVITAI = "civitai"          # civitai 信息
    MANUAL = "manual"            # 用户手动编辑


class LoraMetadata(BaseModel):
    """统一 LoRA 元数据（对接 ModelAsset 的 LoRA 类型）。"""

    id: str = Field(..., description="唯一ID（对应 ModelAsset.id）")
    name: str = Field(..., description="LoRA 名称")
    file_path: str = Field(..., description="文件路径")

    preview_path: Optional[str] = Field(None, description="预览图路径")

    # 触发词 / 标签
    trigger_words: List[str] = Field(
        default_factory=list, description="自定义触发词（LoRA 模型名）"
    )
    tags: List[str] = Field(default_factory=list, description="标签")

    # 训练基底与信息
    base_model: Optional[str] = Field(
        None, description="训练基底 SD/SDXL（可读取或手动）"
    )
    training_info: TrainingInfo = Field(
        default_factory=TrainingInfo, description="训练信息"
    )

    # 推荐权重（手动填写）
    recommended_weight: Optional[float] = Field(
        None, description="推荐权重"
    )

    # 来源
    source: LoraSource = Field(
        LoraSource.SAFETENSORS, description="信息来源"
    )

    # 由源读取的训练 tag（可能很多）
    source_tags: List[str] = Field(
        default_factory=list, description="从源（如 ss_tag_frequency）读取的训练tag"
    )

    created_time: Optional[float] = Field(None, description="创建/记录时间戳")
    custom_notes: str = Field("", description="用户自定义备注")

    # 关联：可反查到底层的 ModelAsset 行（若已索引）
    asset_id: Optional[str] = Field(None, description="关联的 ModelAsset id")
