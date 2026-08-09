"""Extract every region signal the permissions export actually contains.

The CSV has no region column.  It carries five independent witnesses instead, and
this script pulls each one out separately so a placement can be judged on which
witnesses agree rather than on one clever guess:

  1. domain   the AD domain in the login account -- aku\\ Karachi, nbi\\ Nairobi,
              dar\\ Dar es Salaam, ismc\\ London.  A real campus boundary: AKU runs
              a separate directory per campus.
  2. path     a region token as its own path segment (convocation/ke, library/pk)
  3. suffix   a region token ending the section slug (mcpk, sonamea, iedtz)
  4. group    a region token inside a SharePoint group name (CW MC PK, CA EA Lib)
  5. title    a country or city named in the Website Title

Counts are of *unique-scope* rows only, for the reason given in sections.py:
inherited rows repeat the AKU-wide groups into every web and witness nothing.
"""
import csv, re, io, json, os, collections
import paths


SRC = paths.PERMISSIONS_CSV
ZW = str.maketrans('', '', '​﻿­')
DOM = re.compile(r'i:0#\.w\|([^\\]+)\\')

# AD domain -> region.  'aku' is the Karachi directory and also every central
# service account, so it evidences Pakistan only when nothing else competes.
DOMAIN_REGION = {'aku': 'pakistan', 'nbi': 'kenya', 'dar': 'tanzania',
                 'ismc': 'united-kingdom'}
# 'scholar' is a scholarly-publishing service account, not a campus.

TOKEN_REGION = {'pk': 'pakistan', 'pakistan': 'pakistan',
                'ke': 'kenya', 'kenya': 'kenya', 'nbi': 'kenya', 'nairobi': 'kenya',
                'tz': 'tanzania', 'tanzania': 'tanzania',
                'ug': 'uganda', 'uganda': 'uganda', 'kampala': 'uganda',
                'uk': 'united-kingdom', 'london': 'united-kingdom',
                'af': 'afghanistan', 'afghanistan': 'afghanistan', 'kabul': 'afghanistan'}
# 'ea' means East Africa, which spans three regions -- deliberately not mapped.
EA_TOKENS = {'ea', 'east africa', 'eastafrica'}

CITY_REGION = {
    'karachi': 'pakistan', 'matiari': 'pakistan', 'chitral': 'pakistan',
    'gilgit': 'pakistan', 'hyderabad': 'pakistan',
    'nairobi': 'kenya', 'dar es salaam': 'tanzania', 'daressalaam': 'tanzania',
    'arusha': 'tanzania', 'kampala': 'uganda', 'london': 'united-kingdom',
    'kabul': 'afghanistan',
}
COUNTRY_RE = re.compile(
    r'\b(pakistan|kenya|tanzania|uganda|united kingdom|afghanistan|east africa)\b', re.I)
COUNTRY_REGION = {'pakistan': 'pakistan', 'kenya': 'kenya', 'tanzania': 'tanzania',
                  'uganda': 'uganda', 'united kingdom': 'united-kingdom',
                  'afghanistan': 'afghanistan', 'east africa': '(east africa)'}

webs = collections.defaultdict(lambda: {
    'title': set(), 'doms': collections.Counter(),
    'groups': set(), 'unique': 0})
group_names = collections.Counter()
domain_totals = collections.Counter()

with io.open(SRC, encoding='utf-8-sig', newline='') as f:
    for row in csv.DictReader(f):
        if row['Site Collection'] != 'http://aku.edu':
            continue
        url = row['Website URL'].strip().translate(ZW)
        if not url.startswith('http://aku.edu'):
            continue
        path = url.replace('http://aku.edu', '').strip('/')
        w = webs[path]
        w['title'].add(row['Website Title'].strip().translate(ZW))
        if row['Permission Scope'] != 'Unique':
            continue
        w['unique'] += 1
        g = (row['SharePoint Group'] or '').strip()
        if g:
            w['groups'].add(g)
            group_names[g] += 1
        m = DOM.match(row['User Login Account'] or '')
        if m:
            d = m.group(1).lower()
            w['doms'][d] += 1
            domain_totals[d] += 1

def path_tokens(path):
    hits = collections.Counter()
    for seg in path.lower().split('/'):
        if seg in TOKEN_REGION:
            hits[TOKEN_REGION[seg]] += 1
        if seg in EA_TOKENS:
            hits['(east africa)'] += 1
    return hits

def suffix_token(path):
    top = path.split('/')[0].lower()
    for tok in ('pakistan', 'tanzania', 'uganda', 'kenya'):
        if top == tok:
            return TOKEN_REGION[tok]
    m = re.search(r'(?:^|[a-z])[-_]?(pk|ke|tz|ug|uk|ea)$', top)
    if m:
        t = m.group(1)
        return '(east africa)' if t == 'ea' else TOKEN_REGION[t]
    return None

GROUP_TOK = re.compile(r'(?:^|[\s_\-])(PK|EA|KE|TZ|UG|UK)(?:$|[\s_\-])')

