"""Join the two Pages-Pipeline sources into one section inventory.

Source A  aku-university-filtered.csv -> 4,591 page URLs, read through
          page_intake. This replaced AKU-EN_1.HTM, which listed 3,340: the two
          disagree by 1,323 pages, and running the hierarchy off one while the
          migration plan runs off the other would have the tree and the plan
          describing different websites. The HTM is still parsed, but only to
          report what the newer export has since dropped.
Source B  the permissions CSV -> 612 aku.edu webs, their real titles, and the
          owner groups / AD domains that witness region + entity.

Neither is a superset of the other: the CSV knows sections that have no page in A,
and A's pages sit under sub-paths the CSV never lists as their own web.  This
script reports the overlap honestly rather than picking one source and pretending.
"""
import collections
import json
import re

import page_intake
import paths

TAX = paths.taxonomy_seed()
ZW = str.maketrans('', '', '\u200b\ufeff\u00ad')

# ---- A: pages -------------------------------------------------------------
# AKU's disposition, in the two words their export uses, mapped to the codes the
# tree renders as dots. The newer export added two the HTM never had: a page AKU
# has not reviewed yet is not the same as one they have decided to move.
ACTION_CODE = {
    'move as is': 'asis',
    'update and move': 'upd',
    'not reviewed': 'unrev',
    'unclear': 'unclear',
}

# The HTM is no longer the inventory, but it is the only source that ever
# carried a category per page, so it is still parsed for that one column.
html = open(paths.PAGES_HTM, encoding='utf-8').read()
CAT = {}
for act, fname, cat, url in re.findall(
        r'<li data-name="[^"]*">\s*<span class="pact (\w+)"[^>]*></span>'
        r'\s*<span class="pfile mono">([^<]+)</span>'
        r'\s*<span class="pcat">([^<]*)</span>'
        r'\s*<a class="visit" href="(https://www\.aku\.edu/[^"]+)"', html):
    CAT[page_intake.key(url)] = cat

pages = []
for p in page_intake.load():
    web = p['web']
    segs = web.split('/') if web else []
    pages.append({
        # The root web has no section. '' rather than None: this feeds JSON and
        # then a tree that groups by section, and a None key sorts against str.
        'section': segs[0] if segs else '',
        'sub': '/'.join(segs[1:]),
        'web': web,
        'file': p['file'],
        'cat': CAT.get(p['key'], ''),
        'action': ACTION_CODE.get(p['action'].lower(), 'unrev'),
        'status': p['status'],
        'new': p['new'],
        'url': p['url'],
    })

dropped = page_intake.dropped()

# ---- B: webs from the CSV -------------------------------------------------
sites = json.load(open(paths.work('sites.json'), encoding='utf-8'))
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

tax = json.load(open(TAX, encoding='utf-8'))

out = open(paths.work('join_report.txt'), 'w', encoding='utf-8')
out.write('pages parsed .............. %d\n' % len(pages))
out.write('  new in this export ...... %d\n' % sum(1 for p in pages if p['new']))
out.write('  at the site root ........ %d\n' % sum(1 for p in pages if not p['web']))
out.write('dropped since AKU-EN_1.HTM  %d  (see dropped_pages.txt)\n' % len(dropped))
out.write('with a category from the HTM %d\n' % sum(1 for p in pages if p['cat']))
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

json.dump(pages, open(paths.work('pages.json'), 'w', encoding='utf-8'),
          ensure_ascii=False)
print('pages', len(pages), 'csv webs', len(csv_webs), 'csv top', len(csv_top))
