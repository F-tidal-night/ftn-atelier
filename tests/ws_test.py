# 临时测试脚本：验证 FTN Studio 后端 WebSocket 连接
import asyncio
import os
import websockets


async def main():
    port = os.environ.get("FTN_BACKEND_PORT", "19099")
    uri = f"ws://127.0.0.1:{port}/ws"
    try:
        async with websockets.connect(uri) as ws:
            # 接收订阅确认
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            print("服务端消息:", msg)
            # 发送一条消息，期待 echo
            await ws.send("hello-from-tester")
            echo = await asyncio.wait_for(ws.recv(), timeout=5)
            print("回声消息:", echo)
            print("WebSocket 连通性验证通过")
    except Exception as e:
        print("WebSocket 测试失败", e)

asyncio.run(main())
