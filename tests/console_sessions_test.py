# ============================================
# 控制台「自动挂载引擎 cmd」回归测试
#
# 产品定论（对齐绘世）：控制台不做手动新建会话，
# 引擎启动带出的 cmd 自动挂载进软件——每开一个自动新增
# 一个标签、名字与引擎对应，关闭仅终止对应实例。
#
# 前置：后端已在 19099 端口运行（FTN_BACKEND_PORT=19099 python main.py）
# 覆盖：
#   1. 引擎启动 → 控制台会话自动出现（名字对应引擎）
#   2. WebSocket 实时推送引擎日志（验证 log→WS 桥）
#   3. 多开引擎 → 自动新增 #2 标签；关闭 #2 不影响 #1
#   4. 停止引擎 → 会话自动消失
# ============================================

import json
import sys
import time
import asyncio
import urllib.request

import websockets

BASE = "http://127.0.0.1:19099"


def req(method, path, body=None, timeout=10):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_until(fn, timeout=20, interval=0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = fn()
        if v:
            return v
        time.sleep(interval)
    return None


def session_by_id(sid):
    for s in req("GET", "/api/console/sessions")["sessions"]:
        if s["id"] == sid:
            return s
    return None


def test_auto_attach():
    print("[1] 引擎启动 → 控制台自动挂载（名字对应引擎）")
    r = req("POST", "/api/engine/start?engine=reforge")
    assert r["ok"], r
    st = wait_until(lambda: session_by_id("engine:reforge"), timeout=10)
    assert st and st["title"] == "主引擎", st
    assert st["status"] in ("starting", "running"), st
    print("   通过: engine:reforge / 标题 主引擎")


async def test_ws_push():
    print("[2] WebSocket 实时推送引擎日志（log→WS 桥）")
    seen = []
    async with websockets.connect("ws://127.0.0.1:19099/ws") as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert first.get("type") == "subscribed", first
        # 重启引擎产生新日志
        req("POST", "/api/engine/stop-all")
        time.sleep(1)
        req("POST", "/api/engine/start?engine=reforge")

        def hit(m):
            rec = m.get("record", {})
            return rec.get("source") == "reforge" and "demo mode" in rec.get("content", "")

        deadline = time.time() + 10
        while time.time() < deadline and not any(hit(m) for m in seen):
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
            except asyncio.TimeoutError:
                continue
            if msg.get("type") == "log":
                seen.append(msg)
        assert any(hit(m) for m in seen), "WS 应实时推送引擎日志"
        print("   通过: reforge 日志实时推送 (source=reforge)")


def test_multi_auto_attach():
    print("[3] 多开引擎 → 自动新增 #2 标签；关闭 #2 不影响 #1")
    r = req("POST", "/api/engine/start?engine=reforge")
    assert r["ok"] and r.get("instance") == 2, r
    st2 = wait_until(lambda: session_by_id("engine:reforge:2"), timeout=10)
    assert st2 and st2["title"] == "主引擎 #2", st2
    assert session_by_id("engine:reforge") is not None, "主实例标签应仍在"
    # 关闭 #2 → 仅该实例消失
    req("POST", "/api/console/sessions/engine:reforge:2/stop")
    gone = wait_until(lambda: session_by_id("engine:reforge:2") is None, timeout=10)
    assert gone, "关闭 #2 后该标签应消失"
    assert session_by_id("engine:reforge") is not None, "关闭 #2 不应影响 #1"
    print("   通过: 主引擎 #2 自动出现 / 关闭不影响 #1")


def test_stop_disappear():
    print("[4] 停止引擎 → 会话自动消失")
    req("POST", "/api/engine/stop-all")
    gone = wait_until(lambda: session_by_id("engine:reforge") is None, timeout=10)
    assert gone, "停止后标签应消失"
    assert req("GET", "/api/console/sessions")["sessions"] == [], "无运行实例时控制台应为空"
    print("   通过: 停止后自动消失 / 空态干净")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    test_auto_attach()
    asyncio.run(test_ws_push())
    test_multi_auto_attach()
    test_stop_disappear()
    print("\n=== 控制台自动挂载引擎 cmd 全部验证通过 ===")


if __name__ == "__main__":
    main()
