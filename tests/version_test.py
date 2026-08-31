# M5 VersionManager 冒烟测试（演示模式）
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Source', 'backend')))
from core.version_manager import version_manager

print('is_demo:', version_manager.is_demo)
snap = version_manager.list_versions()
# 当前 API：按基底分组返回 {base: [版本...]}，拍平后再校验
groups = snap if isinstance(snap, dict) else {}
versions = [v for vs in groups.values() for v in vs]
print('版本数:', len(versions))
for v in versions:
    print("  name=%s version=%s active=%s size=%.1fGB" % (v['name'], v['version'], v.get('active'), v['size']/1e9))
cur = version_manager.current()
print('当前:', cur['name'] if cur else None)
print('保护路径:', version_manager.protected_paths()['items'][:3], '...')
# 切换 active
r = version_manager.set_active('reForge-1.10.1')
print('切换:', r)
print('切换后 current:', version_manager.current()['name'])
