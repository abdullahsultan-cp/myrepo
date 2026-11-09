"""fetch_sheet_pages.py -- download the old aku.edu page for every row of a sheet.

Writes out/work/sheet_pages/:
    html/<serial>.html   the page exactly as aku.edu served it
    status.json          serial -> HTTP status
    widgets.json         serial -> the JavaScript-loaded lists on that page

aku.edu is being switched off, so this is the copy that survives it. Read-only
against aku.edu; resumable -- a page already on disk is not fetched again, and
a page already in widgets.json keeps what was recovered for it.

The widget step is recover_widgets.py's, reused rather than copied: the same
call-site parse, the same `$select` fallback. `div_present` is recorded because
a call whose div is missing is a dead initialiser (MC-PK-RULES §4).

Run:  python fetch_sheet_pages.py --csv <sheet.csv> [--only 1909,1910]
"""
import argparse
import json
import os
import time

import paths
import recover_widgets as rw
import requests
import sheet

OUT_DIR = paths.work('sheet_pages')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', required=True)
    ap.add_argument('--only', help='comma-separated serials')
    ap.add_argument('--out', default=OUT_DIR)
    a = ap.parse_args()

    rows = sheet.read(a.csv)
    if a.only:
        want = set(a.only.split(','))
        rows = [r for r in rows if r['Serial No.'] in want]
    html_dir = os.path.join(a.out, 'html')
    os.makedirs(html_dir, exist_ok=True)
    st_path = os.path.join(a.out, 'status.json')
    status = json.load(open(st_path, encoding='utf-8')) if os.path.exists(st_path) else {}
    sess = requests.Session()
    ua = {'User-Agent': rw.UA['User-Agent']}

    for n, row in enumerate(rows, 1):
        sn, url = row['Serial No.'], row['Old URL']
        path = os.path.join(html_dir, f'{sn}.html')
        if os.path.exists(path):
            continue
        code = None
        for i in range(4):
            try:
                r = sess.get(url, headers=ua, timeout=60)
                code = r.status_code
                if code == 200:
                    r.encoding = 'utf-8'
                    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
                        fh.write(r.text)
                if code < 500:
                    break
            except requests.RequestException as e:
                code = f'ERR {type(e).__name__}'
            time.sleep(2 ** i)
        status[sn] = code
        print(f'  {n}/{len(rows)}  {code}  {url}', flush=True)
        if n % 25 == 0:
            json.dump(status, open(st_path, 'w', encoding='utf-8'), indent=1)
    json.dump(status, open(st_path, 'w', encoding='utf-8'), indent=1)

    # MERGE, never replace -- the same rule recover_widgets.py learnt the hard way.
    wpath = os.path.join(a.out, 'widgets.json')
    out = json.load(open(wpath, encoding='utf-8')) if os.path.exists(wpath) else {}
    seen = {}
    for row in rows:
        sn = row['Serial No.']
        path = os.path.join(html_dir, f'{sn}.html')
        if sn in out or not os.path.exists(path):
            continue
        raw = open(path, encoding='utf-8').read()
        widgets = []
        for m in rw.CALL.finditer(raw):
            fn, div, lst, web = m.group(1), m.group(2), m.group(3), m.group(4)
            if not lst or not web:
                continue
            kind = rw.KIND[fn]
            off = raw.find(f'id="{div}"')
            key = (web, lst, kind)
            if key not in seen:
                seen[key] = rw.fetch_list(sess, web, lst, kind)
                time.sleep(0.2)
            if seen[key]:
                widgets.append({'kind': kind, 'div': div, 'list': lst,
                                'title': (m.group(5) or '').strip(),
                                'offset': off if off >= 0 else m.start(),
                                'div_present': off >= 0, 'data': seen[key]})
        widgets.sort(key=lambda w: w['offset'])
        out[sn] = widgets
    json.dump(out, open(wpath, 'w', encoding='utf-8', newline='\n'),
              indent=1, ensure_ascii=False)
    ok = sum(1 for v in status.values() if v == 200)
    print(f'\n{ok} of {len(status)} pages on disk -> {a.out}')
    bad = {k: v for k, v in status.items() if v != 200}
    if bad:
        print(f'  not fetched: {bad}')


if __name__ == '__main__':
    main()
