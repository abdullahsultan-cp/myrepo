"""Turn SharePoint's 336 groups and 35 role strings into a hierarchy of custom

Storyblok roles -- and say, per person, which ones replace what they hold today.

Why this exists
  build_migration_plan.py emits a FLAT list: one `<unit>-editor` / `<unit>-publisher`
  pair per team, 280 roles. Flat has three costs. Someone who runs a whole faculty
  needs twenty roles instead of one. `Design` (11,992 rows) collapses into editor,
  so "may change a component" and "may write a page" become the same grant. And
  `Limited Access` (2,503 rows) -- SharePoint plumbing that grants nothing -- reads
  as a capability.

The model
  A role is a point on two independent axes.

  TIER   where its power reaches. Scope inherits DOWNWARD: a role anchored on
         regions/pakistan/medical-college also covers every department under it.
         space -> region -> entity -> department -> section

  CAPABILITY  what it may do. Each level contains the one below it:
         viewer -> contributor -> approver -> steward -> admin

  Five FUNCTIONAL roles sit outside both axes, because the thing they govern is
  not a folder: assets, taxonomy, component schemas, translation, comments.

  So a role id reads as its own documentation:
         pakistan.medical-college.anaesthesiology.contributor

Nothing here is invented. Every role records the SharePoint groups and role
strings that witness it, and `provenance` separates what the export proves from
what the tier ladder adds by design.

Inputs   plan.json, groups.json (from build_migration_plan.py / probe_csv.py)
         the permissions CSV, re-read for the per-person role strings the
         earlier passes discard

Outputs (Pages-Pipeline/)
  aku-role-hierarchy.csv     one row per custom role
  aku-role-capabilities.csv  one row per action x capability
  aku-old-role-inventory.csv one row per old SharePoint group -> new role
  aku-old-role-strings.csv   one row per old role string -> new capability
  aku-user-roles.csv         one row per person: what they hold -> what to give
  roles.json                 the same, for the portal
"""
import csv, io, os, re, json, collections
import paths

SRC = paths.PERMISSIONS_CSV
ZW = str.maketrans('', '', '​﻿­')
DOM = re.compile(r'i:0#\.w\|([^\\]+)\\(.+)$')
ROOT_DUMP = 30          # a folder listing more groups than this names no owner

plan = json.load(io.open(paths.work('plan.json'), encoding='utf-8'))
groups = json.load(io.open(paths.work('groups.json'), encoding='utf-8'))
GKIND = {g['group']: g['kind'] for g in groups}
GUNIT = {g['group']: g['unit'] for g in groups}
GPEOPLE = {g['group']: g['people'] for g in groups}
GROLES = {g['group']: g['roles'] for g in groups}

FOLDERS = {f['new_path']: f for f in plan['folders']}

# SharePoint web path -> destination folder. Needed early: the group inventory,
# the unit scopes and the per-person grants all start from a web path.
dest_of = {}
for _f in plan['folders']:
    for _s in _f['source_web'].split(';'):
        _s = _s.strip()
        if _s and not _s.startswith('('):
            dest_of[_s] = _f['new_path']

# ---- the capability ladder ----------------------------------------------
# Ordered weakest to strongest. Each level is a superset of the one before, so a
# person needs exactly one content role per scope -- never a stack of them.
LADDER = ['viewer', 'contributor', 'approver', 'steward', 'admin']
RANK = {c: i for i, c in enumerate(LADDER)}

# Roles that govern something other than a folder, so no tier applies.
FUNCTIONAL = ['component-developer', 'asset-librarian', 'taxonomy-manager',
              'translator', 'comment-moderator']

CAP_MEANS = {
    'viewer': 'read any draft or published story in scope, and comment',
    'contributor': 'create and edit drafts in scope; cannot make them public',
    'approver': 'publish, unpublish and schedule in scope',
    'steward': 'also create, rename and move folders inside scope',
    'admin': 'the whole space, including roles and settings',
    'component-developer': 'component schemas and presets, space-wide',
    'asset-librarian': 'the asset library: upload, replace, delete, re-folder',
    'taxonomy-manager': 'datasources and tag lists',
    'translator': 'translated field values only, never structure',
    'comment-moderator': 'comments and discussion threads',
}

