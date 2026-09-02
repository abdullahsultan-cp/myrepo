"""Open every page the metadata export cannot vouch for, and check where AKU files it.

Three sources place a page, and two of them are about the *folder* it sits in:
the permissions export names the owners of its web, and the URL names its section.
`SPPagesAKU-Metadata.csv` is the only one that speaks per page -- its CW/CA columns
name the team that writes that page -- and it covers 3,265 of the 4,591. Every one
of the 1,323 pages AKU's filtered export added is outside it.

So those are checked the way site_visits.py checked the section landing pages, and
by hand: open the page and read its breadcrumb. AKU publishes "Home > Convocation >
Pakistan" on a convocation/pk page and "Home > School of Nursing and Midwifery,
Uganda > ... > Alumni" on a sonamug/alumni one. That is AKU stating where the page
belongs, in their own words, and it is independent of both exports.

What this does NOT do is move anything. It writes what the live site said next to
what the plan decided, and flags the two apart. A breadcrumb that disagrees is a
question for a human, not a reason to re-file a page automatically -- several
disagreements are AKU's own left-nav being wrong, which is exactly the kind of
thing that has to be seen rather than resolved by a rule.

Results are cached in out/work/live_checks.json and re-used: a second run only
fetches what it has not seen, so this can be re-run after AKU sends a new export
without hammering their server for pages already checked.

Run: python verify_live.py [--all] [--limit N] [--refresh]
     --all      also re-check pages the metadata export already covers
     --limit N  stop after N fetches (for a trial run)
     --refresh  ignore the cache and fetch everything again
"""
import concurrent.futures as futures
import csv
import json
import os
import re
import sys
import time

import page_intake
import paths

csv.field_size_limit(10 ** 9)

CACHE = paths.work('live_checks.json')
OUT = paths.out('aku-live-page-verification.csv')

# A real browser string. AKU's server answers the default python-requests UA with
# a 403 on some webs, which would read as "page is gone" when it is not.
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
WORKERS = 6          # polite: AKU's SharePoint is not a CDN
TIMEOUT = 30
PAUSE = 0.15         # between completions, per worker


def breadcrumb_of(soup):
    """The trail AKU prints at the top of the page, as a list of names.

    SharePoint renders it into an element whose class contains "breadcrumb"; the
    separators are markup, not text, so the parts are joined explicitly. The
    leading "Home" is dropped -- every page has it and it says nothing.
    """
    el = soup.select_one('[class*=readcrumb], [id*=readcrumb]')
    if not el:
        return []
    parts = [re.sub(r'\s+', ' ', t).strip()
             for t in el.stripped_strings]
    # "Currently selected" is SharePoint's own accessibility label for the node
    # you are on, not a step in the trail.
    parts = [p for p in parts if p and p not in ('>', '/', '|', '›')
             and p.lower() != 'currently selected']
    # SharePoint repeats the section for its own landing page: "Home > ACER >
    # ACER > Research". A run of the same name says nothing extra.
    out = []
    for p in parts:
        if not out or out[-1].lower() != p.lower():
            out.append(p)
    return out[1:] if out and out[0].lower() == 'home' else out


def fetch(url):
    import requests
    from bs4 import BeautifulSoup
    rec = {'url': url, 'http': 0, 'title': '', 'h1': '', 'crumb': [],
           'final_url': '', 'error': ''}
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT, allow_redirects=True)
    except Exception as ex:
        rec['error'] = type(ex).__name__
        return rec
    rec['http'] = r.status_code
    rec['final_url'] = r.url
    if r.status_code == 200 and 'html' in r.headers.get('Content-Type', ''):
        s = BeautifulSoup(r.text, 'html.parser')
        t, h = s.find('title'), s.find('h1')
        rec['title'] = (t.get_text(strip=True) if t else '')[:300]
        rec['h1'] = (h.get_text(strip=True) if h else '')[:200]
        rec['crumb'] = breadcrumb_of(s)
    return rec


def norm(s):
    """Compare names the way a person would: case, punctuation and & vs and."""
    s = (s or '').lower().replace('&', 'and')
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def load_cache():
    if os.path.exists(CACHE):
        with open(CACHE, encoding='utf-8') as fh:
            return json.load(fh)
    return {}


