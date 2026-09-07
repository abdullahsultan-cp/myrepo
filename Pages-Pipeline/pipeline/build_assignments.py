"""build_assignments.py -- who migrates which page, as a work sheet.

The team's assignment list names a person per faculty. This turns that into one
row per page so progress can be tracked against something countable, and so two
people are never handed the same folder.

Assignment is by DESTINATION PATH, not by the entity column, and that is the
whole reason this file has a rule instead of a dictionary lookup. 44 pages carry
`entity = medical-college` while LIVING in `regions/global/blogs` -- the CCIT
blog posts, consolidated into the global hub. Assigning by entity would have
handed those to a Medical College reviewer and put two people in the shared
blogs hub. Assigning by path cannot: a path belongs to exactly one owner, and
the check at the bottom fails the build if two owners ever claim one prefix.

Where the list puts two people on one faculty the split is by sub-folder, for
the same reason -- so nobody has to coordinate inside a folder. It is recorded
here rather than agreed verbally, because a verbal split is the thing both
people remember differently in three weeks.

Inputs   out/aku-master-pages.csv, out/aku-master-folders.csv
Outputs  out/aku-folder-assignments.csv   the assignment itself: complete folders
         out/aku-page-assignments.csv     the same assignment, one row per page
         out/aku-progress.csv             how far each person has got
"""
import collections
import csv
import datetime

import page_titles
import paths

ASSIGNED_ON = '2026-09-07'

MC_PK = 'regions/pakistan/entities/medical-college'
UG_SONAM = 'regions/uganda/entities/school-of-nursing-and-midwifery'

# Longest prefix wins, so a split inside a faculty can sit under the faculty's
# own line without the two fighting. Order in this list does not matter.
OWNERS = [
    ('Uzair',
     ['regions/pakistan/entities/school-of-nursing-and-midwifery']),

    # Medical College, Pakistan is 960 pages and two people are named for it.
    # The cleanest boundary the tree offers: `departments/` is 544 pages and a
    # self-contained sub-tree, everything else is the faculty's own 416. Neither
    # reviewer ever opens a folder the other is working in.
    ('Abdullah Sultan', [MC_PK + '/departments']),
    ('Rabee', [MC_PK]),

    ('Hamza Khan', [
        'regions/pakistan/entities/centre-of-excellence-for-trauma-and-emergencies',
        'regions/pakistan/entities/clinical-trials-unit',
        'regions/pakistan/entities/digital-health-resource-centre']),

    ('Sherayar',
     ['regions/pakistan/entities/institute-for-educational-development']),

    ('Fazila',
     ['regions/pakistan/entities/faculty-of-arts-and-sciences']),

    # The list gives no region for this one. There is only one: Pakistan, 92 pages.
    ('Noman Jawaid',
     ['regions/pakistan/entities/centre-for-regenerative-medicine']),

    # Uganda is 51 pages and two people are named. Split by sub-folder to land
    # 25 / 26: alumni is the single biggest branch at 23.
    ('Hussain', [UG_SONAM + '/alumni', UG_SONAM + '/partners']),
    ('Priyanchal', ['regions/uganda']),
]

PREFIXES = sorted(((p, who) for who, ps in OWNERS for p in ps),
                  key=lambda x: -len(x[0]))

_claimed = collections.Counter(p for p, _ in PREFIXES)
_twice = [p for p, n in _claimed.items() if n > 1]
if _twice:
    raise SystemExit('two owners claim one prefix, so a folder has two people '
                     'in it: %s' % '; '.join(_twice))


def owner_of(dest):
    for prefix, who in PREFIXES:
        if dest == prefix or dest.startswith(prefix + '/'):
            return who
    return '(unassigned)'