# ---- what each capability may do ----------------------------------------
# One row per action, so the matrix is a table AKU can sign off rather than a
# paragraph. `s` = only inside the role's own scope.
ACTIONS = [
    ('Read a published story', 'y', 'y', 'y', 'y', 'y'),
    ('Read an unpublished draft', 'y', 'y', 'y', 'y', 'y'),
    ('Comment on a story', 'y', 'y', 'y', 'y', 'y'),
    ('Create a story', '-', 's', 's', 's', 'y'),
    ('Edit and save a draft', '-', 's', 's', 's', 'y'),
    ('Upload an asset into a story', '-', 's', 's', 's', 'y'),
    ('Publish, so the public sees it', '-', '-', 's', 's', 'y'),
    ('Unpublish or schedule', '-', '-', 's', 's', 'y'),
    ('Delete a story', '-', '-', 's', 's', 'y'),
    ('Create or rename a folder', '-', '-', '-', 's', 'y'),
    ('Move a folder or its stories', '-', '-', '-', 's', 'y'),
    ('Delete a folder', '-', '-', '-', '-', 'y'),
    ('Change a component schema', '-', '-', '-', '-', 'y'),
    ('Edit the asset library outside a story', '-', '-', '-', '-', 'y'),
    ('Edit datasources or tags', '-', '-', '-', '-', 'y'),
    ('Create a role or change its scope', '-', '-', '-', '-', 'y'),
    ('Change space settings or webhooks', '-', '-', '-', '-', 'y'),
]

# ---- old SharePoint role string -> new capabilities ---------------------
# A role string carries several grants at once ("Design, Contribute, Approve"),
# so this returns a SET. Two deliberate silences:
#   Limited Access grants nothing -- SharePoint adds it so a user can traverse to
#   a child item they were given directly. Treating it as a capability is what
#   makes 2,503 rows look like access.
#   Design is not a content grant. It edits layout and markup, which in Storyblok
#   is the component schema -- a space-wide functional role, not a folder one.
def caps_of(role_string):
    r = (role_string or '').lower()
    out = set()
    if 'full control' in r or 'manage permissions' in r:
        out.add('admin')
    if 'manage hierarchy' in r:
        out.add('steward')
    if 'approve' in r:
        out.add('approver')
    if 'contribute' in r or 'edit' in r:
        out.add('contributor')
    if 'read' in r or 'view only' in r:
        out.add('viewer')
    if 'translation' in r:
        out.add('translator')
    return out

# `Design` appears on 26,000 rows -- more than half the grants -- because on a
# SharePoint publishing site it is handed out with Contribute as a matter of
# course. Deriving component-developer from it would tell AKU that 400 content
# people may rewrite component schemas. They may not, and they do not today
# either: Design edits page layout and master pages, which in Storyblok is a
# developer action. So it is NOT carried over as a grant. The only source of
# component-developer is the `Designers` group itself.
def has_design(role_string):
    return 'design' in (role_string or '').lower()

def top_content_cap(caps):
    """The single content role that covers a set of capabilities."""
    c = [x for x in caps if x in RANK]
    return max(c, key=lambda x: RANK[x]) if c else ''

# ---- tier of a folder ---------------------------------------------------
# `kind` is what the plan already decided the folder IS, so read it first and use
# depth only where kind does not say. Recording both keeps the row checkable.
TIER_BY_KIND = {
    'root': 'space', 'region': 'region',
    'entity': 'entity', 'region-folder': 'entity', 'centre': 'entity',
    'office': 'entity', 'department': 'department', 'division': 'department',
}
TIERS = ['space', 'region', 'entity', 'department', 'section']

def is_scaffold(path):
    """`regions/`, `pakistan/entities/`, `medical-college/departments/`.

    These exist so permissions and editors have something to hang on. Nobody owns
    one, so no role may anchor there: a scope that lands on scaffolding means the
    tier above it.
    """
    f = FOLDERS.get(path)
    return bool(f) and f['kind'] == 'container' and path != 'regions'

def normalize(path):
    while path and is_scaffold(path):
        path = path.rsplit('/', 1)[0] if '/' in path else ''
    return path

def tier_of(path):
    if not path or path == 'regions':
        return 'space'
    p = normalize(path)
    if p != path:
        return tier_of(p)
    f = FOLDERS.get(p)
    return TIER_BY_KIND.get(f['kind'], 'section') if f else 'section'

