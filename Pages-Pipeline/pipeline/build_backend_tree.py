"""build_backend_tree.py -- the region/entity/department tree, for the backend.

`out/AKU-Hierarchy-Map.json` is the whole picture: 1,384 nodes, every section
and every `news`/`blogs`/`events` leaf. The backend does not need most of it.
The backend owns exactly three tables --

    regions            region_entities            entity_departments

-- and it seeds `news`, `blogs` and `events` inside each row it creates. So this
is the same join, cut down to the 190 nodes those three tables cover, and
written in the backend's OWN vocabulary rather than ours: `shortName`,
`storyblokFolderId`, and the row's UUID, so a value can be pasted into a table
without translating anything first.

The seed shape is read off the dev's own `regions/test` folder rather than
assumed, and it is not the same at all three levels:

    region      blogs  entities  events  news
    entity      blogs  departments  events  news
    department  blogs  events  news              <- no `departments` below it

Two things to know before applying it.

**`action` says what to do, and only 38 of 190 rows are anything but `keep`.**
The tree is mostly already right; what matters is the small set that is not.

    keep     it exists, in the right place            do nothing
    adopt    it exists in Storyblok, the DB has no row  write the id into the DB
    create   the pages plan needs it, it is not there   create it, seed its leaves
    rename   same folder, different slug                rename; stories move with it

**A rename is the only action that moves live stories**, so each one carries
`from` and `to` blocks with both ids, and a flat `moves` array repeats them at
the top level -- a script applying three renames should not have to walk the
tree to find them.

Inputs   out/aku-hierarchy-map.csv            the join, with actions
         data/backend/{regions,region_entities,entity_departments}.json
         ../storyblok_space/folder_tree.json  refresh it first
Outputs  out/AKU-Backend-Tree.json   the tree, and ONLY the tree -- a bare JSON
                                     array of regions. This is the file the
                                     backend dev is sent.
         out/aku-folder-aliases.json where the pages plan spells a folder out in
                                     full and the space uses a short code. Not
                                     the backend's problem: it is for whoever
                                     creates the pages, who would otherwise look
                                     for `.../departments/fam-med`, not find it,
                                     and create the duplicate this avoided.
"""
import collections
import csv
import datetime
import json
import os
import re

import paths

SPACE_ID = '289824742951963'

# ---- the backend's own tables ---------------------------------------------
# Each file is a query dump: one top-level key, whose name is the SQL that
# produced it, holding the rows. The key is read rather than hardcoded because
# it carries whitespace and a trailing newline from whoever ran the query.
def table(name):
    with open(paths.data('backend/%s.json' % name), encoding='utf-8') as fh:
        doc = json.load(fh)
    rows = next(iter(doc.values()))
    if not isinstance(rows, list):
        raise SystemExit('%s.json is not a query dump: expected one key holding '
                         'a list of rows, found %r' % (name, type(rows).__name__))
    return rows


DB_REGIONS = table('regions')
DB_ENTITIES = table('region_entities')
DB_DEPTS = table('entity_departments')

# Keyed by Storyblok folder id, which is the one value the DB and the space
# agree on. Short names collide across regions -- there is an `MC` in PK, KE and
# TZ -- so a short name cannot be the key.
DB_BY_SB = {}
for _rows, _lvl in ((DB_REGIONS, 'region'), (DB_ENTITIES, 'entity'),
                    (DB_DEPTS, 'department')):
    for _r in _rows:
        _sb = str(_r.get('storyblokFolderId') or '')
        if _sb:
            DB_BY_SB[_sb] = (_lvl, _r)

# ---- the live space ------------------------------------------------------
SB = {}
# Resolved through paths.ROOT, the way build_hierarchy_map.py does it. Not by
# counting dirname() calls -- that has broken four times in this repo.
SNAPSHOT = os.path.join(paths.ROOT, 'storyblok_space', 'folder_tree.json')
with open(SNAPSHOT, encoding='utf-8') as fh:
    for f in json.load(fh)['folders']:
        SB[f['full_slug']] = f

# The seed shape, read off the folder the dev built to show us: regions/test,
# regions/test/entities/testent, and .../departments/testdep. Asserted rather
# than hardcoded so that if the dev changes the template this file says so
# instead of quietly seeding the old one.
SEED = {}
for _probe, _lvl in (('regions/test', 'region'),
                     ('regions/test/entities/testent', 'entity'),
                     ('regions/test/entities/testent/departments/testdep',
                      'department')):
    _kids = sorted(v['slug'] for v in SB.values()
                   if _probe in SB and v['parent_id'] == SB[_probe]['id'])
    SEED[_lvl] = _kids or None

