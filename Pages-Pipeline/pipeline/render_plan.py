"""Render the plan as one page AKU can check, filter, and export.

This file goes to AKU. Nobody reading it has run the pipeline, and nobody
reading it should have to: it is the whole plan — every page, where it will
live, who will be able to edit it, and what we still need them to answer.

Three things follow from that audience, and they are the reason this is not
just a dump of the CSVs.

**Columns are named in words, not field names.** `new_path`, `managed_by_source`
and `do_not_migrate` mean something to this repo and nothing to a reader at AKU.
Every column has a plain label and a plain sentence explaining it, and the ones
that only matter to us are hidden until someone asks for them.

**Filters compare a field to its own value.** The old bar was one search box and
one dropdown, both matching a substring of every field joined together, so
choosing *Kenya* also returned Kenya pages filed under Global — the word occurs
in `regions/global/…/training-kenyan-manufacturers`. 112 rows for a region with
100 pages. A reviewer cannot verify anything against a filter that quietly
includes rows it should not, so every dropdown now tests the column it names,
and carries the count each value would give.

**Export gives you the rows you are looking at.** The current filter, every
matching row, the columns on screen, with their plain headings — UTF-8 with a
BOM so Excel opens it directly. That is how AKU sends corrections back.

Everything is inline: no CDN, no fonts, no fetch. It opens from a bare clone by
double-clicking, which is the rule for every portal in this repo.
"""
import csv
import html
import json
import os

import paths

csv.field_size_limit(10 ** 9)

OUT = paths.out('AKU-Migration-Plan.html')
plan = json.load(open(paths.work('plan.json'), encoding='utf-8'))
F, P, R = plan['folders'], plan['pages'], plan['roles']
DECISIONS = plan['decisions']
e = html.escape

# ---- join what opening the live page said -------------------------------
# verify_live.py runs after the plan is built, so its results come from the CSV.
# Absent on a clone that has not run it, and the tab then says so.
VERIFY = paths.out('aku-live-page-verification.csv')
checks = []
if os.path.exists(VERIFY):
    with open(VERIFY, encoding='utf-8-sig', newline='') as fh:
        checks = list(csv.DictReader(fh))
by_url = {c['current_url']: c for c in checks}

# ---- pages the crawl found that AKU's export never listed ----------------
# They are shown beside the listed pages, in the same tree and the same table,
# because a separate report is a report nobody opens — and the whole point is
# that SharePoint is being switched off and these would go with it. Every one is
# marked, and "In AKU's list" filters them out in a click for anyone who wants
# the agreed scope and nothing else.
FOUND = paths.out('aku-pages-not-in-the-list.csv')
found = []
if os.path.exists(FOUND):
    with open(FOUND, encoding='utf-8-sig', newline='') as fh:
        for r in csv.DictReader(fh):
            if str(r.get('http')) != '200':
                continue          # a 404 is a broken link on their site, not a page
            found.append({
                'current_url': r['url'],
                'new_url': '', 'new_path': '', 'content_type': 'page',
                'action': '', 'review_status': '', 'new_in_export': '',
                'in_list': 'Not in AKU’s list',
                'region': r['would_be_region'], 'region_code': '',
                'entity': r['would_be_entity'], 'department': '',
                'folder': r['would_be_folder'], 'moved_from': '',
                'managed_by': '', 'managed_by_source': '', 'page_owner': '',
                'countries': '', 'confidence': '', 'collision': '',
                'do_not_migrate': '', 'live_http': r['http'],
                'live_verdict': '', 'breadcrumb': r.get('breadcrumb', ''),
                'title': r.get('title', ''), 'linked_from': r.get('linked_from', ''),
            })
for r in P:
    r['in_list'] = 'In AKU’s list'
    r['linked_from'] = ''
    r['title'] = ''
P = P + found
for r in P:
    c = by_url.get(r['current_url'], {})
    r['live_http'] = c.get('http', '')
    r['live_verdict'] = c.get('verdict', '')
    r['breadcrumb'] = c.get('breadcrumb', '')

# ---- values, said in words ----------------------------------------------
# Not decoration. "page CW/CA" and "fallback — nobody named" are this pipeline's
# shorthand; a reader at AKU has no way to know that the first means we read the
# team off the page itself.
SAY = {
    'managed_by_source': {
        'permissions export': 'SharePoint permissions',
        'page CW/CA': 'The page’s own editor group',
        'fallback — nobody named': 'No owner recorded anywhere',
    },
    'live_verdict': {
        'agrees': 'Confirmed — matches the live page',
        'agrees (section deeper in trail)': 'Confirmed — matches the live page',
        'agrees (looser name)': 'Confirmed — matches the live page',
        'not reachable': 'Could not open it (not public)',
        'no breadcrumb': 'Page has no trail to check against',
        'site root — no section above it': 'Top-level page — nothing above it',
        'SharePoint library page — trail is local to the library':
            'Inside a SharePoint library — no trail to check',
        'no title to compare': 'Nothing to compare against',
    },
    'confidence': {
        'witnessed': 'Proven by the export',
        'inferred': 'Inferred — please confirm',
        'decide': 'Needs your decision',
    },
    'new_in_export': {'new': 'New in this list'},
    'review_status': {
        'MIGRATE': 'Ready to migrate',
        'NOT_REVIEWED': 'Not reviewed yet',
        'UNCLEAR': 'Marked unclear',
    },
    'own_permissions': {'yes': 'Yes', 'no': 'Inherited from parent'},
}


def say(col, v):
    return SAY.get(col, {}).get(v, v)