def role_scope(path):
    """The readable scope key: drop the `regions/` scaffold, keep the shape."""
    return re.sub(r'^regions/', '', path) or 'space'

_ids = {}

def role_id(path, cap):
    """`pakistan.medical-college.anaesthesiology.approver`.

    The `entities/` and `departments/` segments come out, the same way
    public_url() drops them: they are there so permissions have something to hang
    on, and a role id that reads like a sentence is the point. If dropping them
    would make two different scopes share one id the full path wins instead --
    a silently merged scope is a silently widened grant.
    """
    key = role_scope(path)
    short = '.'.join(s for s in key.split('/')
                     if s not in ('entities', 'departments')) or 'space'
    rid = '%s.%s' % (short, cap)
    owner = _ids.setdefault(rid, key)
    if owner == key:
        return rid
    return '%s.%s' % (key.replace('/', '.'), cap)

# ---- the anchors: folders that set their own permissions ----------------
# Every other folder inherits, so it needs no role of its own. 159 anchors, not
# 628 folders, and not 280 unit pairs.
anchors = sorted(f['new_path'] for f in plan['folders']
                 if f['own_permissions'] == 'yes')
ANCHOR = set(anchors)

def nearest_anchor(path):
    p = path
    while p:
        if p in ANCHOR:
            return p
        p = p.rsplit('/', 1)[0] if '/' in p else ''
    return ''

def parent_anchor(path):
    return nearest_anchor(path.rsplit('/', 1)[0]) if '/' in path else ''

# ---- which groups witness which anchor ---------------------------------
# managed_by names units; groups.json maps group -> unit. Go through the unit so
# a team that owns four scattered folders is still one team.
UNIT_GROUPS = collections.defaultdict(list)
for g, u in GUNIT.items():
    if u:
        UNIT_GROUPS[u].append(g)

def units_of(folder):
    raw = FOLDERS.get(folder, {}).get('managed_by', '')
    return [u.strip() for u in raw.split(';') if u.strip()]

# ---- lift a scattered scope onto the folder above it --------------------
# EventsOwners is why this exists: 150 people, 33 event microsites, all siblings
# under global/events. Anchoring one role per microsite gave every one of those
# people 33 roles. A hierarchy is supposed to answer that -- if a team owns two
# or more children of the same folder, its scope IS that folder.
#
# The lift stops below the region tier unless the team already owns something at
# that tier. Otherwise a microsite team that happens to own two sibling folders
# would climb, one merge at a time, into running a whole country.
def lift(paths, allow_upto='entity'):
    cur = {p for p in paths if p}
    cap = TIERS.index(allow_upto)
    while True:
        kids = collections.Counter()
        for p in cur:
            if '/' in p:
                kids[p.rsplit('/', 1)[0]] += 1
        target = next((par for par, n in kids.items()
                       if n >= 2 and par in FOLDERS
                       and TIERS.index(tier_of(par)) >= cap), None)
        if target is None:
            break
        cur = {p for p in cur if p.rsplit('/', 1)[0] != target} | {normalize(target)}
        cur.discard('')
    # a folder already covered by an ancestor in the set is redundant
    return sorted(p for p in cur
                  if not any(p != q and p.startswith(q + '/') for q in cur))

def unit_caps(unit):
    """The rungs the export proves this team holds, from its groups' role strings."""
    out = collections.defaultdict(list)
    for g in UNIT_GROUPS.get(unit, []):
        for rs, _n in GROLES.get(g, []):
            for c in caps_of(rs):
                out[c].append(g)
    return out

# ---- build the role rows -----------------------------------------------
role_rows = []
seen_roles = {}

def subtree(path):
    if not path:
        return list(FOLDERS)
    return [p for p in FOLDERS if p == path or p.startswith(path + '/')]