# The dev built these to show us the seed shape, and they must not be handed
# back as work: `regions/test/entities/testent` classifies as a real entity to
# adopt, and its parent `regions/test` classifies as a stray, so seeding this
# would have created a Test region in the backend AND left testent orphaned.
#
# Written as explicit PATHS, not as a match on the word "test". A substring
# filter would be shorter and would eventually catch something real -- there is
# already a `regions/pk/announce/test`, and AKU publishes pages about testing.
# The two paths below are the only ones the dev has said are scaffolding.
TEST_SCAFFOLD = (
    'regions/test',              # Region: Test / Entity: TestEnt / Dept: TestDep
    'regions/gl/entities/test',  # the same shape, one level down
)


def is_scaffold(path):
    return any(path == t or path.startswith(t + '/') for t in TEST_SCAFFOLD)


# ---- the same folder under two names ------------------------------------
# The pages plan spells an entity out in full; the space uses a short code. Most
# of the time the join reconciles them, but where it does not the node arrives
# as `create` and seeding it would build a SECOND folder for an institute that
# already has one -- beside the original, which holds the stories.
#
# One case is real: the pages plan wants
# `regions/pk/entities/centre-for-regenerative-medicine`, and the space has had
# `regions/pk/entities/crm` since July, whose DB title is "Centre for
# Regenerative Medicine and Stem Cell Research". The plan's slug is a PREFIX of
# that title, not equal to it, which is why nothing matched them.
#
# Written as an explicit table, and then guarded. Prefix-matching every create
# against every DB title would have found this one and would eventually merge
# two institutes that genuinely share an opening phrase. So the table is the fix
# and `check_for_unlisted_duplicates` is the alarm: it stops the build on any
# case that looks like this one and is not listed here.
ENTITY_ALIASES = {
    ('pk', 'centre-for-regenerative-medicine'): 'crm',
}


def _norm(text):
    out = (text or '').lower().replace('&', 'and')
    return '-'.join(x for x in re.split(r'[^a-z0-9]+', out) if x)


def check_for_unlisted_duplicates(creates, existing_by_region):
    """Stop if a create looks like an entity the space already has."""
    suspect = []
    for region, slug, title in creates:
        if (region, slug) in ENTITY_ALIASES:
            continue
        for short, db_title in existing_by_region.get(region, {}).items():
            a, b = _norm(slug), _norm(db_title)
            # A prefix either way, and long enough that the shared opening is
            # the institute's name rather than the words "centre for".
            if len(a) >= 14 and len(b) >= 14 and (a.startswith(b) or b.startswith(a)):
                suspect.append('regions/%s/entities/%s looks like the existing '
                               'regions/%s/entities/%s (%r)'
                               % (region, slug, region, short, db_title))
    if suspect:
        raise SystemExit(
            'these would be created beside an entity that already exists, and '
            'the original holds the stories. Add each to ENTITY_ALIASES with '
            'the short code it belongs to, or confirm it is genuinely separate '
            'and add it to the table pointing at itself:\n  '
            + '\n  '.join(suspect))


# ---- the join, already computed -----------------------------------------
MAP = list(csv.DictReader(open(paths.out('aku-hierarchy-map.csv'),
                               encoding='utf-8-sig')))
BACKEND_LEVELS = {'region', 'entity', 'department'}
OWNED = [r for r in MAP if r['level'] in BACKEND_LEVELS
         and not is_scaffold(r['to_path'] or r['from_path'])]
EXCLUDED = [r for r in MAP if r['level'] in BACKEND_LEVELS
            and is_scaffold(r['to_path'] or r['from_path'])]


def path_of(row):
    return row['to_path'] or row['from_path']


# Every entity the space already has in each region, by short code, with the
# title the backend DB gives it -- the only place the full name is recorded.
EXISTING_ENTITIES = collections.defaultdict(dict)
for _slug, _f in SB.items():
    _parts = _slug.split('/')
    if len(_parts) == 4 and _parts[0] == 'regions' and _parts[2] == 'entities':
        _row = DB_BY_SB.get(str(_f['id']), (None, {}))[1]
        EXISTING_ENTITIES[_parts[1]][_parts[3]] = _row.get('title') or _f['name']