# 31 webs are scoped Unique but list the site-collection's entire group roster
# instead of an owner -- 47 to 93 distinct groups, where a genuinely owned web
# carries 2 to 8.  Nothing falls between 8 and 47, so the split is unambiguous.
# Reading region tokens off those rosters would witness every region at once, so
# the group witness has to abstain on them.
ROOT_DUMP = 30

def group_tokens(groups):
    if len(groups) > ROOT_DUMP:
        return collections.Counter()
    hits = collections.Counter()
    for g in groups:
        for t in GROUP_TOK.findall(g):
            t = t.lower()
            hits['(east africa)' if t == 'ea' else TOKEN_REGION[t]] += 1
        gl = g.lower()
        for city, r in CITY_REGION.items():
            if city in gl:
                hits[r] += 1
    return hits

def title_tokens(titles):
    hits = collections.Counter()
    for t in titles:
        tl = t.lower()
        for m in COUNTRY_RE.findall(t):
            hits[COUNTRY_REGION[m.lower()]] += 1
        for city, r in CITY_REGION.items():
            if city in tl:
                hits[r] += 1
    return hits

# ---- per-web witness table ------------------------------------------------
rows = []
for path, w in sorted(webs.items()):
    if not path:
        continue
    dom_r = collections.Counter()
    for d, n in w['doms'].items():
        if d in DOMAIN_REGION:
            dom_r[DOMAIN_REGION[d]] += n
    rows.append({
        'path': path,
        'title': sorted(w['title'])[0] if w['title'] else '',
        'unique_rows': w['unique'],
        'domain': dict(dom_r),
        'path_token': dict(path_tokens(path)),
        'suffix': suffix_token(path),
        'group': dict(group_tokens(w['groups'])),
        'title_token': dict(title_tokens(w['title'])),
    })

# which witnesses fire, and how often
fire = collections.Counter()
for r in rows:
    for k in ('path_token', 'group', 'title_token'):
        if r[k]:
            fire[k] += 1
    if r['suffix']:
        fire['suffix'] += 1
    if r['domain']:
        fire['domain'] += 1

# strong evidence = anything other than the domain count, which is noisy because
# every central service account lives in aku\
strong = collections.defaultdict(set)
for r in rows:
    top = r['path'].split('/')[0]
    for k in ('path_token', 'group', 'title_token'):
        for reg in r[k]:
            strong[reg].add(top)
    if r['suffix']:
        strong[r['suffix']].add(top)

out = io.open(paths.work('regions_extracted.txt'), 'w', encoding='utf-8')
out.write('REGION EXTRACTION — aku.edu only (%d webs, %d unique-scope groups)\n\n'
          % (len(webs), len(group_names)))

out.write('== 1. AD domains present (unique-scope rows) ==\n')
for d, n in domain_totals.most_common():
    out.write('  %-8s %6d rows   -> %s\n'
              % (d, n, DOMAIN_REGION.get(d, 'not a campus (service account)')))

out.write('\n== 2. how many webs each witness fires on ==\n')
for k in ('domain', 'suffix', 'path_token', 'group', 'title_token'):
    out.write('  %-12s %d webs\n' % (k, fire[k]))

out.write('\n== 3. regions found, and the sections that witness them ==\n')
for reg in sorted(strong, key=lambda r: -len(strong[r])):
    secs = sorted(strong[reg])
    out.write('\n  %s  (%d sections)\n' % (reg, len(secs)))
    for i in range(0, len(secs), 6):
        out.write('      %s\n' % '  '.join('/' + s for s in secs[i:i + 6]))

out.write('\n== 3b. webs that abstain: unique scope but the whole group roster ==\n')
abstain = [r for r in rows if len(webs[r['path']]['groups']) > ROOT_DUMP]
out.write('  %d webs carry 47-93 groups instead of an owner, so neither their\n'
          '  group names nor their domain spread witnesses anything:\n' % len(abstain))
for r in abstain:
    out.write('      /%-38s %d groups\n' % (r['path'][:38], len(webs[r['path']]['groups'])))

out.write('\n== 4. group names carrying a region token ==\n')
for g, n in sorted(group_names.items()):
    t = group_tokens({g})
    if t:
        out.write('  %-34s %-24s %d rows\n' % (g, dict(t), n))

out.write('\n== 5. webs whose title names a country or city ==\n')
for r in rows:
    if r['title_token']:
        out.write('  /%-38s %-46s %s\n'
                  % (r['path'][:38], r['title'][:46], dict(r['title_token'])))

out.write('\n== 6. every web with an explicit region path segment ==\n')
for r in rows:
    if r['path_token']:
        out.write('  /%-38s %-40s %s\n'
                  % (r['path'][:38], r['title'][:40], dict(r['path_token'])))
out.close()

json.dump(rows, io.open(paths.work('region_witnesses.json'), 'w',
                        encoding='utf-8'), ensure_ascii=False, indent=1)
print('webs', len(webs), 'regions found', sorted(strong))
print('witness fire counts', dict(fire))
