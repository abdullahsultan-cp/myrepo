"""One collapsible tree. Click a row, its contents open underneath it.

Why the order is fixed rather than alphabetical: AKU's own faculty menus already
agree on About -> Programmes -> Research, and most folders are already named that
way (about 27, research 16, programmes 14, faculty 10, departments 52). What makes
the current site hard to read is the 276-name long tail around them. So every
folder here lists its children in the SAME order -- the canonical sections first,
then everything else A-Z -- which is what makes two different entities readable
side by side. Nothing is re-parented on a guess; a folder whose name is not one
AKU itself uses is marked "check" instead of being moved somewhere it might belong.
"""
import io, os, json, html, collections
import paths


OUT = paths.out('AKU-Structure.html')
plan = json.load(io.open(paths.work('plan.json'), encoding='utf-8'))
F, P, R = plan['folders'], plan['pages'], plan['roles']
e = html.escape

# The order AKU's own menus use, applied to every folder. The first block is the
# university's six top-level menus and their children, read off aku.edu; the
# second is the shape a faculty page uses, read off /mcpk, /sonampk and /iedpk.
CANON = [
    # the site's own top-level menus, in their own order
    'about', 'about-us', 'at-a-glance', 'academics', 'admissions', 'research',
    'supportus', 'support-us', 'students', 'alumni', 'faculty', 'media',
    'careers', 'library', 'libraries', 'news', 'events', 'blogs',
    'registrar', 'convocation', 'geo', 'leads',
    # the About Us submenu, exactly as aku.edu lists it
    'chancellor', 'trustees', 'president', 'provostoffice', 'officers',
    'charters', 'environment',
    # the shape every faculty menu shares
    'programmes', 'programs', 'study', 'departments', 'centres', 'partners',
    'resources', 'people', 'staff', 'contact', 'giving', 'impact',
]
CANON_RANK = {n: i for i, n in enumerate(CANON)}

TYPE_WORDS = {
    'root': 'top level',
    'container': 'grouping folder',
    'region': 'region',
    'entity': 'entity — faculty, school, institute or centre',
    'department': 'department',
    'division': 'programme or centre',
    'section': 'section',
    'folder': 'folder',
    'region-folder': 'region folder',
}
# Every kind build_migration_plan.py can emit. A missing key raised a KeyError
# here rather than mislabelling a folder, which is the behaviour we want -- but it
# means a new kind has to be added in both places.
SHORT = {'root': 'top level', 'container': 'grouping', 'region': 'region',
         'entity': 'entity', 'department': 'department', 'division': 'programme',
         'section': 'section', 'folder': 'folder',
         'region-folder': 'region folder', 'centre': 'centre', 'office': 'office',
         'publication': 'publication'}

# unit -> the Storyblok roles that carry it
ROLE_BY_UNIT = {}
for r in R:
    ROLE_BY_UNIT.setdefault(r['unit'], []).append(r)

by_path = {r['new_path']: r for r in F}
kids = collections.defaultdict(list)
for r in F:
    if r['parent_path']:
        kids[r['parent_path']].append(r['new_path'])
roots = sorted([r['new_path'] for r in F if not r['parent_path']],
               key=lambda p: {'global': 0, 'regions': 1, 'staging': 2}.get(p, 3))

pages_by_folder = collections.defaultdict(list)
for p in P:
    if p['new_path']:
        pages_by_folder[p['folder']].append(p)

def sort_key(path):
    name = path.split('/')[-1]
    return (CANON_RANK.get(name, 500), name)

def subtree_pages(path):
    n = len(pages_by_folder.get(path, []))
    return n + sum(subtree_pages(c) for c in kids.get(path, []))

def subtree_folders(path):
    return 1 + sum(subtree_folders(c) for c in kids.get(path, []))

def needs_check(r):
    """A folder that is nobody's standard name and holds almost nothing.

    Only ordinary folders qualify. A top-level section is not suspect just for
    being thin -- `academics` and `convocation` are items in AKU's own main menu
    and belong at the top level whatever their page count. Regions, entities and
    departments are structural and never flagged.
    """
    if r['kind'] not in ('folder',):
        return False
    name = r['new_path'].split('/')[-1]
    if name in CANON_RANK:
        return False
    return subtree_pages(r['new_path']) <= 2

