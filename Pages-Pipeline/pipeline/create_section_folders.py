"""create_section_folders.py -- the folders the backend does not make.

The tree is owned in two halves, agreed with AKU on 8 Sep 2026:

    the backend    region, entity, department -- and it auto-seeds `news`,
                   `blogs` and `events` inside each one it creates
    us             everything else: `about`, `research`, `study`, `alumni`,
                   `programmes` ... the SECTION folders the pages hang off

The backend's half is done: 193 of 193 nodes verified present in the space.
This creates our half -- **438 section folders**, every one of which holds at
least one page (an empty section is `skip` in the map and never reaches here).

**It is a dry run unless you pass --apply.** The plan is written either way, so
`out/aku-section-folders.csv` can be read and argued with before anything is
created.

Five guards, and every one of them is here because of something in CLAUDE.md
that has already gone wrong once in this repo:

1. **It refuses to create anything that is not a section.** A region, an entity,
   a department, or a `news`/`blogs`/`events` leaf belongs to the backend. If
   one of those is missing the backend has not finished, and inventing it here
   would give the space two owners for one folder.

2. **It never invents a path.** Only paths the pages plan names. `NO_CREATE` in
   the shared `pipeline/migrate/upload/upload.py` stops that uploader creating
   anything under `regions/` at all, and it is deliberately left alone -- it
   guards the news, blogs and events uploads, which have no business making
   folders. This script is the narrow, named exception, not a weakening of it.

3. **It looks up before it creates.** `ensure_asset_folder` used to POST first
   and search only if the POST failed, assuming Storyblok rejects a duplicate
   name under one parent. It does not. The space reached 769 asset folders, 444
   of them redundant.

4. **A missing parent stops the run.** Storyblok puts a story with no valid
   parent at the ROOT, silently, so one bad parent id is how you get a folder
   called `about` beside `regions/`. Parents are created before children and
   every id is checked before it is used.

5. **200, 201 and 204 all mean success.** Accepting only (200, 201) is how a run
   that moved 786 assets perfectly reported `0 moved, 786 failed`.

The folder shape is copied from one the dev already made
(`regions/pk/entities/sonam/programmes`), not guessed:
`is_folder: true`, `default_root: "page"`, `content: {body: [], component:
"page"}`.

**Take a backup the moment this finishes.** Storyblok keeps no version history,
so the read-back archive is the only record of what the space held:

    python pipeline/migrate/review/dump_sb_tree.py
    python pipeline/migrate/review/backup.py --type news

Usage
    python create_section_folders.py                 # plan only, writes the CSV
    python create_section_folders.py --apply         # create them
    python create_section_folders.py --apply --limit 5   # prove it on five first

Inputs   out/aku-hierarchy-map.csv            which sections, and their titles
         ../storyblok_space/folder_tree.json  what exists -- REFRESH IT FIRST
         ../config/storyblok.json             the management token (--apply only)
Outputs  out/aku-section-folders.csv          the plan, in creation order
         out/work/created_folders.json        ids as they come back, so a crash
                                              resumes instead of starting over
"""
import argparse
import csv
import json
import os
import sys
import time

import paths

BACKEND_OWNS = ('region', 'entity', 'department', 'container')
LEAVES = ('news', 'blogs', 'events')

ap = argparse.ArgumentParser()
ap.add_argument('--apply', action='store_true',
                help='actually create the folders; without it nothing is written '
                     'to the space')
ap.add_argument('--limit', type=int, default=0,
                help='stop after N creations -- prove it on a handful first')
ap.add_argument('--sleep', type=float, default=0.25,
                help='seconds between calls; Storyblok rate-limits above ~6/s')
args = ap.parse_args()

# ---- what exists now ------------------------------------------------------
SNAPSHOT = os.path.join(paths.ROOT, 'storyblok_space', 'folder_tree.json')
with open(SNAPSHOT, encoding='utf-8') as fh:
    _snap = json.load(fh)
BY_PATH = {f['full_slug']: f['id'] for f in _snap['folders']}
print('snapshot: %d folders, space %s' % (len(BY_PATH), _snap['space_id']))

# Ids this run has created, so an interrupted run resumes. Written after every
# single creation rather than at the end -- a crash halfway through 438 folders
# must not lose the 200 it already made.
PROGRESS = paths.work('created_folders.json')
try:
    with open(PROGRESS, encoding='utf-8') as fh:
        DONE = json.load(fh)
except (FileNotFoundError, ValueError):
    DONE = {}
if DONE:
    print('resuming: %d folder(s) already created by a previous run' % len(DONE))
BY_PATH.update(DONE)

# ---- what to create -------------------------------------------------------
MAP = list(csv.DictReader(open(paths.out('aku-hierarchy-map.csv'),
                               encoding='utf-8-sig')))


