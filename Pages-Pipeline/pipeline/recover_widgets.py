"""recover_widgets.py -- every client-side webpart on a page, and where it sits.

A SharePoint page renders its galleries, accordions, tile rows and tab strips in
the browser: the markup holds an empty `<div id="ctl00_ctl62_g_...">` and a call
that fills it. So a plain fetch of `Allied Health Events` returns prose and
nothing else, while the live page is text, gallery, text, gallery.

The call IS the wiring, and it names both the list and the div:

    galleryapp('ctl00_ctl62_g_adaa…', 'Faculty development | 2023', '<web>', '<title>')
    ReadAccordion('ctl00_ctl62_g_dbf4…', 'Academic-and-Traineeship-Programmes', '<web>', …)
    ReadTiles('ctl00_ctl62_g_5cac…', 'allied-health-tiles', '<web>', 'Four')
    ReadTabs('ctl00_ctl62_g_1797…', 'CBCB Areas', '<web>')

Because the div is in the document, its POSITION is the widget's position. That
is the whole point of this step: the first version appended every gallery to the
end of the page, which is not where any of them belong.

aku.edu answers its REST API anonymously, so the list behind each call is
readable without a browser.

Writes out/work/page_widgets.json:
    serial -> [{kind, div, list, title, offset, data}]

Run:  python recover_widgets.py [--only 801,802]
"""
import argparse
import json
import os
import re
import time
import urllib.parse

import paths
import requests

HTML_DIR = paths.work('legacy_html')
OUT = paths.work('page_widgets.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/124.0 Safari/537.36',
      'Accept': 'application/json;odata=nometadata'}

KIND = {'galleryapp': 'gallery', 'ReadAccordion': 'accordion',
        'ReadTiles': 'tiles', 'ReadTabs': 'tabs'}

CALL = re.compile(
    r'\b(galleryapp|ReadAccordion|ReadTiles|ReadTabs)\s*\(\s*'
    r"'(ctl00_[^']+)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'"
    r"(?:\s*,\s*'([^']*)')?", re.S)

SELECT = {
    'gallery': '$select=FileRef,FileLeafRef&$top=500',
    'accordion': '$select=Title,Body,OrderBy&$top=200',
    'tabs': '$select=Title,Body,OrderBy&$top=200',
    'tiles': ('$select=FileRef,NewTitle,NewDescription,ButtonText,'
              'ButtonHyperLInk,IsActive,IsButtonRequired,OrderBy&$top=200'),
}


def fetch_list(sess, web, title, kind):
    """Read one SharePoint list. Falls back to every column if $select fails.

    `$select` naming a column the list does not have is a 400 for the WHOLE
    request, not a missing key -- and the list keeps its own names. ccbp's
    `Tabs` has no `OrderBy`, so the Publications page came back empty and
    published as a blank page with nobody the wiser. Ask for everything rather
    than lose the list.
    """
    base = f"{web}/_api/web/lists/getbytitle('{urllib.parse.quote(title)}')/items"
    r = None
    for query in (SELECT[kind], '$top=500'):
        try:
            r = sess.get(f'{base}?{query}', headers=UA, timeout=45)
        except requests.exceptions.RequestException:
            return []
        if r.status_code == 200:
            break
        if r.status_code != 400:
            return []                       # 401/404 -- not a column problem
    if r is None or r.status_code != 200:
        return []
    vals = r.json().get('value', [])
    if kind == 'gallery':
        return [v['FileRef'] for v in vals
                if (v.get('FileRef') or '').lower().endswith(
                    ('.jpg', '.jpeg', '.png', '.gif', '.webp'))]
    if kind in ('accordion', 'tabs'):
        out = [{'title': (v.get('Title') or '').strip(),
                'body': v.get('Body') or '',
                'order': v.get('OrderBy') or 0} for v in vals]
        return [x for x in out if x['title'] or x['body']]
    # tiles
    out = []
    for v in vals:
        if v.get('IsActive') is False:
            continue
        link = (v.get('ButtonHyperLInk') or {})
        out.append({'image': v.get('FileRef') or '',
                    'title': (v.get('NewTitle') or v.get('Title') or '').strip(),
                    'description': (v.get('NewDescription') or '').strip(),
                    'cta_label': (v.get('ButtonText') or '').strip()
                    if v.get('IsButtonRequired') is not False else '',
                    'cta_url': link.get('Url') or '',
                    'order': v.get('OrderBy') or 0})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', help='comma-separated serials')
    a = ap.parse_args()

    rows = json.load(open(paths.work('build_list_v2.json'), encoding='utf-8'))
    if a.only:
        want = set(a.only.split(','))
        rows = [r for r in rows if r['serial'] in want]

    # MERGE, never replace -- a `--only` run once discarded 781 recovered images.
    out = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    sess = requests.Session()
    seen_lists = {}

    for r in rows:
        path = os.path.join(HTML_DIR, f"{r['serial']}.html")
        if not os.path.exists(path):
            continue
        raw = open(path, encoding='utf-8').read()
        widgets = []
        for m in CALL.finditer(raw):
            fn, div, lst, web = m.group(1), m.group(2), m.group(3), m.group(4)
            kind = KIND[fn]
            if not lst or not web:
                continue
            # the div's own position in the document is the widget's position
            off = raw.find(f'id="{div}"')
            if off < 0:
                off = m.start()
            key = (web, lst, kind)
            if key not in seen_lists:
                seen_lists[key] = fetch_list(sess, web, lst, kind)
                time.sleep(0.2)
            data = seen_lists[key]
            if not data:
                continue
            widgets.append({'kind': kind, 'div': div, 'list': lst,
                            'title': (m.group(5) or '').strip(), 'offset': off,
                            'data': data})
        widgets.sort(key=lambda w: w['offset'])
        if widgets:
            out[r['serial']] = widgets
        counts = {}
        for w in widgets:
            counts[w['kind']] = counts.get(w['kind'], 0) + 1
        print(f"  {r['serial']:>4}  {r['title'][:36]:<38} "
              f"{counts if counts else '-'}", flush=True)

    json.dump(out, open(OUT, 'w', encoding='utf-8', newline='\n'),
              indent=1, ensure_ascii=False)
    tally = {}
    for v in out.values():
        for w in v:
            tally[w['kind']] = tally.get(w['kind'], 0) + 1
    print(f'\n{len(out)} pages have widgets -> {OUT}')
    print('  ', tally)


if __name__ == '__main__':
    main()
