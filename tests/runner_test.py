# 验证 M2 Runner：一键启动/停止引擎（演示模式）
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Source', 'backend')))

from core.runner import runner, EngineStatus
from core.config_manager import config_manager
from core.log_manager import log_manager
from core.status import status_manager

# 确保 reforge 路径为空 → 演示模式
config_manager.reset()

print("=" * 50)
print("M2 Runner 生命周期验证（演示模式）")
print("=" * 50)

# 1. 初始状态
snap = runner.snapshot()
print("1. 初始状态:", snap["status"])
assert snap["status"] == EngineStatus.STOPPED, "初始应为 stopped"

# 2. 启动
print("2. 调用 start() ...")
res = runner.start()
print("   start 返回:", res["ok"], "| status:", res.get("status"), "| demo:", res.get("demo"))
assert res["ok"] and res.get("status") == "starting"

# 3. 等待启动完成（就绪→running）
print("3. 等待引擎就绪(running) ...")
deadline = time.time() + 15
reached_running = False
while time.time() < deadline:
    if runner.snapshot()["status"] == "running":
        reached_running = True
        break
    time.sleep(1)
print("   达到 running 状态:", reached_running)
assert reached_running, "应达到 running"

# 4. 查询状态
snap = runner.snapshot()
print("4. running 快照:", snap)
assert snap["pid"] is not None

# 5. 期间日志
logs = log_manager.recent(limit=20, source="reforge")
print("5. reforge 产生的日志条数:", len(logs))
for lg in logs[-3:]:
    print("   >", lg["content"])

# 6. 停止
print("6. 调用 stop() ...")
res2 = runner.stop()
print("   stop 返回:", res2["ok"], "| status:", res2.get("status"))
assert res2["ok"] and res2.get("status") == "stopped"

# 7. 最终状态 + 互斥释放
snap = runner.snapshot()
print("7. 最终状态:", snap["status"], "| 互斥已释放:", not status_manager.is_busy)
assert snap["status"] == "stopped"
assert not status_manager.is_busy

print("\n=== M2 Runner 验证完成 ===")