def node(path, depth=0):
    r = by_path[path]
    name = path.split('/')[-1]
    ch = sorted(kids.get(path, []), key=sort_key)
    pgs = sorted(pages_by_folder.get(path, []),
                 key=lambda x: x['new_path'].split('/')[-1])
    tp, tf = subtree_pages(path), subtree_folders(path) - 1
    has = bool(ch or pgs)

    bits = []
    if tf:
        bits.append('%d folder%s' % (tf, '' if tf == 1 else 's'))
    if tp:
        bits.append('%s page%s' % ('{:,}'.format(tp), '' if tp == 1 else 's'))
    if not bits:
        bits.append('empty')
    meta = ' · '.join(bits)

    team = r['managed_by']
    central = 'central' in team
    tag = ''
    if r.get('countries'):
        tag = '<span class="tag">works in %s</span>' % e(r['countries'])
    check = '<span class="chk">check</span>' if needs_check(r) else ''

    # A role is attached where the folder carries its own permissions; everything
    # below simply inherits, which is how SharePoint runs it today.
    roles = ''
    if r['own_permissions'] == 'yes':
        names = []
        for u in [x.strip() for x in team.split(';')]:
            for rr in ROLE_BY_UNIT.get(u, []):
                names.append(rr['storyblok_role'])
        if names:
            roles = ('<span class="roles" title="Roles that apply here: %s">'
                     '%d role%s</span>'
                     % (e(', '.join(sorted(set(names)))), len(set(names)),
                        '' if len(set(names)) == 1 else 's'))

    open_ = depth < 1
    head = (
        '<div class="row k-%s" data-n="%s" title="%s">'
        '<span class="tw%s"></span>'
        '<span class="nm">%s</span>'
        '<span class="ty">%s</span>%s%s%s'
        '<span class="meta">%s</span>'
        '<span class="team%s">%s</span>'
        '<span class="path">%s</span>'
        '</div>'
        % (r['kind'], e((path + ' ' + name + ' ' + team + ' ' + r['kind']).lower()),
           e(path + (' — ' + r['entity_basis'] if r.get('entity_basis') else '')),
           '' if has else ' leaf', e(name), e(SHORT[r['kind']]), tag, check, roles,
           meta, ' c' if central else '',
           e('Public Affairs' if central else team), e(path)))

    inner = ''
    if has:
        inner = ('<div class="ch">'
                 + ''.join(node(c, depth + 1) for c in ch)
                 + (('<div class="pgs" data-n="pages">'
                     + ''.join('<div class="pg" data-n="%s"><span class="pd"></span>'
                               '<a href="%s" target="_blank" rel="noopener">%s</a>'
                               '<span class="pa%s">%s</span></div>'
                               % (e((x['new_path'] + ' ' + x['current_url']).lower()),
                                  e(x['current_url']),
                                  e(x['new_path'].split('/')[-1]),
                                  ' u' if x['action'] == 'Update and move' else '',
                                  'update first' if x['action'] == 'Update and move'
                                  else 'move as is')
                               for x in pgs)
                     + '</div>') if pgs else '')
                 + '</div>')
    return ('<div class="n%s" data-p="%s" data-empty="%d">%s%s</div>'
            % ('' if open_ else ' cl', e(path), 0 if tp else 1, head, inner))

tree = ''.join(node(p) for p in roots)

# ---- the same hierarchy, seen as permissions -----------------------------
# Only folders that carry their own permissions get a role; everything below
# inherits. So the permission tree is the folder tree with the inheriting
# middle pruned away -- which is the shortest true picture of who can edit what.
def owns(path):
    return by_path[path]['own_permissions'] == 'yes'

def has_owner_below(path):
    return owns(path) or any(has_owner_below(c) for c in kids.get(path, []))

def roles_at(path):
    r = by_path[path]
    out = []
    for u in [x.strip() for x in r['managed_by'].split(';')]:
        for rr in ROLE_BY_UNIT.get(u, []):
            out.append(rr)
    seen, uniq = set(), []
    for rr in sorted(out, key=lambda x: (x['unit'], x['capability'])):
        if rr['storyblok_role'] not in seen:
            seen.add(rr['storyblok_role'])
            uniq.append(rr)
    return uniq

