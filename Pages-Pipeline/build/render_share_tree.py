"""One self-contained HTML file: the whole destination tree, for sending to AKU.

Everything is inline — no data file, no server, no network. Double-click it, or
attach it to an email, and it opens.

It shows every level in one place: regions, the entities inside them, the
departments, centres, offices and publications inside those, every plain folder,
and under each folder every page with its old slug and its new one.

Order is fixed, never alphabetical-only: each folder lists its children in the
order AKU's own menus use — about, programmes, research, faculty, departments,
then news, events and blogs — and only then A-Z. Two entities are readable side
by side because they read the same way down.

Ownership is hierarchical. A folder that sets its own permissions names its team;
everything beneath it says `inherits` and names the team it inherits from. Nothing
is labelled with a central department that does not, in fact, manage it.

Output  Pages-Pipeline/AKU-Tree.html
"""
import io, os, json, html, collections

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'AKU-Tree.html')
plan = json.load(io.open(os.path.join(HERE, 'plan.json'), encoding='utf-8'))
F, P = plan['folders'], plan['pages']
e = html.escape

# The order AKU's own menus use, read off aku.edu: first the university's
# top-level menus, then the shape every faculty page shares.
CANON = [
    'about', 'about-us', 'at-a-glance', 'academics', 'admissions', 'research',
    'supportus', 'support-us', 'students', 'alumni', 'faculty', 'media',
    'careers', 'library', 'libraries', 'news', 'events', 'blogs',
    'registrar', 'convocation', 'geo', 'leads', 'chancellor', 'trustees',
    'president', 'provostoffice', 'officers', 'charters', 'environment',
    'programmes', 'programs', 'study', 'departments', 'centres', 'partners',
    'resources', 'people', 'staff', 'contact', 'giving', 'impact',
]
RANK = {n: i for i, n in enumerate(CANON)}

# Every kind build_migration_plan.py can emit, and what it means to a reader who
# has not read the docs. A missing key is a KeyError on purpose: a new kind must
# be described here before it can ship in a file we send to AKU.
KIND = {
    'root':          ('top level',   'The two things at the root of the space.'),
    'container':     ('grouping',    'A level Storyblok needs so the folder beneath it can exist. Holds no page of its own.'),
    'region':        ('region',      'A country, or Global for what no country owns.'),
    'entity':        ('entity',      'A faculty, school or institute AKU lists under Academics or Research.'),
    'department':    ('department',  'A unit with its own writers and approvers, confirmed on its own page.'),
    'centre':        ('centre',      'A standing unit inside a faculty that calls itself a centre.'),
    'office':        ('office',      'An office inside a faculty — neither a department nor a programme.'),
    'publication':   ('publication', 'Something a unit publishes: a newsletter or a magazine.'),
    'division':      ('programme',   'A programme or project run by an entity.'),
    'section':       ('section',     'A top-level section of aku.edu that no faculty owns.'),
    'folder':        ('folder',      'An ordinary folder.'),
    'region-folder': ('region folder', 'A real unit at region level that AKU does not publish as an entity.'),
}

by_path = {r['new_path']: r for r in F}
kids = collections.defaultdict(list)
for r in F:
    if r['parent_path']:
        kids[r['parent_path']].append(r['new_path'])

pages_by_folder = collections.defaultdict(list)
for p in P:
    if not p.get('do_not_migrate'):
        pages_by_folder[p['folder']].append(p)

def sort_key(path):
    n = path.split('/')[-1]
    return (RANK.get(n, 500), n)

for k in kids:
    kids[k].sort(key=sort_key)
roots = sorted([r['new_path'] for r in F if not r['parent_path']],
               key=lambda p: {'regions': 0, 'staging': 1}.get(p, 2))

_pc, _fc = {}, {}
def sub_pages(path):
    if path not in _pc:
        _pc[path] = len(pages_by_folder.get(path, [])) + \
                    sum(sub_pages(c) for c in kids.get(path, []))
    return _pc[path]

def sub_folders(path):
    if path not in _fc:
        _fc[path] = 1 + sum(sub_folders(c) for c in kids.get(path, []))
    return _fc[path]