check_for_unlisted_duplicates(
    [(path_of(r).split('/')[1], path_of(r).rsplit('/', 1)[-1],
      r['to_title'] or r['from_title'])
     for r in OWNED if r['level'] == 'entity' and r['action'] == 'create'],
    EXISTING_ENTITIES)


def node(row):
    """One backend row, in the backend's vocabulary."""
    path = path_of(row)
    slug = path.rsplit('/', 1)[-1]
    sb_id = row['sb_id'] or row['from_sb_id'] or None
    db = DB_BY_SB.get(str(sb_id or ''), (None, {}))[1]
    out = {
        'action': row['action'],
        'level': row['level'],
        'title': row['to_title'] or row['from_title'],
        'shortName': (row['to_short'] or row['from_short'] or slug).upper(),
        'slug': slug,
        'path': path,
        'storyblokFolderId': str(sb_id) if sb_id else None,
        'dbId': db.get('id') or row['from_db_id'] or None,
        'stories': int(row['stories'] or 0),
        'pages': int(row['pages_subtree'] or 0),
        # What the backend makes on its own, so none of it is anybody's work.
        # The two CONTAINER folders are left out of this list and reported
        # separately below, because they are conditional: the backend seeds them
        # when the row gets its first child, which is why 28 of the 60 entities
        # have no departments folder yet and why the DB carries
        # isDepartmentFolderCreated as a column at all.
        'autoSeeded': [x for x in (SEED.get(row['level']) or [])
                       if x not in ('entities', 'departments')],
    }
    # AKU's decision, 8 Sep 2026: THE SPACE'S SHORT CODE WINS, so nothing is
    # renamed. The three rename rows the join produced all made the code LONGER
    # -- FM to FAM-MED, ONC to ONCO, PSYCH to PSYCHIATRY -- which is the
    # opposite of the naming rule everything else follows, and each one would
    # have moved live stories to achieve it: 17 stories, no reader benefit.
    #
    # The folder keeps its name and its id. What the pages plan calls it is
    # recorded as pagesPlanSlug instead, so whoever creates pages under it knows
    # the two names are one folder. Dropping that would leave the pages plan
    # pointing at a path nothing will ever create.
    # An entity the space already holds under a short code. Same treatment as
    # a declined rename: keep the folder that exists, record the plan's name.
    alias_to = ENTITY_ALIASES.get((path.split('/')[1], slug))
    if alias_to and row['level'] == 'entity':
        exists = 'regions/%s/entities/%s' % (path.split('/')[1], alias_to)
        sb = SB.get(exists)
        out['action'] = 'keep'
        out['slug'] = alias_to
        out['shortName'] = alias_to.upper()
        out['path'] = exists
        out['storyblokFolderId'] = str(sb['id']) if sb else None
        out['dbId'] = DB_BY_SB.get(str(sb['id']) if sb else '', (None, {}))[1] \
            .get('id') or out['dbId']
        out['pagesPlanSlug'] = slug
        out['renameDeclined'] = (
            'the pages plan calls this %s; the space has had %s since July and '
            'the stories are filed there. Kept as-is. File pages planned for '
            '%s into this folder.' % (slug, exists, slug))
        return out
    if row['action'] == 'rename':
        here = row['from_path'].rsplit('/', 1)[-1]
        out['action'] = 'keep'
        out['shortName'] = (row['from_short'] or here).upper()
        out['slug'] = here
        out['path'] = row['from_path']
        out['storyblokFolderId'] = row['from_sb_id'] or None
        out['dbId'] = row['from_db_id'] or out['dbId']
        out['pagesPlanSlug'] = slug
        out['renameDeclined'] = (
            'the pages plan calls this %s; the space calls it %s and %s stories '
            'are filed there. Kept as-is -- renaming would lengthen the short '
            'code and move live stories for no reader benefit. File pages '
            'planned for %s into this folder.'
            % (slug, here, row['moves_stories'] or row['stories'] or 0, slug))
    if row['remark']:
        out['remark'] = row['remark']
    return out


