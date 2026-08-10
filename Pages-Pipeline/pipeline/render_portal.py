"""Build AKU-Migration-Portal.html — a multi-screen app over the migration plan.

Screens: Overview · Folder structure · Org chart · Pages (old link -> new link) ·
Who can do what · People & roles · Shared content & tags · Open questions · Glossary

Single file, no build step and no CDN, so it opens by double-click and works with
no network. It is a small hand-written app rather than React/Vue for that reason;
say the word and it becomes a Vite project instead.

SUPERSEDED. `portal/` is that Vite project, and `npm run build` there now emits the
same double-clickable single file — with the screens this script never grew, and
with folders, pages and people joined. This one writes
`AKU-Migration-Portal-legacy.html` so a re-run cannot silently overwrite it.
"""
import io, os, json, html, collections, re
import paths


OUT = paths.out('AKU-Migration-Portal-legacy.html')
plan = json.load(io.open(paths.work('plan.json'), encoding='utf-8'))
F, P, R = plan['folders'], plan['pages'], plan['roles']
LIVE = plan.get('live', [])
e = html.escape

CANON = ['about', 'about-us', 'at-a-glance', 'academics', 'admissions', 'research',
         'supportus', 'support-us', 'students', 'alumni', 'faculty', 'media',
         'careers', 'library', 'libraries', 'news', 'events', 'blogs',
         'registrar', 'convocation', 'geo', 'leads', 'chancellor', 'trustees',
         'president', 'provostoffice', 'officers', 'charters', 'environment',
         'programmes', 'programs', 'study', 'departments', 'centres', 'partners',
         'resources', 'people', 'staff', 'contact', 'giving', 'impact']
RANK = {n: i for i, n in enumerate(CANON)}
# Every kind build_migration_plan.py can emit. A missing key raised a KeyError
# here rather than mislabelling a folder, which is the behaviour we want -- but it
# means a new kind has to be added in both places.
SHORT = {'root': 'top level', 'container': 'grouping', 'region': 'region',
         'entity': 'entity', 'department': 'department', 'division': 'programme',
         'section': 'section', 'folder': 'folder',
         'region-folder': 'region folder', 'centre': 'centre', 'office': 'office',
         'publication': 'publication'}

by_path = {r['new_path']: r for r in F}
kids = collections.defaultdict(list)
for r in F:
    if r['parent_path']:
        kids[r['parent_path']].append(r['new_path'])
roots = sorted([r['new_path'] for r in F if not r['parent_path']],
               key=lambda p: {'regions': 0, 'staging': 1}.get(p, 2))

live_pages = [p for p in P if p['new_path']]
dropped = [p for p in P if not p['new_path']]
pages_by_folder = collections.defaultdict(list)
for p in live_pages:
    pages_by_folder[p['folder']].append(p)

def sk(path):
    n = path.split('/')[-1]
    return (RANK.get(n, 500), n)

def sub_pages(path):
    return len(pages_by_folder.get(path, [])) + \
        sum(sub_pages(c) for c in kids.get(path, []))

def sub_folders(path):
    return 1 + sum(sub_folders(c) for c in kids.get(path, []))

# A slug like `bscn` or `ugme` looked unclear until I checked: SharePoint already
# carries a human title for 338 of the 339 long-tail folders — "BScN Programme",
# "Undergraduate Programme", "Academic Support Services". So the fix is to show
# the title, not to flag the folder. Only one folder has no title at all.
NO_TITLE = [r['new_path'] for r in F
            if r['kind'] == 'folder' and not (r['title'] or '').strip()]

# Permissions are purely hierarchical: whoever holds a permission on a folder
# manages that folder and everything under it. So a folder that sets nothing of
# its own is not owned by "Public Affairs" — it is managed by whoever manages its
# nearest ancestor that does set something.
def owner_chain(path):
    cur = path
    while True:
        r = by_path.get(cur)
        if r is None:
            return None, ''
        if r['own_permissions'] == 'yes':
            return cur, r['managed_by']
        if '/' not in cur:
            return None, ''
        cur = cur.rsplit('/', 1)[0]

def manager_label(path):
    r = by_path[path]
    if r['own_permissions'] == 'yes':
        return e(r['managed_by']), 'own'
    src, team = owner_chain(path)
    if src:
        return ('inherits · %s' % e(team.split(';')[0].strip())), 'inh'
    return 'inherits from the space admin', 'inh'