def rnode(path, depth=0):
    if not has_owner_below(path):
        return ''
    r = by_path[path]
    name = path.split('/')[-1]
    ch = [c for c in sorted(kids.get(path, []), key=sort_key) if has_owner_below(c)]
    mine = roles_at(path) if owns(path) else []

    chips = ''.join(
        '<span class="rc %s">%s<i>%s</i>%s</span>'
        % ('pub' if x['capability'] == 'publisher' else 'ed',
           e(x['storyblok_role']),
           'can publish' if x['capability'] == 'publisher' else 'draft only',
           '<b>%d</b>' % x['members'] if x['members'] else '')
        for x in mine)

    head = ('<div class="row k-%s" data-n="%s">'
            '<span class="tw%s"></span><span class="nm">%s</span>'
            '<span class="ty">%s</span>'
            '<span class="rteam">%s</span>'
            '<span class="path">%s</span></div>'
            % (r['kind'], e((path + ' ' + name + ' ' + r['managed_by']).lower()),
               '' if ch else ' leaf', e(name), e(SHORT[r['kind']]),
               e(r['managed_by']) if owns(path) else '<i>inherits</i>', e(path)))
    if not owns(path):
        head = head.replace('<span class="rteam">', '<span class="rteam dim">')

    body = ('<div class="chips">' + chips + '</div>') if chips else ''
    inner = ('<div class="ch">' + body
             + ''.join(rnode(c, depth + 1) for c in ch) + '</div>') \
        if (ch or body) else ''
    return ('<div class="n%s" data-p="%s">%s%s</div>'
            % ('' if depth < 2 else ' cl', e(path), head, inner))

rtree = ''.join(rnode(p) for p in roots)

# ---- org chart: the same folders, drawn top to bottom --------------------
# Folders only. Adding 3,337 page boxes would make it kilometres wide and it is
# the shape people want from this view, not the contents.
OC_ICON = {'root': '⌂', 'container': '⋯', 'region': '◉', 'entity': '■',
           'department': '▪', 'division': '◆', 'section': '▬',
           'region-folder': '□', 'folder': '·'}

def oc(path, depth=0):
    r = by_path[path]
    name = path.split('/')[-1]
    ch = sorted(kids.get(path, []), key=sort_key)
    tp = subtree_pages(path)
    team = r['managed_by']
    central = 'central' in team
    cross = r.get('also_belongs_to') or ''

    sub = SHORT[r['kind']]
    badge = ''
    if cross:
        badge = '<span class="ocx" title="Also belongs to %s">shared</span>' % e(cross)

    toggle = ''
    if ch:
        toggle = ('<span class="octg" title="%d folders inside">%s</span>'
                  % (len(ch), '−' if depth < 1 else '+'))

    box = ('<div class="ocb k-%s" data-n="%s" title="%s">'
           '<span class="oci">%s</span>'
           '<span class="ocn"><b>%s</b><i>%s</i></span>'
           '%s%s'
           '<span class="occ">%s</span>%s</div>'
           % (r['kind'], e((path + ' ' + name + ' ' + team).lower()), e(path),
              OC_ICON.get(r['kind'], '·'), e(name), e(sub), badge,
              ('<span class="oct%s">%s</span>'
               % (' c' if central else '',
                  e('Public Affairs' if central else team))),
              '%s' % ('{:,}'.format(tp) if tp else '—'), toggle))

    if not ch:
        return '<li>%s</li>' % box
    return ('<li class="%s">%s<ul>%s</ul></li>'
            % ('' if depth < 1 else 'cl', box,
               ''.join(oc(c, depth + 1) for c in ch)))

ochart = ('<div class="ocwrap"><div class="oc"><ul>%s</ul></div></div>'
          % ''.join(oc(p) for p in roots))

# plain-sentence summary, in the shape the user asked for
def count_kind(prefix, kind):
    return sum(1 for r in F if r['kind'] == kind
               and (r['new_path'] == prefix or r['new_path'].startswith(prefix + '/')))

lines = []
for r in sorted(F, key=lambda x: (x['new_path'] != 'regions/global',
                                  x['new_path'])):
    if r['kind'] == 'region' and r['new_path'].count('/') == 1:
        slug = r['new_path'].split('/')[-1]
        if slug == 'global':
            lines.append(
                '<b>Global</b> is a region too — it holds the %d section folders '
                'and %s pages that no faculty owns: news, events and blogs, plus '
                'about us, academics, admissions, research, support us, and the '
                'pages for students, alumni, faculty, media, careers and libraries.'
                % (count_kind(r['new_path'], 'section'),
                   '{:,}'.format(subtree_pages(r['new_path']))))
            continue
        ents = count_kind(r['new_path'], 'entity')
        deps = count_kind(r['new_path'], 'department')
        if not ents and not subtree_pages(r['new_path']):
            lines.append('<b>%s</b> has no section on aku.edu at all.'
                         % slug.replace('-', ' ').title())
            continue
        rf = count_kind(r['new_path'], 'region-folder')
        lines.append('<b>%s</b> holds %d entit%s%s%s, and %s pages.'
                     % (slug.replace('-', ' ').title(), ents,
                        'y' if ents == 1 else 'ies',
                        ', %d departments inside them' % deps if deps else '',
                        ', plus %d folder%s of its own that are not entities'
                        % (rf, '' if rf == 1 else 's') if rf else '',
                        '{:,}'.format(subtree_pages(r['new_path']))))