def manager(path):
    """The team that manages this folder, walking up to whoever sets rights.

    A folder either sets its own permissions or inherits them. Naming a central
    department on a folder it does not administer was the old behaviour and it
    misled every reader who saw it.
    """
    cur = path
    while cur:
        r = by_path.get(cur)
        if r and r.get('own_permissions') == 'yes' and r.get('managed_by'):
            return r['managed_by'], cur == path
        cur = cur.rsplit('/', 1)[0] if '/' in cur else ''
    return '', False

def cset(v):
    """The countries, order-insensitive.

    IED East Africa reads "Tanzania, Kenya, Uganda" and its Development Projects
    read "Kenya, Uganda, Tanzania" -- the same three countries written in a
    different order. Compared as strings that looks like a change and printed a
    chip that said nothing.
    """
    return frozenset(x.strip().lower() for x in (v or '').split(',') if x.strip())

def strip_host(u):
    return u.replace('https://www.aku.edu', '').replace('http://www.aku.edu', '')

# ---- rows ---------------------------------------------------------------
out = []

def render(path, depth, parent_countries=''):
    r = by_path[path]
    ch = kids.get(path, [])
    pgs = sorted(pages_by_folder.get(path, []), key=lambda x: x['new_path'].lower())
    tp, tf = sub_pages(path), sub_folders(path) - 1
    has = bool(ch or pgs)
    name = path.split('/')[-1]
    title = (r.get('title') or '').strip()
    show_title = title and title.lower() != name.replace('-', ' ').lower()
    label, _ = KIND[r['kind']]
    team, own = manager(path)

    chips = []
    # Only where it CHANGES. The countries tag is inherited by every descendant, so
    # printing it on each one put the same chip on eight consecutive rows and buried
    # the folders whose reach genuinely differs from their parent's.
    if r.get('countries') and cset(r['countries']) != cset(parent_countries):
        chips.append('<span class="c c-b">works in %s</span>' % e(r['countries']))
    if r.get('also_belongs_to'):
        chips.append('<span class="c c-b" title="%s">shared</span>'
                     % e(r['also_belongs_to']))
    if r.get('event_owner'):
        chips.append('<span class="c c-b" title="Run by %s">%s</span>'
                     % (e(r['event_owner']),
                        ('ran %s' % e(r['last_ran'])) if r.get('last_ran') else 'event'))
    if r.get('archive_candidate'):
        chips.append('<span class="c c-a" title="%s">archive?</span>'
                     % e(r['archive_candidate']))

    meta = []
    if tf:
        meta.append('%s folder%s' % (format(tf, ','), '' if tf == 1 else 's'))
    if tp:
        meta.append('%s page%s' % (format(tp, ','), '' if tp == 1 else 's'))
    if not meta:
        meta.append('empty')

    # data-s carries everything the search box matches, lowercased once here so
    # the browser never has to build it for 628 rows on every keystroke.
    hay = ' '.join([path, title, team, r['kind'], r.get('entity') or '']).lower()

    out.append(
        '<div class="n%s" data-k="%s" data-p="%d" data-s="%s">'
        % (' x' if not tp else '', e(r['kind']), tp, e(hay)))
    out.append(
        '<div class="r k-%s"%s><span class="t%s"></span>'
        '<span class="nm">%s</span>%s<span class="ty">%s</span>%s'
        '<span class="mt">%s</span><span class="tm%s">%s</span></div>'
        % (e(r['kind']),
           ' onclick="tg(this)"' if has else '',
           '' if has else ' lf',
           e(name),
           ('<span class="tt">%s</span>' % e(title)) if show_title else '',
           e(label), ''.join(chips), ' · '.join(meta),
           ' own' if own else '',
           e(team if own else ('inherits · ' + team if team else '—'))))

    if has:
        out.append('<div class="ch">')
        for c in ch:
            render(c, depth + 1, r.get('countries') or parent_countries)
        if pgs:
            out.append('<div class="pl">')
            for p in pgs:
                old, new = strip_host(p['current_url']), strip_host(p['new_url'])
                out.append(
                    '<div class="pg" data-s="%s"><span class="d %s"></span>'
                    '<span class="pn">%s</span>'
                    '<code class="o">%s</code><span class="ar">→</span>'
                    '<code class="w">%s</code>'
                    '<span class="ac%s">%s</span></div>'
                    % (e((old + ' ' + new).lower()),
                       e(p.get('content_type') or 'page'),
                       e(p['new_path'].split('/')[-1]),
                       e(old), e(new),
                       ' u' if p.get('action') == 'Update and move' else '',
                       'update first' if p.get('action') == 'Update and move'
                       else 'move as is'))
            out.append('</div>')
        out.append('</div>')
    out.append('</div>')