# ---- one folder, two names ------------------------------------------------
# Four folders are aliased: the pages plan spells them out, the space uses a
# short code, and nothing is renamed. Skipping the four alias paths is not
# enough -- their CHILDREN inherit the plan's spelling, so eight sections were
# planned under `regions/pk/entities/centre-for-regenerative-medicine`, a parent
# that correctly does not exist and never will. Guard 4 would have stopped the
# run at folder 308 of 438; rewriting the prefix here means it never arises.
try:
    with open(paths.out('aku-folder-aliases.json'), encoding='utf-8') as fh:
        _al = json.load(fh)['aliases']
except FileNotFoundError:
    _al = []

# plan spelling -> what the space actually calls it, longest first so a nested
# alias is rewritten before its parent could partially match.
REWRITE = sorted(
    ((a['path'].rsplit('/', 1)[0] + '/' + a['pagesPlanSlug'], a['path'])
     for a in _al),
    key=lambda x: -len(x[0]))
ALIAS_SLUGS = {a['pagesPlanSlug'] for a in _al}


def real_path(path):
    """The path as the SPACE spells it."""
    for plan_spelling, in_space in REWRITE:
        if path == plan_spelling:
            return in_space
        if path.startswith(plan_spelling + '/'):
            return in_space + path[len(plan_spelling):]
    return path


def path_of(row):
    return real_path(row['to_path'] or row['from_path'])


wanted = []
for row in MAP:
    path = path_of(row)
    if not path or row['action'] in ('ignore', 'skip'):
        continue
    if path in BY_PATH:
        continue
    leaf = path.rsplit('/', 1)[-1]
    # Guard 1. Not ours to make. A gap here means the backend has not finished,
    # and creating it would hand the space two owners for one folder.
    if row['level'] in BACKEND_OWNS or leaf in LEAVES:
        wanted.append((path, row, 'BACKEND'))
        continue
    wanted.append((path, row, 'ours'))

theirs = [w for w in wanted if w[2] == 'BACKEND']
mine = [w for w in wanted if w[2] == 'ours']

# Anything still carrying a plan-only spelling after the rewrite. There should
# be none; if one appears it means an alias was added to the JSON without the
# hierarchy map being rebuilt, and creating it would make the duplicate folder
# this whole exercise exists to avoid.
aliased = [w for w in theirs
           if w[0].rsplit('/', 1)[-1] in ALIAS_SLUGS
           or any(('/' + a + '/') in w[0] for a in ALIAS_SLUGS)]
theirs = [w for w in theirs if w not in aliased]

if theirs:
    print()
    print('STOPPING: %d folder(s) the BACKEND owns are missing from the space.'
          % len(theirs))
    print('Creating them here would give one folder two owners. Ask the backend')
    print('dev to seed these, refresh the snapshot, and re-run:')
    for path, row, _ in theirs[:15]:
        print('   %-11s %s' % (row['level'], path))
    if len(theirs) > 15:
        print('   ... and %d more' % (len(theirs) - 15))
    sys.exit(1)

# ---- creation order: every parent before its children ---------------------
# Sorting by depth then path is not a tidy-up, it is the whole correctness
# argument: 212 of the 438 have a parent that is also on this list.
mine.sort(key=lambda w: (w[0].count('/'), w[0]))

plan = []
for path, row, _ in mine:
    parent_path = path.rsplit('/', 1)[0]
    plan.append({
        'order': len(plan) + 1,
        'path': path,
        'slug': path.rsplit('/', 1)[-1],
        'name': (row['to_title'] or row['from_title'] or '').strip()
                or path.rsplit('/', 1)[-1].replace('-', ' ').title(),
        'depth': path.count('/'),
        'parent_path': parent_path,
        'parent_id': BY_PATH.get(parent_path, ''),
        'parent_made_by_this_run': '' if parent_path in BY_PATH else 'yes',
        'pages_in_subtree': row['pages_subtree'],
        'managed_by': row['managed_by'],
        'source_web': row['source_web'],
        'storyblok_id': '',
    })

COLS = ['order', 'path', 'slug', 'name', 'depth', 'parent_path', 'parent_id',
        'parent_made_by_this_run', 'pages_in_subtree', 'managed_by',
        'source_web', 'storyblok_id']

# The order is the whole correctness argument -- 212 of the 438 have a parent
# this run creates first -- so it is proved here rather than trusted. Sorting by
# depth is necessary but not sufficient: a parent can be missing from the plan
# altogether, which is how eight sections came to sit under an alias path.
_available = set(BY_PATH)
_unreachable = []
for _r in plan:
    if _r['parent_path'] not in _available:
        _unreachable.append((_r['path'], _r['parent_path']))
    _available.add(_r['path'])
if _unreachable:
    print()
    print('STOPPING: %d folder(s) name a parent that neither exists nor gets '
          'created by this run. Creating them would put each one at the ROOT '
          'of the space.' % len(_unreachable))
    for _path, _parent in _unreachable[:10]:
        print('   %-56s wants parent %s' % (_path[-56:], _parent))
    sys.exit(1)


def write_plan():
    with open(paths.out('aku-section-folders.csv'), 'w',
              encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction='ignore')
        w.writeheader()
        w.writerows(plan)