lines.append('<b>Staging</b> holds %d folders that are test copies or unfinished '
             'rebuilds. Nothing in it should move.'
             % (subtree_folders('staging') - 1))
summary = ''.join('<li>%s</li>' % x for x in lines)

n_check = sum(1 for r in F if needs_check(r))
n_empty = sum(1 for r in F if not subtree_pages(r['new_path']))

# ---- what to create in Storyblok ----------------------------------------
caps = collections.Counter(r['capability'] for r in R)
space = [r for r in R if r['unit'] == '(space-wide)']
unscoped = [r for r in R if r['unit'] != '(space-wide)' and not r['folders_scoped']]

MAPPING = [
    ('Full Control · Manage Permissions', 'Admin',
     'the whole space, including settings and roles', '1 role'),
    ('Manage Hierarchy', 'Structure manager',
     'may create, move and delete folders — nobody else should',
     '1 role, %d people' % sum(r['members'] for r in space
                               if r['capability'] == 'structure')),
    ('Contribute + Approve · Approve', 'Publisher',
     'edits and publishes inside its own folders',
     '%d roles' % caps['publisher']),
    ('Design + Contribute · Contribute', 'Editor',
     'edits and saves a draft, cannot publish', '%d roles' % caps['editor']),
    ('Read · View Only · Restricted Read', 'Viewer',
     'reads unpublished content, changes nothing', '1 role'),
    ('Restricted Interfaces for Translation', 'Translator',
     'translation fields only', '1 role'),
]
map_rows = ''.join(
    '<tr><td class="mono">%s</td><td><b>%s</b></td><td>%s</td><td class="nm2">%s</td></tr>'
    % (e(a), e(b), e(c), e(d)) for a, b, c, d in MAPPING)

space_rows = ''.join(
    '<li><span class="mono rn">%s</span> — %s%s</li>'
    % (e(r['storyblok_role']), e(r['note']),
       ' · <b>%d people</b>' % r['members'] if r['members'] else '')
    for r in space)