def add_role(path, cap, provenance, groups_in, note='', units_in=()):
    """Create the role for (scope, rung), or merge into the one already there.

    Merging is deliberate. If MC PK and PGME PK both hold approve on the medical
    college, that is ONE role -- a role is a rung at a scope, and which committee
    someone sat on is membership, not identity. Both groups stay in
    `replaces_groups` so the row is still checkable against the export.
    """
    rid = role_id(path, cap)
    r = seen_roles.get(rid)
    if r is not None:
        r['_groups'] |= set(groups_in)
        r['_units'] |= set(units_in)
        if r['provenance'] == 'designed' and groups_in:
            r['provenance'] = 'witnessed'
            r['note'] = note
        return r
    r = {
        'role': rid,
        'tier': tier_of(path),
        'capability': cap,
        'scope_path': path or '(whole space)',
        'scope_folders': len(subtree(path)),
        'parent_role': '',
        'can_publish': 'yes' if cap in ('approver', 'steward', 'admin') else 'no',
        'means': CAP_MEANS[cap],
        'unit': '',
        'members': 0,
        'replaces_groups': '',
        'old_role_strings': '',
        'provenance': provenance,
        'note': note,
        '_groups': set(groups_in),
        '_units': set(units_in),
    }
    seen_roles[rid] = r
    role_rows.append(r)
    return r

# space tier -- one role per rung, always present. Someone has to be able to
# answer for the whole space, and the ladder has to start somewhere.
SPACE_GROUPS_FOR = {
    'admin': ['AKU Owners', 'Administrators', 'IT Webteam'],
    'steward': ['Hierarchy Managers'],
    'approver': ['CA Public Affairs', 'Approvers', 'Global Approvers'],
    'contributor': ['CW Public Affairs'],
    'viewer': ['AKU Visitors', 'Viewers', 'Restricted Readers',
               'Style Resource Readers'],
}
for cap in LADDER:
    gs = [g for g in SPACE_GROUPS_FOR[cap] if g in GPEOPLE]
    add_role('', cap, 'witnessed' if gs else 'designed', gs,
             'central comms and IT hold the space tier today',
             units_in=['(space-wide)'])

# functional roles
FUNC_GROUPS = {
    'component-developer': ['Designers'],
    'translator': ['Translation Managers'],
    'comment-moderator': ['Comments Moderator'],
    'asset-librarian': [],
    'taxonomy-manager': [],
}
for cap in FUNCTIONAL:
    gs = [g for g in FUNC_GROUPS[cap] if g in GPEOPLE]
    r = add_role('', cap, 'witnessed' if gs else 'designed', gs,
                 'governs a space-wide resource, so no folder scope applies',
                 units_in=['(space-wide)'])
    del seen_roles[r['role']]
    r['role'] = cap
    r['tier'] = 'functional'
    r['scope_folders'] = ''
    seen_roles[cap] = r

# ---- the unit roles ------------------------------------------------------
# One role per (scope, rung), built from the teams the export names. A team's
# scope is its anchors, lifted onto the folder above wherever it owns siblings --
# which is what turns EventsOwners' 33 microsites into one role on global/events.
unit_anchors = collections.defaultdict(set)
for p in anchors:
    for u in units_of(p):
        unit_anchors[u].add(p)

# `managed_by` names the unit that OWNS a folder, which misses the umbrella
# groups: EventsOwners holds all 33 event microsites but is named on none of
# them, so without this it gets no role and its 150 people fall back to a grant
# per microsite. A group's own `owns` list is the export's own evidence.
for g in groups:
    u = GUNIT.get(g['group'])
    if not u:
        continue
    for w in (g.get('owns') or []):
        f = dest_of.get(w) or dest_of.get(w.strip('/'))
        if f and f in ANCHOR:
            unit_anchors[u].add(f)

for u in sorted(unit_anchors):
    raw = unit_anchors[u]
    # a team already holding a region or the root may lift that far; nobody else
    at = {tier_of(p) for p in raw}
    ceiling = 'region' if ('region' in at or 'space' in at) else 'entity'
    scopes = lift(raw, ceiling) or sorted(raw)
    if not scopes:
        continue
    caps = unit_caps(u)
    rungs = [c for c in ('contributor', 'approver', 'steward') if c in caps]
    if not rungs:
        rungs = ['contributor']
    # One role per scope, never one role carrying a list of scopes. MC EA owns an
    # event microsite AND the East Africa medical college; folding the college in
    # as a secondary scope of the events role handed it to all 155 people who
    # publish events. A role is one rung at ONE place, and a team that spans two
    # places holds two roles.
    for cap in rungs:
        for sc in scopes:
            add_role(sc, cap, 'witnessed' if caps.get(cap) else 'designed',
                     sorted(set(caps.get(cap, []))),
                     '' if caps.get(cap) else 'team owns the folder but no role '
                                              'string on it proves this rung',
                     units_in=[u])

