# ============================================
# FTN Studio 模型资产数据结构 ModelAsset
#
# 对应蓝图 M1 数据模型：
#   AssetManager 使用 SQLite + 本数据结构统一管理各类模型。
#
# 设计约束：
# - 支持未来多引擎（reForge / Forge / 其他）
# - 字段留足扩展，来源/归属通过 source_type/engine 区分
# - 前端只依赖本结构，禁止直接读取各来源原始数据
# ============================================

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ModelType(str, Enum):
    """模型分类（对应蓝图 2 模型管理的分类）。"""

    CHECKPOINT = "checkpoint"      # SD/SDXL 主模型
    EMBEDDING = "embedding"        # 嵌入式模型
    LORA = "lora"                  # 原生 LORA
    LORA_PLUGIN = "lora_plugin"    # 插件 LORA
    VAE = "vae"                    # VAE 编码器


class EngineType(str, Enum):
    """来源引擎类型（支持未来多引擎扩展）。"""

    REFORGE = "reforge"
    COMFYUI = "comfyui"            # 历史兼容保留：不再作为可选基底，仅兼容旧索引数据
    OTHER = "other"
    MANUAL = "manual"              # 手动登记，非扫描来源


class ModelAsset(BaseModel):
    """统一模型资产记录（对应 SQLite models 表）。"""

    # 基础标识
    id: str = Field(..., description="唯一ID（UUID）")
    name: str = Field(..., description="文件基名（不含扩展名）")
    type: ModelType = Field(..., description="模型分类")

    # 文件信息
    file_path: str = Field(..., description="模型文件完整路径")
    file_size: int = Field(0, description="文件大小（字节）")
    mtime: Optional[float] = Field(None, description="文件最后修改时间戳")

    # 预览图
    preview_path: Optional[str] = Field(
        None, description="预览图路径（同名png或自定义）"
    )

    # 来源与归属（支持多引擎扩展）
    source_type: EngineType = Field(
        EngineType.REFORGE, description="来源引擎类型"
    )
    source_path: str = Field("", description="扫描源根路径（引擎目录）")
    engine: str = Field("", description="归属引擎标识（未来多版本）")

    # 元数据与标签
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="来源相关原始元数据（JSON）"
    )
    tags: List[str] = Field(default_factory=list, description="用户标签")
    base_model: Optional[str] = Field(
        None, description="训练基底 SD/SDXL（可读或手动）"
    )

    # 检测层字段（与 base_model 语义分离：架构 vs 具体模型）
    architecture: Optional[str] = Field(
        None, description="模型架构 SD1/SD2/SDXL/SD3/Flux/Unknown"
    )
    format: Optional[str] = Field(
        None, description="文件格式 safetensors/ckpt/pt/bin/other"
    )
    sha256: Optional[str] = Field(
        None, description="内容 SHA256（重复检测身份，后台计算）"
    )
    detection_source: Optional[str] = Field(
        None, description="检测依据 modelspec_metadata/metadata/tensor_structure/path/filename/unknown"
    )
    confidence: Optional[str] = Field(
        None, description="检测置信度 high/medium/low"
    )

    # 时间信息
    created_time: Optional[float] = Field(None, description="入库/创建时间戳")
    updated_time: Optional[float] = Field(None, description="最近更新时间戳")

    def to_index_row(self) -> Dict[str, Any]:
        """转换为便于 SQLite 插入的字典。"""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "mtime": self.mtime,
            "preview_path": self.preview_path,
            "source_type": self.source_type.value,
            "source_path": self.source_path,
            "engine": self.engine,
            # metadata/tags 序列化为 JSON
            "metadata": self._json(self.metadata),
            "tags": self._json(self.tags),
            "base_model": self.base_model,
            "created_time": self.created_time,
            "updated_time": self.updated_time,
            "architecture": self.architecture,
            "format": self.format,
            "sha256": self.sha256,
            "detection_source": self.detection_source,
            "confidence": self.confidence,
        }

    @staticmethod
    def _json(obj) -> str:
        import json

        return json.dumps(obj, ensure_ascii=False, default=str)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "ModelAsset":
        """从 SQLite 行字典还原对象。"""
        import json

        def _load(s, default):
            try:
                return json.loads(s) if s else default
            except Exception:
                return default

        data = dict(row)
        data["metadata"] = _load(data.get("metadata"), {})
        data["tags"] = _load(data.get("tags"), [])
        data["type"] = ModelType(data.get("type", "checkpoint"))
        data["source_type"] = EngineType(data.get("source_type", "reforge"))
        # 过滤掉未知字段，仅保留模型字段
        known = set(cls.model_fields.keys())
        return cls(**{k: v for k, v in data.items() if k in known})
