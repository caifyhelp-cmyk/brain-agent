# -*- coding: utf-8 -*-
import sys, json
from pathlib import Path
sys.path.insert(0, '.')
import db

# 깨진 패턴 삭제
for pid in range(1335, 1345):
    db.delete_pattern(pid)

# JSON 파일에서 읽어서 추가
data = json.loads(Path('_today_patterns.json').read_text(encoding='utf-8'))
for cat, rule in data:
    new_id = db.add_pattern(cat, rule)

# 확인
patterns_data = json.loads(Path('brain/patterns.json').read_text(encoding='utf-8'))
for p in patterns_data['patterns']:
    if p['id'] >= 1335:
        print(repr(p['id']) + ' ' + repr(p['rule'][:50]))