# What the two status columns should already say. Leaving them blank for 4,591
# rows means somebody types the same four words 4,591 times, and the reasons a
# page cannot be migrated are already known and already measured.
def status_of(row):
    if row['build'] == 'yes':
        return 'Not started', 'Not started', ''
    if row['build'] == 'later':
        return 'Second priority', 'N/A', 'not in AKU list, found by crawling'
    http = row['http']
    if http == '401':
        return ('Blocked - AKU to unblock', 'N/A',
                'login only: the place is reserved, the content is not readable')
    if http in ('404', '403', '500'):
        return ('Not migrating - gone', 'N/A',
                'HTTP %s on the live site, nothing to copy' % http)
    return ('Not migrating - superseded', 'N/A',
            'another page carries this content')


def page_name(row):
    """The page's own name, cleaned, and never SharePoint's whole title chain.

    Titles arrive as "Academic Content | Anaesthesiology | MC, PK | The Aga Khan
    University" -- the page, then its section, then the faculty, then the site.
    Everything after the first bar is already its own column here, and repeating
    it makes a 90-character cell nobody can scan.

    page_titles.clean has already decoded the entities and deleted the
    invisibles by the time this runs: 135 of AKU's titles carry a zero-width
    space, which is invisible on screen but sorts as a different string, so nine
    pages named "Dean's Communiqué" came out as three groups that looked
    identical and would not group.
    """
    title = page_titles.short(row['title'])
    if title:
        return title
    leaf = (row['destination_path'] or row['source_url']).rstrip('/').split('/')[-1]
    return leaf.replace('.aspx', '').replace('-', ' ').strip().title()


# Titles are not unique and were never meant to be: one owner has nine pages
# called "Dean's Communiqué", and 34 pages across the site are called "Home". A
# work sheet whose name column cannot tell two rows apart is a work sheet nobody
# can report against.
#
# The qualifier is the FOLDERS above the page, widened one level at a time until
# the group separates, because a folder is what a person would say out loud --
# "Our Team, in research" rather than "Our Team, our-team". Two things make this
# fiddlier than it looks, and both were found by counting what was left over
# rather than by reading the code:
#
#   * `Pages` is a segment of every single SharePoint URL. A page with no
#     destination falls back to its old slug, so 14 pages called "Events" all
#     qualified to "(Pages)", then to "(events/Pages)", then to "(home.aspx)" --
#     three candidates, all identical. The segment is dropped.
#   * The leaf is not a guarantee. 34 pages have the leaf `home`, so "use the
#     slug if the folders fail" fails too. The floor is the full path, which is
#     unique -- the audit proves 0 shared paths and 0 shared addresses.
# `Pages` and `SitePages` are SharePoint's; `regions`, `entities` and
# `departments` are our own scaffolding, invisible in the address and just as
# invisible to a reader. None of them tells two pages apart, and all of them
# make the qualifier longer.
NOISE = {'pages', 'sitepages', 'regions', 'entities', 'departments'}


def _segments(row):
    """The folders above this page, outermost first, minus the scaffolding."""
    src = row['Storyblok Path'] or row['Old Slug']
    parts = [x for x in src.strip('/').split('/') if x]
    return [x for x in parts[:-1] if x.lower() not in NOISE]


def _leaf(row):
    return (row['Storyblok Path'] or row['Old Slug']).strip('/').split('/')[-1]


def disambiguate(rows):
    named = 0
    groups = collections.defaultdict(list)
    for r in rows:
        groups[(r['Owner'], r['Page Name'])].append(r)
    for group in groups.values():
        if len(group) < 2:
            continue
        segs = {id(r): _segments(r) for r in group}
        deepest = max(len(v) for v in segs.values()) or 1
        marks = None
        for width in range(1, deepest + 1):
            trial = {k: '/'.join(v[-width:]) for k, v in segs.items()}
            if len(set(trial.values())) == len(group) and all(trial.values()):
                marks = trial
                break
        if marks is None:
            # No set of folders separates them, so the page itself must. This is
            # the `home` / `home-archive` pair: same folder, different leaf.
            # Jumping straight to the full path here is what produced 318 names
            # over 70 characters, "Research-BBS (regions/pakistan/entities/
            # medical-college/departments/bbs/research)" among them.
            for pick in (lambda r: _leaf(r),
                         lambda r: '/'.join(_segments(r)[-1:] + [_leaf(r)])):
                trial = {id(r): pick(r) for r in group}
                if len(set(trial.values())) == len(group) and all(trial.values()):
                    marks = trial
                    break
        if marks is None:
            # The floor. Paths are unique by construction -- the audit proves
            # 0 shared paths and 0 shared addresses -- so this always separates.
            marks = {id(r): '/'.join(_segments(r) + [_leaf(r)]) for r in group}
        for r in group:
            r['Page Name'] = '%s (%s)' % (r['Page Name'], marks[id(r)])
            named += 1
    return named


