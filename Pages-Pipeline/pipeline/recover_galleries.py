"""recover_galleries.py -- get the image galleries that are NOT in the page HTML.

A SharePoint page renders its galleries client-side: the markup holds the list's
NAME and nothing else, and the pictures are fetched from that list at runtime. So
a plain HTTP fetch of `HD4 Pakistan` returns one image, while the page a reader
sees has 115. That is the whole reason these pages looked like walls of text.

aku.edu answers its own REST API anonymously, so the pictures are recoverable
without a browser:

    /_api/web/lists?$select=Title,BaseTemplate      -- what lists this web has
    /_api/web/lists/getbytitle('NAME')/items        -- FileRef per picture

BaseTemplate 109 is a Picture Library; 101 is a Document Library. Only those hold
gallery images, and only list names that actually appear in the page's own HTML
are used -- a web has dozens of lists and most belong to other pages.

Writes out/work/page_galleries.json: serial -> [{list, images: [url, ...]}].

Run:  python recover_galleries.py [--only 848]
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
OUT = paths.work('page_galleries.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/124.0 Safari/537.36',
      'Accept': 'application/json;odata=nometadata'}

# Lists that exist in every web and never hold a page's gallery.
SKIP = {'Images', 'Pages', 'Documents', 'Composed Looks', 'Master Page Gallery',
        'Workflow History', 'Workflow Tasks', 'Style Library', 'Site Assets',
        'Form Templates', 'Site Collection Images', 'Reusable Content'}
PICTURE_TEMPLATES = {109, 101, 851}


def web_of(url):
    """The SharePoint web a page lives in: everything before /Pages/<x>.aspx."""
    p = urllib.parse.urlparse(url)
    path = re.sub(r'/Pages/[^/]+\.aspx$', '', p.path, flags=re.I)
    return f'{p.scheme}://{p.netloc}{path}'


def lists_of(sess, web, cache):
    if web in cache:
        return cache[web]
    try:
        r = sess.get(f'{web}/_api/web/lists?$select=Title,BaseTemplate,ItemCount',
                     headers=UA, timeout=45)
        cache[web] = r.json().get('value', []) if r.status_code == 200 else []
    except requests.exceptions.RequestException:
        cache[web] = []
    return cache[web]


def items_of(sess, web, title):
    """Every picture in one list, as server-relative URLs, in list order."""
    out, skip = [], 0
    while True:
        u = (f"{web}/_api/web/lists/getbytitle('{urllib.parse.quote(title)}')"
             f"/items?$select=FileRef,FileLeafRef&$top=200&$skiptoken=Paged=TRUE%26p_ID={skip}")
        try:
            r = sess.get(u, headers=UA, timeout=45)
        except requests.exceptions.RequestException:
            break
        if r.status_code != 200:
            break
        vals = r.json().get('value', [])
        if not vals:
            break
        for it in vals:
            ref = it.get('FileRef') or ''
            if ref.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                out.append(ref)
        if len(vals) < 200:
            break
        skip = len(out) + 1
        time.sleep(0.2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', help='comma-separated serials')
    a = ap.parse_args()

    rows = json.load(open(paths.work('build_list_v2.json'), encoding='utf-8'))
    if a.only:
        want = set(a.only.split(','))
        rows = [r for r in rows if r['serial'] in want]

    sess = requests.Session()
    # MERGE, never replace. A `--only 802` run once overwrote the whole file with
    # four pages and threw away 781 recovered images; the REST API had to be
    # walked again to get them back.
    out = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    cache = {}
    for r in rows:
        path = os.path.join(HTML_DIR, f"{r['serial']}.html")
        if not os.path.exists(path):
            continue
        raw = open(path, encoding='utf-8').read()
        web = web_of(r['aku_url'])
        found = []
        for lst in lists_of(sess, web, cache):
            title = lst.get('Title') or ''
            if title in SKIP or not title:
                continue
            if lst.get('BaseTemplate') not in PICTURE_TEMPLATES:
                continue
            if not lst.get('ItemCount'):
                continue
            # only a list the page itself names
            if title not in raw:
                continue
            imgs = items_of(sess, web, title)
            if imgs:
                found.append({'list': title, 'images': imgs})
            time.sleep(0.15)
        if found:
            out[r['serial']] = found
        n = sum(len(f['images']) for f in found)
        print(f"  {r['serial']:>4}  {len(found)} gallery(ies)  {n:>4} images  {r['title'][:40]}",
              flush=True)

    json.dump(out, open(OUT, 'w', encoding='utf-8', newline='\n'),
              indent=1, ensure_ascii=False)
    tot = sum(len(f['images']) for v in out.values() for f in v)
    print(f'\n{len(out)} pages have galleries; {tot} images recovered -> {OUT}')


if __name__ == '__main__':
    main()
