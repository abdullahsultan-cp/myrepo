"""Join the two Pages-Pipeline sources into one section inventory.

Source A  AKU-EN_1.HTM  -> 3,340 live page URLs (the only page-level inventory).
Source B  the permissions CSV -> 612 aku.edu webs, their real titles, and the
          owner groups / AD domains that witness region + entity.

Neither is a superset of the other: the CSV knows sections that have no page in A,
and A's pages sit under sub-paths the CSV never lists as their own web.  This
script reports the overlap honestly rather than picking one source and pretending.
"""
import re, io, json, os, collections
import paths


TAX = paths.taxonomy_seed()
ZW = str.maketrans('', '', '\u200b\ufeff\u00ad')

# ---- A: pages -------------------------------------------------------------
html = io.open(paths.PAGES_HTM, encoding='utf-8').read()
rows = re.findall(
    r'<li data-name="[^"]*">\s*<span class="pact (\w+)"[^>]*></span>'
    r'\s*<span class="pfile mono">([^<]+)</span>'
    r'\s*<span class="pcat">([^<]*)</span>'
    r'\s*<a class="visit" href="(https://www\.aku\.edu/[^"]+)"', html)
pages = []
for act, fname, cat, url in rows:
    path = url.replace('https://www.aku.edu/', '')
    segs = path.split('/')
    # .../Pages/<file>.aspx  — everything before /Pages/ is the web path
    web = segs[:-2] if len(segs) >= 2 and segs[-2].lower() == 'pages' else segs[:-1]
    pages.append({'section': web[0], 'sub': '/'.join(web[1:]),
                  'web': '/'.join(web), 'file': fname, 'cat': cat,
                  'action': act, 'url': url})

# ---- B: webs from the CSV -------------------------------------------------
sites = json.load(io.open(paths.work('sites.json'), encoding='utf-8'))
csv_webs, csv_top = {}, {}
for u, s in sites.items():
    if not u.startswith('http://aku.edu'):
        continue  # app-73ab25e32d9614/ImageCarousel — SharePoint app web, not content
    rest = u.replace('http://aku.edu', '').strip('/')
    csv_webs[rest] = s
    if rest:
        csv_top.setdefault(rest.split('/')[0], []).append(rest)

page_secs = collections.Counter(p['section'] for p in pages)
page_webs = collections.Counter(p['web'] for p in pages)

tax = json.load(io.open(TAX, encoding='utf-8'))

out = io.open(paths.work('join_report.txt'), 'w', encoding='utf-8')
out.write('pages parsed .............. %d\n' % len(pages))
out.write('distinct webs in pages .... %d\n' % len(page_webs))
out.write('sections in pages ......... %d\n' % len(page_secs))
out.write('CSV webs .................. %d\n' % len(csv_webs))
out.write('CSV top-level sections .... %d\n' % len(csv_top))

both = set(page_secs) & set(csv_top)
only_pages = set(page_secs) - set(csv_top)
only_csv = set(csv_top) - set(page_secs)
out.write('\nsections in BOTH .......... %d\n' % len(both))
out.write('sections only in pages .... %d  %s\n' % (len(only_pages), sorted(only_pages)))
out.write('sections only in CSV ...... %d\n' % len(only_csv))
for s in sorted(only_csv):
    t = csv_webs[s]['titles']
    out.write('    /%-34s %-45s webs=%d\n' % (s, ' | '.join(t)[:44], len(csv_top[s])))

out.write('\n== webs holding pages that the CSV does not list as a web ==\n')
missing = [w for w in sorted(page_webs) if w not in csv_webs]
out.write('%d of %d\n' % (len(missing), len(page_webs)))
for w in missing[:40]:
    out.write('    %-50s %d pages\n' % (w, page_webs[w]))

out.write('\n== taxonomy seed shape ==\n')
out.write('top keys: %s\n' % list(tax)[:12])
out.write(json.dumps(tax, ensure_ascii=False)[:1500] + '\n')

out.write('\n== per section: pages, sub-webs, CSV title, region witnesses ==\n')
for s, n in page_secs.most_common():
    t = ' | '.join(csv_webs.get(s, {}).get('titles', ['(not in CSV)']))
    doms = csv_webs.get(s, {}).get('doms', {})
    grps = list(csv_webs.get(s, {}).get('groups', {}))[:6]
    subs = len({p['sub'] for p in pages if p['section'] == s})
    out.write('%-24s pages=%-4d subwebs=%-3d  %-42s doms=%s\n      groups=%s\n'
              % (s, n, subs, t[:42], doms, grps))
out.close()

json.dump(pages, io.open(paths.work('pages.json'), 'w', encoding='utf-8'),
          ensure_ascii=False)
print('pages', len(pages), 'csv webs', len(csv_webs), 'csv top', len(csv_top))