COLS = ['Serial No.', 'Assigned Date', 'Page Name', 'Entity', 'Region', 'Owner',
        'Migration Status', 'Testing Status', 'Tester', 'Tester Remarks',
        'Old Slug', 'New Slug',
        # The slug is the path, which is what "slug" means and what a reviewer
        # compares. The full URLs follow because a path is not clickable and
        # Excel turns a bare https:// into a link on its own.
        'Old URL', 'New URL',
        # Beyond the requested set, and each one earns its place:
        'Department',        # Medical College alone has 544 department pages
        'Storyblok Path',    # where it is CREATED, as opposed to its address
        'Build',             # yes / no / later, so a filter can hide the noise
        'Blocker',           # why not, when not
        'AKU Review',        # AKU's own flag: Not Reviewed, Unclear, ...
        'Managed By (AKU)',  # the AKU unit that owns the CONTENT, not the migrator
        'Notes']

SRC = list(csv.DictReader(open(paths.out('aku-master-pages.csv'),
                               encoding='utf-8-sig')))

rows = []
for r in SRC:
    if r['priority'] != '1':
        continue
    who = owner_of(r['destination_path'])
    mig, test, blocker = status_of(r)
    rows.append({
        'Assigned Date': ASSIGNED_ON if who != '(unassigned)' else '',
        'Page Name': page_name(r),
        'Entity': r['entity'] or '(region level)',
        'Region': r['region'],
        'Owner': who,
        'Migration Status': mig,
        'Testing Status': test,
        'Tester': '',
        'Tester Remarks': '',
        'Old Slug': r['source_url'].replace('https://www.aku.edu', ''),
        'New Slug': r['destination_url'].replace('https://www.aku.edu', ''),
        'Old URL': r['source_url'],
        'New URL': r['destination_url'],
        'Department': r['department'],
        'Storyblok Path': r['destination_path'],
        'Build': r['build'],
        'Blocker': blocker,
        'AKU Review': r['aku_action'],
        'Managed By (AKU)': r['managed_by'],
        'Notes': r['remark'],
    })

_named = disambiguate(rows)