# ---- the delegation rungs the ladder still needs -------------------------
# A region or entity with no team of its own still needs the rung to exist, or
# there is no way to hand someone a whole faculty without listing its departments.
# `designed` says the export does not witness it -- AKU decides who holds it. Do
# not read one of these as an existing team.
for f in plan['folders']:
    p = f['new_path']
    if f['region'] in ('staging', '') or is_scaffold(p):
        continue
    if tier_of(p) not in ('region', 'entity'):
        continue
    for cap in ('contributor', 'approver'):
        add_role(p, cap, 'designed', [],
                 'rung exists so the tier below can be delegated; AKU says who '
                 'holds it', units_in=['(vacant)'])

# ---- parent_role: the rung above that already covers this scope ----------
# This is the column that makes the list a hierarchy rather than a list. Whoever
# holds the parent role covers everything this role covers, so the parent is
# always the shorter grant to give.
def parent_of(path, cap):
    p = path
    while '/' in p:
        p = p.rsplit('/', 1)[0]
        q = normalize(p)
        if q and role_id(q, cap) in seen_roles and role_id(q, cap) != role_id(path, cap):
            return role_id(q, cap)
    return role_id('', cap) if path else ''

for r in role_rows:
    if r['tier'] != 'functional':
        path = '' if r['scope_path'] == '(whole space)' else r['scope_path']
        r['parent_role'] = parent_of(path, r['capability']) if path else ''
    gs = sorted(r.pop('_groups'))
    r['unit'] = '; '.join(sorted(r.pop('_units'))) or '(vacant)'
    r['replaces_groups'] = '; '.join(gs)
    r['members'] = sum(GPEOPLE.get(g, 0) for g in gs)
    strs = sorted({rs for g in gs for rs, _ in GROLES.get(g, [])})
    r['old_role_strings'] = ' | '.join(strs[:4]) + (' …' if len(strs) > 4 else '')

# every distinct role string, and what it becomes
str_counts = collections.Counter()
for g in groups:
    for rs, n in g['roles']:
        str_counts[rs] += n
str_rows = []
for rs, n in str_counts.most_common():
    caps = caps_of(rs)
    content = top_content_cap(caps)
    func = sorted(c for c in caps if c in FUNCTIONAL)
    note = ''
    if not caps:
        note = ('SharePoint plumbing — auto-granted so a user can traverse to an '
                'item granted directly. Grants nothing on its own.')
    if has_design(rs):
        note = (note + ' ' if note else '') + (
            'Design is not carried over: on a publishing site it ships with '
            'Contribute by default, and layout in Storyblok is a developer '
            'action. Only the Designers group becomes component-developer.')
    str_rows.append({
        'old_role_string': rs,
        'permission_rows': n,
        'new_capability': content or '(none)',
        'plus_functional_role': '; '.join(func),
        'means': CAP_MEANS.get(content, '') if content else 'nothing',
        'note': note,
    })

# ---- per person: what they hold today -> what to give them -------------
people = {}
rows = []
with io.open(SRC, encoding='utf-8-sig', newline='') as f:
    for row in csv.DictReader(f):
        if row['Site Collection'] != 'http://aku.edu':
            continue
        url = row['Website URL'].strip().translate(ZW)
        if not url.startswith('http://aku.edu'):
            continue
        if row['Permission Scope'] != 'Unique':
            continue
        rows.append((url.replace('http://aku.edu', '').strip('/'),
                     (row['SharePoint Group'] or '').strip(), row))

per_web_groups = collections.defaultdict(set)
for web, g, _ in rows:
    if g:
        per_web_groups[web].add(g)
DUMP = {w for w, gs in per_web_groups.items() if len(gs) > ROOT_DUMP}

SPACE_GROUPS = set(SPACE_GROUPS_FOR['admin']) | {
    'AKU Visitors', 'Designers', 'Hierarchy Managers', 'Approvers', 'Viewers',
    'Restricted Readers', 'Style Resource Readers', 'Translation Managers',
    'Comments Moderator', 'AKUJobOwners', 'None (Direct Access)'}
