# 验证 M1 核心数据模块：DB / AppConfig / ModelAsset / LoraMetadata
import os
import sys

# 确保可导入 backend 模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Source', 'backend')))

from core.db import db, new_uuid
from core.config_manager import config_manager
from core.models.app_config import AppConfig
from core.models.model_asset import ModelAsset, ModelType, EngineType
from core.models.lora_metadata import LoraMetadata, LoraSource

print("=" * 50)
print("1. 数据库初始化")
print("DB 路径:", db.DATABASE_PATH)
print("app_meta 表存在:", bool(db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='app_meta'")))
print("models 表存在:", bool(db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='models'")))

print("\n2. AppConfig 加载（默认）")
conf = config_manager.load()
print("默认主题:", conf.preference.theme)
print("默认端口:", conf.start_args.port)
print("默认显存模式:", conf.start_args.vram_mode)
print("reforge 路径(默认空):", repr(conf.engine_paths.reforge))

print("\n3. AppConfig 更新 + 持久化")
config_manager.update({
    "engine_paths": {"reforge": "D:/AI/reforge"},
    "start_args": {"port": 7861},
    "preference": {"theme": "purple"},
})
conf2 = config_manager.load()
print("reforge 路径已更新:", conf2.engine_paths.reforge)
print("端口已更新:", conf2.start_args.port)
print("主题已更新:", conf2.preference.theme)
print("配置文件存在:", os.path.exists(config_manager.CONFIG_PATH))

print("\n4. ModelAsset 入库 + 查询")
asset = ModelAsset(
    id=new_uuid(),
    name="majicMIX realistic",
    type=ModelType.CHECKPOINT,
    file_path="D:/models/Stable-diffusion/majicmix.safetensors",
    file_size=2147483648,
    base_model="SDXL",
    tags=["写实", "人像"],
    source_type=EngineType.REFORGE,
    source_path="D:/reforge",
    engine="reforge-1.10",
    metadata={"config": {"arch": "sdxl"}},
)
db.upsert_model(asset.to_index_row())
got = db.get_model_by_path(asset.file_path)
print("按路径查询到:", got["name"])
print("tags 还原:", got["tags"])
print("source_type:", got["source_type"])
print("当前模型总数:", db.query("SELECT COUNT(*) as c FROM models")[0]["c"])

print("\n5. LoraMetadata 结构验证")
lora_meta = LoraMetadata(
    id=new_uuid(),
    name="example-lora",
    file_path="D:/models/Lora/example.safetensors",
    trigger_words=["example"],
    source_tags=["woman", "solo", "1girl"],
    base_model="SD1.5",
    source=LoraSource.SAFETENSORS,
    recommended_weight=0.8,
)
print("触发词:", lora_meta.trigger_words)
print("读取的训练tag数量:", len(lora_meta.source_tags))
print("推荐权重:", lora_meta.recommended_weight)
print("来源:", lora_meta.source.value)

print("\n6. 重置配置（清理测试影响）")
config_manager.reset()
print("已重置。final theme:", config_manager.load().preference.theme)

print("\n=== M1 核心数据模块验证完成 ===")