# ---- columns: label, plain description, and whether AKU sees it first ----
# (field, label, description, default-visible)
PAGE_COLS = [
    ('current_url', 'Page today', 'The page as it is now on aku.edu. Click to open it.', 1, 290, 0),
    ('new_url', 'Goes to', 'What the address becomes once migrated.', 1, 290, 0),
    ('region', 'Region', 'Which part of the University it belongs to.', 1, 120, 0),
    ('entity', 'Faculty / institute', 'The academic unit, where the page belongs to one. '
     'Blank means it sits at region level and belongs to no single faculty.', 1, 210, 0),
    ('department', 'Department', 'The department, where the SharePoint permissions prove '
     'one owns it.', 1, 130, 0),
    ('managed_by', 'Managed by', 'The team that will be able to edit it after the move. '
     'This is the one to check hardest — it decides who gets access.', 1, 190, 0),
    ('new_in_export', 'New?', 'Marked when this page is in your latest list and was not in '
     'the earlier one.', 1, 120, 0),
    ('in_list', 'In your list?', 'Every page in your export says "In AKU’s list". The rest '
     'we found by following links on your own site — they are live, and no export mentions '
     'them, so nothing would migrate them. Filter this to see or hide them.', 1, 160, 0),
    ('title', 'Page title', 'The page’s own title, for the ones we found on the site.',
     0, 240, 0),
    ('linked_from', 'Found via', 'The page that links to it — how we know it exists.',
     0, 280, 0),
    ('review_status', 'Your review status', 'From your own list: ready to migrate, not '
     'reviewed yet, or unclear. Where the page goes is settled either way.', 0, 150, 0),
    ('live_verdict', 'Did we check it?', 'We opened each page and read the trail AKU '
     'prints at the top of it, to confirm the page lands where you already file it.', 0, 230, 0),
    ('new_path', 'Folder path in the new system', 'The internal path. `regions/`, '
     '`entities/` and `departments/` are structure for editors and permissions; readers '
     'never see them.', 0),
    ('folder', 'Destination folder', 'The folder it lands in.', 0),
    ('content_type', 'Kind', 'A normal page, or news / event / blog, which live in one '
     'shared hub rather than in each faculty’s own folder.', 0),
    ('action', 'Your instruction', 'From your list: move as is, or update then move.', 0),
    ('moved_from', 'Moved out of', 'Set when a page was pulled from a faculty folder into '
     'a shared hub. Its old home, so a redirect can be made.', 0),
    ('managed_by_source', 'How we know the owner', 'Whether the team came from the '
     'SharePoint permissions on the folder, or from the editor group set on the page '
     'itself where the folder named nobody.', 0),
    ('page_owner', 'Editor group on the page', 'The content writer / approver groups set '
     'on the page in SharePoint.', 0),
    ('countries', 'Countries', 'For a unit that works across several.', 0),
    ('confidence', 'How sure we are', 'Proven by your export, inferred from a naming '
     'convention, or genuinely needing your decision.', 0),
    ('collision', 'Name clash', 'Two pages want the same address. Shown, not silently '
     'resolved — you pick.', 0),
    ('do_not_migrate', 'Not migrating', 'Why a page does not move — in the words of what '
     'the server actually returned when we opened it.', 0),
    ('live_http', 'Server response', '200 answered, 401 is not publicly reachable, 404 is '
     'gone.', 0),
    ('breadcrumb', 'Trail on the live page', 'The trail AKU prints at the top of the page '
     '— your own statement of where it belongs.', 0),
]
FOLDER_COLS = [
    ('new_path', 'Folder', 'Where the folder sits in the new system.', 1),
    ('title', 'Name', 'Its name, as SharePoint has it today.', 1),
    ('kind', 'What it is', 'A region, a faculty or institute, a department, or a plain '
     'folder.', 1),
    ('region', 'Region', 'Which part of the University it belongs to.', 1),
    ('entity', 'Faculty / institute', 'The academic unit it belongs to, if any.', 1),
    ('pages_subtree', 'Pages inside', 'Pages in it and everything under it.', 1),
    ('managed_by', 'Managed by', 'The team that will administer it.', 1),
    ('pages_here', 'Pages directly in it', 'Not counting sub-folders.', 0),
    ('source_web', 'Comes from', 'The SharePoint site it is built from.', 0),
    ('level', 'Depth', 'How deep it sits in the tree.', 0),
    ('own_permissions', 'Own permissions', 'Whether it has its own permissions or '
     'inherits them.', 0),
    ('permission_source', 'Permissions from', 'Which site its permissions come from.', 0),
    ('countries', 'Countries', 'For a unit working across several.', 0),
    ('also_belongs_to', 'Also belongs to', 'A folder run by a team from another faculty — '
     'it can only live in one place, so this records the other.', 0),
    ('event_owner', 'Event run by', 'For an event microsite, the unit its own page says '
     'runs it.', 0),
    ('last_ran', 'Last edition', 'The most recent year the event page names.', 0),
    ('archive_candidate', 'Archive?', 'Flagged where the last edition is old enough that '
     'it may be worth archiving rather than migrating.', 0),
    ('confidence', 'How sure we are', 'Proven, inferred, or needing your decision.', 0),
    ('provenance', 'Why it is placed here', 'The evidence for this placement, in full.', 0),
]
ROLE_COLS = [
    ('storyblok_role', 'Role', 'The role to create in the new system.', 1),
    ('capability', 'Can do', 'Edit, publish, manage structure, or read only.', 1),
    ('unit', 'Team', 'The AKU team it belongs to.', 1),
    ('members', 'People', 'How many people would hold it.', 1),
    ('folders_scoped', 'Folders', 'How many folders it covers.', 1),
    ('can_publish', 'Can publish', 'Whether it can make content live.', 0),
    ('source_sharepoint_groups', 'Replaces', 'The SharePoint groups it replaces.', 0),
    ('allowed_paths', 'Applies to', 'The folders it applies to.', 0),
    ('note', 'Note', '', 0),
]
CHECK_COLS = [
    ('current_url', 'Page we opened', 'Click to open it yourself.', 1),
    ('verdict', 'Result', 'Whether the trail on the live page agrees with where we file '
     'it.', 1),
    ('breadcrumb', 'Trail on the page', 'What AKU prints at the top of the page.', 1),
    ('folder', 'Where we file it', 'The folder the plan sends it to.', 1),
    ('region', 'Region', 'Region of that folder.', 1),
    ('new_in_export', 'New?', 'Whether this page is new in your latest list.', 1),
    ('http', 'Server response', '200 answered, 401 not public, 404 gone.', 0),
    ('live_title', 'Page title', 'The page’s own title.', 0),
    ('section', 'Section in the address', 'The section its web address puts it in.', 0),
    ('section_title_in_export', 'Section name in your export', 'What we compared the '
     'trail against.', 0),
    ('entity', 'Faculty / institute', 'Entity of that folder, if any.', 0),
]
DEC_COLS = [
    ('question', 'What we need you to decide', '', 1),
    ('group', 'Kind of question', '', 1),
    ('evidence', 'What we already know', 'Usually what the live site returned.', 1),
    ('options', 'The choices', 'The answers actually available.', 1),
    ('pages', 'Pages affected', 'How many pages the answer moves.', 1),
    ('folders', 'Folders affected', '', 1),
    ('example_paths', 'For example', 'A few of the folders involved.', 0),
    ('blocks', 'Holds up', 'What cannot proceed until it is answered.', 0),
    ('id', 'Reference', 'Quote this when you reply.', 0),
]

# Two tables, because the deliverable is the hierarchy and nothing else: the
# folder tree, and the pages that sit in it. Roles, the live-check evidence and
# the open questions are all real work and all live in their own files — they are
# not what this page is for, and putting them here made it a report to read
# rather than a structure to check.
SPEC = {'folders': FOLDER_COLS, 'pages': PAGE_COLS}
SRC = {'folders': F, 'pages': P}

# Columns are (field, label, description, shown-by-default[, width, wrap]).
# Width fixes the grid so headings line up down the page; without it the browser
# sizes every column to its longest value and a 162-character address drags the
# whole table out of shape. `wrap` is for the few columns that are a sentence
# rather than a value — a question or a reason, which has to be readable in full.
WIDE = {'question': 420, 'evidence': 320, 'options': 300, 'provenance': 420,
        'breadcrumb': 320, 'do_not_migrate': 340, 'note': 280, 'allowed_paths': 300,
        'source_sharepoint_groups': 260, 'collision': 300, 'live_title': 260,
        'new_path': 300, 'folder': 260, 'moved_from': 240, 'source_web': 220,
        'also_belongs_to': 260, 'example_paths': 320, 'blocks': 240,
        'entity_basis': 360, 'current_url': 290, 'new_url': 290}
