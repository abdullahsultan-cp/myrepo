"""Render plan.json as three filterable tables. Tables, not prose.

Folders  where each folder goes, and which team manages it
Pages    every page's current URL and its destination path
Roles    the Storyblok roles to create, and who belongs in each
"""
import collections
import html
import json
import os

import paths

OUT = paths.out('AKU-Migration-Plan.html')
plan = json.load(open(paths.work('plan.json'), encoding='utf-8'))
F, P, R = plan['folders'], plan['pages'], plan['roles']
L = plan['live']
e = html.escape

CONF = {'witnessed': ('ok', '✓'), 'inferred': ('inf', '~'), 'decide': ('dec', '!')}

def badge(c):
    cls, mark = CONF.get(c, ('inf', '~'))
    return '<span class="b %s">%s %s</span>' % (cls, mark, c)

# ---- folders: indent the path so a table still reads as a tree -----------
# Path order alone puts `staging` first, which is the least useful thing to see;
# lead with global, then the regions, and leave the discard pile last.
TOP_RANK = {'global': 0, 'regions': 1, 'staging': 2}

def folder_key(r):
    p = r['new_path'].split('/')
    return (TOP_RANK.get(p[0], 1), r['new_path'])

frows = []
for r in sorted(F, key=folder_key):
    lvl = int(r['level'])
    name = r['new_path'].split('/')[-1]
    ind = (lvl - 1) * 14
    central = 'central' if 'central' in r['managed_by'] else ''
    frows.append(
        '<tr data-s="%s"><td class="p"><span style="padding-left:%dpx">'
        '<i class="k %s"></i><b>%s</b></span><span class="full">%s</span></td>'
        '<td>%s</td><td class="num">%s</td><td class="num">%s</td>'
        '<td class="%s">%s</td><td class="mono sm">%s</td><td>%s</td></tr>'
        % (e((r['new_path'] + ' ' + r['title'] + ' ' + r['managed_by'] + ' ' +
              r['source_web'] + ' ' + r['kind'] + ' ' + r['region']).lower()),
           ind, e(r['kind']), e(name), e(r['new_path']),
           e(r['kind']), r['pages_here'] or '', r['pages_subtree'] or '',
           central, e(r['managed_by']), e(r['source_web']), badge(r['confidence'])))

prows = []
for r in P:
    prows.append(
        '<tr data-s="%s"><td class="mono sm"><a href="%s" target="_blank" '
        'rel="noopener">%s</a></td><td class="mono sm p">%s</td>'
        '<td class="%s">%s</td><td class="mono sm">%s</td>'
        '<td class="%s">%s</td><td>%s</td></tr>'
        % (e((r['current_url'] + ' ' + r['new_path'] + ' ' + r['managed_by'] + ' ' +
              r['region'] + ' ' + r['entity'] + ' ' + r['department'] + ' ' +
              r['action']).lower()),
           e(r['current_url']), e(r['current_url'].replace('https://www.aku.edu', '')),
           e(r['new_path']),
           'upd' if r['action'] == 'Update and move' else 'asis', e(r['action']),
           e(r['managed_by']),
           'coll' if r['do_not_migrate'] else '',
           e(r['do_not_migrate'] or (r['countries'] and 'tag: ' + r['countries']) or '—'),
           badge(r['confidence'])))

rrows = []
for r in R:
    rrows.append(
        '<tr data-s="%s"><td class="mono"><b>%s</b></td><td class="cap %s">%s</td>'
        '<td class="num">%s</td><td>%s</td><td class="num">%s</td>'
        '<td class="mono sm">%s</td><td class="sm">%s</td></tr>'
        % (e((r['storyblok_role'] + ' ' + r['unit'] + ' ' + r['capability'] + ' ' +
              r['source_sharepoint_groups']).lower()),
           e(r['storyblok_role']), e(r['capability']), e(r['capability']),
           r['members'] or '', e(r['unit']), r['folders_scoped'] or '',
           e(r['source_sharepoint_groups']), e(r['allowed_paths'] or r['note'])))

lrows = ''.join(
    '<tr data-s="%s"><td class="mono sm"><a href="%s" target="_blank" '
    'rel="noopener">%s</a></td><td class="sm">%s</td><td class="sm">%s</td></tr>'
    % (e((x['page_checked'] + ' ' + x['what_it_settles']).lower()),
       e(x['page_checked']),
       e(x['page_checked'].replace('https://www.aku.edu/', '')),
       e(x['what_aku_shows']), e(x['what_it_settles']))
    for x in L)

kinds = collections.Counter(r['kind'] for r in F)
caps = collections.Counter(r['capability'] for r in R)
coll = sum(1 for r in P if r['collision'])
named = sum(1 for r in P if 'central' not in r['managed_by'])

