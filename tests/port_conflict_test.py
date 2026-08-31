# ============================================
# 端口冲突自动处理验证
# - 占用探测：_port_in_use / _next_free_port
# - webui 引擎（launch.py 等）：端口被占用 → 改写 --port 为空闲端口
# - bat 引擎（webui.bat / 一键启动.bat）：注入 COMMANDLINE_ARGS --port=<空闲>
# - 演示模式不参与探测；全段占用 → 明确失败
# ============================================

import os
import sys
import socket

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Source', 'backend')))

from core.runner import runner  # noqa: E402


def main():
    # 1. 占用 / 空闲探测
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 17990))
    s.listen(1)
    assert runner._port_in_use(17990) is True, "已占用端口应被识别"
    assert runner._port_in_use(17991) is False, "空闲端口应通过"
    assert runner._next_free_port(17990) == 17991, "应从占用端口起找到第一个空闲端口"
    print("[1] 占用探测 / 空闲端口查找 ✅")

    # 2. webui 引擎：改写 --port 参数
    cmd, port, env, ok = runner._apply_free_port(
        "reforge", ["python", "launch.py", "--port=17990"], False, 17990, False
    )
    assert ok and port == 17991, (ok, port)
    assert "--port=17991" in cmd and "--port=17990" not in cmd, cmd
    assert env is None, "非 bat 引擎不应注入环境变量"
    print("[2] webui 引擎自动改 --port ✅", cmd)

    # 3. bat 引擎：注入 COMMANDLINE_ARGS
    cmd2, port2, env2, ok2 = runner._apply_free_port(
        "wd", ["cmd", "/c", "webui.bat"], False, 17990, True
    )
    assert ok2 and port2 == 17991 and env2, (ok2, port2)
    assert "--port=17991" in env2["COMMANDLINE_ARGS"], env2
    print("[3] bat 引擎注入 COMMANDLINE_ARGS ✅", env2["COMMANDLINE_ARGS"])

    # 4. 演示模式跳过端口探测
    cmd3, port3, env3, ok3 = runner._apply_free_port(
        "reforge", ["python", "-c", "demo"], True, 17990, False
    )
    assert ok3 and port3 == 17990 and env3 is None
    print("[4] 演示模式跳过端口探测 ✅")

    # 5. 连续占用超过查找范围 → 明确失败
    held = []
    for p in range(17980, 17980 + 35):
        ss = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ss.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ss.bind(("127.0.0.1", p))
        ss.listen(1)
        held.append(ss)
    _, _, _, ok4 = runner._apply_free_port(
        "reforge", ["python", "launch.py", "--port=17980"], False, 17980, False
    )
    assert ok4 is False, "无空闲端口时应返回失败"
    for ss in held:
        ss.close()
    print("[5] 无空闲端口 → 明确失败 ✅")

    s.close()
    print("\n=== 端口冲突自动处理验证通过 ===")


if __name__ == "__main__":
    main()