# ---- nest it ------------------------------------------------------------
# Keyed by the node's FINAL path, not the path it arrived with. An aliased node
# is rewritten to point at the folder that already exists, so it lands on a key
# something else already holds -- and keying by the arrival path let both
# through: `regions/pk/entities/centre-for-regenerative-medicine` and
# `regions/pk/entities/crm` became two entity nodes with ONE dbId, one folder
# id, and the same parent.
#
# The backend dev's dry run caught it, merged first-seen, and carried on. It
# only survived because his merge kept the departments; first-seen here was the
# alias node, which has none, so a merge that took the first node wholesale
# would have silently dropped Oncology and Regenerative Medicine from CRM.
# Merging is this file's job, not his.
def merge(into, other):
    """Fold an aliased node into the real one. The real one keeps its content."""
    # Whichever has departments is the one the join actually populated.
    keep, alias = (into, other) if len(into.get('departments') or []) >= \
        len(other.get('departments') or []) else (other, into)
    for field in ('pagesPlanSlug', 'renameDeclined'):
        if field in alias and field not in keep:
            keep[field] = alias[field]
    # The DB title is the authority on what the unit is called. An alias node
    # carries the pages plan's shorter name for it.
    if alias.get('pages') and not keep.get('pages'):
        keep['pages'] = alias['pages']
    return keep


by_path = {}
for _r in OWNED:
    _n = node(_r)
    _key = _n['path']
    by_path[_key] = merge(by_path[_key], _n) if _key in by_path else _n

_dupe = collections.Counter(n['path'] for n in by_path.values())
_dupe = [p for p, c in _dupe.items() if c > 1]
if _dupe:
    raise SystemExit('two nodes claim one path after merging, which means the '
                     'backend would receive one folder twice: %s' % '; '.join(_dupe))
regions, entities, orphans = [], {}, []
for path, n in sorted(by_path.items()):
    path = n['path']
    if n['level'] == 'region':
        n['entities'] = []
        regions.append(n)
        continue
    # `regions/pk/entities/mc` -> parent `regions/pk`; a department's parent is
    # its entity, three segments up past `departments/`.
    parent = path.rsplit('/entities/', 1)[0] if n['level'] == 'entity' \
        else path.rsplit('/departments/', 1)[0]
    if parent not in by_path:
        n['expectedParent'] = parent
        orphans.append(n)
        continue
    if n['level'] == 'entity':
        n['departments'] = []
        by_path[parent]['entities'].append(n)
        entities[path] = n
    else:
        by_path[parent].setdefault('departments', []).append(n)

# The container folders, now that the children are known. The id is read from
# the backend's OWN columns -- storyblokEntitiesFolderId on a region,
# storyblokDepartmentFolderId on an entity -- because those are the columns it
# writes back to. Reading it out of the space instead would hand over a number
# the DB has no field for.
DB_BY_ID = {}
for _rows in (DB_REGIONS, DB_ENTITIES, DB_DEPTS):
    for _r in _rows:
        if _r.get('id'):
            DB_BY_ID[_r['id']] = _r

for r in regions:
    r['entities'].sort(key=lambda x: x['slug'])
    _db = DB_BY_ID.get(r['dbId'], {})
    r['entitiesFolder'] = {
        'needed': bool(r['entities']),
        'exists': bool(_db.get('storyblokEntitiesFolderId')),
        'storyblokFolderId': str(_db['storyblokEntitiesFolderId'])
                             if _db.get('storyblokEntitiesFolderId') else None,
        'seededBy': 'backend, when the region gets its first entity',
    }
    for e in r['entities']:
        e.setdefault('departments', []).sort(key=lambda x: x['slug'])
        _edb = DB_BY_ID.get(e['dbId'], {})
        e['departmentsFolder'] = {
            'needed': bool(e['departments']),
            'exists': bool(_edb.get('isDepartmentFolderCreated')),
            'storyblokFolderId': str(_edb['storyblokDepartmentFolderId'])
                                 if _edb.get('storyblokDepartmentFolderId')
                                 else None,
            'seededBy': 'backend, when the entity gets its first department',
        }
regions.sort(key=lambda x: x['slug'])

# Every declined rename, flat, so the pages side can pick the aliases up
# without walking the tree. Deliberately NOT called moves: nothing moves, and a
# key called moves in a hand-off file reads as an instruction to move something.
aliases = [{'level': n['level'], 'title': n['title'], 'dbId': n['dbId'],
            'shortName': n['shortName'], 'slug': n['slug'], 'path': n['path'],
            'storyblokFolderId': n['storyblokFolderId'],
            'pagesPlanSlug': n['pagesPlanSlug'],
            'why': n['renameDeclined']}
           for n in by_path.values() if 'pagesPlanSlug' in n]
aliases.sort(key=lambda m: m['path'])