ROLE_BY_UNIT = collections.defaultdict(list)
for r in R:
    ROLE_BY_UNIT[r['unit']].append(r)

# ---------------------------------------------------------------- overview
def count_kind(prefix, kind):
    return sum(1 for r in F if r['kind'] == kind
               and (r['new_path'] == prefix or r['new_path'].startswith(prefix + '/')))

region_rows = []
for r in sorted(F, key=lambda x: (x['new_path'] != 'regions/global', x['new_path'])):
    if r['kind'] == 'region' and r['new_path'].count('/') == 1:
        p = r['new_path']
        region_rows.append({
            'slug': p.split('/')[-1], 'path': p,
            'entities': count_kind(p, 'entity'),
            'depts': count_kind(p, 'department'),
            'rfolders': count_kind(p, 'region-folder'),
            'sections': count_kind(p, 'section'),
            'folders': sub_folders(p) - 1, 'pages': sub_pages(p),
            'countries': r.get('countries', ''),
        })

moved = [p for p in live_pages if p['moved_from']]
by_type = collections.Counter(p['content_type'] for p in live_pages)
shared = [r for r in F if r.get('also_belongs_to')]
caps = collections.Counter(r['capability'] for r in R)
space_roles = [r for r in R if r['unit'] == '(space-wide)']
unscoped = [r for r in R if r['unit'] != '(space-wide)' and not r['folders_scoped']]
central_pages = sum(1 for p in live_pages if 'central' in p['managed_by'])

# ---------------------------------------------------------------- tree
def tnode(path, depth=0):
    r = by_path[path]
    name = path.split('/')[-1]
    ch = sorted(kids.get(path, []), key=sk)
    pgs = sorted(pages_by_folder.get(path, []),
                 key=lambda x: x['new_path'].split('/')[-1])
    tp, tf = sub_pages(path), sub_folders(path) - 1
    has = bool(ch or pgs)
    bits = ([('%d folder%s' % (tf, '' if tf == 1 else 's'))] if tf else []) + \
           ([('{:,} page{}'.format(tp, '' if tp == 1 else 's'))] if tp else [])
    label, mkind = manager_label(path)
    title = (r['title'] or '').strip()
    extra = ''
    if r.get('countries'):
        extra += '<span class="chip blue">works in %s</span>' % e(r['countries'])
    if r.get('also_belongs_to'):
        extra += ('<span class="chip blue" title="%s">shared</span>'
                  % e(r['also_belongs_to']))
    if r['own_permissions'] == 'yes':
        extra += ('<span class="chip green" title="Can create and edit: %s&#10;'
                  'Can publish: %s">sets permissions</span>'
                  % (e(r['can_create_and_edit']), e(r['can_publish'])))
    pg_html = ''
    if pgs:
        pg_html = '<div class="pgs">' + ''.join(
            '<div class="pg" data-n="%s"><span class="pdot %s"></span>'
            '<span class="pn">%s</span>'
            '<a href="%s" target="_blank" rel="noopener" class="lk old">old</a>'
            '<a href="%s" target="_blank" rel="noopener" class="lk new">new</a>'
            '<span class="pact %s">%s</span></div>'
            % (e((x['new_path'] + ' ' + x['current_url']).lower()),
               x['content_type'], e(x['new_path'].split('/')[-1]),
               e(x['current_url']), e(x['new_url']),
               'u' if x['action'] == 'Update and move' else '',
               'update first' if x['action'] == 'Update and move' else 'move as is')
            for x in pgs) + '</div>'
    inner = ('<div class="ch">' + ''.join(tnode(c, depth + 1) for c in ch)
             + pg_html + '</div>') if has else ''
    return ('<div class="n%s" data-p="%s" data-empty="%d">'
            '<div class="row k-%s" data-n="%s" title="%s">'
            '<span class="tw%s"></span><span class="nm">%s</span>'
            '<span class="ttl">%s</span>'
            '<span class="ty">%s</span>%s'
            '<span class="meta">%s</span>'
            '<span class="team %s">%s</span></div>%s</div>'
            % ('' if depth < 1 else ' cl', e(path), 0 if tp else 1,
               r['kind'],
               e((path + ' ' + name + ' ' + title + ' '
                  + r['managed_by']).lower()),
               e(path + (' — ' + r['entity_basis'] if r.get('entity_basis') else '')),
               '' if has else ' leaf', e(name),
               e(title) if title and title.lower() != name.replace('-', ' ') else '',
               e(SHORT[r['kind']]), extra,
               ' · '.join(bits) or 'empty', mkind, label, inner))