write_plan()
print()
print('aku-section-folders.csv   %d folder(s) to create' % len(plan))
if aliased:
    print('   %d alias path(s) skipped -- one folder, two names, already exists'
          % len(aliased))
by_depth = {}
for r in plan:
    by_depth[r['depth']] = by_depth.get(r['depth'], 0) + 1
print('   by depth:', dict(sorted(by_depth.items())))
print('   %d have a parent this run creates first'
      % sum(1 for r in plan if r['parent_made_by_this_run']))

if not plan:
    print()
    print('nothing to create -- every section in the plan already exists.')
    sys.exit(0)

if not args.apply:
    print()
    print('DRY RUN. Nothing was written to the space.')
    print('Read out/aku-section-folders.csv, then re-run with --apply.')
    sys.exit(0)

# ---- create them ----------------------------------------------------------
try:
    import requests
except ImportError:
    sys.exit('pip install -r requirements.txt')

with open(os.path.join(paths.ROOT, 'config', 'storyblok.json'),
          encoding='utf-8') as fh:
    CFG = json.load(fh)
TOKEN = CFG.get('management_token')
SPACE = str(CFG.get('space_id') or '')
if not TOKEN or not SPACE:
    sys.exit('config/storyblok.json needs management_token and space_id')
if SPACE != str(_snap['space_id']):
    sys.exit('the snapshot is from space %s and the config points at %s -- '
             'refusing to create folders in a space this plan was not built '
             'against' % (_snap['space_id'], SPACE))
API = 'https://mapi.storyblok.com/v1/spaces/%s' % SPACE
SESSION = requests.Session()
SESSION.headers.update({'Authorization': TOKEN,
                        'Content-Type': 'application/json'})
OK = (200, 201, 204)


def call(method, url, **kw):
    """Retry a rate-limit, a server error, AND a dropped connection.

    Retrying only on HTTP status is what ended two earlier runs at 95 and 8
    minutes: a ConnectionError raised straight through.
    """
    for attempt in range(6):
        try:
            r = SESSION.request(method, url, timeout=45, **kw)
        except requests.exceptions.RequestException as exc:
            if attempt == 5:
                raise
            print('      %s -- retrying in %ds' % (type(exc).__name__, 2 ** attempt))
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == 5:
                return r
            time.sleep(2 ** attempt)
            continue
        return r
    return r


def already_there(path):
    """Guard 3: ask the space, do not assume the snapshot is current."""
    r = call('GET', API + '/stories',
             params={'with_slug': path, 'per_page': 1})
    if r.status_code != 200:
        return None
    for st in r.json().get('stories') or []:
        if st.get('full_slug') == path and st.get('is_folder'):
            return st['id']
    return None


made = skipped = 0
print()
print('creating %d folder(s) in space %s' % (len(plan), SPACE))
for row in plan:
    if args.limit and made >= args.limit:
        print('   --limit %d reached, stopping' % args.limit)
        break

    parent_id = BY_PATH.get(row['parent_path'])
    # Guard 4. Storyblok puts a story with no valid parent at the ROOT, without
    # complaining, so one missing id is how a folder called `about` ends up
    # beside `regions/`.
    if not parent_id:
        sys.exit('\n  STOPPING at %s: its parent %r has no id.\n'
                 '  Creating it now would put the folder at the ROOT of the '
                 'space.\n  Refresh the snapshot and re-run.'
                 % (row['path'], row['parent_path']))

    existing = already_there(row['path'])
    if existing:
        BY_PATH[row['path']] = existing
        row['storyblok_id'] = existing
        skipped += 1
        print('   exists   %-58s id=%s' % (row['path'][-58:], existing))
        continue

    r = call('POST', API + '/stories', data=json.dumps({'story': {
        'name': row['name'],
        'slug': row['slug'],
        'is_folder': True,
        'parent_id': int(parent_id),
        'default_root': 'page',
        'content': {'body': [], 'component': 'page'},
    }}))
    if r.status_code not in OK:
        write_plan()
        sys.exit('\n  FAILED on %s: %s %s\n  %d created before this. The plan '
                 'CSV and out/work/created_folders.json hold what succeeded; '
                 'fix the cause and re-run -- it resumes.'
                 % (row['path'], r.status_code, r.text[:300], made))

    new_id = (r.json().get('story') or {}).get('id')
    BY_PATH[row['path']] = new_id
    DONE[row['path']] = new_id
    row['storyblok_id'] = new_id
    made += 1
    # After every creation, not at the end.
    with open(PROGRESS, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(DONE, fh, indent=1)
    print('   created  %-58s id=%s' % (row['path'][-58:], new_id))
    time.sleep(args.sleep)

write_plan()
print()
print('created %d | already there %d | of %d planned' % (made, skipped, len(plan)))
print()
print('NOW, before anything else -- Storyblok keeps no version history:')
print('   python pipeline/migrate/review/dump_sb_tree.py')
print('   python Pages-Pipeline/pipeline/create_section_folders.py   # re-verify')