CSS = """
*{box-sizing:border-box}
:root{--bg:#f7f8f8;--card:#fff;--ink:#12181b;--ink2:#556066;--mut:#8b959b;
--line:#e6eaec;--brand:#00594f;--brand2:#0b7f6f;--blue:#2a78d6;--amber:#b06a00;
--red:#c0362f;color-scheme:light}
@media(prefers-color-scheme:dark){:root{--bg:#0e1011;--card:#171a1c;--ink:#f2f5f6;
--ink2:#b7c0c5;--mut:#7d878d;--line:#262b2e;--brand:#0b7f6f;--brand2:#15a892;
--blue:#5aa0ea;--amber:#e0a02a;--red:#e0716a;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
-webkit-font-smoothing:antialiased}
.wrap{max-width:1240px;margin:0 auto;padding:0 22px 90px}
header{background:var(--brand);color:#fff;padding:30px 0 26px}
header .wrap{padding-bottom:0}
h1{margin:0 0 14px;font-size:23px;font-weight:640;letter-spacing:-.2px}
ul.sum{margin:0;padding:0;list-style:none;display:grid;gap:7px;max-width:96ch}
ul.sum li{font-size:14px;color:rgba(255,255,255,.9);padding-left:16px;position:relative}
ul.sum li::before{content:"";position:absolute;left:0;top:9px;width:6px;height:6px;
border-radius:50%;background:rgba(255,255,255,.5)}
ul.sum b{color:#fff}
.bar{position:sticky;top:0;z-index:20;background:var(--bg);
border-bottom:1px solid var(--line);padding:12px 0;margin-bottom:14px}
.bar .wrap{padding-bottom:0;display:flex;gap:9px;align-items:center;flex-wrap:wrap}
#q{flex:1;min-width:230px;padding:11px 14px;border:1px solid var(--line);
border-radius:10px;font-size:14px;background:var(--card);color:var(--ink)}
#q:focus{outline:2px solid var(--brand2);outline-offset:-1px}
.btn{padding:10px 13px;border:1px solid var(--line);background:var(--card);
border-radius:10px;cursor:pointer;font-size:13.5px;color:var(--ink2)}
.btn:hover{border-color:var(--brand2);color:var(--brand2)}
#hits{font-size:13px;color:var(--mut);min-width:150px}

/* the tree */
#tree{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:10px 8px}
.n{position:relative}
.ch{margin-left:26px;padding-left:16px;border-left:1px solid var(--line)}
.n.cl>.ch{display:none}
.row{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:9px;
cursor:pointer;min-height:42px}
.row:hover{background:var(--bg)}
.tw{width:16px;height:16px;flex:none;position:relative}
.tw::before{content:"";position:absolute;left:4px;top:3px;width:6px;height:6px;
border-right:2px solid var(--mut);border-bottom:2px solid var(--mut);
transform:rotate(45deg);transition:transform .13s}
.n.cl>.row>.tw::before{transform:rotate(-45deg);left:3px;top:4px}
.tw.leaf::before{border:0;background:var(--line);width:5px;height:5px;
border-radius:50%;left:5px;top:5px;transform:none}
.nm{font-size:15px;font-weight:600}
.ty{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.5px}
.meta{font-size:12.5px;color:var(--ink2);margin-left:auto;white-space:nowrap}
.team{font-size:12.5px;color:var(--brand2);min-width:190px;text-align:right;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.team.c{color:var(--mut)}
.path{display:none}
.tag{font-size:11px;color:var(--blue);background:rgba(42,120,214,.1);
padding:2px 7px;border-radius:5px;white-space:nowrap}
.chk{font-size:10.5px;color:var(--amber);background:rgba(176,106,0,.12);
padding:2px 7px;border-radius:5px;font-weight:600}

/* row colour by level */
.k-root>.nm{font-size:19px;font-weight:680;font-family:ui-monospace,Menlo,Consolas,monospace}
.k-root{background:linear-gradient(90deg,rgba(0,89,79,.09),transparent)}
.k-region>.nm{font-size:17px;font-weight:660;color:var(--brand2)}
.k-region{background:linear-gradient(90deg,rgba(11,127,111,.07),transparent)}
.k-entity>.nm{font-size:15.5px;color:var(--blue)}
.k-department>.nm{color:var(--brand2)}
.k-container>.nm{color:var(--mut);font-weight:500}

/* pages */
.pgs{margin-left:26px;padding-left:16px;border-left:1px solid var(--line)}
.pg{display:flex;align-items:center;gap:9px;padding:5px 12px;font-size:13px}
.pd{width:5px;height:5px;border-radius:50%;background:var(--line);flex:none}
.pg a{color:var(--ink2);text-decoration:none;font-family:ui-monospace,Menlo,Consolas,monospace;
font-size:12.5px}
.pg a:hover{color:var(--blue);text-decoration:underline}
.pa{font-size:11px;color:var(--mut);margin-left:auto}
.pa.u{color:var(--amber)}
.hide{display:none!important}

/* ---- org chart: pure-CSS connectors, top to bottom ---- */
.ocwrap{overflow:auto;background:var(--card);border:1px solid var(--line);
border-radius:14px;padding:26px 18px}
.oc{width:max-content;min-width:100%;margin:0 auto}
.oc ul{display:flex;justify-content:center;padding-top:22px;margin:0;list-style:none;
position:relative}
.oc li{position:relative;padding:22px 9px 0;list-style:none;text-align:center;
display:flex;flex-direction:column;align-items:center}
.oc>ul{padding-top:0}
.oc li::before,.oc li::after{content:"";position:absolute;top:0;
border-top:1.5px solid var(--line);width:50%;height:22px}
.oc li::after{left:50%;border-left:1.5px solid var(--line)}
.oc li::before{right:50%}
.oc li:only-child::after,.oc li:only-child::before{display:none}
.oc li:only-child{padding-top:22px}
.oc li:first-child::before,.oc li:last-child::after{border:0}
.oc li:last-child::before{border-right:1.5px solid var(--line);border-radius:0 7px 0 0}
.oc li:first-child::after{border-radius:7px 0 0 0}
.oc ul ul::before{content:"";position:absolute;top:0;left:50%;
border-left:1.5px solid var(--line);width:0;height:22px}
.oc>ul>li>ul::before{top:0}
.oc li.cl>ul{display:none}
.ocb{position:relative;display:flex;align-items:center;gap:9px;background:var(--bg);
border:1.5px solid var(--line);border-radius:11px;padding:9px 13px;min-width:210px;
max-width:300px;text-align:left;cursor:pointer;transition:border-color .12s}
.ocb:hover{border-color:var(--brand2)}
.oci{width:30px;height:30px;border-radius:50%;background:var(--card);
border:1px solid var(--line);display:flex;align-items:center;justify-content:center;
font-size:14px;color:var(--brand2);flex:none}
.ocn{display:flex;flex-direction:column;min-width:0;flex:1}
.ocn b{font-size:13.5px;font-weight:620;white-space:nowrap;overflow:hidden;
text-overflow:ellipsis;max-width:190px}
.ocn i{font-style:normal;font-size:10.5px;color:var(--mut);text-transform:uppercase;
letter-spacing:.4px}
.oct{font-size:10.5px;color:var(--brand2);max-width:96px;text-align:right;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.oct.c{color:var(--mut)}
.occ{font-size:12px;font-weight:620;color:var(--ink2);min-width:34px;text-align:right;
font-variant-numeric:tabular-nums}
.octg{position:absolute;left:50%;transform:translateX(-50%);bottom:-11px;width:21px;
height:21px;border-radius:50%;background:var(--card);border:1.5px solid var(--line);
color:var(--ink2);font-size:13px;line-height:18px;text-align:center;cursor:pointer;
z-index:2}
.octg:hover{border-color:var(--brand2);color:var(--brand2)}
.ocx{font-size:9.5px;font-weight:700;color:var(--blue);background:rgba(42,120,214,.13);
padding:2px 6px;border-radius:4px;white-space:nowrap}
.ocb.k-region{border-color:var(--brand2);border-width:2px}
.ocb.k-region .ocn b{font-size:15px;color:var(--brand2)}
.ocb.k-entity{border-color:var(--blue)}
.ocb.k-entity .ocn b{color:var(--blue)}
.ocb.k-department{border-color:rgba(11,127,111,.55)}
.ocb.k-root{border-color:var(--ink2);border-width:2px}
.ocb.k-root .ocn b{font-family:ui-monospace,Menlo,Consolas,monospace}
.tabs{display:flex;gap:3px;background:var(--line);border-radius:11px;padding:3px}
.tb{border:0;background:transparent;padding:9px 15px;border-radius:9px;cursor:pointer;
font-size:13.5px;color:var(--ink2);font-weight:560}
.tb.on{background:var(--card);color:var(--brand2);box-shadow:0 1px 2px rgba(0,0,0,.08)}
.view{display:none}.view.on{display:block}
.rteam{font-size:12.5px;color:var(--brand2);margin-left:auto;white-space:nowrap}
.rteam.dim{color:var(--mut)}
.rteam i{font-style:normal}
.chips{display:flex;flex-wrap:wrap;gap:6px;padding:4px 12px 10px}
.rc{font-size:11.5px;font-family:ui-monospace,Menlo,Consolas,monospace;
padding:4px 9px;border-radius:6px;display:inline-flex;align-items:center;gap:7px}
.rc i{font-style:normal;font-family:system-ui;font-size:10px;opacity:.75}
.rc b{font-family:system-ui;font-size:10.5px}
.rc.ed{background:rgba(42,120,214,.12);color:var(--blue)}
.rc.pub{background:rgba(11,127,111,.14);color:var(--brand2)}
#tree.he .n[data-empty="1"]{display:none}
#rtree{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:10px 8px}
.roles{font-size:10.5px;color:var(--brand2);background:rgba(11,127,111,.12);
padding:2px 7px;border-radius:5px;white-space:nowrap;cursor:help}
.k-region-folder>.nm{font-size:15px;color:var(--ink)}
label.tg{display:flex;align-items:center;gap:7px;font-size:13.5px;color:var(--ink2);
background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:10px 13px;cursor:pointer;user-select:none}
label.tg input{accent-color:var(--brand2);width:15px;height:15px;cursor:pointer}
details.be{background:var(--card);border:1px solid var(--line);border-radius:13px;
padding:0;margin:0 0 14px;overflow:hidden}
details.be>summary{cursor:pointer;list-style:none;padding:15px 18px;
font-weight:640;font-size:15.5px;display:flex;align-items:center;gap:10px}
details.be>summary::-webkit-details-marker{display:none}
details.be>summary::before{content:"▸";color:var(--brand2);font-size:13px}
details.be[open]>summary::before{content:"▾"}
.bb{padding:0 18px 18px;font-size:13.5px;color:var(--ink2)}
.bb h4{margin:16px 0 8px;font-size:13px;color:var(--ink);font-weight:640}
.bb table{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:6px}
.bb th{text-align:left;padding:7px 9px;font-size:10.5px;text-transform:uppercase;
letter-spacing:.5px;color:var(--mut);border-bottom:1px solid var(--line)}
.bb td{padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}
.bb td.nm2{color:var(--brand2);white-space:nowrap}
.bb ul{margin:6px 0 0;padding-left:18px}
.bb li{margin-bottom:5px}
.rn{color:var(--brand2);font-weight:600}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.9em}
.note{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--amber);
border-radius:0 11px 11px 0;padding:13px 16px;margin:0 0 14px;font-size:13.5px;
color:var(--ink2)}
.note b{color:var(--ink)}
@media(max-width:900px){.team{display:none}.ty{display:none}}
"""