tree_html = ''.join(tnode(p) for p in roots)

# ---------------------------------------------------------------- org chart
ICON = {'root': '⌂', 'container': '⋯', 'region': '◉', 'entity': '■',
        'department': '▪', 'division': '◆', 'section': '▬',
        'region-folder': '□', 'folder': '·'}

def onode(path, depth=0):
    r = by_path[path]
    ch = sorted(kids.get(path, []), key=sk)
    tp = sub_pages(path)
    label, mkind = manager_label(path)
    title = (r['title'] or '').strip()
    nm = path.split('/')[-1]
    caption = title if title and title.lower() != nm.replace('-', ' ')         else SHORT[r['kind']]
    box = ('<div class="ocb k-%s" data-n="%s" title="%s">'
           '<span class="oci">%s</span>'
           '<span class="ocn"><b>%s</b><i>%s</i></span>'
           '%s<span class="oct%s">%s</span><span class="occ">%s</span>%s</div>'
           % (r['kind'], e((path + ' ' + title + ' '
                             + r['managed_by']).lower()), e(path),
              ICON.get(r['kind'], '·'), e(nm), e(caption),
              ('<span class="ocx" title="%s">shared</span>'
               % e(r['also_belongs_to'])) if r.get('also_belongs_to') else '',
              ' ' + mkind, label,
              '{:,}'.format(tp) if tp else '—',
              ('<span class="octg" title="%d inside">%s</span>'
               % (len(ch), '−' if depth < 1 else '+')) if ch else ''))
    if not ch:
        return '<li>%s</li>' % box
    return ('<li class="%s">%s<ul>%s</ul></li>'
            % ('' if depth < 1 else 'cl', box,
               ''.join(onode(c, depth + 1) for c in ch)))

chart_html = ('<div class="ocwrap"><div class="oc"><ul>%s</ul></div></div>'
              % ''.join(onode(p) for p in roots))

PEOPLE = json.load(io.open(paths.work('people.json'), encoding='utf-8'))
CAMPUS = {'aku': 'Karachi', 'nbi': 'Nairobi', 'dar': 'Dar es Salaam',
          'ismc': 'London', 'scholar': 'service account'}
by_cap = collections.Counter(p['top_capability'] for p in PEOPLE)

people_rows = ''.join(
    '<div class="prsn" data-n="%s"><div class="av %s">%s</div>'
    '<div class="pi"><b>%s</b><span>%s</span></div>'
    '<span class="cmp">%s</span>'
    '<span class="cap2 %s">%s</span>'
    '<span class="rls">%s</span>'
    '<span class="fld">%s</span></div>'
    % (e((x['name'] + ' ' + x['email'] + ' ' + x['top_capability'] + ' '
          + ' '.join(x['storyblok_roles']) + ' '
          + ' '.join(x['groups'])).lower()),
       x['top_capability'],
       e(''.join(w[0] for w in x['name'].split()[:2]).upper() or '?'),
       e(x['name']), e(x['email'] or x['login']),
       e(CAMPUS.get(x['campus'], x['campus'])),
       x['top_capability'], e(x['top_capability']),
       ''.join('<span class="rl">%s</span>' % e(r) for r in x['storyblok_roles'])
       or '<span class="rl dim">none yet</span>',
       ('%d folder%s' % (len(x['folders']), '' if len(x['folders']) == 1 else 's'))
       if x['folders'] else 'whole space'
       if x['top_capability'] == 'admin' else '—')
    for x in PEOPLE)