SPACE_ROLE = {}
for cap, gs in SPACE_GROUPS_FOR.items():
    for g in gs:
        SPACE_ROLE[g] = role_id('', cap)
for cap, gs in FUNC_GROUPS.items():
    for g in gs:
        SPACE_ROLE[g] = cap

for web, g, row in rows:
    la = row['User Login Account'] or ''
    m = DOM.match(la)
    if not m:
        continue
    domain, account = m.group(1).lower(), m.group(2).lower()
    key = domain + '\\' + account
    p = people.setdefault(key, {
        'name': (row['User Display Name'] or account).strip(),
        'email': (row['User Email'] or '').strip(), 'login': la,
        'campus': domain, 'groups': set(), 'old_strings': set(),
        'grants': {}, 'flat': set(), 'func': set()})
    if not p['email'] and row['User Email']:
        p['email'] = row['User Email'].strip()
    if g:
        p['groups'].add(g)
    p['old_strings'].add((row['Assigned Roles'] or '').strip())
    caps = caps_of(row['Assigned Roles'])
    p['func'] |= {c for c in caps if c in FUNCTIONAL}
    if web in DUMP or g in SPACE_GROUPS:
        continue
    folder = dest_of.get(web)
    if folder is None:
        continue
    cap = top_content_cap(caps)
    if not cap:
        continue                      # Limited Access only: not a grant
    cur = p['grants'].get(folder)
    if cur is None or RANK[cap] > RANK[cur]:
        p['grants'][folder] = cap
    if GUNIT.get(g):
        p['flat'].add('%s-%s' % (re.sub(r'[^a-z0-9]+', '-', GUNIT[g].lower()).strip('-'),
                                 'publisher' if cap == 'approver' else 'editor'))

# ---- folder grant -> the role that covers it ----------------------------
# Walk up from the folder to the nearest scope that carries a role at this rung.
# This is where the lift pays off: all 33 event microsites resolve to the one
# role on global/events, instead of 33 roles on 150 people.
COVER = collections.defaultdict(set)
for r in role_rows:
    if r['tier'] == 'functional':
        continue
    if r['scope_path'] != '(whole space)':
        COVER[r['capability']].add(r['scope_path'])

def role_for(folder, cap):
    """The narrowest role at or above `folder` granting `cap` -- or a lower rung
    at the same scope, never a wider scope than the grant."""
    p = folder
    while True:
        for c in reversed(LADDER[:RANK[cap] + 1]):
            if p in COVER[c] and role_id(p, c) in seen_roles:
                return role_id(p, c)
        if '/' not in p:
            break
        p = p.rsplit('/', 1)[0]
    return role_id('', cap)

# ---- old-site inventory: every group, and where it lands ---------------
# "all the roles and permission of the old site" means nothing may be dropped
# silently. One row per group, including the ones that become no role at all --
# `Limited Access` on its own is real in SharePoint and empty here, and the row
# has to say so rather than vanish.
old_rows = []
for g in groups:
    name = g['group']
    caps = set()
    for rs, _n in g['roles']:
        caps |= caps_of(rs)
    content = top_content_cap(caps)
    func = sorted(c for c in caps if c in FUNCTIONAL)
    lands = []
    if name == 'None (Direct Access)':
        # SharePoint's label for a permission handed to a person with no group
        # behind it. There is no group to translate, so these 23 people are
        # resolved individually in aku-user-roles.csv.
        lands = ['(per person — see aku-user-roles.csv)']
    elif name in SPACE_ROLE:
        # a space-level group -- and these must be read as space-level, or
        # `Viewers` looks like the owner of the 113 folders it is scoped onto
        lands = [SPACE_ROLE[name]]
    elif content:
        # resolve through the unit's own roles, the same way a person's grant
        # does. Going folder-by-folder instead lists 26 microsites for
        # EventsOwners when the answer is the one role on global/events.
        lands = [r['role'] for r in role_rows
                 if name in r['replaces_groups'].split('; ')
                 and r['capability'] == content]
        if not lands:
            lands = [r['role'] for r in role_rows
                     if name in r['replaces_groups'].split('; ')]
        if not lands:
            lands = [role_id('', content)]
    lands += [c for c in func if c in seen_roles]
    uniq = sorted(set(lands))
    old_rows.append({
        'sharepoint_group': name,
        'kind': g['kind'],
        'unit': g['unit'],
        'members': g['people'],
        'permission_rows': g['rows'],
        'old_role_strings': ' | '.join(rs for rs, _ in g['roles'][:4]),
        'old_capability': content or '(none — grants nothing)',
        'new_roles': ('; '.join(uniq[:4]) + (' …+%d' % (len(uniq) - 4)
                                             if len(uniq) > 4 else ''))
                     or '(no role — plumbing only)',
        'new_role_count': len(uniq),
        'folders_owned': len(g.get('owns') or []),
    })
