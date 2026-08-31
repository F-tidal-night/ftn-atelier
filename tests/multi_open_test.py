# ============================================
# 引擎多开验证（自由多开：取消多开开关，任意叠加启动）
# 每个实例独立进程/日志源/关闭控制，互不影响。
# ============================================

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Source', 'backend')))

from core.runner import runner  # noqa: E402
from core.engine_registry import engine_registry  # noqa: E402
from core.config_manager import config_manager  # noqa: E402


def wait_status(pred, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.5)
    return False


def main():
    # 空路径 → 演示模式；清空引擎自定义（多开开关默认关）
    config_manager.reset()
    engine_registry.reset()

    # 1. 启动第一个实例
    r1 = runner.start("reforge")
    assert r1["ok"] and r1.get("demo"), r1
    print("[1] 主引擎启动 ✅")

    # 2. 自由多开：同引擎叠加启动第二个实例（无需任何开关）
    r2 = runner.start("reforge")
    assert r2["ok"] and r2.get("instance") == 2, r2
    print("[2] 自由多开: 同引擎第二个实例已启动 ✅")

    def both_running():
        insts = runner.engine_instances()
        return len(insts) >= 2 and all(x["status"] == "running" for x in insts)

    assert wait_status(both_running), runner.engine_instances()
    insts = runner.engine_instances()
    pids = {x["pid"] for x in insts}
    assert len(insts) == 2 and len(pids) == 2, insts
    print("   两个实例并存、pid 不同 ✅",
          [(x["instance"], x["status"]) for x in insts])

    # 3. 日志源独立
    sources = {x["log_source"] for x in insts}
    assert sources == {"reforge", "reforge-2"}, sources
    print("[3] 日志源独立: reforge / reforge-2 ✅")

    # 4. 关闭实例 #2 → 主实例仍在
    res = runner.stop_instance("reforge", 2)
    assert res["ok"], res
    assert wait_status(lambda: len(runner.engine_instances()) == 1)
    assert runner.engine_instances()[0]["instance"] == 1
    print("[4] 关闭实例 #2 不影响主实例 ✅")

    # 5. stop_all → 全部停止
    rr = runner.stop_all()
    assert rr["ok"], rr
    assert runner.snapshot()["status"] == "stopped"
    assert len(runner.engine_instances()) == 0
    print("[5] stop_all 全部停止 ✅")
    print("\n=== 引擎多开验证通过 ===")


if __name__ == "__main__":
    main()
