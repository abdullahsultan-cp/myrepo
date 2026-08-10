"""Profile the SharePoint groups so a Storyblok role model can be derived from them.

Three questions this answers, none of which the hierarchy work needed:
  - what does each group actually let you do (the Assigned Roles string),
  - who is in it (real named people, with counts),
  - which folders it controls (unique-scope rows only).

Group naming is AKU's own convention and carries the meaning: "CW <X>" is the
content writer for X and "CA <X>" the content approver, so the pair identifies
both the owning unit and the two-step publish workflow already in use.
"""
import collections
import csv
import json
import re

import paths

SRC = paths.PERMISSIONS_CSV
ZW = str.maketrans('', '', '​﻿­')
DOM = re.compile(r'i:0#\.w\|([^\\]+)\\(.+)$')
ROOT_DUMP = 30

groups = collections.defaultdict(lambda: {
    'roles': collections.Counter(), 'people': set(), 'domains': collections.Counter(),
    'webs_unique': set(), 'webs_inherited': set(), 'rows': 0})
web_groups = collections.defaultdict(set)
role_totals = collections.Counter()

with open(SRC, encoding='utf-8-sig', newline='') as f:
    for row in csv.DictReader(f):
        if row['Site Collection'] != 'http://aku.edu':
            continue
        url = row['Website URL'].strip().translate(ZW)
        if not url.startswith('http://aku.edu'):
            continue
        path = url.replace('http://aku.edu', '').strip('/')
        g = (row['SharePoint Group'] or '').strip()
        if not g:
            g = '(direct user assignment)'
        G = groups[g]
        G['rows'] += 1
        G['roles'][row['Assigned Roles'].strip()] += 1
        role_totals[row['Assigned Roles'].strip()] += 1
        la = row['User Login Account'] or ''
        m = DOM.match(la)
        if m:
            G['domains'][m.group(1).lower()] += 1
            G['people'].add(m.group(0).lower())
        elif la.startswith('c:0'):
            G['people'].add('(everyone claim)')
        if row['Permission Scope'] == 'Unique':
            G['webs_unique'].add(path)
            web_groups[path].add(g)
        else:
            G['webs_inherited'].add(path)

# classify each group by what AKU named it
def kind(name):
    n = name.strip()
    if n.startswith('CW ') or 'Writer' in n or 'Writers' in n:
        return 'writer'
    if n.startswith('CA ') or 'Approver' in n or 'Approvers' in n:
        return 'approver'
    if 'Owner' in n:
        return 'owner'
    if n in ('Designers', 'Hierarchy Managers', 'IT Webteam', 'Administrators'):
        return 'platform'
    if ('Visitor' in n or 'Reader' in n or 'Viewers' in n or 'Member' in n
            or n == 'Everyone'):
        return 'reader'
    if 'Translation' in n:
        return 'translator'
    if 'Moderator' in n:
        return 'moderator'
    return 'other'

# the unit a CW/CA pair refers to, e.g. "CW MC PK" -> "MC PK"
def unit(name):
    n = re.sub(r'^(CW|CA)\s+', '', name.strip())
    n = re.sub(r'\s*(News\s*)?(Writers?|Approvers?)$', '', n, flags=re.I)
    return n.strip()

rows = []
for g, G in groups.items():
    rows.append({
        'group': g, 'kind': kind(g), 'unit': unit(g),
        'people': len(G['people']), 'rows': G['rows'],
        'roles': G['roles'].most_common(3),
        'domains': dict(G['domains'].most_common(4)),
        'owns': sorted(w for w in G['webs_unique']
                       if len(web_groups[w]) <= ROOT_DUMP),
    })
rows.sort(key=lambda r: (-r['people'], r['group']))

out = open(paths.work('roles_probe.txt'), 'w', encoding='utf-8')
out.write('%d groups · %d distinct role strings\n' % (len(groups), len(role_totals)))

out.write('\n== every distinct Assigned Roles value ==\n')
for r, n in role_totals.most_common():
    out.write('%8d  %s\n' % (n, r))

out.write('\n== groups by kind ==\n')
byk = collections.Counter(r['kind'] for r in rows)
for k, n in byk.most_common():
    out.write('  %-11s %d groups\n' % (k, n))

out.write('\n== writer/approver pairs (the unit that owns content) ==\n')
units = collections.defaultdict(dict)
for r in rows:
    if r['kind'] in ('writer', 'approver'):
        units[r['unit']][r['kind']] = r
for u in sorted(units):
    w, a = units[u].get('writer'), units[u].get('approver')
    out.write('  %-30s writer=%-4s approver=%-4s owns=%s\n'
              % (u, w['people'] if w else '-', a['people'] if a else '-',
                 sorted(set((w['owns'] if w else []) + (a['owns'] if a else [])))[:4]))

out.write('\n== the 40 largest groups ==\n')
for r in rows[:40]:
    out.write('  %-34s %-9s people=%-4d rows=%-6d owns=%d\n'
              % (r['group'], r['kind'], r['people'], r['rows'], len(r['owns'])))
    out.write('        roles: %s\n' % '; '.join('%s (%d)' % (a, b)
                                                for a, b in r['roles']))
out.close()

json.dump(rows, open(paths.work('groups.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
json.dump({w: sorted(g) for w, g in web_groups.items()
           if len(g) <= ROOT_DUMP},
          open(paths.work('web_owners.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('groups', len(groups), 'units with a writer/approver pair', len(units))