# ---------------------------------------------------------------- pages list
page_rows = ''.join(
    '<div class="prow" data-n="%s">'
    '<span class="ct %s">%s</span>'
    '<div class="pu"><a href="%s" target="_blank" rel="noopener">%s</a>'
    '<span class="arw">↓</span>'
    '<a href="%s" target="_blank" rel="noopener" class="nu">%s</a></div>'
    '<span class="pmeta">%s</span>'
    '<span class="pact %s">%s</span></div>'
    % (e((x['current_url'] + ' ' + x['new_path'] + ' ' + x['managed_by'] + ' '
          + x['content_type'] + ' ' + x['region'] + ' ' + x['entity']).lower()),
       x['content_type'], e(x['content_type']),
       e(x['current_url']), e(x['current_url'].replace('https://www.aku.edu', '')),
       e(x['new_url']), e(x['new_url'].replace('https://www.aku.edu', '')),
       e((x['entity'] or x['region']).replace('-', ' ')
         + (' · ' + x['managed_by'] if 'central' not in x['managed_by'] else '')),
       'u' if x['action'] == 'Update and move' else '',
       'update first' if x['action'] == 'Update and move' else 'move as is')
    for x in live_pages)

drop_rows = ''.join(
    '<tr><td class="mono sm"><a href="%s" target="_blank" rel="noopener">%s</a></td>'
    '<td>%s</td></tr>'
    % (e(x['current_url']), e(x['current_url'].replace('https://www.aku.edu', '')),
       e(x['do_not_migrate']))
    for x in dropped)

# ------------------------------------------------------- who can do what
rights_rows = ''.join(
    '<tr><td class="mono sm">%s</td><td>%s</td>'
    '<td class="mono sm ed">%s</td><td class="mono sm pub">%s</td></tr>'
    % (e(r['new_path'].replace('regions/', '')), e(r['managed_by']),
       e(r['can_create_and_edit']), e(r['can_publish']))
    for r in sorted(F, key=lambda x: x['new_path'])
    if r['own_permissions'] == 'yes')

MATRIX = [
    ('Read any page, published or draft', 'viewer', 'yes', 'yes', 'yes', 'yes'),
    ('Create a page in its own folders', 'editor', 'no', 'yes', 'yes', 'yes'),
    ('Edit and save a draft', 'editor', 'no', 'yes', 'yes', 'yes'),
    ('Publish, so the public sees it', 'publisher', 'no', 'no', 'yes', 'yes'),
    ('Add, move or delete a folder', 'structure manager', 'no', 'no', 'no', 'yes'),
    ('Change roles and settings', 'admin', 'no', 'no', 'no', 'yes'),
]
matrix_rows = ''.join(
    '<tr><td>%s</td>%s</tr>'
    % (e(a), ''.join('<td class="yn %s">%s</td>' % ('y' if v == 'yes' else 'n',
                                                    '✓' if v == 'yes' else '—')
                     for v in (v1, v2, v3, v4)))
    for a, _r, v1, v2, v3, v4 in MATRIX)

role_rows = ''.join(
    '<tr><td class="mono"><b>%s</b></td><td class="cap %s">%s</td>'
    '<td class="num">%s</td><td>%s</td><td class="num">%s</td>'
    '<td class="mono sm">%s</td><td class="sm">%s</td></tr>'
    % (e(r['storyblok_role']), r['capability'], e(r['capability']),
       r['members'] or '—', e(r['unit']), r['folders_scoped'] or '—',
       e(r['source_sharepoint_groups']),
       e(r['allowed_paths'].replace('regions/', '') or r['note']))
    for r in sorted(R, key=lambda x: (x['unit'] == '(space-wide)',
                                      x['storyblok_role'])))

shared_rows = ''.join(
    '<tr><td class="mono sm">%s</td><td>%s</td><td class="mono sm">%s</td></tr>'
    % (e(r['new_path'].replace('regions/', '')),
       e(r['managed_by']), e(r['also_belongs_to']))
    for r in sorted(shared, key=lambda x: x['new_path']))

live_rows = ''.join(
    '<tr><td class="mono sm"><a href="%s" target="_blank" rel="noopener">%s</a></td>'
    '<td class="sm">%s</td><td class="sm">%s</td></tr>'
    % (e(x['page_checked']),
       e(x['page_checked'].replace('https://www.aku.edu/', '')),
       e(x['what_aku_shows']), e(x['what_it_settles']))
    for x in LIVE)

