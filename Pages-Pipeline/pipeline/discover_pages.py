"""Crawl aku.edu for pages AKU's list does not mention.

Everything else in this pipeline starts from AKU's export and asks where each
page goes. This asks the opposite question — what is on the site that the export
never listed — and it matters more than it sounds: **SharePoint is being switched
off**, so a page nobody listed is a page nobody migrates, and then it is gone.

It is not hypothetical. `/academics` links to `/Pages/pakistan.aspx`, the
Pakistan academic-units page. It answers 200. It is not in the export. Neither is
`/Pages/united-kingdom.aspx`, nor `/Pages/covid-19-updates.aspx`. The export
carries `/Pages/east-africa.aspx` and stops there, so whatever produced it saw
some of the root and not the rest.

Method: fetch every page we know of, take every internal link out of it, and keep
the ones that are pages and are not in the export. Then fetch those and take
their links too, round after round, until a round finds nothing new. Each URL is
recorded with the page that linked to it, so a discovery can be traced rather
than trusted.

What it does NOT do is add anything to the plan. AKU's list is what AKU has
agreed to migrate; this produces the argument for extending it, page by page,
with the evidence attached.

Run: python discover_pages.py [--rounds N] [--limit N] [--seeds-only]
"""
import concurrent.futures as futures
import csv
import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlsplit

import page_intake
import paths

csv.field_size_limit(10 ** 9)

CACHE = paths.work('discovered.json')
OUT = paths.out('aku-pages-not-in-the-list.csv')

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
WORKERS = 6
TIMEOUT = 30
PAUSE = 0.12

# A page, not an asset, a list view or a form. SharePoint hangs a lot off a web
# that is not content.
SKIP_DIR = re.compile(r'/(_layouts|_catalogs|_vti|Lists|Forms|PublishingImages|'
                      r'SiteAssets|Style Library|DocumentTemplates)/', re.I)
PAGE_RE = re.compile(r'\.aspx$', re.I)


def norm(href, base):
    """An absolute aku.edu page URL, or None if this link is not one."""
    if not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
        return None
    u = urljoin(base, href.strip())
    s = urlsplit(u)
    if s.scheme not in ('http', 'https'):
        return None
    host = s.netloc.lower().removeprefix('www.')
    if host != 'aku.edu':
        return None
    path = s.path
    if not PAGE_RE.search(path) or SKIP_DIR.search(path):
        return None
    # A whole URL pasted into an href that already had one: mcea/Pages/mbchb.aspx
    # links to `https://www.aku.edu/https://www.aku.edu/students/…`, which
    # resolves to a real-looking address that answers Error. It is a broken link
    # on AKU's page, not a page, and `broken_links()` reports it as such.
    if re.search(r'https?:/', path, re.I):
        return None
    return 'https://www.aku.edu' + path


def links_of(url):
    import requests
    from bs4 import BeautifulSoup
    out = {'url': url, 'http': 0, 'links': [], 'title': '', 'error': ''}
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT, allow_redirects=True)
    except Exception as ex:
        out['error'] = type(ex).__name__
        return out
    out['http'] = r.status_code
    if r.status_code != 200 or 'html' not in r.headers.get('Content-Type', ''):
        return out
    s = BeautifulSoup(r.text, 'html.parser')
    t = s.find('title')
    out['title'] = (t.get_text(strip=True) if t else '')[:200]
    found = set()
    for a in s.find_all('a', href=True):
        u = norm(a['href'], r.url)
        if u:
            found.add(u)
    out['links'] = sorted(found)
    return out


def load():
    if os.path.exists(CACHE):
        with open(CACHE, encoding='utf-8') as fh:
            return json.load(fh)
    return {'scanned': {}, 'found_by': {}}


def save(state):
    with open(CACHE, 'w', encoding='utf-8') as fh:
        json.dump(state, fh, ensure_ascii=False)


def main():
    args = sys.argv[1:]
    rounds = int(args[args.index('--rounds') + 1]) if '--rounds' in args else 4
    limit = int(args[args.index('--limit') + 1]) if '--limit' in args else None

    listed = {page_intake.key(p['url']) for p in page_intake.load()}
    state = load()
    scanned = state['scanned']          # url -> {http, title, nlinks}
    found_by = state['found_by']        # url -> the page that linked it

    # Seeds: everything AKU listed. They are the map we already have; their links
    # are where anything missing will show up.
    frontier = [p['url'] for p in page_intake.load() if p['url'] not in scanned]
    if '--seeds-only' in args:
        rounds = 1

    for rnd in range(1, rounds + 1):
        todo = [u for u in frontier if u not in scanned]
        if limit:
            todo = todo[:limit]
        if not todo:
            print('round %d: nothing left to scan' % rnd)
            break
        print('round %d: scanning %d pages' % (rnd, len(todo)), flush=True)
        done = 0
        with futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for res in ex.map(links_of, todo):
                scanned[res['url']] = {'http': res['http'], 'title': res['title'],
                                       'n': len(res['links']), 'error': res['error']}
                for l in res['links']:
                    found_by.setdefault(l, res['url'])
                done += 1
                time.sleep(PAUSE)
                if done % 100 == 0:
                    print('   %d/%d' % (done, len(todo)), flush=True)
                    save(state)
        save(state)
        # Anything linked, not listed by AKU, and not yet scanned goes round again.
        frontier = [u for u in found_by
                    if page_intake.key(u) not in listed and u not in scanned]
        print('   round %d found %d unlisted pages still to scan'
              % (rnd, len(frontier)), flush=True)
        if not frontier:
            break

    unlisted = sorted(u for u in found_by if page_intake.key(u) not in listed)
    rows = []
    for u in unlisted:
        s = scanned.get(u, {})
        rows.append({
            'url': u,
            'http': s.get('http') or s.get('error') or '(not scanned)',
            'title': s.get('title', ''),
            'section': (page_intake.section_of(page_intake.web_of(u)) or '(site root)'),
            'linked_from': found_by.get(u, ''),
        })
    with open(OUT, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=['url', 'http', 'title', 'section',
                                           'linked_from'])
        w.writeheader()
        w.writerows(rows)

    import collections
    live = [r for r in rows if str(r['http']) == '200']
    print()
    print('pages AKU listed .............. %d' % len(listed))
    print('pages scanned ................. %d' % len(scanned))
    print('linked pages NOT in the list .. %d' % len(rows))
    print('   of those, answering 200 .... %d' % len(live))
    print('-> %s' % os.path.basename(OUT))
    print()
    print('by section:')
    for s, n in collections.Counter(r['section'] for r in live).most_common(20):
        print('   %-26s %d' % (s, n))


if __name__ == '__main__':
    main()
