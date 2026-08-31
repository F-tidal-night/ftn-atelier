# ============================================
# FTN Studio SQLite 数据库层
#
# 职责：
# - 初始化数据库（Database/ftn.db）
# - 创建表结构（models / app_meta 等）
# - 提供统一的数据库连接与会话管理
#
# 未来 AssetManager 会在此之上做模型扫描、索引、增删改查。
# ============================================

import json
import os
import sqlite3
import threading
import uuid

from core.paths import app_root


# 项目根目录（FTN Studio 根）
PROJECT_ROOT = app_root()
DATABASE_DIR = os.path.join(PROJECT_ROOT, "Database")
DATABASE_PATH = os.path.join(DATABASE_DIR, "ftn.db")


class Database:
    """SQLite 数据库封装（线程安全，单连接 + 线程锁）。"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_conn()
            return cls._instance

    def _init_conn(self):
        os.makedirs(DATABASE_DIR, exist_ok=True)
        # 同时暴露为实例属性，便于外部读取
        self.DATABASE_DIR = DATABASE_DIR
        self.DATABASE_PATH = DATABASE_PATH
        self._conn = sqlite3.connect(
            DATABASE_PATH,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        # 启用外键
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    # ---------- 初始化表结构 ----------
    def _init_schema(self):
        with self._lock:
            cur = self._conn.cursor()

            # models 表：模型资产索引（对应 ModelAsset）
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS models (
                    id          TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    type        TEXT NOT NULL,
                    file_path   TEXT NOT NULL,
                    file_size   INTEGER DEFAULT 0,
                    mtime       REAL,
                    preview_path TEXT,
                    source_type TEXT,
                    source_path TEXT,
                    engine      TEXT,
                    metadata    TEXT,
                    tags        TEXT,
                    base_model  TEXT,
                    created_time REAL,
                    updated_time REAL
                )
                """
            )
            # 扫描加速索引
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_models_path ON models(file_path)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_models_type ON models(type)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_models_name ON models(name)"
            )
            # 迁移：新增检测字段（老库 ALTER TABLE 补齐）
            cur.execute("PRAGMA table_info(models)")
            cols = {r[1] for r in cur.fetchall()}
            for col, ddl in [
                ("architecture", "TEXT DEFAULT ''"),
                ("format", "TEXT DEFAULT ''"),
                ("sha256", "TEXT DEFAULT ''"),
                ("detection_source", "TEXT DEFAULT ''"),
                ("confidence", "TEXT DEFAULT ''"),
            ]:
                if col not in cols:
                    try:
                        cur.execute(f"ALTER TABLE models ADD COLUMN {col} {ddl}")
                    except Exception:
                        pass

            # 内容指纹索引（重复模型检测；须在列迁移之后）
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_models_sha256 ON models(sha256)"
            )
            self._conn.commit()

            # app_meta 表：配置 / 版本 / 键值存储
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS app_meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )

            self._conn.commit()

    # ---------- 通用执行 ----------
    def execute(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur.lastrowid

    def query(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def query_one(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None

    # ---------- meta 键值 ----------
    def set_meta(self, key: str, value):
        self.execute(
            "INSERT OR REPLACE INTO app_meta (key, value) VALUES (?, ?)",
            (key, json.dumps(value, ensure_ascii=False, default=str)),
        )

    def get_meta(self, key: str, default=None):
        row = self.query_one("SELECT value FROM app_meta WHERE key = ?", (key,))
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return row["value"]

    # ---------- models CRUD（AssetManager 将扩展） ----------
    def upsert_model(self, asset: dict):
        """插入或更新一条模型记录（按 id）。"""
        self.execute(
            """
            INSERT OR REPLACE INTO models (
                id, name, type, file_path, file_size, mtime,
                preview_path, source_type, source_path, engine,
                metadata, tags, base_model, created_time, updated_time,
                architecture, format, sha256, detection_source, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset["id"], asset["name"], asset["type"], asset["file_path"],
                asset["file_size"], asset["mtime"], asset["preview_path"],
                asset["source_type"], asset["source_path"], asset["engine"],
                asset["metadata"], asset["tags"], asset["base_model"],
                asset["created_time"], asset["updated_time"],
                asset.get("architecture", ""), asset.get("format", ""),
                asset.get("sha256", ""), asset.get("detection_source", ""),
                asset.get("confidence", ""),
            ),
        )

    def delete_model(self, model_id: str):
        self.execute("DELETE FROM models WHERE id = ?", (model_id,))

    def get_all_models(self, model_type=None):
        if model_type:
            return self.query(
                "SELECT * FROM models WHERE type = ? ORDER BY name",
                (model_type,),
            )
        return self.query("SELECT * FROM models ORDER BY name")

    def get_model_by_path(self, file_path: str):
        return self.query_one(
            "SELECT * FROM models WHERE LOWER(file_path) = LOWER(?)", (file_path,)
        )

    # ---------- 工具 ----------
    def close(self):
        with self._lock:
            self._conn.close()


def new_uuid() -> str:
    return str(uuid.uuid4())


# 单例实例
db = Database()