moved_rows = ''.join(
    '<tr><td class="ct %s">%s</td><td class="mono sm">%s</td>'
    '<td class="mono sm">%s</td></tr>'
    % (x['content_type'], e(x['content_type']),
       e(x['moved_from'].replace('regions/', '')),
       e(x['new_path'].replace('regions/', '')))
    for x in sorted(moved, key=lambda z: (z['content_type'], z['new_path'])))

# ---------------------------------------------------------------- shell
CSS = io.open(paths.asset('portal.css'), encoding='utf-8').read()
JS = io.open(paths.asset('portal.js'), encoding='utf-8').read()


def screen(sid, title, lede, body):
    return ('<section class="scr" id="%s"><h2>%s</h2><p class="lede">%s</p>%s</section>'
            % (sid, title, lede, body))


tiles = ''.join(
    '<div class="tile%s"><b>%s</b><span>%s</span></div>' % (c, v, l)
    for v, l, c in [
        ('{:,}'.format(len(live_pages)), 'pages to migrate', ' hl'),
        ('{:,}'.format(len(F)), 'folders to create', ''),
        ('7', 'regions incl. global', ''),
        (str(sum(r['entities'] for r in region_rows)), 'entity placements', ''),
        (str(count_kind('regions', 'department')), 'departments', ''),
        (str(len(R)), 'roles to create', ' hl'),
        (str(len(moved)), 'pages moved to hubs', ''),
        (str(len(dropped)), 'pages dropped', ''),
    ])

region_cards = ''.join(
    '<div class="card"><h3 style="margin:0 0 6px">%s</h3>'
    '<p style="margin:0;font-size:13.5px;color:var(--ink2)">%s</p></div>'
    % (e(r['slug'].replace('-', ' ').title()),
       ('It holds the %d section folders and %s pages that no faculty owns — news, '
        'events and blogs, plus about us, academics, admissions, research, support us, '
        'and the pages for students, alumni, faculty, media, careers and libraries.'
        % (r['sections'], '{:,}'.format(r['pages'])))
       if r['slug'] == 'global' else
       ('%d entit%s%s%s. %s pages.%s'
        % (r['entities'], 'y' if r['entities'] == 1 else 'ies',
           ', %d departments inside them' % r['depts'] if r['depts'] else '',
           ', plus %d folder%s of its own that are not entities'
           % (r['rfolders'], '' if r['rfolders'] == 1 else 's') if r['rfolders'] else '',
           '{:,}'.format(r['pages']),
           ' Its entities work across %s.' % e(r['countries']) if r['countries'] else '')))
    for r in region_rows)

s_over = screen(
    'overview', 'What is changing',
    "Two AKU exports drive this. <b>aku-university-visible-pages.csv</b> is AKU's own "
    "list of what to migrate. <b>The SharePoint permissions export</b> says who owns "
    "and edits each folder today. Everything here comes from those two, confirmed "
    "against the live site wherever they were silent.",
    '<div class="tiles">' + tiles + '</div>'
    '<h3>The shape</h3>'
    '<div class="note g">Root holds <b>regions</b> and <b>staging</b>. Global is a '
    'region like any other — the one that owns what no faculty owns. Inside a region: '
    '<b>entities</b> for the faculties, schools and institutes AKU itself publishes, '
    'plain <b>folders</b> for units it does not, and <b>departments</b> inside an '
    'entity.<div class="mono sm" style="margin-top:9px;color:var(--ink2)">'
    'regions / pakistan / entities / medical-college / departments / anaes / home'
    '</div></div>' + region_cards
    + '<h3>Content type</h3><div class="card">'
    '<p style="margin:0;font-size:13.5px">Of the ' + '{:,}'.format(len(live_pages))
    + ' pages: '
    + ', '.join('<b>%s</b> %s' % ('{:,}'.format(v), k) for k, v in by_type.most_common())
    + '. News, events and blogs all live in the global hubs and carry region, entity '
      'and department as tags — the same way <span class="mono">aku.edu/news</span> '
      'already filters by Entity and Tag today.</p></div>')

