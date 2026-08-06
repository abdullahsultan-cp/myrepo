"""Per-section fact sheet for all 82 aku.edu top-level sections.

Inherited permission rows carry the AKU-wide groups (AKU Owners, Designers,
Hierarchy Managers ...) into every web, so they say nothing about ownership.
Only rows whose Permission Scope is "Unique" name the group that actually
administers that web -- those are the CW/CA/News-Writer groups that identify the
owning entity.  Everything below filters on that.
"""
import csv, re, io, json, os, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = r"c:\Users\Cloud Primero\Desktop\aku-data-transformation-pipeline-news"
SRC = os.path.join(ROOT, 'Pages-Pipeline',
                   'AKU - User - Permissions - Sites - Groups - '
                   'SharePoint_2016_User_Roles_Mapping.csv')
ZW = str.maketrans('', '', '\u200b\ufeff\u00ad')
DOM = re.compile(r'i:0#\.w\|([^\\]+)\\')
AKU_WIDE = {'AKU Owners', 'AKU Visitors', 'Style Resource Readers', 'Designers',
            'Hierarchy Managers', 'Approvers', 'Restricted Readers', 'Viewers',
            'Translation Managers', 'Comments Moderator', 'Administrators',
            'IT Webteam', 'None (Direct Access)', 'AKUJobOwners', ''}

webs = collections.defaultdict(lambda: {
    'title': set(), 'uniq_groups': collections.Counter(),
    'uniq_doms': collections.Counter(), 'unique': 0, 'inherited': 0})

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
        if row['Permission Scope'] == 'Unique':
            w['unique'] += 1
            g = row['SharePoint Group']
            if g not in AKU_WIDE:
                w['uniq_groups'][g] += 1
            m = DOM.match(row['User Login Account'] or '')
            if m:
                w['uniq_doms'][m.group(1).lower()] += 1
        else:
            w['inherited'] += 1

pages = json.load(io.open(os.path.join(HERE, 'pages.json'), encoding='utf-8'))
pg_by_sec = collections.Counter(p['section'] for p in pages)
pg_by_web = collections.Counter(p['web'] for p in pages)

tops = sorted({p.split('/')[0] for p in webs if p})
out = io.open(os.path.join(HERE, 'sections.txt'), 'w', encoding='utf-8')
out.write('%d top-level sections\n\n' % len(tops))
for t in tops:
    kids = sorted(p for p in webs if p == t or p.startswith(t + '/'))
    # groups seen anywhere in the section subtree, unique-scope only
    gs = collections.Counter()
    ds = collections.Counter()
    for k in kids:
        gs.update(webs[k]['uniq_groups'])
        ds.update(webs[k]['uniq_doms'])
    title = ' | '.join(sorted(webs[t]['title'])) if t in webs else '(no root web)'
    out.write('/%-30s %-52s webs=%-3d pages=%-4d\n' % (t, title[:52], len(kids), pg_by_sec.get(t, 0)))
    out.write('%34s doms=%s\n' % ('', dict(ds.most_common(6))))
    out.write('%34s groups=%s\n' % ('', [g for g, _ in gs.most_common(10)]))
out.close()

# machine-readable for the builder
json.dump({p: {'title': sorted(v['title']),
               'uniq_groups': dict(v['uniq_groups']),
               'uniq_doms': dict(v['uniq_doms']),
               'unique': v['unique'], 'inherited': v['inherited'],
               'pages': pg_by_web.get(p, 0)}
           for p, v in webs.items()},
          io.open(os.path.join(HERE, 'webs.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('tops', len(tops), 'webs', len(webs))
