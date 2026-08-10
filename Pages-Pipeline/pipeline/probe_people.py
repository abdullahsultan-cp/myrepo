"""Who, by name, can edit what — and the Storyblok role each person should get.

The permissions export names real people. This turns it into the answer to
"what should Ambreen get?": her groups, the capability each group carries, the
folders it applies to, and therefore the Storyblok roles to put her in.

Only Unique-scope rows are grants. Inherited rows repeat the AKU-wide groups into
every folder and would make everyone look like an administrator of everything.
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

plan = json.load(open(paths.work('plan.json'), encoding='utf-8'))
groups = json.load(open(paths.work('groups.json'), encoding='utf-8'))
GKIND = {g['group']: g['kind'] for g in groups}
GUNIT = {g['group']: g['unit'] for g in groups}

# source web -> destination folder, from the plan
dest_of = {}
for r in plan['folders']:
    for s in r['source_web'].split(';'):
        s = s.strip()
        if s and not s.startswith('('):
            dest_of[s] = r['new_path']

ROLE_OF = {}
for r in plan['roles']:
    ROLE_OF[(r['unit'], r['capability'])] = r['storyblok_role']

def capability(role_string):
    r = (role_string or '').lower()
    if 'manage permissions' in r or r.startswith('full control'):
        return 'admin'
    if 'manage hierarchy' in r:
        return 'structure'
    if 'translation' in r:
        return 'translator'
    if 'approve' in r:
        return 'publisher'
    if 'contribute' in r or 'edit' in r:
        return 'editor'
    return 'viewer'

CAP_RANK = {'admin': 0, 'structure': 1, 'publisher': 2, 'editor': 3,
            'translator': 4, 'viewer': 5}

# These groups are space-level, not folder-level. SharePoint scopes them onto ~163
# folders each, which would make every member look like the owner of 163 folders.
# They map to a space-wide Storyblok role instead; a person's real folder grants
# come only from their unit groups (CW/CA <X>, FacultyOwners-<x>, <X> News Writer).
SPACE_GROUPS = {
    'AKU Owners', 'AKU Visitors', 'Designers', 'Hierarchy Managers', 'Approvers',
    'Viewers', 'Restricted Readers', 'Style Resource Readers',
    'Translation Managers', 'Comments Moderator', 'Administrators', 'IT Webteam',
    'AKUJobOwners', 'None (Direct Access)',
}
SPACE_ROLE = {
    'AKU Owners': 'space-admin', 'Administrators': 'space-admin',
    'IT Webteam': 'space-admin', 'Hierarchy Managers': 'structure-manager',
    'Translation Managers': 'translator', 'Comments Moderator': 'comment-moderator',
    'AKU Visitors': 'viewer', 'Viewers': 'viewer', 'Restricted Readers': 'viewer',
    'Style Resource Readers': 'viewer', 'Designers': 'space-admin',
    'Approvers': 'central-comms-publisher',
}

people = {}
web_groupcount = collections.Counter()
rows = []
with open(SRC, encoding='utf-8-sig', newline='') as f:
    for row in csv.DictReader(f):
        if row['Site Collection'] != 'http://aku.edu':
            continue
        url = row['Website URL'].strip().translate(ZW)
        if not url.startswith('http://aku.edu'):
            continue
        if row['Permission Scope'] != 'Unique':
            continue
        web = url.replace('http://aku.edu', '').strip('/')
        g = (row['SharePoint Group'] or '').strip()
        web_groupcount[(web, g)] += 1
        rows.append((web, g, row))

# the 31 folders that list the whole roster name no owner; a grant there is not
# a real grant, it is the site-wide list leaking in
roster = collections.Counter()
for web, g, _ in rows:
    roster[web] += 0
per_web_groups = collections.defaultdict(set)
for web, g, _ in rows:
    if g:
        per_web_groups[web].add(g)
DUMP = {w for w, gs in per_web_groups.items() if len(gs) > ROOT_DUMP}

for web, g, row in rows:
    la = row['User Login Account'] or ''
    m = DOM.match(la)
    if not m:
        continue                      # claims like "Everyone" are not a person
    domain, account = m.group(1).lower(), m.group(2).lower()
    key = domain + '\\' + account
    name = (row['User Display Name'] or account).strip()
    email = (row['User Email'] or '').strip()
    cap = capability(row['Assigned Roles'])
    p = people.setdefault(key, {
        'key': key, 'name': name, 'login': la, 'email': email,
        'campus': domain, 'groups': set(), 'grants': {}, 'caps': set()})
    if email and not p['email']:
        p['email'] = email
    if g:
        p['groups'].add(g)
    p['caps'].add(cap)
    if web in DUMP or g in SPACE_GROUPS:
        continue     # roster leak or a space-level group, not a folder grant
    folder = dest_of.get(web)
    if folder is None:
        continue
    cur = p['grants'].get(folder)
    if cur is None or CAP_RANK[cap] < CAP_RANK[cur['capability']]:
        p['grants'][folder] = {'folder': folder, 'capability': cap,
                               'group': g, 'unit': GUNIT.get(g, '')}

# the Storyblok roles each person should be put in
out = []
for p in people.values():
    roles = set()
    for gr in p['grants'].values():
        r = ROLE_OF.get((gr['unit'], gr['capability']))
        if r:
            roles.add(r)
    for g in p['groups']:
        if g in SPACE_ROLE:
            roles.add(SPACE_ROLE[g])
    if not roles and p['grants']:
        roles.add('viewer')
    # rank by what they can actually do, from the roles they end up with
    if 'space-admin' in roles:
        top = 'admin'
    elif any(r.endswith('-publisher') for r in roles):
        top = 'publisher'
    elif any(r.endswith('-editor') for r in roles):
        top = 'editor'
    elif 'structure-manager' in roles:
        top = 'structure'
    else:
        top = 'viewer'
    out.append({
        'name': p['name'], 'email': p['email'], 'login': p['login'],
        'campus': p['campus'], 'top_capability': top,
        'groups': sorted(p['groups']),
        'folders': sorted(p['grants']),
        'grants': sorted(p['grants'].values(), key=lambda g: g['folder']),
        'storyblok_roles': sorted(roles),
    })
RANK = {'admin': 0, 'publisher': 1, 'editor': 2, 'structure': 3, 'translator': 4,
        'viewer': 5}
out.sort(key=lambda p: (RANK[p['top_capability']], -len(p['folders']),
                        p['name'].lower()))

json.dump(out, open(paths.work('people.json'), 'w', encoding='utf-8'),
          ensure_ascii=False)

CAMPUS = {'aku': 'Karachi', 'nbi': 'Nairobi', 'dar': 'Dar es Salaam',
          'ismc': 'London', 'scholar': 'service account'}
w = open(paths.work('people_probe.txt'), 'w', encoding='utf-8')
w.write('%d named people hold at least one permission on aku.edu\n' % len(out))
w.write('with a real folder grant: %d\n'
        % sum(1 for p in out if p['folders']))
w.write('\nby campus directory\n')
for k, v in collections.Counter(p['campus'] for p in out).most_common():
    w.write('  %-8s %-16s %d\n' % (k, CAMPUS.get(k, ''), v))
w.write('\nby highest capability\n')
for k, v in collections.Counter(p['top_capability'] for p in out).most_common():
    w.write('  %-11s %d\n' % (k, v))
w.write('\nthe 25 people with the widest access\n')
for p in out[:25]:
    w.write('  %-30s %-34s %-9s %d folders · roles: %s\n'
            % (p['name'][:30], p['email'][:34], p['top_capability'],
               len(p['folders']), ', '.join(p['storyblok_roles'][:3])))
w.close()
print('people', len(out), '| with grants',
      sum(1 for p in out if p['folders']))
