# M4 AssetManager 冒烟测试（demo 扫描）
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Source', 'backend')))
from core.asset_manager import asset_manager
from core.db import db

db.execute('DELETE FROM models')
r = asset_manager.scan(full=True, demo=True)
print('扫描结果:', r)
print('stats:', asset_manager.stats())
for m in asset_manager.list():
    print("  type=%s base=%s name=%s size=%d tags=%s" % (m['type'], m['base_model'], m['name'], m['file_size'], m['tags'][:30]))
print('按分类 lora 查询:', len(asset_manager.list(model_type='lora')))
print('搜索 "anime":', len(asset_manager.list(query='anime')))
