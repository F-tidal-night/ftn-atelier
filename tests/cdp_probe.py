# 调试工具：通过 CDP 检查打包版页面状态（头图加载排查等）
# 用法：先以 --remote-debugging-port=9222 启动应用，再运行本脚本
import json
import asyncio
import urllib.request

import websockets


async def main():
    targets = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json").read())
    page = next(
        (t for t in targets if t["type"] == "page" and "view=startup" not in t["url"]),
        next((t for t in targets if t["type"] == "page"), None),
    )
    ws_url = page["webSocketDebuggerUrl"]
    expr = (
        "JSON.stringify({url: location.href.slice(0,80), body: document.body.innerText.slice(0,120), "
        "imgs: [...document.images].map(i=>({src:i.src.slice(0,90), complete:i.complete, nw:i.naturalWidth})), "
        "heroEl: !!document.querySelector(\"img[src*='hero']\")})"
    )
    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({
            "id": 1, "method": "Runtime.evaluate",
            "params": {"expression": expr, "returnByValue": True},
        }))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if m.get("id") == 1:
                print("RESULT:", m.get("result", {}).get("result", {}).get("value"))
                break


if __name__ == "__main__":
    asyncio.run(main())