old_rows.sort(key=lambda r: (-r['members'], r['sharepoint_group']))

def collapse(grants):
    """Drop a grant an ancestor already covers.

    This is the whole point of the tier ladder: holding approver on
    pakistan/medical-college already covers every department under it, so the
    department rows are noise. Keep the shallowest anchor per capability chain.
    """
    keep = {}
    for a, cap in grants.items():
        redundant = False
        for b, cap2 in grants.items():
            if a != b and a.startswith(b + '/') and RANK[cap2] >= RANK[cap]:
                redundant = True
                break
        if not redundant:
            keep[a] = cap
    return keep

ROLE_BY_ID = {r['role']: r for r in role_rows}

user_rows = []
for key, p in people.items():
    kept = collapse(p['grants'])
    new = {role_for(a, cap) for a, cap in kept.items()}
    # resolving to roles can itself make one redundant: two departments that both
    # resolve to their faculty are the same role twice, and a contributor role is
    # noise beside an approver role on the same scope
    for r in sorted(new):
        rr = ROLE_BY_ID.get(r)
        if not rr:
            continue
        sp = rr['scope_path']
        for other in list(new):
            o = ROLE_BY_ID.get(other)
            if not o or other == r:
                continue
            wider = o['scope_path'] == '(whole space)' or (
                sp != '(whole space)' and sp.startswith(o['scope_path'] + '/'))
            if (wider or o['scope_path'] == sp) and \
               RANK.get(o['capability'], -1) >= RANK.get(rr['capability'], -1) and \
               not (o['scope_path'] == sp and o['capability'] == rr['capability']):
                new.discard(r)
                break
    for g in p['groups']:
        if g in SPACE_ROLE:
            new.add(SPACE_ROLE[g])
    for c in p['func']:
        if c in seen_roles:
            new.add(c)
    # The space rungs arrive last, from the space-level groups, and they outrank
    # everything: someone holding space.admin does not also need approver on 17
    # faculties. Same rule as the folder collapse, applied at the top of the tree.
    space_rank = max((RANK[c] for c in LADDER if role_id('', c) in new), default=-1)
    if space_rank >= 0:
        for r in list(new):
            rr = ROLE_BY_ID.get(r)
            if rr and rr['tier'] != 'functional' and rr['role'] != role_id(
                    '', LADDER[space_rank]) and RANK.get(rr['capability'], 9) <= space_rank:
                new.discard(r)
        # admin is the one rung that also covers the functional roles -- it is the
        # only capability the matrix gives component schemas and settings to
        if space_rank == RANK['admin']:
            for r in list(new):
                if r in FUNCTIONAL:
                    new.discard(r)

    if not new:
        new = {role_id('', 'viewer')}
    caps_held = {r['capability'] for r in role_rows if r['role'] in new}
    top = top_content_cap(caps_held) or 'viewer'

    # Where someone holds the same rung on several entities inside one region,
    # the region role would replace the lot. Offer it, never apply it: widening
    # a real person's access is AKU's decision, not a script's.
    simplify = ''
    by_region = collections.defaultdict(list)
    for rid in new:
        rr = ROLE_BY_ID.get(rid)
        if rr and rr['tier'] == 'entity' and rr['scope_path'].startswith('regions/'):
            by_region[(rr['scope_path'].split('/')[1], rr['capability'])].append(rid)
    best = max(by_region.items(), key=lambda kv: len(kv[1]), default=None)
    if best and len(best[1]) >= 3:
        (reg, cap), held = best
        cand = role_id('regions/' + reg, cap)
        if cand in seen_roles:
            simplify = '%s would replace %d entity roles' % (cand, len(held))
    user_rows.append({
        'name': p['name'], 'email': p['email'], 'login': p['login'],
        'campus': p['campus'],
        'old_groups': '; '.join(sorted(p['groups'])),
        'old_group_count': len(p['groups']),
        'old_role_strings': ' | '.join(sorted(x for x in p['old_strings'] if x)),
        'old_flat_roles': len(p['flat'] | {r for r in new if r.startswith('space.')}),
        'new_roles': '; '.join(sorted(new)),
        'new_role_count': len(new),
        'top_capability': top,
        'highest_tier': min(
            (r['tier'] for r in role_rows if r['role'] in new),
            key=lambda t: TIERS.index(t) if t in TIERS else 99, default=''),
        'simplify_to': simplify,
        'folders_before_collapse': len(p['grants']),
        'folders_after_collapse': len(kept),
        'scopes': '; '.join(sorted({ROLE_BY_ID[r]['scope_path'] for r in new
                                    if r in ROLE_BY_ID
                                    and ROLE_BY_ID[r]['tier'] != 'functional'})),
    })
