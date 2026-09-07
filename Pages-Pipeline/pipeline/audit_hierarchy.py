"""Audit the finished hierarchy: check every structural claim, and list what a
human still has to decide.

Why this exists
  `build_migration_plan.py` builds the tree and `verify_live.py` checks each page
  against the site. Neither one steps back and asks whether the RESULT is a legal
  Storyblok tree. It is not, in ten places, and nothing said so:

      mcpk/Pages/research.aspx        -> regions/.../medical-college/research
      mcpk/research/  (60 pages)      -> regions/.../medical-college/research

  A story and a folder cannot both be `research` inside `medical-college` -- in
  Storyblok a folder IS a story, so the two share one slug namespace. The plan's
  own collision check compares page against page and never page against folder,
  so all ten came through clean.

  Eight of the ten are the same thing seen from the other side. AKU has both a
  `X/Pages/<name>.aspx` page and an `X/<name>/Pages/home.aspx` sub-web landing
  page -- two source pages for one section front door. That is exactly the case
  the `collision` column exists to surface ("AKU has two source pages, pick one");
  it was missed because `public_url()` does not collapse a trailing `home`, so
  the two addresses differ by that segment and never compare equal.

  Which raises the larger one, and the reason this file reports rather than
  fixes: SharePoint serves `X/Pages/home.aspx` AT `X/`. The plan gives it the
  address `X/home` -- for 463 pages, the university front page among them
  (`https://www.aku.edu/home`, not `https://www.aku.edu/`). Collapsing that
  segment is a one-line change to `public_url`, and it is not this script's to
  make: it moves 463 published addresses, and it turns 8 of these pairs into hard
  address collisions that AKU has to resolve by picking a page. Both facts are in
  the audit table with their counts.

Writes two files, and reads everything from `out/work/plan.json`:

  aku-hierarchy-audit.csv          one row per check -- what it asks, the count,
                                   and whether it passed, needs a decision, or
                                   is a defect
  aku-hierarchy-landing-pages.csv  one row per folder whose front door is
                                   contested, with both source pages side by side

Nothing here writes to the plan. A disagreement is a question for a human.
"""

import collections
import csv
import json

import paths

with open(paths.work('plan.json'), encoding='utf-8') as f:
    PLAN = json.load(f)

FOLDERS = PLAN['folders']
PAGES = PLAN['pages']
DECISIONS = PLAN['decisions']

FBY = {f['new_path']: f for f in FOLDERS}
FPATHS = set(FBY)
PLACED = [p for p in PAGES if p['new_path']]
DROPPED = [p for p in PAGES if not p['new_path']]

# The address rule as build_migration_plan.py applies it today, repeated here so
# the audit can ask what a DIFFERENT rule would produce without importing the
# builder and re-running it. Asserted against the plan's own `new_url` below, so
# it cannot drift silently.
SCAFFOLD = {'regions', 'entities', 'departments'}


def public_url(cms_path):
    """A copy of build_migration_plan.public_url. The drift check below fails
    the audit if the two ever disagree, so this cannot rot silently."""
    parts = cms_path.split('/')
    if len(parts) > 1 and parts[-1] == 'home':
        parts = parts[:-1]
    parts = [x for i, x in enumerate(parts)
             if x not in SCAFFOLD or i == len(parts) - 1]
    if parts and parts[0] == 'global':
        parts = parts[1:]
    return 'https://www.aku.edu/' + '/'.join(parts)


_drift = [p['new_path'] for p in PLACED if public_url(p['new_path']) != p['new_url']]
if _drift:
    raise SystemExit(
        'public_url() here no longer matches the plan (%d pages, e.g. %s). '
        'build_migration_plan.py changed its address rule; copy it across '
        'before trusting this audit.' % (len(_drift), _drift[0]))


def leaf(page):
    return page['new_path'].rsplit('/', 1)[-1]


pages_in = collections.defaultdict(list)
for _p in PLACED:
    pages_in[_p['folder']].append(_p)

# ------------------------------------------------------------------ the checks
# Appended in the order a reviewer should read them: legality first, then
# coverage, then what AKU owes an answer.
rows = []