for r in roots:
    render(r, 0)

# ---- summary ------------------------------------------------------------
kind_counts = collections.Counter(r['kind'] for r in F)
regions = [r for r in F if r['kind'] == 'region']
rows = []
for r in sorted(regions, key=lambda x: -sub_pages(x['new_path'])):
    p_ = r['new_path']
    ents = sum(1 for f in F if f['kind'] == 'entity'
               and f['new_path'].startswith(p_ + '/'))
    deps = sum(1 for f in F if f['kind'] == 'department'
               and f['new_path'].startswith(p_ + '/'))
    rows.append('<tr><td><b>%s</b></td><td class="n">%s</td><td class="n">%s</td>'
                '<td class="n">%s</td><td class="n">%s</td></tr>'
                % (e(r['new_path'].split('/')[-1].replace('-', ' ').title()),
                   ents or '—', deps or '—',
                   format(sub_folders(p_) - 1, ','),
                   format(sub_pages(p_), ',') if sub_pages(p_) else '—'))

legend = ''.join(
    '<div class="lg"><span class="sw k-%s"></span><b>%s</b><i>%s</i>'
    '<u>%s</u></div>' % (k, e(KIND[k][0]), e(KIND[k][1]),
                         format(kind_counts.get(k, 0), ','))
    for k in ['region', 'entity', 'department', 'centre', 'office', 'publication',
              'division', 'region-folder', 'section', 'folder', 'container']
    if kind_counts.get(k))

TOTAL_PAGES = sum(1 for p in P if not p.get('do_not_migrate'))