counts = collections.Counter((n['level'], n['action']) for n in by_path.values())
# The notes that used to ride along in a `meta` key. They are ABOUT the file
# rather than part of it, and a seeding script has to step over them to reach
# the tree, so they live beside it instead -- same information, nothing for the
# dev to skip.
notes = {
    'about': {
        'generated': datetime.date.today().isoformat(),
        'spaceId': SPACE_ID,
        'naming': 'short codes -- the space is named this way and 6,399 stories '
                  'are already filed under it; the front end expands short to '
                  'long for the public URL',
        'seedTemplate': SEED,
        'seedTemplateReadFrom': 'regions/test, the folder the dev created to '
                                'show the shape',
        'actions': {
            'keep': 'exists, in the right place -- do nothing',
            'adopt': 'exists in Storyblok, the DB has no row -- write the id in',
            'create': 'the pages plan needs it and it is not there -- create it '
                      'and seed its leaves',
        },
        'renames': 'none. The space short code wins, so no folder is renamed and '
                   'no story moves. Where the pages plan uses a different slug '
                   'it is listed under "aliases" -- one folder, two names.',
        'containerFolders': 'the entities folder under a region and the '
                            'departments folder under an entity are seeded by '
                            'the backend when the row gets its first child. '
                            'They are reported per node as entitiesFolder and '
                            'departmentsFolder, not as work.',
        'counts': {'%s.%s' % k: v for k, v in sorted(counts.items())},
        'totals': {
            'regions': sum(1 for n in by_path.values() if n['level'] == 'region'),
            'entities': sum(1 for n in by_path.values() if n['level'] == 'entity'),
            'departments': sum(1 for n in by_path.values()
                               if n['level'] == 'department'),
            'aliases': len(aliases),
        },
    },
}
# Named rather than silently absent: somebody comparing the tree against the
# space will notice two entities missing and should find the reason here.
if EXCLUDED:
    notes['about']['excludedAsScaffold'] = [
        {'path': r['to_path'] or r['from_path'],
         'level': r['level'],
         'wouldHaveBeen': r['action'],
         'storyblokFolderId': r['sb_id'] or r['from_sb_id'] or None}
        for r in sorted(EXCLUDED, key=lambda x: x['to_path'] or x['from_path'])]
if orphans:
    # Not dropped. A node whose parent is missing is the one thing here that
    # cannot be applied, so it is named rather than silently absent.
    notes['about']['unplaced'] = orphans

def write(name, payload):
    with open(paths.out(name), 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write('\n')


# The tree, on its own. No wrapper object, no keys to step over: the top level
# is the list of regions, each with entities[], each with departments[].
write('AKU-Backend-Tree.json', regions)
write('aku-folder-aliases.json', {'notes': notes['about'], 'aliases': aliases})

print('AKU-Backend-Tree.json      a bare array of %d regions -- send this one'
      % len(regions))
print('  entities %d | departments %d'
      % (notes['about']['totals']['entities'],
         notes['about']['totals']['departments']))
print()
print('  %-12s %s' % ('level', 'action'))
for (lvl, act), n in sorted(counts.items()):
    print('  %-12s %-8s %d' % (lvl, act, n))
print()
print('  seed template read from regions/test:')
for lvl in ('region', 'entity', 'department'):
    print('    %-11s %s' % (lvl, SEED.get(lvl) or '(NOT FOUND -- has the dev '
                                                 'removed regions/test?)'))
print()
print('  renames: none -- the space short code wins, 0 stories move')
print('  %d alias(es), where the pages plan uses a different slug:' % len(aliases))
for m in aliases:
    print('    %-30s space=%-8s pages plan=%s'
          % (m['path'].rsplit('/entities/', 1)[-1], m['slug'], m['pagesPlanSlug']))
print()
_need = [(r['slug'], e['slug']) for r in regions for e in r['entities']
         if e['departmentsFolder']['needed'] and not e['departmentsFolder']['exists']]
print('  %d entity/ies need a departments folder the backend has not seeded:'
      % len(_need))
for reg, ent in _need:
    print('    %s/%s' % (reg, ent))
if EXCLUDED:
    print()
    print('  %d node(s) excluded as the dev test scaffold:' % len(EXCLUDED))
    for r in EXCLUDED:
        print('    %-46s would have been %s'
              % ((r['to_path'] or r['from_path'])[:46], r['action']))
if orphans:
    print()
    print('  %d node(s) whose parent is not in this tree -- see "unplaced"'
          % len(orphans))
