"""Write <sid>.after.json's content to the story, in place. Unpublished unless --publish.

Refuses if the story changed since <sid>.before.json was read. Backs up the
before and the read-back after into Pages-Pipeline/backup/storyblok/fixes/.
Usage (from Pages-Pipeline/pipeline):  python apply_fix.py <sid> [--publish]
"""
import gzip
import json
import os
import sys
import time

sys.path.insert(0, os.getcwd())
from create_pages import SB  # noqa: E402

SID = sys.argv[1]
PUBLISH = 1 if '--publish' in sys.argv else 0
HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, '..', 'out', 'work', 'fix')
BK = os.path.join(HERE, '..', 'backup', 'storyblok', 'fixes')
sb = SB()
before = json.load(open(os.path.join(FIX, f'{SID}.before.json'), encoding='utf-8'))
after = json.load(open(os.path.join(FIX, f'{SID}.after.json'), encoding='utf-8'))
cur = sb.call('GET', f'stories/{SID}').json()['story']
if cur['updated_at'] != before['updated_at']:
    raise SystemExit(f"story changed since it was read ({cur['updated_at']}); re-read before writing")
r = sb.call('PUT', f'stories/{SID}', {'story': {'name': cur['name'], 'slug': cur['slug'],
                                                 'parent_id': cur['parent_id'],
                                                 'content': after['content']}, 'publish': PUBLISH})
print('PUT', r.status_code)
if r.status_code not in (200, 201, 204):
    raise SystemExit(r.text[:300])
time.sleep(1)
back = sb.call('GET', f'stories/{SID}').json()['story']
ts = time.strftime('%Y%m%d-%H%M%S')
os.makedirs(BK, exist_ok=True)
for tag, obj in (('BEFORE', before), ('AFTER', back)):
    with gzip.open(os.path.join(BK, f'fix_{SID}_{tag}_{ts}.json.gz'), 'wt', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)
print('read back:', [b['component'] for b in back['content']['body']],
      '| published:', back.get('published'), '| unpublished changes:', back.get('unpublished_changes'))