WRAPS = {'question', 'evidence', 'options', 'provenance', 'do_not_migrate',
         'note', 'entity_basis', 'blocks'}


def spec(name):
    """Every column padded to (field, label, doc, default, width, wrap)."""
    out = []
    for c in SPEC[name]:
        f, label, doc, deflt = c[0], c[1], c[2], c[3]
        width = c[4] if len(c) > 4 else WIDE.get(f, 160)
        wrap = c[5] if len(c) > 5 else (1 if f in WRAPS else 0)
        out.append((f, label, doc, deflt, width, wrap))
    return out


# The order rows arrive in is the order the plan was built in — by address, so
# `about/…` then `academics/…`, with regions and faculties interleaved all the
# way down. Nothing groups, and a reviewer checking one faculty has to read
# 4,591 rows to find its pages. Sorting by region, then faculty, then address
# puts every related row together, which is what makes the table readable before
# anyone touches a filter.
DEFAULT_SORT = {
    # Folders in path order, which is the tree read top to bottom.
    'folders': ['new_path'],
    'pages': ['region', 'entity', 'department', 'current_url'],
}


def table(name):
    sp = spec(name)
    cols = [c[0] for c in sp]
    rows = [[say(c, str(r.get(c, '') or '')) for c in cols] for r in SRC[name]]
    keys = [cols.index(k) for k in DEFAULT_SORT.get(name, []) if k in cols]
    if keys:
        # Blank sorts last: an empty faculty is "no faculty", not the first one.
        rows.sort(key=lambda r: tuple((r[i] == '', r[i].lower()) for i in keys))
    return {
        'cols': cols,
        'labels': [c[1] for c in sp],
        'docs': [c[2] for c in sp],
        'deflt': [c[3] for c in sp],
        'width': [c[4] for c in sp],
        'wrap': [c[5] for c in sp],
        'rows': rows,
    }


# Which columns get a dropdown. Only fields with a small closed set of values —
# a filter over 4,591 distinct addresses is a search box, not a list.
FILTERS = {
    'folders': ['region', 'entity', 'kind', 'managed_by', 'level'],
    'pages': ['in_list', 'region', 'entity', 'department', 'managed_by',
              'new_in_export', 'live_http', 'review_status', 'live_verdict',
              'content_type', 'action', 'confidence', 'managed_by_source'],
}
# The first few sit in the bar; the rest are behind "More filters", so the
# default view is four dropdowns instead of fourteen.
PRIMARY = {'folders': 4, 'pages': 5}
# Columns holding a different sentence on every row: the useful question is
# whether there is one at all, so these get Any / Yes / No.
FLAGS = {'folders': [], 'pages': ['do_not_migrate', 'collision', 'moved_from']}
# One click for the views a reviewer would otherwise rebuild by hand.
PRESETS = {
    'folders': [['Faculties and institutes', {'kind': 'entity'}],
                ['Departments', {'kind': 'department'}]],
    'pages': [['Only what you listed', {'in_list': 'In AKU’s list'}],
              ['Only what we found', {'in_list': 'Not in AKU’s list'}],
              ['New in this list', {'new_in_export': 'New in this list'}],
              ['Did not open (401)', {'live_http': '401'}]],
}

DATA = {k: table(k) for k in SPEC}

# ---- the hierarchy itself -------------------------------------------------
# Two flat tables can say where every page goes and still not show the shape of
# the thing: to see what lands in one folder you had to read the folder table,
# note its path, then filter the page table by it. So the folders are nested
# here and their pages hung underneath, which is the view AKU is actually being
# asked to check — this folder, and these pages inside it.
pages_by_folder = {}
for r in P:
    pages_by_folder.setdefault(r['folder'], []).append(r)

node = {}
for f in F:
    node[f['new_path']] = {
        'p': f['new_path'],
        'n': (f['title'] or '').strip() or f['new_path'].split('/')[-1],
        'sl': f['new_path'].split('/')[-1],
        'k': f['kind'],
        'r': f['region'],
        'e': f['entity'],
        'm': f['managed_by'],
        'sub': 0,
        'c': [],
        'g': [],
    }
roots = []
for path in sorted(node):
    parent = path.rsplit('/', 1)[0] if '/' in path else ''
    (node[parent]['c'] if parent in node else roots).append(node[path])

for path, n in node.items():
    for r in sorted(pages_by_folder.get(path, []),
                    key=lambda x: x['current_url'].lower()):
        # Everything a filter in the hierarchy needs, kept per page so the tree
        # can answer "show me only the ones that did not open" without going
        # back to the tables.
        n['g'].append([
            r['current_url'].replace('https://www.aku.edu/', ''),
            r['new_url'].replace('https://www.aku.edu', ''),
            1 if r['new_in_export'] else 0,
            r['do_not_migrate'] or '',
            r.get('live_http', ''),
            r['review_status'],
            0 if r['in_list'].startswith('In') else 1,
        ])

# Pages whose folder has no row of its own would vanish from the tree, and the
# whole point of this view is that nothing does.
orphans = sum(len(v) for k, v in pages_by_folder.items() if k not in node)
if orphans:
    raise SystemExit('%d pages land in a folder with no row — the tree would '
                     'lose them' % orphans)


def rollup(n):
    """Count the pages actually hanging below this node.

    `pages_subtree` in the folder map counts from the source webs, and the
    levels this tree invents to hold things — `regions`, `entities`, each region
    folder — have no source web, so it reads 0. A region showing no page count
    while holding 438 of them is worse than no count at all, so the tree counts
    what the tree contains.
    """
    n['sub'] = len(n['g']) + sum(rollup(c) for c in n['c'])
    return n['sub']


for r in roots:
    rollup(r)

TREE = roots


named = sum(1 for r in P if 'central' not in r['managed_by'])
new_pages = sum(1 for r in P if r['new_in_export'])
n_found = len(found)
n_listed = len(P) - n_found
agree = sum(1 for c in checks if c['verdict'].startswith('agrees'))
unreach = sum(1 for c in checks if c['verdict'] == 'not reachable')
dnm = sum(1 for r in P if r['do_not_migrate'])
dec_pages = sum(int(d.get('pages') or 0) for d in DECISIONS)