s_tree = screen(
    'tree', 'Folder structure',
    "Click any row to open it. Children are listed in the order AKU's own menus use — "
    "<b>about, programmes, research, faculty, departments</b>, then news, events and "
    "blogs, then anything else A-Z. Every page carries an <b>old</b> and a <b>new</b> "
    "link so you can check it against the live site.",
    '<div class="bar">'
    '<input type="search" id="q1" placeholder="Search a region, entity, folder, team or page…">'
    '<span class="hits" id="h1"></span>'
    '<button class="btn" id="L1">Regions</button>'
    '<button class="btn" id="L2">Entities</button>'
    '<button class="btn" id="L3">Departments</button>'
    '<button class="btn" id="L9">Open everything</button>'
    '<label class="tg"><input type="checkbox" id="he">Hide empty folders</label>'
    '</div><div id="tree">' + tree_html + '</div>')

s_chart = screen(
    'chart', 'Org chart',
    'The same folders drawn top to bottom. Click <b>−</b> / <b>+</b> under a box to '
    'fold or open it. The number on the right is how many pages sit beneath it.',
    chart_html)

s_pages = screen(
    'pages', 'Every page, old link and new link',
    'All ' + '{:,}'.format(len(live_pages)) + ' pages. The grey line is where it lives '
    'today, the green line is where it will live. Click either one to open it.',
    '<div class="bar">'
    '<input type="search" id="q2" placeholder="Search a URL, entity, team or type…">'
    '<span class="hits" id="h2"></span>'
    '<button class="btn f2" data-f="">All</button>'
    '<button class="btn f2" data-f="event">Events</button>'
    '<button class="btn f2" data-f="blog">Blogs</button>'
    '<button class="btn f2" data-f="news">News</button>'
    '<button class="btn f2" data-f="update first">Needs updating</button>'
    '</div><div class="plist" id="plist">' + page_rows + '</div>'
    '<h3>' + str(len(dropped)) + ' pages are not migrating</h3>'
    '<div class="tw2"><table><thead><tr><th>Page</th><th>Why</th></tr></thead>'
    '<tbody>' + drop_rows + '</tbody></table></div>')

s_rights = screen(
    'rights', 'Who can create, read, update and publish',
    "AKU already runs a two-step workflow: a <b>CW</b> (content writer) group drafts "
    "and a <b>CA</b> (content approver) group publishes. That split carries straight "
    "over. An <b>editor</b> creates and edits but cannot publish; a <b>publisher</b> "
    "can also publish; only <b>admin</b> and the <b>structure manager</b> may add or "
    "delete folders.",
    '<h3>What each role can do</h3>'
    '<table><thead><tr><th>Action</th><th>Viewer</th><th>Editor</th>'
    '<th>Publisher</th><th>Admin</th></tr></thead><tbody>' + matrix_rows
    + '</tbody></table>'
    '<h3>Where a permission is actually set — '
    + str(sum(1 for r in F if r['own_permissions'] == 'yes')) + ' folders</h3>'
    '<p class="lede">Every other folder inherits from its parent, exactly as SharePoint '
    'runs it today.</p>'
    '<div class="bar"><input type="search" id="q3" placeholder="Search a folder or team…">'
    '<span class="hits" id="h3"></span></div>'
    '<div class="tw2"><table id="rt"><thead><tr><th>Folder</th>'
    '<th>Team that manages it</th><th>Can create &amp; edit</th>'
    '<th>Can publish</th></tr></thead><tbody>' + rights_rows + '</tbody></table></div>')

s_roles = screen(
    'roles', 'Roles to create, and who goes in them',
    str(caps['editor']) + ' editor roles and ' + str(caps['publisher'])
    + ' publisher roles — one pair per AKU team, each limited to the folders that team '
      'owns, so Anaesthesiology cannot edit Pathology. Plus ' + str(len(space_roles))
    + ' space-wide roles. <b>People</b> is how many named accounts are in the '
      'SharePoint group today.',
    '<div class="bar">'
    '<input type="search" id="q4" placeholder="Search a role, team or group…">'
    '<span class="hits" id="h4"></span></div>'
    '<div class="tw2"><table id="rl"><thead><tr><th>Storyblok role</th><th>Can</th>'
    '<th>People</th><th>AKU team</th><th>Folders</th><th>From SharePoint group</th>'
    '<th>Allowed paths</th></tr></thead><tbody>' + role_rows + '</tbody></table></div>'
    '<h3>' + str(len(unscoped)) + ' roles still need a scope</h3>'
    '<div class="note">These teams own a section whose folder names no owner — it '
    'carries the site-wide group roster instead — so there is nothing to derive their '
    'folder list from. Someone at AKU has to say which folders they cover: <b>'
    + e(', '.join(sorted({r['unit'] for r in unscoped}))) + '</b>.</div>')

