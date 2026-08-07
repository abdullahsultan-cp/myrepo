"""Probe the SharePoint permissions CSV for aku.edu only.

The permission export is the only authoritative list of *site sections* (SharePoint
webs) and who owns them.  Two signals matter for placement:
  - SharePoint group names ("MCPK Owners", "IED Members") name the owning entity;
  - the AD domain in the login account (aku\\ = Karachi, nbi\\ = Nairobi,
    dar\\ = Dar es Salaam, kbl\\ = Kabul, lon\\ = London) is a *region* witness
    that no other column carries.
"""
import csv, collections, re, json, io, os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = (r"c:\Users\Cloud Primero\Desktop\aku-data-transformation-pipeline-news"
       r"\Pages-Pipeline\AKU - User - Permissions - Sites - Groups - "
       r"SharePoint_2016_User_Roles_Mapping.csv")

DOM = re.compile(r'i:0#\.w\|([^\\]+)\\')
ZW = str.maketrans('', '', '\u200b\ufeff\u00ad')

dom = collections.Counter()
grp = collections.Counter()
scope = collections.Counter()
atype = collections.Counter()
roles = collections.Counter()
sites = collections.defaultdict(lambda: {
    'titles': set(), 'groups': collections.Counter(),
    'doms': collections.Counter(), 'scope': set(), 'rows': 0})

with io.open(SRC, encoding='utf-8-sig', newline='') as f:
    for row in csv.DictReader(f):
        if row['Site Collection'] != 'http://aku.edu':
            continue
        url = row['Website URL'].strip().translate(ZW)
        la = row['User Login Account'] or ''
        m = DOM.match(la)
        d = m.group(1).lower() if m else ('(claim)' if la.startswith('c:0') else '(none)')
        dom[d] += 1
        grp[row['SharePoint Group']] += 1
        scope[row['Permission Scope']] += 1
        atype[row['Assignee Type']] += 1
        roles[row['Assigned Roles']] += 1
        s = sites[url]
        s['rows'] += 1
        s['titles'].add(row['Website Title'].strip().translate(ZW))
        if row['SharePoint Group']:
            s['groups'][row['SharePoint Group']] += 1
        s['doms'][d] += 1
        s['scope'].add(row['Permission Scope'])

with io.open(os.path.join(HERE, 'csv_probe.txt'), 'w', encoding='utf-8') as w:
    w.write('aku.edu sites: %d\n' % len(sites))
    for label, c, n in (('login domains', dom, 40), ('permission scope', scope, 20),
                        ('assignee type', atype, 20), ('assigned roles', roles, 25),
                        ('sharepoint groups (%d distinct)' % len(grp), grp, 120)):
        w.write('\n== %s ==\n' % label)
        for k, v in c.most_common(n):
            w.write('%7d  %s\n' % (v, k))

json.dump({u: {'titles': sorted(s['titles']), 'groups': dict(s['groups']),
               'doms': dict(s['doms']), 'scope': sorted(s['scope']), 'rows': s['rows']}
           for u, s in sites.items()},
          io.open(os.path.join(HERE, 'sites.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('sites', len(sites), 'groups', len(grp))