CSS = """
*{box-sizing:border-box}
:root{--plane:#f9f9f7;--card:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--mut:#898781;
--grid:#e1e0d9;--ring:rgba(11,11,11,.10);--brand:#00594f;--brand2:#0b7f6f;
--ok:#0ca30c;--inf:#fab219;--dec:#d03b3b;--ser:#2a78d6;--chip:rgba(11,11,11,.05);
color-scheme:light}
@media(prefers-color-scheme:dark){:root{--plane:#0d0d0d;--card:#1a1a19;--ink:#fff;
--ink2:#c3c2b7;--mut:#898781;--grid:#2c2c2a;--ring:rgba(255,255,255,.12);
--brand:#0b7f6f;--brand2:#12a08c;--ser:#3987e5;--chip:rgba(255,255,255,.06);
color-scheme:dark}}
body{margin:0;background:var(--plane);color:var(--ink);
font:14px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
header{background:var(--brand);color:#fff;padding:16px 22px 15px}
h1{margin:0 0 3px;font-size:18px;font-weight:640}
header p{margin:0;font-size:12.5px;color:rgba(255,255,255,.85)}
header b{color:#fff}
.bar{position:sticky;top:0;z-index:20;background:var(--plane);
border-bottom:1px solid var(--grid);padding:10px 18px;display:flex;gap:8px;
align-items:center;flex-wrap:wrap}
.tabs{display:flex;gap:3px;background:var(--grid);border-radius:9px;padding:3px}
.tab{border:0;background:transparent;padding:7px 13px;border-radius:7px;
cursor:pointer;font-size:13px;color:var(--ink2);font-weight:550}
.tab.on{background:var(--card);color:var(--brand2)}
#q{flex:1;min-width:210px;padding:9px 12px;border:1px solid var(--ring);
border-radius:8px;font-size:13px;background:var(--card);color:var(--ink)}
select,.btn{padding:8px 10px;border:1px solid var(--ring);border-radius:8px;
font-size:12.5px;background:var(--card);color:var(--ink);cursor:pointer}
.btn:hover{border-color:var(--brand2);color:var(--brand2)}
.btn.pri{background:var(--brand);color:#fff;border-color:var(--brand);font-weight:600}
.btn.pri:hover{background:var(--brand2)}
.fbar{padding:10px 18px;border-bottom:1px solid var(--grid);display:flex;gap:9px;
flex-wrap:wrap;align-items:flex-end;background:var(--card)}
.fbar label.f{display:flex}
/* Filters live in one panel behind one button. Fourteen dropdowns across the
   top read as a form to fill in; a single button with a count reads as a tool
   you reach for. */
.pop{position:absolute;right:14px;top:52px;z-index:40;background:var(--card);
border:1px solid var(--ring);border-radius:12px;padding:14px;
box-shadow:0 14px 40px rgba(0,0,0,.17);display:grid;
grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:11px;
min-width:min(680px,94vw);max-width:94vw;max-height:74vh;overflow:auto}
.pop[hidden]{display:none}
.pop label{display:flex;flex-direction:column;gap:3px;font-size:10.5px;
color:var(--mut);text-transform:uppercase;letter-spacing:.04em;font-weight:650}
.pop select{width:100%}
.pop .full{grid-column:1/-1;display:flex;gap:14px;align-items:center;
flex-wrap:wrap;border-top:1px solid var(--grid);padding-top:11px;margin-top:2px;
text-transform:none;letter-spacing:0;font-size:12.5px;color:var(--ink2);
flex-direction:row}
.pop .full label{flex-direction:row;align-items:center;gap:6px;font-size:12.5px;
text-transform:none;letter-spacing:0;color:var(--ink2);font-weight:500}
.badge{background:var(--brand);color:#fff;border-radius:999px;padding:0 6px;
font-size:10.5px;margin-left:5px;font-weight:700}
.fbar label{display:flex;flex-direction:column;gap:2px;font-size:10.5px;
color:var(--mut);text-transform:uppercase;letter-spacing:.04em;font-weight:650}
.chips{padding:8px 18px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;
border-bottom:1px solid var(--grid)}
.chips:empty{display:none}
.chip{border:1px solid var(--ring);background:var(--chip);border-radius:999px;
padding:5px 11px;font-size:12px;cursor:pointer;color:var(--ink2)}
.chip:hover{border-color:var(--brand2);color:var(--brand2)}
.chip.on{background:var(--brand);color:#fff;border-color:var(--brand)}
.count{font-size:12.5px;color:var(--ink2);margin-left:auto;white-space:nowrap}
.count b{color:var(--ink)}
.wrap{padding:0 18px 70px;overflow-x:auto}
/* Fixed layout, one line per cell. Left to itself the browser sizes each column
   to its longest value — a 162-character address — and the headings stop lining
   up with anything below them. A clipped cell keeps its full text in the tooltip
   and in the export. */
table{border-collapse:separate;border-spacing:0;font-size:12.5px;
table-layout:fixed;min-width:100%}
th{position:sticky;top:0;background:var(--plane);text-align:left;
border-bottom:1px solid var(--grid);padding:10px 10px;font-size:11px;
letter-spacing:.02em;color:var(--ink2);cursor:pointer;white-space:nowrap;
z-index:5;font-weight:660;overflow:hidden;text-overflow:ellipsis}
th:hover{color:var(--brand2)}
th .ar{opacity:.55;font-size:9px;margin-left:2px}
td{border-bottom:1px solid var(--grid);padding:7px 10px;vertical-align:top;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
td.w{white-space:normal;overflow-wrap:anywhere}
tbody tr:nth-child(even) td{background:rgba(127,127,127,.035)}
tbody tr:hover td{background:var(--chip)}
a{color:var(--ser)}
.b{display:inline-block;padding:1px 7px;border-radius:999px;font-size:10.5px;
font-weight:660;white-space:nowrap}
.b.ok{background:rgba(12,163,12,.13);color:#0a7d0a}
.b.inf{background:rgba(250,178,25,.18);color:#8a6100}
.b.dec{background:rgba(208,59,59,.13);color:#b02c2c}
.b.new{background:var(--ok);color:#fff}
.hint{color:var(--ink2);font-size:13px;margin:14px 0 10px;max-width:88ch}
details.docs{margin:12px 0 14px;border:1px solid var(--grid);border-radius:10px;
background:var(--card)}
details.docs summary{cursor:pointer;padding:11px 14px;font-weight:620;font-size:13px}
details.docs .in{padding:2px 14px 14px}
dl{margin:0;display:grid;grid-template-columns:minmax(130px,210px) 1fr;gap:6px 14px;
font-size:12.5px}
dt{color:var(--brand2);font-weight:640}
dd{margin:0;color:var(--ink2)}
.more{margin:16px 0;text-align:center}
.empty{padding:44px 8px;text-align:center;color:var(--mut)}
.cols{padding:10px 18px;border-bottom:1px solid var(--grid);font-size:12px;
color:var(--ink2);display:flex;gap:14px;flex-wrap:wrap;align-items:center;
background:var(--card)}
.cols label{display:inline-flex;gap:5px;align-items:center;cursor:pointer}
.btn.on{border-color:var(--brand2);color:var(--brand2);font-weight:640}
/* Secondary filters stay out of the way until asked for: four dropdowns read as
   a control bar, fourteen read as a form. */
.fbar .extra{display:none}
.fbar.open .extra{display:flex}
/* The folder table is the tree, so its first column is indented by depth and
   carries the folder's own name; the full path is in the tooltip and export. */
.tree{display:inline-block}
/* ---- the hierarchy view ---- */
#tree{padding:6px 0 40px;font-size:13px}
#tree ul{list-style:none;margin:0;padding:0 0 0 17px}
#tree>ul{padding-left:0}
#tree li{position:relative}
#tree li.cl>ul{display:none}
.row2{display:flex;align-items:center;gap:8px;padding:4px 8px;border-radius:7px;
cursor:default;white-space:nowrap}
.row2:hover{background:var(--chip)}
.fold>.row2{cursor:pointer}
.tw2{width:13px;flex:none;color:var(--mut);font-size:9px;text-align:center}
.fold>.row2 .tw2::before{content:'▾'}
.fold.cl>.row2 .tw2::before{content:'▸'}
.nm{font-weight:600}
.slug{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:10.5px;
color:var(--mut);flex:none}
.pg .nm{font-weight:400;font-family:ui-monospace,Menlo,Consolas,monospace;
font-size:12px;color:var(--ink2)}
.arrow{color:var(--mut);font-size:11px}
.dest{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11.5px;
color:var(--ser);overflow:hidden;text-overflow:ellipsis}
.kind{font-size:10px;padding:1px 6px;border-radius:999px;background:var(--chip);
color:var(--ink2);flex:none}
.kind.entity{background:rgba(11,127,111,.14);color:var(--brand2);font-weight:640}
.kind.department{background:rgba(42,120,214,.13);color:var(--ser);font-weight:600}
.kind.region{background:var(--brand);color:#fff;font-weight:640}
.cnt{font-size:11px;color:var(--mut);flex:none}
.team{font-size:11px;color:var(--mut);margin-left:auto;flex:none;
overflow:hidden;text-overflow:ellipsis;max-width:230px}
.nl{background:var(--dec);color:#fff;font-size:9.5px;padding:0 5px;border-radius:999px;font-weight:700;flex:none}
.nw{background:var(--ok);color:#fff;font-size:9.5px;padding:0 5px;
border-radius:999px;font-weight:700;flex:none}
.dnm{color:var(--dec);font-size:10.5px;flex:none}
.err{background:rgba(250,178,25,.2);color:#8a6100;font-size:9.5px;padding:0 5px;
border-radius:999px;font-weight:700;flex:none}
.err.g{background:rgba(208,59,59,.15);color:var(--dec)}
#tree li.hide{display:none}
.tree .tw{display:inline-block;width:9px;height:9px;margin-right:6px;
border-left:1px solid var(--grid);border-bottom:1px solid var(--grid);
vertical-align:middle;transform:translateY(-2px)}
"""