# ---- keep what a person typed ---------------------------------------------
# This script is re-run every time the plan changes, and the four columns a
# person fills in by hand are the whole point of the sheet. Overwriting them
# with the pre-filled defaults would silently throw away everyone's progress --
# so the previous file is read back first and those four are carried across,
# keyed on the source URL, which is the one column no rebuild can change.
#
# The exception is a page that is NOT buildable. Blocked, gone and superseded
# are measured facts, not progress, and if the live site's answer changes the
# sheet has to say the new one -- a page that went 401 must not keep reading
# "Done" from before it did.
KEEP = ['Migration Status', 'Testing Status', 'Tester', 'Tester Remarks']
prior = {}
try:
    with open(paths.out('aku-page-assignments.csv'), encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            url = r.get('Old URL') or r.get('old-page') or ''
            if url:
                prior[url] = {k: (r.get(k) or '').strip() for k in KEEP}
except FileNotFoundError:
    pass

carried = 0
for r in rows:
    was = prior.get(r['Old URL'])
    if not was:
        continue
    if r['Build'] != 'yes':
        r['Tester'], r['Tester Remarks'] = was['Tester'], was['Tester Remarks']
        continue
    # Only a value that DIFFERS from the pre-fill is somebody's work. Counting
    # every carried cell reported 3,982 rows of "progress" on a first re-run,
    # when all it had done was copy its own default back over itself.
    changed = False
    for k in KEEP:
        if was[k]:
            changed = changed or was[k] != r[k]
            r[k] = was[k]
    if changed:
        carried += 1

# Assigned work first, so the sheet opens on the rows somebody has to act on.
# Nothing is removed -- the unassigned rows stay, per the standing rule that a
# page dropped from the sheet is a page nobody can look up again.
rows.sort(key=lambda r: (r['Owner'] == '(unassigned)', r['Owner'],
                         r['Region'], r['Entity'], r['Storyblok Path']))
for i, r in enumerate(rows, 1):
    r['Serial No.'] = i

with open(paths.out('aku-page-assignments.csv'), 'w',
          encoding='utf-8-sig', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=COLS, extrasaction='ignore')
    w.writeheader()
    w.writerows(rows)

if datetime.date.fromisoformat(ASSIGNED_ON) > datetime.date.today():
    raise SystemExit('ASSIGNED_ON is in the future: %s' % ASSIGNED_ON)

print('aku-page-assignments.csv   %d rows, %d columns' % (len(rows), len(COLS)))
print('   %d page names shared a title and are qualified by folder' % _named)
print('   %d rows carried a status somebody had already typed' % carried)
print()
per = collections.Counter(r['Owner'] for r in rows)
build = collections.Counter((r['Owner'], r['Build']) for r in rows)
print('%-22s %6s %7s %7s' % ('owner', 'pages', 'build', 'blocked'))
for who, n in sorted(per.items(), key=lambda x: (x[0] == '(unassigned)', -x[1])):
    print('%-22s %6d %7d %7d'
          % (who, n, build[(who, 'yes')], build[(who, 'no')]))
print()
print('assigned %d of %d pages; %d are nobody\'s yet'
      % (len(rows) - per['(unassigned)'], len(rows), per['(unassigned)']))

# ---- the assignment as the team states it: complete folders ---------------
# The page sheet is what gets worked through, but it is not how the assignment
# was made. AKU handed out FOLDERS -- "School of Nursing & Midwifery, Pakistan"
# -- and a 4,591-row sheet cannot be checked against a sentence like that. This
# is the same assignment at the altitude it was agreed, so somebody can confirm
# they were given what they think they were given before anyone starts.
FCOLS = ['Serial No.', 'Assigned Date', 'Owner', 'Folder', 'Folder Path',
         'Kind', 'Region', 'Entity', 'Level',
         'Pages Here', 'Pages In Subtree', 'To Build', 'Blocked',
         'Managed By (AKU)', 'Notes']

FSRC = list(csv.DictReader(open(paths.out('aku-master-folders.csv'),
                                encoding='utf-8-sig')))

# Per-folder build totals, counted from the pages that actually landed there
# rather than from the folder's own page count -- the two differ wherever a page
# was consolidated into a global hub.
here = collections.Counter()
build_here = collections.Counter()
for r in SRC:
    if r['priority'] != '1' or not r['destination_path']:
        continue
    folder = r['destination_path'].rsplit('/', 1)[0]
    here[folder] += 1
    build_here[(folder, r['build'])] += 1

frows = []
for f in FSRC:
    who = owner_of(f['destination_path'])
    if who == '(unassigned)':
        continue
    frows.append({
        'Assigned Date': ASSIGNED_ON,
        'Owner': who,
        'Folder': f['title'] or f['destination_path'].split('/')[-1],
        'Folder Path': f['destination_path'],
        'Kind': f['kind'],
        'Region': f['region'],
        'Entity': f['entity'],
        'Level': f['level'],
        'Pages Here': here.get(f['destination_path'], 0),
        'Pages In Subtree': f['pages_subtree'],
        'To Build': build_here.get((f['destination_path'], 'yes'), 0),
        'Blocked': build_here.get((f['destination_path'], 'no'), 0),
        'Managed By (AKU)': f['managed_by'],
        'Notes': f['remark'],
    })
frows.sort(key=lambda r: (r['Owner'], r['Folder Path']))
for i, r in enumerate(frows, 1):
    r['Serial No.'] = i

with open(paths.out('aku-folder-assignments.csv'), 'w',
          encoding='utf-8-sig', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=FCOLS, extrasaction='ignore')
    w.writeheader()
    w.writerows(frows)

print()
print('aku-folder-assignments.csv %d folders' % len(frows))
fper = collections.Counter(r['Owner'] for r in frows)
print('%-22s %8s %7s' % ('owner', 'folders', 'pages'))
for who, n in sorted(fper.items(), key=lambda x: -x[1]):
    print('%-22s %8d %7d' % (who, n, per[who]))


# ---- how far has each person got ------------------------------------------
# Read back from the sheet people actually fill in, so there is one place a
# status is recorded and no second thing to keep in step. Re-run this script
# after the team updates the sheet and this file is the standing report.
#
# `Migration Status` is free text in a spreadsheet, so it is matched loosely --
# "done", "Done", "DONE " all count -- and anything unrecognised lands in a
# column of its own rather than being quietly counted as not started. A status
# nobody expected should be visible, not averaged away.
DONE = {'done', 'complete', 'completed', 'migrated', 'finished'}
DOING = {'in progress', 'in-progress', 'wip', 'started', 'ongoing'}
TODO = {'not started', 'not-started', 'todo', 'to do', ''}


def bucket(status):
    v = (status or '').strip().lower()
    if v in DONE:
        return 'Done'
    if v in DOING:
        return 'In Progress'
    if v in TODO:
        return 'Not Started'
    if v.startswith(('blocked', 'not migrating', 'second priority')):
        return 'Not Buildable'
    return 'Other'


PCOLS = ['Owner', 'Folders', 'Pages Assigned', 'To Build', 'Done',
         'In Progress', 'Not Started', 'Not Buildable', 'Other',
         'Percent Done', 'Pages Left To Build']

folders_per = collections.Counter(r['Owner'] for r in frows)
prows = []
for who in sorted({r['Owner'] for r in rows if r['Owner'] != '(unassigned)'})         + ['(unassigned)']:
    mine = [r for r in rows if r['Owner'] == who]
    b = collections.Counter(bucket(r['Migration Status']) for r in mine)
    to_build = sum(1 for r in mine if r['Build'] == 'yes')
    prows.append({
        'Owner': who,
        'Folders': folders_per.get(who, 0),
        'Pages Assigned': len(mine),
        'To Build': to_build,
        'Done': b['Done'],
        'In Progress': b['In Progress'],
        'Not Started': b['Not Started'],
        'Not Buildable': b['Not Buildable'],
        'Other': b['Other'],
        # Of the pages this person CAN build. Measuring against the raw
        # assignment would show Noman at 57% before he starts, because 40 of
        # his 92 pages are login-only and will never be his to finish.
        'Percent Done': '%.0f%%' % (100.0 * b['Done'] / to_build) if to_build else '-',
        'Pages Left To Build': to_build - b['Done'] - b['In Progress'],
    })

with open(paths.out('aku-progress.csv'), 'w',
          encoding='utf-8-sig', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=PCOLS, extrasaction='ignore')
    w.writeheader()
    w.writerows(prows)

print()
print('aku-progress.csv')
print('%-20s %7s %6s %6s %6s %6s %7s' % ('owner', 'build', 'done', 'doing', 'todo',
                                         'blocked', 'done %'))
for r in prows:
    print('%-20s %7d %6d %6d %6d %6d %7s'
          % (r['Owner'], r['To Build'], r['Done'], r['In Progress'],
             r['Not Started'], r['Not Buildable'], r['Percent Done']))
_odd = sum(r['Other'] for r in prows)
if _odd:
    print('%d rows carry a status this script does not recognise -- see the '
          'Other column' % _odd)