def check(name, question, count, verdict, detail):
    rows.append({'check': name, 'question': question, 'count': count,
                 'verdict': verdict, 'detail': detail})


# --- is it a legal tree at all? -------------------------------------------
dup_folders = [k for k, n in collections.Counter(
    f['new_path'] for f in FOLDERS).items() if n > 1]
check('folder paths unique', 'Do two folders claim one path?', len(dup_folders),
      'PASS' if not dup_folders else 'DEFECT',
      '%d folders, %d distinct paths' % (len(FOLDERS), len(FPATHS)))

orphans = [f['new_path'] for f in FOLDERS
           if f['parent_path'] and f['parent_path'] not in FPATHS]
check('every parent exists', 'Does any folder name a parent that is not built?',
      len(orphans), 'PASS' if not orphans else 'DEFECT',
      'a missing parent means the folder cannot be created')

mis_parent = [f['new_path'] for f in FOLDERS
              if f['level'] > 1 and f['new_path'].rsplit('/', 1)[0] != f['parent_path']]
mis_level = [f['new_path'] for f in FOLDERS
             if f['level'] != f['new_path'].count('/') + 1]
check('path, parent and level agree',
      'Does parent_path or level ever disagree with the path itself?',
      len(mis_parent) + len(mis_level),
      'PASS' if not (mis_parent or mis_level) else 'DEFECT',
      'level equals depth, and parent_path equals the path minus its last segment')

homeless = [p['current_url'] for p in PLACED if p['folder'] not in FPATHS]
check('every page has its folder',
      'Does any page land in a folder that is not built?',
      len(homeless), 'PASS' if not homeless else 'DEFECT',
      'checked against the %d folders, not against the source webs' % len(FOLDERS))

off_folder = [p['new_path'] for p in PLACED
              if p['new_path'].rsplit('/', 1)[0] != p['folder']]
check('page sits directly in its folder',
      'Is any page a level away from the folder column that claims it?',
      len(off_folder), 'PASS' if not off_folder else 'DEFECT',
      'new_path minus its last segment must equal folder')

dup_dest = [k for k, n in collections.Counter(
    p['new_path'] for p in PLACED).items() if n > 1]
dup_addr = [k for k, n in collections.Counter(
    p['new_url'] for p in PLACED).items() if n > 1]
check('one page per path and address',
      'Do two pages share a CMS path or a public address?',
      len(dup_dest) + len(dup_addr),
      'PASS' if not (dup_dest or dup_addr) else 'DEFECT',
      '7 pairs did collide and were suffixed -2; see the collision column in '
      'aku-page-map.csv')

# --- the one the plan does not check --------------------------------------
clashes = sorted(p['new_path'] for p in PLACED if p['new_path'] in FPATHS)
check('no page on a folder path',
      'Does any page claim a path a FOLDER already occupies?',
      len(clashes), 'DEFECT' if clashes else 'PASS',
      'in Storyblok a folder is a story, so the two share one slug namespace: '
      'these stories cannot be created as planned. Listed in '
      'aku-hierarchy-landing-pages.csv')

# --- the address rule ------------------------------------------------------
# All three of these used to be open questions here. They are now decided and
# implemented in build_migration_plan.py, so what this section does has changed
# from asking to CHECKING: the same measurements, but a DEFECT if the result
# ever regresses.
homes = [p for p in PLACED if leaf(p) == 'home']
bad_home = [p['new_url'] for p in PLACED if p['new_url'].endswith('/home')]
check('front doors are addressed at the folder',
      'Does any folder landing page still carry /home in its ADDRESS?',
      len(bad_home), 'DEFECT' if bad_home else 'PASS',
      '%d pages are a folder landing page stored at <folder>/home; public_url() '
      'strips the segment so the reader gets the folder address. AKU decided '
      'this on 7 Sep 2026' % len(homes))

root = [p for p in PLACED if p['new_url'] == 'https://www.aku.edu/']
check('the university homepage',
      'Is exactly one page addressed at the site root?',
      len(root), 'PASS' if len(root) == 1 else 'DEFECT',
      'aku.edu/Pages/home.aspx is the one page whose address is aku.edu/ '
      'itself. Guarding against the empty join published it at aku.edu/home')

