# Runner 自由多开冒烟测试
# 产品定论：取消全局互斥，主引擎 + 其他引擎可同时运行（自由多开）
import sys, os, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Source', 'backend')))
from core.runner import runner


def wait_running(timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        insts = runner.engine_instances()
        if insts and all(x['status'] == 'running' for x in insts):
            return insts
        time.sleep(0.5)
    return runner.engine_instances()


print("1. 启动主引擎 (demo)")
r = runner.start('reforge')
assert r['ok'] and r.get('demo'), r
print("   ", r)
time.sleep(1)

print("2. 主引擎运行中，再启动 wd（自由多开 → 额外实例）")
r2 = runner.start('wd')
assert r2['ok'], r2
print("   ", r2, "| instance=", r2.get('instance'))
insts = wait_running()
assert len(insts) >= 2, insts
print("   并存实例:", [(x['engine'], x['instance'], x['status']) for x in insts])

print("3. 同引擎再开一个（主引擎 #2）")
r3 = runner.start('reforge')
assert r3['ok'] and r3.get('instance') == 2, r3
insts = wait_running()
assert len(insts) >= 3, insts
print("   并存实例数:", len(insts))

print("4. 只停 wd（不影响主引擎）")
res = runner.stop(engine_key='wd')
print("   ", res)
assert len([x for x in runner.engine_instances() if x['engine'] == 'wd']) == 0

print("5. stop_all 全部停止")
rr = runner.stop_all()
assert runner.snapshot()['status'] == 'stopped'
assert len(runner.engine_instances()) == 0
print("   ", rr)
print("   自由多开全部通过")