CSS = """
*{box-sizing:border-box}
:root{--plane:#f9f9f7;--card:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--mut:#898781;
--grid:#e1e0d9;--ring:rgba(11,11,11,.10);--brand:#00594f;--brand2:#0b7f6f;
--ok:#0ca30c;--inf:#fab219;--dec:#d03b3b;--ser:#2a78d6;color-scheme:light}
@media(prefers-color-scheme:dark){:root{--plane:#0d0d0d;--card:#1a1a19;--ink:#fff;
--ink2:#c3c2b7;--mut:#898781;--grid:#2c2c2a;--ring:rgba(255,255,255,.10);
--brand:#0b7f6f;--brand2:#12a08c;--ser:#3987e5;color-scheme:dark}}
body{margin:0;background:var(--plane);color:var(--ink);
font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.sm{font-size:12px}
header{background:var(--brand);color:#fff;padding:20px 22px}
h1{margin:0 0 4px;font-size:19px;font-weight:640}
header p{margin:0;font-size:13px;color:rgba(255,255,255,.85)}
.bar{position:sticky;top:0;z-index:10;background:var(--plane);
border-bottom:1px solid var(--grid);padding:11px 22px;display:flex;gap:8px;
align-items:center;flex-wrap:wrap}
.tabs{display:flex;gap:3px;background:var(--grid);border-radius:9px;padding:3px}
.tab{border:0;background:transparent;padding:7px 13px;border-radius:7px;
cursor:pointer;font-size:13px;color:var(--ink2);font-weight:550}
.tab.on{background:var(--card);color:var(--brand2)}
#q{flex:1;min-width:200px;padding:9px 12px;border:1px solid var(--ring);
border-radius:8px;font-size:13px;background:var(--card);color:var(--ink)}
select{padding:9px 10px;border:1px solid var(--ring);border-radius:8px;
background:var(--card);color:var(--ink);font-size:13px}
#n{font-size:12px;color:var(--mut);min-width:150px}
.wrap{padding:0 22px 60px}
.pane{display:none}.pane.on{display:block}
.hint{font-size:12.5px;color:var(--ink2);margin:14px 0 10px}
.hint code{background:var(--card);border:1px solid var(--grid);padding:1px 5px;
border-radius:4px;font-size:11.5px}
table{width:100%;border-collapse:collapse;background:var(--card);
border:1px solid var(--ring);border-radius:10px;overflow:hidden}
.tw{max-height:calc(100vh - 250px);overflow:auto;border:1px solid var(--ring);
border-radius:10px;background:var(--card)}
table{border:0!important;border-radius:0}
th{position:sticky;top:0;background:var(--plane);text-align:left;
padding:9px 11px;font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;
color:var(--mut);border-bottom:1px solid var(--grid);white-space:nowrap;z-index:5}
td{padding:7px 11px;border-bottom:1px solid var(--grid);vertical-align:top}
tr:hover td{background:var(--plane)}
td.num{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2)}
td.p b{font-weight:600}
td.p .full{display:block;font-size:10.5px;color:var(--mut);
font-family:ui-monospace,Menlo,Consolas,monospace;margin-top:2px}
a{color:var(--ser);text-decoration:none}a:hover{text-decoration:underline}
i.k{display:inline-block;width:7px;height:7px;border-radius:2px;margin-right:7px;
background:var(--grid);vertical-align:middle}
i.k.region{background:var(--brand)}i.k.entity{background:var(--ser)}
i.k.department{background:var(--brand2)}i.k.container{background:var(--mut)}
i.k.division{background:var(--inf)}
.b{font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;white-space:nowrap}
.b.ok{background:rgba(12,163,12,.13);color:var(--ok)}
.b.inf{background:rgba(250,178,25,.16);color:#8a6000}
.b.dec{background:rgba(208,59,59,.13);color:var(--dec)}
@media(prefers-color-scheme:dark){.b.inf{color:var(--inf)}}
td.central{color:var(--mut)}
td.upd{color:#8a6000}
@media(prefers-color-scheme:dark){td.upd{color:var(--inf)}}
td.coll{color:var(--dec)}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:11.5px;color:var(--mut);
margin:10px 0 12px}
.legend span{display:flex;align-items:center;gap:5px}
"""

JS = """
const q=document.getElementById('q'),sel=document.getElementById('kind'),
      n=document.getElementById('n');
const panes=[...document.querySelectorAll('.pane')];
function active(){return panes.find(p=>p.classList.contains('on'));}
function filter(){
  const t=q.value.trim().toLowerCase(), k=sel.value;
  const p=active(), rows=[...p.querySelectorAll('tbody tr')];
  let v=0;
  rows.forEach(r=>{
    const s=r.dataset.s;
    const ok=(!t||s.includes(t))&&(!k||s.includes(k));
    r.style.display=ok?'':'none';
    if(ok)v++;
  });
  n.textContent=v.toLocaleString()+' of '+rows.length.toLocaleString()+' rows';
}
let tm;q.addEventListener('input',()=>{clearTimeout(tm);tm=setTimeout(filter,120);});
sel.addEventListener('change',filter);
document.querySelectorAll('.tab').forEach(b=>{
  b.onclick=()=>{
    document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===b));
    panes.forEach(p=>p.classList.toggle('on',p.id===b.dataset.p));
    filter();
  };
});
filter();
"""

