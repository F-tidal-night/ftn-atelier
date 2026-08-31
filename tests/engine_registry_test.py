# M7-A EngineRegistry 冒烟测试
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Source', 'backend')))
from core.engine_registry import engine_registry

print('=== 初始引擎列表 ===')
for e in engine_registry.list_engines():
    print("  key=%s label=%s kind=%s primary=%s root=%s entry=%s" % (e['key'], e['label'], e['kind'], e['primary'], e['root'], e['entry']))

print('=== 新增引擎 ===')
print(engine_registry.add_engine('forge', 'Forge', 'webui', 'Forge 工作流'))
print(engine_registry.add_engine('reforge', 'dup', 'webui'))  # 应 dup

print('=== 改名 reforge（允许）===')
print(engine_registry.rename_engine('reforge', 'reForge 我的'))

print('=== 删除 reforge（应拒绝）===')
print(engine_registry.remove_engine('reforge'))

print('=== 删除新增的 forge（允许）===')
print(engine_registry.remove_engine('forge'))

print('=== 最终列表 ===')
for e in engine_registry.list_engines():
    print("  key=%s label=%s kind=%s primary=%s" % (e['key'], e['label'], e['kind'], e['primary']))

print('=== 重置 ===')
print(engine_registry.reset())
for e in engine_registry.list_engines():
    print("  key=%s label=%s" % (e['key'], e['label']))
