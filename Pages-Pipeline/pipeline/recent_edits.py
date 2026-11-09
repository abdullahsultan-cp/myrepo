"""recent_edits.py -- what Abdullah changed by hand after a page was fixed.

He corrects pages in the editor after they are written, and those corrections
ARE the house style (house_style.py, Pages-Pipeline/CLAUDE.md §0a). This reads
every story fixed in the last N days, compares the live story with the
read-back taken right after our write (backup/storyblok/fixes/*_AFTER_*), and
prints what differs, blok by blok. Run it before starting a new batch of pages
and fold any new pattern into house_style.py / CLAUDE.md.

    python recent_edits.py            # last 3 days
    python recent_edits.py --days 10
GET only.
"""
import argparse
import glob
import gzip
import json
import os
import re
import time

import fix_page as fp
from create_pages import SB


NOISE = ('_uid', '_editable', 'plugin', 'focus', 'backgroundColor', 'id', 'meta_data', 'is_external_url')


def strip(x):
    """Comparable form: what the editor rewrites on every save, without anyone
    choosing to (colour-picker plugin name, null attrs, image focus points,
    asset metadata), and empty values, are not corrections."""
    if isinstance(x, dict):
        out = {k: strip(v) for k, v in x.items() if k not in NOISE}
        return {k: v for k, v in out.items() if v not in (None, '', {}, [])}
    if isinstance(x, list):
        return [strip(v) for v in x]
    return x


def short(x, n=160):
    s = json.dumps(strip(x), ensure_ascii=False)
    return s if len(s) <= n else s[:n] + '...'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=float, default=3)
    a = ap.parse_args()
    cutoff = time.time() - a.days * 86400
    latest = {}
    for f in glob.glob(os.path.join(fp.BACKUP, 'fix_*_AFTER_*.json.gz')):
        # the time is read from the NAME: a fresh clone stamps every file "now"
        m = re.search(r'fix_(\d+)_AFTER_(\d{8}-\d{6})', f)
        if not m or time.mktime(time.strptime(m.group(2), '%Y%m%d-%H%M%S')) < cutoff:
            continue
        if m.group(1) not in latest or f > latest[m.group(1)]:
            latest[m.group(1)] = f
    sb = SB()
    changed = 0
    for sid, f in sorted(latest.items(), key=lambda kv: kv[1]):
        mine = json.load(gzip.open(f, 'rt', encoding='utf-8'))
        r = sb.call('GET', f'stories/{sid}')
        if r.status_code != 200:
            print(f'{sid}: HTTP {r.status_code}')
            continue
        now = r.json()['story']
        if now['updated_at'] == mine['updated_at']:
            continue
        who = (now.get('last_author') or {}).get('friendly_name')
        A = mine['content'].get('body') or []
        Bn = now['content'].get('body') or []
        ours = {b['_uid']: b for b in A}
        theirs = {b['_uid'] for b in Bn}
        lines = [f"  REMOVED  {b['component']}  {short(b)}" for b in A if b['_uid'] not in theirs]
        for b in Bn:
            o = ours.get(b['_uid'])
            if o is None:
                lines.append(f"  ADDED    {b['component']}  {short(b, 300)}")
                continue
            for k in sorted(set(o) | set(b)):
                if k in ('_uid', '_editable') or strip(o.get(k)) == strip(b.get(k)):
                    continue
                lines.append(f"  CHANGED  {b['component']}.{k}\n           was {short(o.get(k))}"
                             f"\n           now {short(b.get(k))}")
        if not lines:
            continue                          # re-saved only: nothing chosen differently
        changed += 1
        print(f"\n=== {now['full_slug']}  ({sid})  edited {now['updated_at']} by {who}")
        print('  ours:', ' | '.join(b['component'] for b in A))
        print('  now :', ' | '.join(b['component'] for b in Bn))
        print('\n'.join(lines))
    print(f'\n{len(latest)} page(s) fixed in the last {a.days:g} day(s); {changed} corrected by hand since.')


if __name__ == '__main__':
    main()
