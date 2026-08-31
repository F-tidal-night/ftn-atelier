# ============================================
# FTN Studio 配置管理器 ConfigManager
#
# 职责：
# - 加载/保存 AppConfig（持久化到 Database/app_config.json）
# - 提供单例、默认配置、读写接口
#
# 设计原则：配置结构先确定（AppConfig），M3 设置页面只是可视化编辑。
# 本模块保证配置的加载与写回安全（原子写）。
# ============================================

import json
import os
import threading

from core.models.app_config import AppConfig
from core.paths import app_root


# 项目根目录（FTN Studio 根）
PROJECT_ROOT = app_root()
DATABASE_DIR = os.path.join(PROJECT_ROOT, "Database")
CONFIG_PATH = os.path.join(DATABASE_DIR, "app_config.json")


class ConfigManager:
    """AppConfig 读写管理（线程安全）。"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._config = None
        self._lock = threading.Lock()
        # 暴露路径为实例属性，便于外部访问
        self.CONFIG_PATH = CONFIG_PATH
        self.DATABASE_DIR = DATABASE_DIR

    # ---------- 加载 ----------
    def load(self):
        """加载配置；文件不存在或损坏时返回默认配置（不动原文件）。"""
        if self._config is not None:
            return self._config

        default = AppConfig()

        # 定位配置文件
        if not os.path.exists(CONFIG_PATH):
            self._config = default
            return default

        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 用 model_validate 做字段过滤（容忍未知/缺失字段）
            self._config = AppConfig.model_validate(data)
        except Exception:
            # 配置文件损坏：返回默认，不覆盖原文件（等用户明确保存）
            self._config = default
        return self._config

    # ---------- 保存 ----------
    def save(self, config=None):
        """原子保存配置到文件。"""
        target = config or self._config
        if target is None:
            return
        os.makedirs(DATABASE_DIR, exist_ok=True)
        # 原子写：先写临时文件再替换
        tmp_path = CONFIG_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(
                target.model_dump(),
                f,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        os.replace(tmp_path, CONFIG_PATH)
        self._config = target

    # ---------- 更新单字段 ----------
    def update(self, updates: dict):
        """按字典局部更新配置（仅更新存在的字段），返回更新后的配置。"""
        config = self.load()
        updated = config.model_copy(deep=True)
        # 用 model_validate 套用更新（基于当前 dict 合并）
        current = updated.model_dump()
        self._deep_merge(current, updates)
        self._config = AppConfig.model_validate(current)
        self.save(self._config)
        return self._config

    @staticmethod
    def _deep_merge(base: dict, updates: dict):
        for k, v in updates.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                ConfigManager._deep_merge(base[k], v)
            else:
                base[k] = v

    # ---------- 访问 ----------
    @property
    def config(self):
        return self.load()

    def reset(self):
        """重置为默认配置。"""
        self._config = AppConfig()
        self.save(self._config)
        return self._config

    # ---------- 首页快捷文件夹解析 ----------
    def quick_folders(self, engine_registry):
        """返回首页快捷文件夹（含解析后的实际路径）。

        - root：主引擎根目录（默认跟随主引擎，可自定义覆盖）
        - txt/txt_grid/img/img_grid：主引擎根目录 + outputs 子目录（可自定义覆盖）
        - 自定义 custom_path 存在则优先使用。
        """
        from core.base_registry import base_registry
        engines = engine_registry.list_engines()
        primary_base = base_registry.primary()
        # 主引擎根目录：跟随 engine_registry 标记的主引擎（primary_key，可指向任意引擎）
        primary = engine_registry.primary_engine()
        root = (primary or {}).get("root", "") or ""
        primary_base = base_registry.primary()

        _OUTPUT_SUB = {
            "txt": "txt2img-images",
            "txt_grid": "txt2img-grids",
            "img": "img2img-images",
            "img_grid": "img2img-grids",
        }

        out = []
        for f in self.config.home_folders:
            mode = f.get("mode", "root")
            custom = f.get("custom_path", "")
            if custom:
                resolved = custom
            elif mode == "root":
                resolved = root
            else:
                sub = _OUTPUT_SUB.get(mode, "")
                resolved = os.path.join(root, "outputs", sub) if root and sub else root
            out.append({
                "key": f.get("key", mode),
                "label": f.get("label", mode),
                "mode": mode,
                "custom_path": f.get("custom_path", ""),
                "path": resolved,
                "has_path": bool(resolved and os.path.isdir(resolved)),
                "primary_base": primary_base,
            })
        return {"folders": out, "primary_base": primary_base, "name": "首页快捷文件夹"}


# 单例实例
config_manager = ConfigManager()