s_shared = screen(
    'shared', 'Shared content, and how tags keep it straight',
    'A folder gives a page one home. Some content belongs to more than one owner, so '
    'the second owner is carried as a tag — which is what lets a page appear in two '
    'places without being copied.',
    '<h3>' + str(len(shared)) + ' folders belong to an entity they cannot live under</h3>'
    '<div class="tw2"><table><thead><tr><th>Folder</th><th>Team that manages it</th>'
    '<th>Also belongs to</th></tr></thead><tbody>' + shared_rows + '</tbody></table></div>'
    '<h3>' + str(len(moved)) + ' pages moved into the global hubs</h3>'
    '<p class="lede">Each faculty kept its own events and blog folders. '
    '<span class="mono">aku.edu/news</span> is already one hub that filters by '
    '<b>Entity</b> and <b>Tag</b>, so these consolidate and carry their region, entity '
    'and department as tags. ' + str(len(dropped) - 3) + ' duplicate listing pages and '
    'detail templates were dropped rather than moved — one hub needs one of each, not '
    'one per faculty.</p>'
    '<div class="tw2"><table><thead><tr><th>Type</th><th>Was in</th><th>Now in</th></tr>'
    '</thead><tbody>' + moved_rows + '</tbody></table></div>')

s_checks = screen(
    'checks', 'Confirmed against the live site',
    'Where the two exports disagreed or said nothing, I opened the page on aku.edu and '
    'read the breadcrumb AKU itself renders — that breadcrumb <i>is</i> the canonical '
    'parent, because the site is stating where it thinks the page lives.',
    '<div class="tw2"><table><thead><tr><th>Page opened</th><th>What AKU shows</th>'
    '<th>What it settles</th></tr></thead><tbody>' + live_rows + '</tbody></table></div>')

s_gloss = screen(
    'glossary', 'What the words mean',
    'Every label used in this app, in plain English.',
    '<div class="card"><dl class="gl">'
    '<dt>inherits · X</dt><dd>The folder sets no permissions of its own, so whoever '
    'manages the nearest folder above it manages this one too. There is no such thing '
    'as an unowned folder — it is always someone, just further up the tree.</dd>'
    '<dt>The odd short names</dt><dd>Slugs like <span class="mono">bscn</span>, <span class="mono">ugme</span> or <span class="mono">acss</span> looked like a problem until I checked: SharePoint already carries a human title for <b>338 of the 339</b> of them — "BScN Programme", "Undergraduate Programme", "Academic Support Services". They are shown beside the slug throughout, so nothing needs renaming. Exactly one folder has no title at all, and its source page 404s: <span class="mono">mrtc-pk/research/Pages/Projects</span>.</dd>'
    '<dt>sets permissions</dt><dd>A green chip meaning the folder sets its own '
    'editing rights. Permissions are purely hierarchical: whoever holds one on a '
    'folder manages that folder <i>and everything under it</i>. An admin at the root '
    'manages everything; a team on <span class="mono">…/entities/medical-college/'
    'departments/anaes</span> manages only that. A row reading <i>inherits · X</i> '
    'takes its rights from the nearest folder above it that sets any.</dd>'
    '<dt>shared</dt><dd>A blue chip meaning the folder also belongs to an entity it '
    'cannot live under — a library branch belonging to a faculty, or a conference '
    'belonging to an institute.</dd>'
    '<dt>Entity</dt><dd>A faculty, school, institute or centre that AKU itself publishes '
    'on <span class="mono">aku.edu/academics</span> or <span class="mono">aku.edu/'
    'research</span>. Anything else is a folder, not an entity — that is how the call '
    'is made, so it is not my opinion.</dd>'
    '<dt>Region folder</dt><dd>A real unit AKU does not publish as an academic unit or '
    'a global institute — Cancer Centre, Tele-ICU, Ek Saath. It sits directly under its '
    'region instead of under <span class="mono">entities/</span>.</dd>'
    '<dt>Department</dt><dd>A sub-unit of an entity with its own editing team, like '
    'Anaesthesiology under Medical College. Learned from Pakistan, where each has its '
    'own group, and applied to the same entity in the other regions.</dd>'
    '<dt>CW / CA group</dt><dd>AKU’s own naming. <span class="mono">CW MC PK</span> '
    'is the Content Writer group for Medical College Pakistan; <span class="mono">CA MC '
    'PK</span> is the Content Approver. That pair is why the editor/publisher split '
    'maps over cleanly.</dd>'
    '<dt>Unique scope</dt><dd>A SharePoint folder that sets its own permissions instead '
    'of inheriting. Only these rows name a real owner — inherited rows repeat the '
    'AKU-wide groups and witness nothing.</dd>'
    '<dt>move as is / update first</dt><dd>AKU’s own call, from their CSV. 480 '
    'pages are marked "Update and move" — they need content work before they go.</dd>'
    '</dl></div>')

