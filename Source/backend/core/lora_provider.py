# ============================================
# FTN Studio SafetensorsMetadataProvider（LoRA）
#
# 对应架构约束 #5「LoraMetadataProvider 抽象」：
#   前端禁止直接读来源数据，只依赖统一 LoraMetadata。
#   本 Provider 从 .safetensors 头部 __metadata__ 读取原始字段，
#   并转换为统一的 LoraMetadata 结构。
#
# 读取的典型字段：
#   ss_tag_frequency / ss_tags        → source_tags / trigger_words
#   ss_sd_model_name / ss_base_model_version → base_model
#   ss_training_comment / ss_resolution / ss_network_dim / ss_network_alpha
#   ss_clip_skip / ss_optimizer / ss_lr_scheduler
# ============================================

import json
import os
import struct

from core.models.lora_metadata import LoraMetadata, TrainingInfo, LoraSource


def _stable_id(path):
    import hashlib
    return "m" + hashlib.md5(path.encode("utf-8")).hexdigest()[:11] if path else ""


class SafetensorsMetadataProvider:
    """从 .safetensors 头部 __metadata__ 读取并转换为统一 LoraMetadata。"""

    def __init__(self, file_path):
        self.file_path = file_path

    # ---------- 读取 ----------
    @staticmethod
    def _read_header_meta(path):
        if not str(path).lower().endswith(".safetensors") or not os.path.isfile(path):
            return {}
        try:
            with open(path, "rb") as f:
                nbytes = struct.unpack("<Q", f.read(8))[0]
                header = json.loads(f.read(nbytes))
            return header.get("__metadata__", {}) or {}
        except Exception:
            return {}

    @staticmethod
    def _to_int(v):
        try:
            return int(float(str(v).strip()))
        except Exception:
            return None

    @staticmethod
    def _to_float(v):
        try:
            return round(float(str(v).strip()), 4)
        except Exception:
            return None

    # ---------- 转换 ----------
    def load(self) -> LoraMetadata:
        meta = self._read_header_meta(self.file_path)
        name = os.path.splitext(os.path.basename(self.file_path))[0]

        # 触发词 / 训练标签（ss_tag_frequency: {"tag": 出现次数, ...}）
        tf = meta.get("ss_tag_frequency", meta.get("ss_tags", ""))
        if isinstance(tf, str):
            try:
                tf = json.loads(tf)
            except Exception:
                tf = None
        source_tags = []
        if isinstance(tf, dict):
            source_tags = [str(k) for k in tf.keys()]
        elif isinstance(tf, list):
            source_tags = [str(x) for x in tf]

        base_model = (
            meta.get("ss_sd_model_name")
            or meta.get("ss_base_model_version")
            or (meta.get("ss_sd_model_hash") and "sd")
            or ""
        )

        training = TrainingInfo(
            comment=meta.get("ss_training_comment") or None,
            resolution=meta.get("ss_resolution") or None,
            network_dim=self._to_int(meta.get("ss_network_dim")),
            network_alpha=self._to_int(meta.get("ss_network_alpha")),
            clip_skip=self._to_int(meta.get("ss_clip_skip")),
            optimizer=meta.get("ss_optimizer") or meta.get("ss_optimizer_type") or None,
            lr_scheduler=meta.get("ss_lr_scheduler") or meta.get("ss_lr_scheduler_type") or None,
            raw=dict(meta),
        )

        return LoraMetadata(
            id=_stable_id(self.file_path),
            name=name,
            file_path=self.file_path,
            trigger_words=source_tags[:10],
            tags=source_tags[:24],
            base_model=str(base_model) if base_model else None,
            training_info=training,
            source_tags=source_tags,
            source=LoraSource.SAFETENSORS,
        )


def load_lora_metadata(file_path) -> LoraMetadata:
    """便捷入口：返回统一 LoraMetadata（非 LoRA/读取失败时仍返回结构齐全的实例）。"""
    return SafetensorsMetadataProvider(file_path).load()