JS = r"""
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let TAB='hierarchy', SORT={col:null,dir:1}, SHOWN=0, VIEW=[], VIS=[];
const STEP=300;
const BADGE={'Proven by the export':'ok','Inferred — please confirm':'inf',
  'Needs your decision':'dec','Confirmed — matches the live page':'ok',
  'Could not open it (not public)':'inf','New in this list':'new',
  'Ready to migrate':'ok','Not reviewed yet':'inf','Marked unclear':'dec'};

const T=()=>DATA[TAB];
const cols=()=>T().cols, rows=()=>T().rows;
const esc=s=>String(s).replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));

/* ---- filtering -------------------------------------------------------
   Each dropdown compares the column it names to that column's own value. The
   previous version matched a substring against every field joined together,
   which is why "Kenya" returned 112 rows for a region that has 100. Only the
   search box looks across the whole row, which is what a search box is for. */
function active(){
  const f={};
  $$('#pop select').forEach(s=>{
    if(s.value) f[(s.dataset.flag?'!':'')+s.dataset.col]=s.value;
  });
  return f;
}
function keep(r,C,f){
  for(const k in f){
    if(k[0]==='!'){
      const i=C.indexOf(k.slice(1)), has=!!(r[i]&&r[i].trim());
      if((f[k]==='yes')!==has) return false;
    }else{
      const i=C.indexOf(k);
      if(i<0) continue;
      if(f[k]==='*'){ if(!(r[i]&&r[i].trim())) return false; }
      else if(r[i]!==f[k]) return false;
    }
  }
  return true;
}
function apply(){
  const t=$('#q').value.trim().toLowerCase(), f=active(), C=cols();
  VIEW=rows().filter(r=>keep(r,C,f)&&(!t||r.some(v=>v&&v.toLowerCase().includes(t))));
  if(SORT.col!==null){
    const i=SORT.col;
    VIEW.sort((a,b)=>{
      const x=a[i]||'',y=b[i]||'',nx=parseFloat(x),ny=parseFloat(y);
      const num=!isNaN(nx)&&!isNaN(ny)&&x.trim()!==''&&y.trim()!=='';
      return (num?nx-ny:x.localeCompare(y))*SORT.dir;
    });
  }
  SHOWN=0; $('#tbody').innerHTML=''; draw();
  $('#count').innerHTML='<b>'+VIEW.length.toLocaleString()+'</b> of '
    +rows().length.toLocaleString()+' rows';
  $('#empty').hidden=!!VIEW.length;
  facets();
}
/* Every dropdown shows what each value would give under the filters already
   set, so a combination that leads nowhere reads as (0) instead of an empty
   table with no explanation. */
function facets(){
  const C=cols(), f=active();
  $$('#pop select').forEach(sel=>{
    const col=sel.dataset.col, i=C.indexOf(col);
    const mine=(sel.dataset.flag?'!':'')+col, other={};
    for(const k in f) if(k!==mine) other[k]=f[k];
    const n={}; let filled=0, empty=0;
    rows().forEach(r=>{
      if(!keep(r,C,other)) return;
      if(r[i]&&r[i].trim()){ filled++; n[r[i]]=(n[r[i]]||0)+1; } else empty++;
    });
    [...sel.options].forEach(o=>{
      if(!o.value){o.textContent=o.dataset.label;return;}
      const c=(o.value==='*'||o.value==='yes')?filled:o.value==='no'?empty:(n[o.value]||0);
      o.textContent=o.dataset.label+' ('+c.toLocaleString()+')';
    });
  });
}

/* ---- drawing ---------------------------------------------------------
   A window of rows, extended as you scroll. Export always covers the whole
   filtered set, so nothing is hidden by having drawn only part of it. */
function cell(c,v,row){
  if(!v) return '';
  /* The folder table IS the hierarchy, so it is indented by depth and shows the
     folder's own name rather than repeating the whole path on every row. The
     full path stays in the tooltip and in the export. */
  if(TAB==='folders'&&c==='new_path'){
    const d=(v.split('/').length-1);
    return '<span class="tree" style="padding-left:'+(d*15)+'px">'
      +(d?'<span class="tw"></span>':'')+esc(v.split('/').pop())+'</span>';
  }
  if(c==='current_url'||c==='new_url')
    return '<a class="mono" href="'+esc(v)+'" target="_blank" rel="noopener">'
      +esc(v.replace('https://www.aku.edu',''))+'</a>';
  if(BADGE[v]) return '<span class="b '+BADGE[v]+'">'+esc(v)+'</span>';
  if(c==='new_path'||c==='folder'||c==='moved_from'||c==='source_web'
     ||c==='storyblok_role') return '<span class="mono">'+esc(v)+'</span>';
  return esc(v);
}
function draw(){
  const C=cols(), W=T().wrap, end=Math.min(SHOWN+STEP,VIEW.length);
  let h='';
  for(let i=SHOWN;i<end;i++){
    h+='<tr>';
    VIS.forEach(j=>{
      const v=VIEW[i][j];
      // The full value in the tooltip, so a clipped cell is never a lost one.
      h+='<td'+(W[j]?' class="w"':'')+(v?' title="'+esc(v)+'"':'')+'>'
        +cell(C[j],v,VIEW[i])+'</td>';
    });
    h+='</tr>';
  }
  $('#tbody').insertAdjacentHTML('beforeend',h);
  SHOWN=end;
  $('#more').hidden=SHOWN>=VIEW.length;
  if(SHOWN<VIEW.length)
    $('#moreb').textContent='Show more  ('+(VIEW.length-SHOWN).toLocaleString()+' still to see)';
}

/* ---- build a tab ----------------------------------------------------- */
function head(){
  const L=T().labels, D=T().docs, W=T().width;
  $('#thead').innerHTML='<tr>'+VIS.map(j=>
    '<th data-i="'+j+'" style="width:'+W[j]+'px" title="'+esc(D[j]||'')+'">'+esc(L[j])
    +'<span class="ar" id="ar'+j+'"></span></th>').join('')+'</tr>';
  $$('#thead th').forEach(th=>th.onclick=()=>{
    const i=+th.dataset.i;
    SORT=(SORT.col===i)?{col:i,dir:-SORT.dir}:{col:i,dir:1};
    $$('#thead .ar').forEach(a=>a.textContent='');
    $('#ar'+i).textContent=SORT.dir>0?'▲':'▼';
    apply();
  });
}
function build(){
  const C=cols(), L=T().labels, D=T().docs;
  VIS=T().deflt.map((d,i)=>d?i:-1).filter(i=>i>=0);

  let h=''; const lim=PRIMARY[TAB]||99;
  (FILTERS[TAB]||[]).forEach((col,n)=>{
    const i=C.indexOf(col); if(i<0) return;
    const extra='';
    const vals=[...new Set(rows().map(r=>r[i]).filter(v=>v&&v.trim()))]
      .sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
    if(!vals.length||vals.length>60) return;
    const blanks=rows().some(r=>!(r[i]&&r[i].trim()));
    h+='<label class="f'+extra+'">'+esc(L[i])+'<select data-col="'+col+'">'
      +'<option value="" data-label="Any">Any</option>'
      +(blanks?'<option value="*" data-label="— has one —">— has one —</option>':'')
      +vals.map(v=>'<option value="'+esc(v)+'" data-label="'+esc(v)+'">'+esc(v)+'</option>').join('')
      +'</select></label>';
  });
  (FLAGS[TAB]||[]).forEach(col=>{
    const i=C.indexOf(col); if(i<0) return;
    h+='<label class="f extra">'+esc(L[i])+'<select data-col="'+col+'" data-flag="1">'
      +'<option value="" data-label="Any">Any</option>'
      +'<option value="yes" data-label="Yes">Yes</option>'
      +'<option value="no" data-label="No">No</option></select></label>';
  });
  $('#pop').innerHTML=h+'<div class="full">'
    +'<button class="btn" id="clear">Clear all filters</button></div>';
  $('#chips').innerHTML=(PRESETS[TAB]||[]).map((p,i)=>
    '<button class="chip preset" data-i="'+i+'">'+esc(p[0])+'</button>').join('')
    +'<button class="chip" id="clearchip">Clear filters</button>';
  $('#cols').innerHTML=C.map((c,i)=>
    '<label><input type="checkbox" data-i="'+i+'"'+(VIS.includes(i)?' checked':'')
    +'> '+esc(L[i])+'</label>').join('')
    +'<button class="btn" id="allcols">Show every column</button>';
  $('#cols').hidden=true; $('#colsb').classList.remove('on');

  $$('#pop select').forEach(s=>s.onchange=()=>{
    $$('#chips .preset').forEach(p=>p.classList.remove('on'));
    apply();
  });
  countActive();
  $$('#chips .preset').forEach(b=>b.onclick=()=>{
    const want=PRESETS[TAB][+b.dataset.i][1], on=!b.classList.contains('on');
    reset();
    if(on){
      b.classList.add('on');
      for(const k in want){
        const s=$('#fbar select[data-col="'+k+'"]');
        if(s) s.value=want[k];
      }
    }
    apply();
  });
  const clearAll=()=>{reset();apply();};
  $('#clear').onclick=clearAll;
  $('#clearchip').onclick=clearAll;
  $$('#cols input').forEach(cb=>cb.onchange=()=>{
    VIS=$$('#cols input').filter(x=>x.checked).map(x=>+x.dataset.i);
    if(!VIS.length){cb.checked=true;VIS=[+cb.dataset.i];}
    head();SHOWN=0;$('#tbody').innerHTML='';draw();
  });
  $('#allcols').onclick=()=>{
    $$('#cols input').forEach(x=>x.checked=true);
    VIS=C.map((_,i)=>i); head();SHOWN=0;$('#tbody').innerHTML='';draw();
  };
  $('#docs').innerHTML='<summary>What every column means</summary><div class="in"><dl>'
    +C.map((c,i)=>'<dt>'+esc(L[i])+'</dt><dd>'+esc(D[i]||'—')+'</dd>').join('')
    +'</dl></div>';
  SORT={col:null,dir:1};
  head(); apply();
}
function reset(){
  $$('#pop select').forEach(s=>s.value='');
  $$('#pop input[type=checkbox]').forEach(c=>c.checked=false);
  $$('#chips .preset').forEach(b=>b.classList.remove('on'));
  $('#q').value='';
}

/* ---- export ----------------------------------------------------------
   The rows currently filtered to and the columns on screen, with the same
   headings — not the whole table, and not only the part drawn. BOM first so
   Excel opens it as UTF-8 without an import dialog. */
function csv(){
  const C=cols(), L=T().labels;
  const q=v=>'"'+String(v==null?'':v).replace(/"/g,'""')+'"';
  const body=[VIS.map(j=>q(L[j])).join(',')]
    .concat(VIEW.map(r=>VIS.map(j=>q(r[j])).join(','))).join('\r\n');
  const bits=[]; const f=active();
  for(const k in f) bits.push(String(k.replace('!','')+'-'+f[k]).replace(/[^\w-]+/g,'-'));
  if($('#q').value.trim()) bits.push('search-'+$('#q').value.trim().replace(/[^\w-]+/g,'-'));
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob(['﻿'+body],{type:'text/csv;charset=utf-8'}));
  a.download=('aku-'+TAB+(bits.length?'--'+bits.join('__'):'')+'.csv').slice(0,180);
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(a.href),4000);
}

$('#moref').onclick=()=>{
  const open=$('#pop').hidden;
  $('#pop').hidden=!open; $('#moref').classList.toggle('on',open);
};
document.addEventListener('click',ev=>{
  if(!$('#pop').hidden && !ev.target.closest('#pop') && ev.target.id!=='moref'
     && !ev.target.closest('#moref')){
    $('#pop').hidden=true; $('#moref').classList.remove('on');
  }
});
$('#colsb').onclick=()=>{
  $('#cols').hidden=!$('#cols').hidden;
  $('#colsb').classList.toggle('on',!$('#cols').hidden);
};
/* ---- hierarchy -------------------------------------------------------
   Folders nested, each with the pages that land in it. Built once; searching
   hides rows rather than rebuilding, so it stays quick at 628 folders and
   4,591 pages. */
function tnode(n,depth){
  const kids=n.c.length||n.g.length;
  const cls='fold'+((depth>=1&&kids)?' cl':'');
  let h='<li class="'+(kids?cls:'leaf')+'" data-s="'+esc((n.p+' '+n.n+' '+n.m).toLowerCase())
    +'" data-r="'+esc(n.r||'')+'" data-e="'+esc(n.e||'')+'" data-m="'+esc(n.m||'')
    +'" data-k="'+esc(n.k||'')+'">'
    +'<div class="row2"><span class="tw2"></span>'
    +'<span class="nm">'+esc(n.n||'/')+'</span>'
    +(n.sl&&n.sl!==n.n?'<span class="slug">'+esc(n.sl)+'</span>':'')
    +(n.k?'<span class="kind '+esc(n.k)+'">'+esc(n.k)+'</span>':'')
    +(n.sub?'<span class="cnt">'+n.sub.toLocaleString()+' page'+(n.sub===1?'':'s')+'</span>':'')
    +(n.m?'<span class="team">'+esc(n.m)+'</span>':'')
    +'</div>';
  if(kids){
    h+='<ul>';
    n.c.forEach(c=>{h+=tnode(c,depth+1);});
    n.g.forEach(g=>{
      h+='<li class="pg leaf" data-s="'+esc(g[0].toLowerCase())+'" data-r="'+esc(n.r||'')
        +'" data-new="'+g[2]+'" data-dnm="'+(g[3]?1:0)+'" data-http="'+esc(g[4]||'')
        +'" data-rev="'+esc(g[5]||'')+'" data-unlisted="'+(g[6]||0)+'">'
        +'<div class="row2"><span class="tw2"></span>'
        +'<span class="nm">'+esc(g[0].split('/').pop())+'</span>'
        +(g[2]?'<span class="nw">new</span>':'')+(g[6]?'<span class="nl">not listed</span>':'')
        +'<span class="arrow">&rarr;</span><span class="dest">'+esc(g[1])+'</span>'
        +(g[4]==='401'?'<span class="err" title="Not publicly reachable — HTTP 401">401</span>':'')
        +(g[4]==='404'?'<span class="err g" title="Gone from the live site — HTTP 404">404</span>':'')
        +(g[3]?'<span class="dnm" title="'+esc(g[3])+'">not migrating</span>':'')
        +'</div></li>';
    });
    h+='</ul>';
  }
  return h+'</li>';
}
function buildTree(){
  if($('#tree').dataset.done) return;
  $('#tree').innerHTML='<ul>'+TREE.map(n=>tnode(n,0)).join('')+'</ul>';
  $('#tree').dataset.done='1';
  $('#tree').addEventListener('click',ev=>{
    const li=ev.target.closest('li.fold'); if(!li) return;
    li.classList.toggle('cl');
  });
}
/* Filtering the tree is a bottom-up pass: decide each page, then each folder by
   what survived beneath it. Done top-down, a folder would have to guess whether
   any of its descendants was going to match. */
function treeFilter(){
  const t=$('#q').value.trim().toLowerCase();
  const reg=fv('t_region'), ent=fv('t_entity'), team=fv('t_team'), kind=fv('t_kind');
  const st=fv('t_status'), hideEmpty=$('#t_empty')&&$('#t_empty').checked;
  const pageFilter=!!(st||t);
  const anyFolder=!!(reg||ent||team||kind);
  const all=[...$('#tree').querySelectorAll('li')];

  /* 1. Top-down — which folders are inside the part of the tree the folder
        filters pick out. Scope INHERITS: everything under Kenya is Kenya, and
        `regions` and each `entities` container carry no region or faculty of
        their own. Testing every folder on its own value hid those containers
        and took every match below with them, so Kenya returned an empty tree.
        Parents come first in document order, so a child can read its parent. */
  all.forEach(li=>{
    if(li.classList.contains('pg')) return;
    const par=li.parentElement.closest('li');
    let self=true;
    if(reg&&li.dataset.r!==reg) self=false;
    if(ent&&li.dataset.e!==ent) self=false;
    if(team&&li.dataset.m!==team) self=false;
    if(kind&&li.dataset.k!==kind) self=false;
    li.dataset.inscope=(self||(par&&par.dataset.inscope==='1'))?'1':'0';
  });

  /* 2. Pages — judged on the page filters, and only inside that scope. A page
        is not exempt from "region = Kenya" just because pages have no region of
        their own; it belongs to the folder holding it. */
  all.forEach(li=>{
    if(!li.classList.contains('pg')) return;
    const par=li.parentElement.closest('li');
    let ok=!par||par.dataset.inscope==='1';
    if(ok&&t&&!li.dataset.s.includes(t)) ok=false;
    if(ok&&st){
      if(st==='new') ok=li.dataset.new==='1';
      else if(st==='dnm') ok=li.dataset.dnm==='1';
      else if(st==='unlisted') ok=li.dataset.unlisted==='1';
      else if(st==='listed') ok=li.dataset.unlisted!=='1';
      else if(st==='401'||st==='404'||st==='200') ok=li.dataset.http===st;
      else ok=li.dataset.rev===st;
    }
    li.classList.toggle('hide',!ok);
  });

  /* 3. Bottom-up — a folder stays if anything under it stayed, which is what
        keeps the path to a match visible, or if it is in scope and nothing was
        asked of its pages. Deepest first, so children are settled. */
  all.slice().reverse().forEach(li=>{
    if(li.classList.contains('pg')) return;
    const live=[...li.querySelectorAll(':scope > ul > li')]
                 .some(c=>!c.classList.contains('hide'));
    const show=live||(li.dataset.inscope==='1'&&!pageFilter&&!hideEmpty);
    li.classList.toggle('hide',!show);
    if(show&&(pageFilter||anyFolder)) li.classList.remove('cl');
  });

  let f=0,p=0;
  all.forEach(li=>{ if(li.classList.contains('hide')) return;
    li.classList.contains('pg')?p++:f++; });
  $('#count').innerHTML='<b>'+f.toLocaleString()+'</b> folder'+(f===1?'':'s')
    +' &middot; <b>'+p.toLocaleString()+'</b> page'+(p===1?'':'s');
  countActive();
}
function fv(id){const el=document.getElementById(id);return el?el.value:'';}
function countActive(){
  let n=0;
  $$('#pop select').forEach(s=>{if(s.value)n++;});
  $$('#pop input[type=checkbox]').forEach(c=>{if(c.checked)n++;});
  $('#fcount').innerHTML=n?'<span class="badge">'+n+'</span>':'';
}

let tm;
$('#q').addEventListener('input',()=>{clearTimeout(tm);
  tm=setTimeout(()=>TAB==='hierarchy'?treeFilter():apply(),140);});
$('#moreb').onclick=draw;
$('#export').onclick=csv;
function show(){
  const h=TAB==='hierarchy';
  $('#treewrap').hidden=!h; $('#tablewrap').hidden=h;
  $('#chips').hidden=h; $('#cols').hidden=true;
  $('#colsb').hidden=h; $('#export').hidden=h;
  $('#treebar').hidden=!h;
  $('#pop').hidden=true; $('#moref').classList.remove('on');
  if(h){ buildTree(); treePanel(); treeFilter(); } else build();
}
/* The hierarchy's filters, built from the tree rather than from a table. */
function treePanel(){
  const seen={r:new Set(),e:new Set(),m:new Set(),k:new Set()};
  (function walk(ns){ns.forEach(n=>{
    if(n.r)seen.r.add(n.r); if(n.e)seen.e.add(n.e);
    if(n.m)seen.m.add(n.m); if(n.k)seen.k.add(n.k);
    walk(n.c);});})(TREE);
  const sel=(id,label,vals)=>'<label>'+label+'<select id="'+id+'">'
    +'<option value="">Any</option>'
    +[...vals].sort().map(v=>'<option value="'+esc(v)+'">'+esc(v)+'</option>').join('')
    +'</select></label>';
  $('#pop').innerHTML=
     sel('t_region','Region',seen.r)
    +sel('t_entity','Faculty / institute',seen.e)
    +sel('t_kind','Kind of folder',seen.k)
    +sel('t_team','Managed by',seen.m)
    +'<label>Page status<select id="t_status">'
      +'<option value="">Any</option>'
      +'<option value="listed">Only pages in AKU&rsquo;s list</option>'
      +'<option value="unlisted">Only pages we found, not listed</option>'
      +'<option value="401">Did not open &mdash; 401</option>'
      +'<option value="404">Gone &mdash; 404</option>'
      +'<option value="200">Opened fine &mdash; 200</option>'
      +'<option value="new">New in the latest list</option>'
      +'<option value="dnm">Not migrating</option>'
      +'<option value="NOT_REVIEWED">Not reviewed yet</option>'
      +'<option value="UNCLEAR">Marked unclear</option>'
      +'<option value="MIGRATE">Ready to migrate</option>'
    +'</select></label>'
    +'<div class="full">'
      +'<label><input type="checkbox" id="t_empty"> Hide folders with no pages</label>'
      +'<button class="btn" id="tclear">Clear all filters</button></div>';
  $$('#pop select').forEach(s=>s.onchange=treeFilter);
  $('#t_empty').onchange=treeFilter;
  $('#tclear').onclick=()=>{
    $$('#pop select').forEach(s=>s.value='');
    $('#t_empty').checked=false; $('#q').value=''; treeFilter();
  };
  countActive();
}
$$('.tab').forEach(b=>b.onclick=()=>{
  $$('.tab').forEach(x=>x.classList.toggle('on',x===b));
  TAB=b.dataset.p; $('#q').value=''; show();
});

$('#tex').onclick=()=>{
  document.querySelectorAll('#tree li.fold').forEach(li=>li.classList.remove('cl'));
};
$('#tcl').onclick=()=>{
  document.querySelectorAll('#tree li.fold').forEach((li,i)=>li.classList.add('cl'));
  document.querySelectorAll('#tree>ul>li.fold').forEach(li=>li.classList.remove('cl'));
};
addEventListener('scroll',()=>{
  if(SHOWN<VIEW.length&&innerHeight+scrollY>document.body.offsetHeight-700) draw();
});
show();
"""

