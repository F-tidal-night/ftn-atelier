# ============================================
# FTN Studio 运行状态管理 (StatusManager)
#
# 职责：
# - 记录当前运行中的启动模式实例（互斥）
# - 管理 WebSocket 连接集合（广播推送）
# - 提供状态快照
#
# 第一版：单实例互斥
# ============================================

import time


class StatusManager:
    """运行状态与推送管理（线程安全）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self._clients = set()
        # 当前运行的实例（互斥）；None 表示无实例运行
        self._active = None
        self._lock_owner = None
        self._started_at = None

    # ---------- WebSocket 客户端管理 ----------
    async def register(self, websocket):
        self._clients.add(websocket)

    async def unregister(self, websocket):
        if websocket in self._clients:
            self._clients.discard(websocket)

    async def push(self, payload: dict):
        """向所有客户端广播消息。"""
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def broadcast_log(self, record: dict):
        await self.push({"type": "log", "record": record})

    async def broadcast_status(self):
        await self.push({"type": "status", "status": self.snapshot()})

    # ---------- 互斥实例管理 ----------
    def try_acquire(self, mode, owner, meta=None) -> bool:
        """尝试获取运行锁（全局互斥，后端最终判断）。"""
        if self._active is not None and self._lock_owner is not None:
            return False
        self._active = {"mode": mode, "meta": meta or {}}
        self._lock_owner = owner
        self._started_at = time.time()
        return True

    def release(self, owner):
        if self._lock_owner == owner:
            self._active = None
            self._lock_owner = None
            self._started_at = None
            return True
        return False

    @property
    def is_busy(self):
        return self._active is not None

    def snapshot(self, include_ws=False):
        data = {
            "active": self._active,
            "busy": self.is_busy,
            "started_at": self._started_at,
        }
        if include_ws:
            data["ws_clients"] = len(self._clients)
        return data


# 单例实例
status_manager = StatusManager()