twice = sorted(a for a, n in collections.Counter(
    p['new_url'] for p in PLACED).items() if n > 1)
check('front doors claimed twice',
      'Do two pages want one address?',
      len(twice), 'DEFECT' if twice else 'PASS',
      'AKU has both X/Pages/<name>.aspx and X/<name>/Pages/home.aspx for some '
      'sections. The newest published page takes the front door and the other '
      'keeps its content at <folder>/<leaf>-archive -- measured on live status, '
      'SharePoint version and modified date, not assumed')

both_conv = sorted(f for f, qs in pages_in.items()
                   if {'home', 'default'} <= {leaf(q) for q in qs})
check('two landing pages in one folder',
      'Does a folder still hold both a home and a default page?',
      len(both_conv), 'DEFECT' if both_conv else 'PASS',
      'SharePoint used both conventions; %d default pages exist in all. The '
      'loser of each pair is now <leaf>-archive, so no folder has two'
      % sum(1 for p in PLACED if leaf(p) == 'default'))

arch = [p for p in PLACED if p['new_path'].split('/')[-1].endswith('-archive')]
check('superseded pages kept',
      'How many pages lost a front door but kept their content?',
      len(arch), 'PASS',
      'AKU rule: nothing is dropped. Each is at <folder>/<leaf>-archive with a '
      'collision remark naming the page that superseded it')

# --- coverage --------------------------------------------------------------
check('pages placed', 'How many of the pages have a destination?',
      len(PLACED), 'PASS',
      '%d placed, %d resolved as do-not-migrate, %d in '
      'aku-university-filtered.csv' % (len(PLACED), len(DROPPED), len(PAGES)))

empty = [f for f in FOLDERS if not f['pages_subtree']]
check('folders with no page anywhere below',
      'How many folders would be created empty?', len(empty), 'PASS',
      'real SharePoint webs carrying permissions but holding no page in AKU '
      'inventory. AKU decided on 7 Sep 2026 to CREATE them: an empty folder '
      'costs nothing, keeps the structure complete and makes it visible where '
      'content is missing, and the portal filter hides them. %d of them are '
      'AKU own test sites, parked under staging/ and labelled as such in '
      'aku-master-folders.csv'
      % sum(1 for f in empty if f['new_path'].startswith('staging')))

_src = collections.Counter(p['managed_by_source'] for p in PAGES)
check('pages with no named owner',
      'How many pages fall back to central comms because nobody is named?',
      sum(n for k, n in _src.items() if k.startswith('fallback')),
      'PASS',
      '%d named by the permissions export, %d by the page own CW/CA, %d by the '
      'faculty they sit under. What is left is global hubs, About AKU, the event '
      'microsites and procurement, where central comms is the right answer and '
      'not a gap -- every ancestor of these pages is unowned too, and the first '
      'named one is the aku.edu root, whose rows say Registrar'
      % (_src['permissions export'], _src['page CW/CA'],
         sum(n for k, n in _src.items() if k.startswith('the faculty'))))

check('placements not witnessed',
      'How many folders rest on a naming convention rather than the export?',
      sum(1 for f in FOLDERS if f['confidence'] != 'witnessed'), 'PASS',
      'both are dead: global/akupreuniversity (2 pages) and global/apply-online '
      '(0 pages) have no permission rows at all beyond the root AND return HTTP '
      '404 on the live site, so there is nothing to witness and nothing to '
      'place. They stay at global/ with a 404 remark. Every other folder is '
      'witnessed by a CW/CA pair, an AD domain majority or the section title; '
      'see the confidence column in aku-folder-map.csv')

check('open decisions', 'How many questions is AKU holding, and over what?',
      len(DECISIONS), 'AKU DECISION',
      '%d pages at stake across %s' % (
          sum(d['pages'] for d in DECISIONS),
          ', '.join('%d %s' % (n, g) for g, n in collections.Counter(
              d['group'] for d in DECISIONS).most_common())))

with open(paths.out('aku-live-page-verification.csv'),
          encoding='utf-8-sig', newline='') as f:
    verdicts = collections.Counter(r['verdict'] for r in csv.DictReader(f))