doc = ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
       '<meta name="viewport" content="width=device-width,initial-scale=1">'
       '<title>AKU website — the new folder hierarchy</title>'
       '<style>' + CSS + '</style></head><body>'

       '<header><h1>AKU website &mdash; the new folder hierarchy</h1>'
       '<p><b>' + f'{len(F):,}' + '</b> folders &middot; <b>' + f'{n_listed:,}'
       + '</b> pages in your list, <b>' + f'{new_pages:,}' + '</b> of them new'
       + (' &middot; <b>' + f'{n_found:,}' + '</b> more we found on your site that '
          'no export lists' if n_found else '')
       + '</p></header>'

       '<div class="bar"><div class="tabs">'
       '<button class="tab on" data-p="hierarchy">Hierarchy</button>'
       '<button class="tab" data-p="pages">All pages</button>'
       '<button class="tab" data-p="folders">All folders</button></div>'
       '<input id="q" type="search" placeholder="Search a folder or a page…">'
       '<button class="btn" id="moref">Filters<span id="fcount"></span></button>'
       '<button class="btn" id="colsb">Columns</button>'
       '<button class="btn pri" id="export">&#11015; Download</button>'
       '<span class="count" id="count"></span></div>'
       '<div class="pop" id="pop" hidden></div>'

       '<div class="chips" id="treebar">'
       '<button class="chip" id="tex">Expand all</button>'
       '<button class="chip" id="tcl">Collapse all</button>'
       '<span style="color:var(--mut);font-size:12px">'
       'Click a folder to open it. Each page inside shows where it goes.</span>'
       '</div>'

       '<div class="chips" id="chips" hidden></div>'
       '<div class="cols" id="cols" hidden></div>'

       '<div class="wrap" id="treewrap"><div id="tree"></div></div>'

       '<div class="wrap" id="tablewrap" hidden>'
       '<table><thead id="thead"></thead><tbody id="tbody"></tbody></table>'
       '<div class="empty" id="empty" hidden>Nothing matches these filters.</div>'
       '<div class="more" id="more" hidden>'
       '<button class="btn" id="moreb"></button></div>'
       '<details class="docs" id="docs"></details>'
       '</div>'

       '<script>const DATA=' + json.dumps(DATA, ensure_ascii=False)
       + ',TREE=' + json.dumps(TREE, ensure_ascii=False)
       + ',TCOUNT=' + json.dumps({'f': len(F), 'p': len(P)})
       + ',FILTERS=' + json.dumps(FILTERS, ensure_ascii=False)
       + ',FLAGS=' + json.dumps(FLAGS, ensure_ascii=False)
       + ',PRIMARY=' + json.dumps(PRIMARY, ensure_ascii=False)
       + ',PRESETS=' + json.dumps(PRESETS, ensure_ascii=False)
       + ';\n' + JS + '</script></body></html>\n')

open(OUT, 'w', encoding='utf-8').write(doc)
print('%s — %.0f KB' % (os.path.basename(OUT), len(doc.encode('utf-8')) / 1024))
print('   %d folders · %d pages · %d new in the latest list' % (len(F), len(P), new_pages))