doc = ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
       '<meta name="viewport" content="width=device-width,initial-scale=1">'
       '<title>AKU migration plan — folders, pages, roles</title>'
       '<style>' + CSS + '</style></head><body>'
       '<header><h1>AKU → Storyblok migration plan</h1>'
       '<p>' + f'{len(F):,}' + ' folders · ' + f'{len(P):,}'
       + ' pages · ' + str(len(R)) + ' roles to create · '
       + f'{named:,}' + ' of ' + f'{len(P):,}'
       + ' pages have a named managing team · '
       + str(sum(1 for r in P if r['do_not_migrate']))
       + ' pages dropped after checking the live site</p></header>'
       '<div class="bar"><div class="tabs">'
       '<button class="tab on" data-p="folders">Folders</button>'
       '<button class="tab" data-p="pages">Pages</button>'
       '<button class="tab" data-p="roles">Roles</button>'
       '<button class="tab" data-p="live">Live checks</button></div>'
       '<input id="q" type="search" placeholder="Filter — path, team, region, entity, URL…">'
       '<select id="kind"><option value="">All</option>'
       '<option value="pakistan">Pakistan</option><option value="kenya">Kenya</option>'
       '<option value="tanzania">Tanzania</option><option value="uganda">Uganda</option>'
       '<option value="united-kingdom">United Kingdom</option>'
       '<option value="global">Global</option>'
       '<option value="department">Departments only</option>'
       '<option value="entity">Entities only</option>'
       '<option value="update and move">Needs updating</option>'
       '<option value="publisher">Publishers</option>'
       '<option value="editor">Editors</option></select>'
       '<span id="n"></span></div>'
       '<div class="wrap">'

       '<div class="pane on" id="folders">'
       '<p class="hint">Every destination folder, in path order and indented by '
       'depth. <b>Manages</b> is the AKU team that administers it today, taken '
       'from the folder\'s own SharePoint group; <code>central</code> means it '
       'falls back to Public Affairs because the folder names no owner of its own.'
       '</p><div class="legend">'
       '<span><i class="k region"></i>region</span><span><i class="k entity"></i>entity</span>'
       '<span><i class="k department"></i>department</span>'
       '<span><i class="k division"></i>division</span>'
       '<span><i class="k container"></i>created, no source folder</span>'
       '<span><i class="k"></i>folder</span></div>'
       '<div class="tw"><table><thead><tr><th>Destination folder</th><th>Kind</th>'
       '<th>Pages</th><th>Subtree</th><th>Manages</th><th>From (SharePoint)</th>'
       '<th>Evidence</th></tr></thead><tbody>' + ''.join(frows)
       + '</tbody></table></div></div>'

       '<div class="pane" id="pages">'
       '<p class="hint">All ' + f'{len(P):,}' + ' pages from '
       '<code>aku-university-visible-pages.csv</code>. Click a URL to open the '
       'live page and check the destination is right.</p>'
       '<div class="tw"><table><thead><tr><th>Today on aku.edu</th><th>Destination path</th>'
       '<th>Action</th><th>Manages</th><th>Conflict</th><th>Evidence</th></tr>'
       '</thead><tbody>' + ''.join(prows) + '</tbody></table></div></div>'

       '<div class="pane" id="roles">'
       '<p class="hint">One role per AKU team per capability, mirroring the '
       'CW/CA split they already use: a <b>publisher</b> may publish, an '
       '<b>editor</b> may only save a draft. <b>Scope</b> is how many folders the '
       'role is limited to — a role scoped to 0 folders owns a section that '
       'inherits the site-wide roster, so its scope has to be set by hand.</p>'
       '<div class="tw"><table><thead><tr><th>Storyblok role</th><th>Capability</th>'
       '<th>People</th><th>AKU team</th><th>Scope</th>'
       '<th>From (SharePoint groups)</th><th>Allowed paths</th></tr></thead>'
       '<tbody>' + ''.join(rrows) + '</tbody></table></div></div>'

       '<div class="pane" id="live">'
       '<p class="hint">Where the two exports disagreed or said nothing, I opened '
       'the page on aku.edu and read the breadcrumb AKU itself renders — that '
       'breadcrumb <i>is</i> the canonical parent, because the site is stating '
       'where it thinks the page lives. These ' + str(len(L)) + ' checks settled '
       'the cross-entity question and both slug clashes.</p>'
       '<div class="tw"><table><thead><tr><th>Page opened</th>'
       '<th>What AKU shows</th><th>What it settles</th></tr></thead><tbody>'
       + lrows + '</tbody></table></div></div>'

       '</div><script>' + JS + '</script></body></html>\n')

open(OUT, 'w', encoding='utf-8').write(doc)
print('%s — %.0f KB' % (os.path.basename(OUT), len(doc.encode('utf-8')) / 1024))
print('folder kinds:', dict(kinds))
print('role capabilities:', dict(caps))