def main():
    args = sys.argv[1:]
    do_all = '--all' in args
    refresh = '--refresh' in args
    limit = None
    if '--limit' in args:
        limit = int(args[args.index('--limit') + 1])

    pages = page_intake.load()
    webs = json.load(open(paths.work('webs.json'), encoding='utf-8'))
    plan = {page_intake.key(r['current_url']): r for r in
            csv.DictReader(open(paths.out('aku-page-map.csv'), encoding='utf-8-sig'))}

    # Pages the metadata export already vouches for are skipped unless --all:
    # their own CW/CA group is a stronger witness than a breadcrumb, and it costs
    # AKU's server nothing to read.
    covered = set()
    meta_csv = paths.data('SPPagesAKU-Metadata.csv')
    if os.path.exists(meta_csv) and not do_all:
        with open(meta_csv, encoding='utf-8-sig', newline='') as fh:
            for r in csv.DictReader(fh):
                u = (r.get('Original Page URL') or '').strip()
                if u:
                    covered.add(page_intake.key(u))

    todo = [p for p in pages if p['key'] not in covered]
    cache = {} if refresh else load_cache()
    want = [p for p in todo if p['url'] not in cache]
    if limit:
        want = want[:limit]

    print('pages in the plan        : %d' % len(pages))
    print('vouched for by metadata  : %d' % len(covered & {p["key"] for p in pages}))
    print('to verify on the live site: %d' % len(todo))
    print('  already cached         : %d' % (len(todo) - len([p for p in todo if p['url'] not in cache])))
    print('  fetching now           : %d' % len(want))

    if want:
        done = 0
        with futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(fetch, p['url']): p for p in want}
            for f in futures.as_completed(futs):
                rec = f.result()
                cache[rec['url']] = rec
                done += 1
                time.sleep(PAUSE)
                if done % 50 == 0 or done == len(want):
                    print('   fetched %d/%d' % (done, len(want)), flush=True)
                    json.dump(cache, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)
        json.dump(cache, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)

    # ---- compare what the site said with what the plan decided --------------
    # Every page there is a cached check for, not just the ones this run would
    # have fetched. `--all` decides what gets *fetched*; it must not decide what
    # gets *reported*, or a later run without it silently rewrites the CSV down
    # to 1,326 rows and throws away a full sweep of 4,591.
    rows = []
    for p in pages:
        rec = cache.get(p['url'])
        if not rec:
            continue
        pr = plan.get(p['key'], {})
        sec = p['section'] or ''
        expected = (webs.get(sec, {}).get('title') or [''])[0]
        # Filtered here as well as at fetch time: records cached before that
        # filter existed still carry the label, and re-fetching 1,326 pages to
        # drop one word would be rude.
        crumb = [c for c in (rec.get('crumb') or [])
                 if c.lower() != 'currently selected']
        # The section can sit anywhere in the trail, not just first. An event
        # microsite prints its own name ahead of the hub -- "SIMPACT > Events >
        # SIMPACT" -- so testing only the first step called 59 correct placements
        # wrong. What matters is that AKU names the section somewhere in it.
        ce = norm(expected)
        hit = next((c for c in crumb if norm(c) == ce), '')
        loose = next((c for c in crumb
                      if ce and (ce in norm(c) or norm(c) in ce)), '')
        # A page inside SharePoint's own SitePages/Documents library gets a trail
        # local to that library -- "Registration form > How To Use This Library"
        # -- which never names the section. Not a disagreement, just a breadcrumb
        # that cannot answer the question.
        # `Pages` is the publishing library every normal page lives in and it
        # renders the site trail; only `SitePages` and `Documents` render a local
        # one, so the test is which container holds the file, not whether one does.
        _segs = page_intake.relative(p['url']).split('/')
        in_library = len(_segs) >= 2 and _segs[-2].lower() in ('sitepages', 'documents')
        if not rec.get('http') or rec['http'] != 200:
            verdict = 'not reachable'
        elif not sec:
            verdict = 'site root — no section above it'
        elif in_library:
            verdict = 'SharePoint library page — trail is local to the library'
        elif not crumb:
            verdict = 'no breadcrumb'
        elif not expected:
            verdict = 'no title to compare'
        elif hit:
            verdict = 'agrees' if norm(crumb[0]) == ce else 'agrees (section deeper in trail)'
        elif loose:
            verdict = 'agrees (looser name)'
        else:
            verdict = 'DISAGREES'
        rows.append({
            'current_url': p['url'],
            'new_in_export': 'new' if p['new'] else '',
            'http': rec.get('http') or rec.get('error') or '',
            'live_title': rec.get('title', ''),
            'breadcrumb': ' > '.join(crumb),
            'section': sec,
            'section_title_in_export': expected,
            'verdict': verdict,
            'folder': pr.get('folder', ''),
            'region': pr.get('region', ''),
            'entity': pr.get('entity', ''),
            'department': pr.get('department', ''),
        })

    cols = ['current_url', 'new_in_export', 'http', 'verdict', 'breadcrumb',
            'live_title', 'section', 'section_title_in_export', 'folder',
            'region', 'entity', 'department']
    with open(OUT, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r['verdict'] != 'DISAGREES',
                                                r['current_url'].lower())))
    import collections
    print()
    print('verified %d pages -> %s' % (len(rows), os.path.basename(OUT)))
    for k, n in collections.Counter(r['verdict'] for r in rows).most_common():
        print('   %-22s %d' % (k, n))
    codes = collections.Counter(str(r['http']) for r in rows)
    print('http:', dict(codes))


if __name__ == '__main__':
    main()