JS = """
const q=document.getElementById('q'),hits=document.getElementById('hits');
const nodes=[...document.querySelectorAll('.n')];
const pgs=[...document.querySelectorAll('.pg')];
document.querySelectorAll('.row').forEach(r=>{
  r.onclick=()=>{const n=r.closest('.n'); if(n.querySelector(':scope > .ch'))
    n.classList.toggle('cl');};
});
function depth(n){let d=0,p=n.parentElement;
  while(p){if(p.classList&&p.classList.contains('n'))d++;p=p.parentElement;}return d;}
function level(k){q.value='';hits.textContent='';
  nodes.forEach(n=>n.classList.remove('hide'));
  pgs.forEach(p=>p.classList.remove('hide'));
  nodes.forEach(n=>{if(n.querySelector(':scope > .ch'))
    n.classList.toggle('cl',depth(n)>=k);});
}
function openUp(el){let p=el.parentElement;
  while(p){if(p.classList&&p.classList.contains('n'))p.classList.remove('cl');
    p=p.parentElement;}}
function search(t){
  t=t.trim().toLowerCase();
  if(!t){level(1);return;}
  let np=0;
  pgs.forEach(p=>{const m=p.dataset.n.includes(t);
    p.classList.toggle('hide',!m);if(m){np++;openUp(p);}});
  [...nodes].reverse().forEach(n=>{
    const self=n.querySelector(':scope > .row').dataset.n.includes(t);
    const kidOn=[...n.querySelectorAll(':scope > .ch > .n')].some(c=>!c.classList.contains('hide'))
      || [...n.querySelectorAll(':scope > .ch > .pgs > .pg')].some(c=>!c.classList.contains('hide'));
    const show=self||kidOn;
    n.classList.toggle('hide',!show);
    if(show){if(self)n.querySelectorAll('.n,.pg').forEach(c=>c.classList.remove('hide'));
      n.classList.remove('cl');openUp(n);}
  });
  const nf=nodes.filter(n=>!n.classList.contains('hide')).length;
  hits.textContent=nf+' folders · '+np+' pages';
}
let tm;q.addEventListener('input',()=>{clearTimeout(tm);tm=setTimeout(()=>search(q.value),120);});
document.getElementById('L1').onclick=()=>level(1);
document.getElementById('L2').onclick=()=>level(2);
document.getElementById('L3').onclick=()=>level(3);
document.getElementById('L9').onclick=()=>{q.value='';hits.textContent='';
  nodes.forEach(n=>{n.classList.remove('hide','cl');});
  pgs.forEach(p=>p.classList.remove('hide'));};
/* An org chart centres its rows, so a chart wider than the window would open
   scrolled to blank canvas. Keep the middle in view instead. */
/* Centre on the FIRST root box, not on the canvas: with two roots side by side
   the canvas midpoint falls in the gap between them and the top of the chart
   scrolls out of view. */
function centreChart(){
  const c=document.querySelector('.ocwrap');if(!c)return;
  const b=c.querySelector('.oc > ul > li > .ocb');
  if(!b){c.scrollLeft=0;return;}
  const cr=c.getBoundingClientRect(),br=b.getBoundingClientRect();
  c.scrollLeft=Math.max(0,c.scrollLeft+(br.left+br.width/2)-(cr.left+cr.width/2));
}
document.querySelectorAll('.octg').forEach(t=>{
  t.onclick=ev=>{const li=t.closest('li');li.classList.toggle('cl');
    t.textContent=li.classList.contains('cl')?'+':'−';
    ev.stopPropagation();centreChart();};
});
document.querySelectorAll('.tb').forEach(b=>{
  b.onclick=()=>{
    document.querySelectorAll('.tb').forEach(x=>x.classList.toggle('on',x===b));
    document.querySelectorAll('.view').forEach(v=>
      v.classList.toggle('on',v.id===b.dataset.v));
    if(b.dataset.v==='v-chart')centreChart();
  };
});
document.getElementById('he').onchange=ev=>{
  document.getElementById('tree').classList.toggle('he',ev.target.checked);};
level(1);
"""