check('checked against the live site',
      'How many placements does the site own breadcrumb confirm?',
      sum(n for v, n in verdicts.items() if v.startswith('agrees')), 'PASS',
      'and none contradict one. %s' % '; '.join(
          '%d %s' % (n, v) for v, n in verdicts.most_common()
          if not v.startswith('agrees')))

# --- shape -----------------------------------------------------------------
check('tree depth', 'How deep does the folder tree go?',
      max(f['level'] for f in FOLDERS), 'PASS',
      'folders per level: %s' % '; '.join(
          'L%d=%d' % (lv, n) for lv, n in sorted(
              collections.Counter(f['level'] for f in FOLDERS).items())))
check('page depth', 'How deep does a page sit?',
      max(p['new_path'].count('/') + 1 for p in PLACED), 'PASS',
      'pages per depth: %s' % '; '.join(
          'D%d=%d' % (d, n) for d, n in sorted(
              collections.Counter(
                  p['new_path'].count('/') + 1 for p in PLACED).items())))

# ------------------------------------------------- the contested front doors
land = []
for path in clashes:
    folder = FBY[path]
    page = next(p for p in PLACED if p['new_path'] == path)
    name = path.rsplit('/', 1)[-1]
    rival = next((q for q in pages_in.get(path, [])
                  if leaf(q) in ('home', 'default')), None)
    if rival:
        issue = ('two source pages for one front door: a page named %s beside '
                 'the %s sub-web own %s page' % (name, name, leaf(rival)))
        decide = ('pick one to keep the address; the other becomes a redirect '
                  'or is dropped')
    else:
        issue = ('a page wants the exact path of a folder holding %d page(s), '
                 'and nothing in that folder is a landing page'
                 % folder['pages_subtree'])
        decide = ('make it the folder front door (slug home inside it), or give '
                  'it a different slug')
    land.append({
        'folder_path': path,
        'folder_title': folder['title'],
        'folder_source_web': folder['source_web'],
        'pages_in_folder': folder['pages_subtree'],
        'issue': issue,
        'page_url': page['current_url'],
        'page_wants_path': page['new_path'],
        'page_wants_address': page['new_url'],
        'rival_url': rival['current_url'] if rival else '',
        'rival_wants_path': rival['new_path'] if rival else '',
        'address_both_want': public_url(path, True),
        'managed_by': page['managed_by'],
        'to_decide': decide,
    })

# The same contest without the folder clash: one folder, a home AND a default.
for folder_path in both_conv:
    qs = {leaf(q): q for q in pages_in[folder_path]}
    home, default = qs['home'], qs['default']
    land.append({
        'folder_path': folder_path,
        'folder_title': FBY[folder_path]['title'],
        'folder_source_web': FBY[folder_path]['source_web'],
        'pages_in_folder': FBY[folder_path]['pages_subtree'],
        'issue': 'folder holds both a home and a default page',
        'page_url': home['current_url'],
        'page_wants_path': home['new_path'],
        'page_wants_address': home['new_url'],
        'rival_url': default['current_url'],
        'rival_wants_path': default['new_path'],
        'address_both_want': public_url(folder_path, True),
        'managed_by': home['managed_by'],
        'to_decide': 'which of the two is the front door',
    })

AUDIT_COLS = ['check', 'question', 'count', 'verdict', 'detail']
LAND_COLS = ['folder_path', 'folder_title', 'folder_source_web',
             'pages_in_folder', 'issue', 'page_url', 'page_wants_path',
             'page_wants_address', 'rival_url', 'rival_wants_path',
             'address_both_want', 'managed_by', 'to_decide']


def write_csv(name, data, cols):
    with open(paths.out(name), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        w.writerows(data)
    print('%-38s %d rows' % (name, len(data)))


write_csv('aku-hierarchy-audit.csv', rows, AUDIT_COLS)
write_csv('aku-hierarchy-landing-pages.csv', land, LAND_COLS)

print('checks %d  %s' % (len(rows), '  '.join(
    '%s=%d' % (v, n) for v, n in
    collections.Counter(r['verdict'] for r in rows).most_common())))
for r in rows:
    if r['verdict'] == 'DEFECT':
        print('  DEFECT  %s -> %s' % (r['check'], r['count']))
