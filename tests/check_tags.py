import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Source', 'backend')))
from core.db import db
import json
r = db.query_one("SELECT tags FROM models WHERE type='lora'")
raw = r['tags']
print('DB原始 repr:', repr(raw))
try:
    arr = json.loads(raw)
    print('解析后:', arr)
except Exception as e:
    print('解析失败:', e)