HTML = u"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AKU → Storyblok · the complete folder and page tree</title>
<style>
*{box-sizing:border-box}
:root{--bg:#fff;--card:#fff;--ink:#12181d;--ink2:#41505c;--mut:#7b8b98;
--line:#e3e9ee;--brand:#0b7f6f;--blue:#1f6fd0;--amber:#9a6100;--hl:#fff7d6}
@media (prefers-color-scheme:dark){:root{--bg:#0e1216;--card:#141a20;
--ink:#e9eef2;--ink2:#b0bcc6;--mut:#7d8b96;--line:#26313a;--brand:#37b8a4;
--blue:#67aaf0;--amber:#d79a2b;--hl:#2c2a12}}
html,body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1500px;margin:0 auto;padding:0 22px 80px}
header{background:var(--brand);color:#fff;padding:26px 0 22px;margin-bottom:0}
header .wrap{padding-bottom:0}
h1{margin:0 0 6px;font-size:22px;font-weight:640;letter-spacing:-.2px}
.sub{opacity:.9;font-size:13.5px;max-width:96ch;margin:0}
.big{display:flex;gap:26px;flex-wrap:wrap;margin-top:16px}
.big div{line-height:1.2}
.big b{display:block;font-size:23px;font-weight:660}
.big span{font-size:11px;text-transform:uppercase;letter-spacing:.6px;opacity:.85}
h2{font-size:14px;text-transform:uppercase;letter-spacing:.7px;color:var(--mut);
margin:26px 0 10px;font-weight:600}
table{border-collapse:collapse;width:100%;max-width:760px;font-size:13.5px}
th,td{text-align:left;padding:6px 12px 6px 0;border-bottom:1px solid var(--line)}
th{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--mut)}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.legend{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));
gap:2px 20px}
.lg{display:flex;align-items:baseline;gap:8px;padding:4px 0;font-size:13px;
border-bottom:1px solid var(--line)}
.lg b{min-width:96px;font-weight:600}
.lg i{color:var(--ink2);font-style:normal;flex:1;font-size:12.5px}
.lg u{text-decoration:none;color:var(--mut);font-variant-numeric:tabular-nums}
.sw{width:9px;height:9px;border-radius:2px;background:var(--mut);flex:none}
.sw.k-region{background:var(--brand)}.sw.k-entity{background:var(--brand)}
.sw.k-department{background:var(--blue)}.sw.k-centre{background:var(--blue)}
.sw.k-office{background:var(--blue)}.sw.k-publication{background:var(--blue)}
.sw.k-division{background:var(--blue)}
.bar{position:sticky;top:0;z-index:9;background:var(--bg);
border-bottom:1px solid var(--line);padding:10px 0;display:flex;gap:8px;
flex-wrap:wrap;align-items:center;margin-top:22px}
input[type=search]{flex:1;min-width:230px;padding:7px 11px;border-radius:8px;
border:1px solid var(--line);background:var(--card);color:var(--ink);font:inherit}
button{padding:6px 11px;border-radius:8px;border:1px solid var(--line);
background:var(--card);color:var(--ink2);font:inherit;font-size:13px;cursor:pointer}
button:hover{border-color:var(--brand);color:var(--brand)}
button.pri{border-color:var(--brand);color:var(--brand);font-weight:560}
button.pri:hover{background:var(--brand);color:#fff}
/* Hiding the 3,306 page rows is one class on the container, not 3,306 class
   toggles -- otherwise "Open all" on a folders-only view stutters. */
#tree.np .pl{display:none}
.lg .c,.lg .tm{flex:none;min-width:0}
.lg .tm{min-width:auto;text-align:left;font-size:11.5px}
label{font-size:13px;color:var(--ink2);display:flex;align-items:center;gap:5px;
cursor:pointer}
.hits{font-size:12.5px;color:var(--mut);margin-left:auto;
font-variant-numeric:tabular-nums}
#tree{margin-top:12px;font-size:13.5px}
.ch{margin-left:15px;border-left:1px solid var(--line);padding-left:9px;
display:none}
.n.o>.ch{display:block}
.r{display:flex;align-items:center;gap:8px;padding:3px 6px;border-radius:6px;
cursor:pointer}
.r:hover{background:var(--card);outline:1px solid var(--line)}
.t{width:9px;height:9px;flex:none;position:relative}
.t:before{content:"";position:absolute;left:1px;top:0;
border:4px solid transparent;border-left-color:var(--mut)}
.n.o>.r>.t:before{transform:rotate(45deg);transform-origin:2px 4px}
.t.lf:before{display:none}
.nm{font-weight:560}
.k-region>.nm,.k-entity>.nm{color:var(--brand);font-weight:640}
.k-department>.nm,.k-centre>.nm,.k-office>.nm,.k-publication>.nm,
.k-division>.nm{color:var(--blue)}
.tt{color:var(--ink2);font-size:12.5px}
.ty{font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;
color:var(--mut);flex:none}
.c{font-size:10.5px;padding:1px 6px;border-radius:5px;white-space:nowrap}
.c-b{background:rgba(31,111,208,.13);color:var(--blue)}
.c-a{background:rgba(154,97,0,.15);color:var(--amber)}
.mt{margin-left:auto;color:var(--mut);font-size:12px;white-space:nowrap;
font-variant-numeric:tabular-nums}
.tm{color:var(--mut);font-size:11.5px;min-width:190px;text-align:right;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tm.own{color:var(--brand)}
.pl{margin:2px 0 6px}
.pg{display:flex;align-items:center;gap:8px;padding:2px 6px;font-size:12.5px;
border-radius:5px}
.pg:hover{background:var(--card)}
.d{width:5px;height:5px;border-radius:50%;background:var(--mut);flex:none}
.d.news{background:var(--brand)}.d.event{background:var(--blue)}
.d.blog{background:var(--amber)}
.pn{color:var(--ink2);min-width:150px}
code{font:12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;
padding:1px 5px;border-radius:4px;background:var(--card);
border:1px solid var(--line)}
code.o{color:var(--mut)}
code.w{color:var(--brand)}
.ar{color:var(--mut)}
.ac{margin-left:auto;font-size:10.5px;text-transform:uppercase;
letter-spacing:.4px;color:var(--mut);flex:none}
.ac.u{color:var(--amber)}
mark{background:var(--hl);color:inherit}
.hide{display:none!important}
footer{margin-top:34px;padding-top:14px;border-top:1px solid var(--line);
color:var(--mut);font-size:12.5px;max-width:96ch}
@media print{
  .bar{position:static}
  .ch{display:block!important}
  .r:hover{background:none;outline:0}
  header{background:none;color:var(--ink);border-bottom:2px solid var(--brand)}
}
</style></head><body>
<header><div class="wrap">
<h1>AKU &rarr; Storyblok &middot; the complete folder and page tree</h1>
<p class="sub">Every region, entity, department, centre, office and folder, and
under each one every page with the address it has today and the address it will
have. Children are listed in the order AKU&rsquo;s own menus use &mdash; about,
programmes, research, faculty, departments, then news, events and blogs &mdash;
then everything else A&ndash;Z.</p>
<div class="big">
<div><b>__PAGES__</b><span>pages</span></div>
<div><b>__FOLDERS__</b><span>folders</span></div>
<div><b>__REGIONS__</b><span>regions</span></div>
<div><b>__ENTITIES__</b><span>entities</span></div>
<div><b>__DEPTS__</b><span>departments</span></div>
</div>
</div></header>
<div class="wrap">

<h2>By region</h2>
<table><thead><tr><th>Region</th><th class="n">Entities</th>
<th class="n">Departments</th><th class="n">Folders</th><th class="n">Pages</th>
</tr></thead><tbody>__ROWS__</tbody></table>

<h2>What each kind means</h2>
<div class="legend">__LEGEND__</div>

<h2>What the tags mean</h2>
<div class="legend">
<div class="lg"><span class="c c-b">works in&hellip;</span>
<i>The countries this unit&rsquo;s <b>own page</b> says it operates in &mdash; which is
deliberately not the same as the folder it sits in. The Brain &amp; Mind Institute
lives under <b>global</b> because no one country owns it, and works in Kenya and
Pakistan. IED East Africa sits in <b>east-africa</b>, and its Development Projects
work in Kenya, Uganda and Tanzania. The tag is the evidence for the placement, and
it only appears where the answer <b>changes</b> from the folder above.</i></div>
<div class="lg"><span class="c c-b">shared</span>
<i>Content that belongs to a second entity as well as the one it is filed under.
It gets one home folder and a tag for the other, rather than being duplicated.
Hover to see which.</i></div>
<div class="lg"><span class="c c-a">archive?</span>
<i>The page names no recent edition &mdash; a conference last held in 2016, a magazine
whose newest issue is 2020. Carrying it forward would publish it as current.
Hover for what the page actually says.</i></div>
<div class="lg"><span class="c c-b">ran 2024</span>
<i>An event microsite, and the most recent edition its own page names.</i></div>
<div class="lg"><span class="tm own">MC EA</span>
<i>This folder sets its own permissions, and that is the team that administers it.</i></div>
<div class="lg"><span class="tm">inherits &middot; MC EA</span>
<i>This folder sets no permissions of its own; whoever administers the nearest
folder above it administers this one too.</i></div>
</div>

<div class="bar">
<input type="search" id="q" placeholder="Search a region, entity, folder, team, or any old or new slug&hellip;">
<button onclick="depth(2)">Regions</button>
<button onclick="depth(4)">Entities</button>
<button onclick="depth(6)">Departments</button>
<button onclick="all(1)" class="pri">Open all</button>
<button onclick="all(0)" class="pri">Collapse all</button>
<label><input type="checkbox" id="np" onchange="pgs()"> Folders only</label>
<label><input type="checkbox" id="he" onchange="empt()"> Hide empty folders</label>
<span class="hits" id="hits">__FOLDERS__ folders &middot; __PAGES__ pages</span>
</div>

<div id="tree">__TREE__</div>

<footer>Generated from AKU&rsquo;s own list of pages to migrate and the SharePoint
2016 permissions export, with every placement checked against the live site.
The team on the right is the team that administers that folder; where a folder
does not set its own permissions it says <b>inherits</b> and names the folder it
inherits from. Slugs are shown as paths only &mdash; the domain is added when the
destination is chosen.</footer>
</div>
<script>
var T=document.getElementById('tree'),Q=document.getElementById('q'),
    H=document.getElementById('hits'),HE=document.getElementById('he'),
    NP_OFF=document.getElementById('np'),
    NODES=[].slice.call(T.querySelectorAll('.n')),
    PAGES=[].slice.call(T.querySelectorAll('.pg')),
    NF=NODES.length,NP=PAGES.length;

function tg(el){el.parentNode.classList.toggle('o');count()}

function all(on){
  NODES.forEach(function(n){n.classList.toggle('o',!!on)});
  count();
}

/* Folders only. The tree is 628 folders and 3,306 pages; opening everything with
   the pages in makes it unreadable, which is the whole reason this exists. */
function pgs(){
  T.classList.toggle('np',NP_OFF.checked);
  count();
}

function depth(k){
  NODES.forEach(function(n){
    var d=0,p=n.parentNode;
    while(p&&p!==T){if(p.classList&&p.classList.contains('n'))d++;p=p.parentNode}
    n.classList.toggle('o',d<k);
  });
  count();
}

/* Hiding empties is independent of searching, so it is a class of its own
   rather than a second pass over the same one — otherwise clearing the search
   box would also clear the checkbox's effect. */
function empt(){
  var on=HE.checked;
  NODES.forEach(function(n){
    n.classList.toggle('hide-e',on&&n.classList.contains('x'));
  });
  count();
}

function count(){
  var f=0,p=0,o=0;
  NODES.forEach(function(n){
    if(hidden(n))return;
    f++;
    if(n.classList.contains('o'))o++;
  });
  if(!NP_OFF.checked)PAGES.forEach(function(n){if(!hidden(n))p++});
  H.innerHTML=f.toLocaleString()+' folders'
    +(NP_OFF.checked?'':' &middot; '+p.toLocaleString()+' pages')
    +(Q.value.trim()?' match':'')
    +' &middot; '+o.toLocaleString()+' open';
}
function hidden(n){
  var p=n;
  while(p&&p!==T){
    if(p.classList&&(p.classList.contains('hide')||p.classList.contains('hide-e')))
      return true;
    p=p.parentNode;
  }
  return false;
}

var timer=null;
Q.addEventListener('input',function(){
  clearTimeout(timer);timer=setTimeout(search,140);
});

function search(){
  var q=Q.value.trim().toLowerCase();
  if(!q){
    NODES.forEach(function(n){n.classList.remove('hide')});
    PAGES.forEach(function(n){n.classList.remove('hide')});
    depth(4);return;
  }
  /* A node survives if it matches, or if anything under it does — so the path
     down to a hit stays visible instead of the hit appearing at the root. */
  var keep=new Set();
  NODES.forEach(function(n){
    if(n.getAttribute('data-s').indexOf(q)>-1)mark(n,keep);
  });
  PAGES.forEach(function(n){
    var hit=n.getAttribute('data-s').indexOf(q)>-1;
    n.classList.toggle('hide',!hit);
    if(hit){var p=n.parentNode;while(p&&p!==T){
      if(p.classList&&p.classList.contains('n'))keep.add(p);p=p.parentNode}}
  });
  NODES.forEach(function(n){
    var on=keep.has(n);
    n.classList.toggle('hide',!on);
    n.classList.toggle('o',on);
  });
  count();
}
function mark(n,keep){
  keep.add(n);
  var p=n.parentNode;
  while(p&&p!==T){if(p.classList&&p.classList.contains('n'))keep.add(p);
    p=p.parentNode}
  /* everything beneath a matching folder stays, so clicking into it works */
  [].forEach.call(n.querySelectorAll('.n'),function(c){keep.add(c)});
  [].forEach.call(n.querySelectorAll('.pg'),function(c){c.classList.remove('hide')});
}

var st=document.createElement('style');
st.textContent='.hide-e{display:none!important}';
document.head.appendChild(st);

depth(4);count();
</script></body></html>"""

HTML = (HTML.replace('__TREE__', ''.join(out))
            .replace('__ROWS__', ''.join(rows))
            .replace('__LEGEND__', legend)
            .replace('__PAGES__', format(TOTAL_PAGES, ','))
            .replace('__FOLDERS__', format(len(F), ','))
            .replace('__REGIONS__', str(kind_counts.get('region', 0)))
            .replace('__ENTITIES__', str(kind_counts.get('entity', 0)))
            .replace('__DEPTS__', str(kind_counts.get('department', 0))))

io.open(OUT, 'w', encoding='utf-8').write(HTML)
print('wrote %s  %.1f MB' % (os.path.basename(OUT), os.path.getsize(OUT) / 1e6))
print('  %s folders  %s pages  %d regions  %d entities  %d departments'
      % (format(len(F), ','), format(TOTAL_PAGES, ','),
         kind_counts.get('region', 0), kind_counts.get('entity', 0),
         kind_counts.get('department', 0)))
print('  kinds:', dict(kind_counts))