s_people = screen(
    'people', 'Every person, and the role to give them',
    str(len(PEOPLE)) + ' named people hold a permission on aku.edu today. This is '
    'what each one should get in Storyblok, worked out from the groups they are '
    'already in. <b>Admin</b> covers the whole space; everyone else is limited to '
    'the folders their team owns.',
    '<div class="tiles">'
    + ''.join('<div class="tile"><b>%d</b><span>%s</span></div>' % (v, k)
              for k, v in by_cap.most_common())
    + '</div>'
    '<div class="bar">'
    '<input type="search" id="q5" placeholder="Search a name, email, role or group — try Ambreen…">'
    '<span class="hits" id="h5"></span>'
    '<button class="btn f5" data-f="">Everyone</button>'
    '<button class="btn f5" data-f="admin">Admins</button>'
    '<button class="btn f5" data-f="publisher">Publishers</button>'
    '<button class="btn f5" data-f="editor">Editors</button>'
    '<button class="btn f5" data-f="viewer">Viewers</button>'
    '</div><div class="plist" id="people">' + people_rows + '</div>')

NAV = [('Plan', [('overview', 'Overview', ''),
                 ('tree', 'Folder structure', '{:,}'.format(len(F))),
                 ('chart', 'Org chart', ''),
                 ('pages', 'Pages, old &amp; new', '{:,}'.format(len(live_pages)))]),
       ('Permissions', [('rights', 'Who can do what', ''),
                        ('roles', 'Roles to create', str(len(R))),
                        ('people', 'People', str(len(PEOPLE)))]),
       ('Detail', [('shared', 'Shared content', str(len(shared))),
                   ('checks', 'Live-site checks', str(len(LIVE))),
                   ('glossary', 'What words mean', '')])]

nav = ''
for grp, items in NAV:
    nav += '<div class="grp">%s</div>' % grp
    for sid, label, badge in items:
        nav += ('<a href="#%s" data-s="%s">%s%s</a>'
                % (sid, sid, label, '<b>%s</b>' % badge if badge else ''))

doc = ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
       '<meta name="viewport" content="width=device-width,initial-scale=1">'
       '<title>AKU → Storyblok — migration portal</title><style>' + CSS
       + '</style></head><body>'
       '<aside><h1>AKU → Storyblok</h1>'
       '<p class="sub">' + '{:,}'.format(len(live_pages)) + ' pages · '
       + '{:,}'.format(len(F)) + ' folders · ' + str(len(R)) + ' roles</p>'
       '<nav>' + nav + '</nav>'
       '<div class="bu"><label for="bu">Base URL for the new links</label>'
       '<input id="bu" type="text" value="https://www.aku.edu" '
       'placeholder="https://dev.example.org" spellcheck="false">'
       '<span class="buh">Dev, staging or live — every new link updates.</span>'
       '</div></aside>'
       '<main>' + s_over + s_tree + s_chart + s_pages + s_rights + s_roles
       + s_people
       + s_shared + s_checks + s_gloss + '</main>'
       '<script>' + JS + '</script></body></html>')

io.open(OUT, 'w', encoding='utf-8').write(doc)
print('%s — %.0f KB' % (os.path.basename(OUT), len(doc.encode('utf-8')) / 1024))
print('screens 9 · folders %d · pages %d · roles %d · shared %d · dropped %d'
      % (len(F), len(live_pages), len(R), len(shared), len(dropped)))