user_rows.sort(key=lambda r: (RANK.get(r['top_capability'], 0) * -1,
                              -r['new_role_count'], r['name'].lower()))

# ---- write ---------------------------------------------------------------
def write_csv(name, rows, cols):
    with io.open(paths.out(name), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)

ROLE_COLS = ['role', 'tier', 'capability', 'scope_path', 'scope_folders',
             'parent_role', 'can_publish', 'unit', 'members',
             'replaces_groups', 'old_role_strings', 'provenance', 'means', 'note']
matrix_rows = [dict(zip(['action'] + LADDER, a)) for a in ACTIONS]
USER_COLS = ['name', 'email', 'campus', 'top_capability', 'highest_tier',
             'new_role_count', 'new_roles', 'simplify_to', 'old_group_count',
             'old_groups', 'old_role_strings', 'folders_before_collapse',
             'folders_after_collapse', 'scopes', 'login']

role_rows.sort(key=lambda r: (TIERS.index(r['tier']) if r['tier'] in TIERS else 99,
                              r['scope_path'], RANK.get(r['capability'], 9)))
write_csv('aku-role-hierarchy.csv', role_rows, ROLE_COLS)
write_csv('aku-role-capabilities.csv', matrix_rows, ['action'] + LADDER)
write_csv('aku-old-role-inventory.csv', old_rows,
          ['sharepoint_group', 'kind', 'unit', 'members', 'permission_rows',
           'old_role_strings', 'old_capability', 'new_roles', 'new_role_count',
           'folders_owned'])
write_csv('aku-old-role-strings.csv', str_rows,
          ['old_role_string', 'permission_rows', 'new_capability',
           'plus_functional_role', 'means', 'note'])
write_csv('aku-user-roles.csv', user_rows, USER_COLS)

json.dump({'roles': role_rows, 'matrix': matrix_rows, 'ladder': LADDER,
           'tiers': TIERS, 'functional': FUNCTIONAL, 'means': CAP_MEANS,
           'old_groups': old_rows, 'old_strings': str_rows, 'users': user_rows},
          io.open(paths.work('roles.json'), 'w', encoding='utf-8'),
          ensure_ascii=False)

by_tier = collections.Counter(r['tier'] for r in role_rows)
print('roles %d  (%s)' % (len(role_rows),
      '  '.join('%s %d' % (t, by_tier[t]) for t in TIERS + ['functional'] if by_tier[t])))
print('old groups %d | old role strings %d | people %d'
      % (len(old_rows), len(str_rows), len(user_rows)))
print('folder-level grants today %d -> role assignments %d  (max per person %d)'
      % (sum(r['folders_before_collapse'] for r in user_rows),
         sum(r['new_role_count'] for r in user_rows),
         max(r['new_role_count'] for r in user_rows)))
print('%d people need one role, %d need two or three, %d need more'
      % (sum(1 for r in user_rows if r['new_role_count'] == 1),
         sum(1 for r in user_rows if 2 <= r['new_role_count'] <= 3),
         sum(1 for r in user_rows if r['new_role_count'] > 3)))
print('designed (AKU must confirm): %d'
      % sum(1 for r in role_rows if r['provenance'] == 'designed'))
