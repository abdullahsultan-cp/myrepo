"""Where each undiscovered page WOULD go, if AKU adds it to the list.

discover_pages.py answers "what is on the site that the export never listed" and
stops there, which is the honest place to stop: AKU's list is what AKU has agreed
to migrate. But a bare list of 368 addresses is not something anyone can act on —
the question back will be "and where would those go?", and the pipeline already
knows, because placement depends on the page's section and its owner groups, not
on whether somebody remembered to export it.

So this runs each discovery through the same rules the plan uses, and opens the
page to check the answer against the breadcrumb AKU prints on it. The output is a
row per page: what it is, where it would land, and the evidence for that.

Nothing here is added to the plan. It is the argument for extending the list.

Run: python place_discovered.py
"""
import concurrent.futures as futures
import csv
import json
import os
import re
import time

import page_intake
import paths
from classification import SEC

csv.field_size_limit(10 ** 9)

IN = paths.out('aku-pages-not-in-the-list.csv')
OUT = paths.out('aku-pages-not-in-the-list.csv')      # rewritten, enriched
CACHE = paths.work('discovered_checks.json')

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
WORKERS = 6


def crumb_of(url):
    import requests
    from bs4 import BeautifulSoup
    out = {'url': url, 'http': 0, 'crumb': '', 'title': ''}
    try:
        r = requests.get(url, headers=UA, timeout=30, allow_redirects=True)
    except Exception as ex:
        out['http'] = type(ex).__name__
        return out
    out['http'] = r.status_code
    if r.status_code != 200:
        return out
    s = BeautifulSoup(r.text, 'html.parser')
    t = s.find('title')
    out['title'] = (t.get_text(strip=True) if t else '')[:200]
    el = s.select_one('[class*=readcrumb], [id*=readcrumb]')
    if el:
        parts, prev = [], None
        for x in el.stripped_strings:
            x = re.sub(r'\s+', ' ', x).strip()
            if not x or x in ('>', '/', '|') or x.lower() == 'currently selected':
                continue
            if prev and prev.lower() == x.lower():
                continue
            parts.append(x)
            prev = x
        if parts and parts[0].lower() == 'home':
            parts = parts[1:]
        out['crumb'] = ' > '.join(parts)
    return out


def main():
    rows = list(csv.DictReader(open(IN, encoding='utf-8-sig')))
    live = [r for r in rows if str(r['http']) == '200']
    cache = json.load(open(CACHE, encoding='utf-8')) if os.path.exists(CACHE) else {}

    todo = [r['url'] for r in live if r['url'] not in cache]
    print('unlisted pages answering 200 : %d' % len(live))
    print('breadcrumbs to fetch         : %d' % len(todo))
    if todo:
        done = 0
        with futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for res in ex.map(crumb_of, todo):
                cache[res['url']] = res
                done += 1
                time.sleep(0.12)
                if done % 50 == 0:
                    print('   %d/%d' % (done, len(todo)), flush=True)
                    json.dump(cache, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)
        json.dump(cache, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)

    # The folder it would land in, resolved the way a page is: the destination
    # built from its own web, or the nearest ancestor web that has one. Carried
    # in the CSV so the portal can hang these in the tree beside the pages that
    # ARE listed, instead of leaving them as a separate list nobody opens.
    folder_of = {}
    with open(paths.out('aku-folder-map.csv'), encoding='utf-8-sig') as fh:
        for f in csv.DictReader(fh):
            for w in f['source_web'].split(';'):
                w = w.strip()
                if w and not w.startswith('('):
                    folder_of[w.lower()] = f['new_path']

    def folder_for(web):
        cur = web
        while True:
            hit = folder_of.get(cur.lower())
            if hit:
                return hit
            if '/' not in cur:
                return folder_of.get('', 'regions/global')
            cur = cur.rsplit('/', 1)[0]

    # Where the plan's own rules would put it. Section decides region and entity;
    # a section SEC does not cover is the one case that needs a human, because
    # the classification is what says which region a section belongs to.
    out = []
    for r in rows:
        url = r['url']
        web = page_intake.web_of(url)
        sec = page_intake.section_of(web)
        c = cache.get(url, {})
        known = sec in SEC if sec else True
        if sec is None:
            region, ent, why = 'global', '', 'the aku.edu root web — central comms'
        elif known:
            region, ent, _n, _d, _c, prov = SEC[sec]
            why = prov
        else:
            region, ent, why = '', '', 'section not in the classification — needs a decision'
        out.append({
            'url': url,
            'http': r['http'],
            'title': c.get('title') or r.get('title', ''),
            'section': sec or '(site root)',
            'section_known': 'yes' if known else 'NO — needs classifying',
            'would_be_region': region,
            'would_be_entity': ent or '',
            'would_be_folder': folder_for(web) if str(r['http']) == '200' else '',
            'breadcrumb': c.get('crumb', ''),
            'why': why[:200],
            'linked_from': r.get('linked_from', ''),
        })

    cols = ['url', 'http', 'title', 'section', 'section_known', 'would_be_region',
            'would_be_entity', 'would_be_folder', 'breadcrumb', 'why', 'linked_from']
    out.sort(key=lambda r: (str(r['http']) != '200', r['section'], r['url']))
    with open(OUT, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(out)

    import collections
    live_rows = [r for r in out if str(r['http']) == '200']
    print()
    print('-> %s' % os.path.basename(OUT))
    print('live pages not in AKU\'s list : %d' % len(live_rows))
    print('   in a section we classify  : %d'
          % sum(1 for r in live_rows if r['section_known'] == 'yes'))
    print('   in a section we do NOT    : %d'
          % sum(1 for r in live_rows if r['section_known'] != 'yes'))
    print()
    print('they would land in:')
    for k, n in collections.Counter(r['would_be_region'] or '(undecided)'
                                    for r in live_rows).most_common():
        print('   %-18s %d' % (k, n))


if __name__ == '__main__':
    main()
