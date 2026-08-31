# 验证 HostWatchdog：宿主消失后后端自清理退出
import os, sys, time, subprocess, ctypes

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Source', 'backend'))

def main():
    # 1. 创建一个"假宿主"进程（短暂的 cmd 进程）
    host = subprocess.Popen(['cmd', '/c', 'timeout', '/t', '60'], creationflags=subprocess.CREATE_NO_WINDOW)
    print('假宿主 PID =', host.pid)

    # 2. 启动后端，FTN_HOST_PID 指向假宿主
    env = dict(os.environ)
    env['FTN_BACKEND_PORT'] = '19031'          # 用独立端口，避免影响用户会话
    env['FTN_HOST_PID'] = str(host.pid)        # 宿主指向假进程
    env['FTN_HOST_CHECK_INTERVAL'] = '1'       # 1秒监控一次，加快验证
    backend = subprocess.Popen(
        [sys.executable, 'main.py'],
        cwd=BACKEND_DIR, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    print('后端 PID =', backend.pid)

    # 3. 等待后端就绪
    import urllib.request
    ok = False
    for _ in range(20):
        try:
            urllib.request.urlopen('http://127.0.0.1:19031/api/health', timeout=1)
            ok = True
            break
        except Exception:
            time.sleep(0.5)
    print('后端就绪:', ok)

    # 4. 杀掉假宿主（模拟 Electron 异常退出），观察后端是否自清理
    print('正在杀死假宿主(模拟异常退出)...')
    os.kill(host.pid, 9)

    # 5. 等待后端自杀
    deadline = time.time() + 15
    exited = False
    while time.time() < deadline:
        if backend.poll() is not None:
            exited = True
            break
        time.sleep(0.5)

    print('后端是否自清理退出:', exited, '退出码:', backend.poll())

    # 清理：若后端未自杀，强制杀掉
    if backend.poll() is None:
        backend.kill()
    print('测试完成')

if __name__ == '__main__':
    main()