doc = ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
       '<meta name="viewport" content="width=device-width,initial-scale=1">'
       '<title>AKU folder and page structure</title><style>' + CSS
       + '</style></head><body>'
       '<header><div class="wrap"><h1>Where every folder and page goes</h1>'
       '<ul class="sum">' + summary + '</ul></div></header>'
       '<div class="bar"><div class="wrap">'
       '<div class="tabs"><button class="tb on" data-v="v-folders">Folder structure'
       '</button><button class="tb" data-v="v-roles">Roles &amp; permissions</button>'
       '<button class="tb" data-v="v-chart">Org chart</button>'
       '</div>'
       '<input id="q" type="search" placeholder="Type a name — pakistan, medical college, anaes, a page…">'
       '<span id="hits"></span>'
       '<button class="btn" id="L1">Regions</button>'
       '<button class="btn" id="L2">Entities</button>'
       '<button class="btn" id="L3">Departments</button>'
       '<button class="btn" id="L9">Open everything</button>'
       '<label class="tg"><input type="checkbox" id="he">Hide empty folders</label>'
       '</div></div><div class="wrap">'
       '<p class="note">Click any row to open it. Every folder lists its children in '
       'the same order AKU\'s own menus use — <b>about, programmes, research, '
       'faculty, departments</b>, then news, events and blogs, then anything else '
       'A-Z. The name on the right is the team that manages that folder today. '
       '<b>' + str(n_check) + ' folders are marked “check”</b>: their name is not one '
       'AKU uses anywhere else and they hold two pages or fewer, so they probably '
       'belong inside one of the standard folders — but I have not moved them on a '
       'guess.</p>'
       '<details class="be"><summary>What to create in the backend — '
       + str(len(R)) + ' roles</summary><div class="bb">'
       '<p style="margin:0">AKU already runs a two-step workflow: a <b>CW</b> '
       '(content writer) group drafts, a <b>CA</b> (content approver) group '
       'publishes. Keep that split — it is the one thing about the current setup '
       'that is working, and it maps onto Storyblok without argument.</p>'
       '<h4>How each SharePoint permission becomes a Storyblok role</h4>'
       '<table><thead><tr><th>SharePoint gives them</th><th>Storyblok role</th>'
       '<th>What it can do</th><th>How many</th></tr></thead><tbody>'
       + map_rows + '</tbody></table>'
       '<h4>Space-wide roles — create these once</h4><ul>' + space_rows + '</ul>'
       '<h4>Per-team roles — ' + str(caps['editor']) + ' editors and '
       + str(caps['publisher']) + ' publishers</h4>'
       '<p style="margin:0">One pair per AKU team, each limited to the folders '
       'that team owns, so Anaesthesiology cannot edit Pathology. The folder rows '
       'below show a <span class="roles">role</span> chip wherever a role attaches; '
       'everything under it inherits, exactly as it does now. Full list with '
       'members and paths: <span class="mono">aku-permission-groups.csv</span>.</p>'
       '<h4>The ' + str(len(unscoped)) + ' roles that still need a scope</h4>'
       '<p style="margin:0">These teams own a section whose folder names no owner — '
       'it carries the site-wide group roster instead — so I cannot tell which '
       'folders to limit them to. Someone at AKU has to say: '
       + e(', '.join(sorted({r['unit'] for r in unscoped}))) + '.</p>'
       '</div></details>'
       '<div class="view on" id="v-folders"><div id="tree">' + tree
       + '</div></div>'
       '<div class="view" id="v-roles">'
       '<p class="note">The same hierarchy, showing only where a permission is '
       'actually set. A folder with a team name carries its own roles; one marked '
       '<i>inherits</i> takes them from its parent, exactly as SharePoint does '
       'today. <span class="rc pub" style="font-size:10.5px">publisher<i>can '
       'publish</i></span> <span class="rc ed" style="font-size:10.5px">editor<i>'
       'draft only</i></span> — the number is how many people are in it.</p>'
       '<div id="rtree">' + rtree + '</div></div>'
       '<div class="view" id="v-chart">'
       '<p class="note">The same folders drawn top to bottom, the way an org chart '
       'reads. Click the <b>−</b> / <b>+</b> under a box to fold or open its '
       'children; the number on the right is how many pages sit beneath it. '
       'A <span class="ocx">shared</span> badge means that folder also belongs to an '
       'entity it cannot live under — the cross-entity case. Pages are not drawn '
       'here; use the folder tab for those.</p>'
       + ochart + '</div></div>'
       '<script>' + JS + '</script></body></html>\n')

io.open(OUT, 'w', encoding='utf-8').write(doc)
print('%s — %.0f KB' % (os.path.basename(OUT), len(doc.encode('utf-8')) / 1024))
print('folders %d · pages shown %d · marked check %d'
      % (len(F), sum(len(v) for v in pages_by_folder.values()), n_check))
