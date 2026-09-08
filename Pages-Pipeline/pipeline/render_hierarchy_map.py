"""render_hierarchy_map.py -- the old-to-new folder map as one HTML file.

Two views of the same 1,288 rows, because two different questions get asked:

  MAP   one row per folder, old address beside new, filterable. This is the
        checking view -- "what happens to regions/pk/entities/mc/departments/fm"
        is a line you find by typing `fm` into the box.
  TREE  the new hierarchy, nested, collapsible. This is the reading view --
        what the space will look like when the map has been applied.

Self-contained on purpose: the JSON is embedded, the CSS and JS are inline, and
nothing is fetched. `git clone`, double-click, it works -- which is the rule for
every portal in this repo, and the one that `blogs-portal.html` broke by
pointing at a gitignored folder and showing 181 broken images to everyone but
the machine that built it.

Input    out/AKU-Hierarchy-Map.json   (build_hierarchy_map.py writes it)
Output   out/AKU-Hierarchy-Map.html
"""
import html
import json

import paths

OUT = 'AKU-Hierarchy-Map.html'

# What each action means, in the words someone applying the map needs. Shown as
# a legend, so nobody has to read the builder to find out what `adopt` is.
ACTIONS = [
    ('keep', 'exists and stays where it is', 'nothing to do'),
    ('create', 'the new tree needs it', 'the backend creates it'),
    ('skip', 'in the new tree but empty', 'do not create it'),
    ('rename', 'same folder, new slug', 'stories move with it'),
    ('adopt', 'exists in Storyblok, not in the DB', 'write its id down'),
    ('ignore', 'named by no plan', 'left alone'),
]

CSS = """
:root{
  --bg:#fbfaf8; --card:#fff; --ink:#1b1a18; --ink2:#5c5852; --line:#e5e1da;
  --keep:#7a8b6f; --create:#3f6ea8; --skip:#9a9691; --rename:#b06a2c;
  --adopt:#7a5fa8; --ignore:#b3aea6;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1500px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:23px;margin:0 0 4px;font-weight:640;letter-spacing:-.01em}
.sub{color:var(--ink2);margin:0 0 22px;max-width:78ch}
.sub b{color:var(--ink);font-weight:600}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}

.tiles{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 18px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:9px;
  padding:9px 13px;cursor:pointer;text-align:left;font:inherit;color:inherit;
  min-width:118px}
.tile:hover{border-color:#c9c3b8}
.tile[aria-pressed=true]{border-color:var(--ink);box-shadow:0 0 0 1px var(--ink)}
.tile .n{font-size:20px;font-weight:660;display:block;line-height:1.15}
.tile .l{font-size:11.5px;color:var(--ink2);text-transform:uppercase;
  letter-spacing:.06em}
.tile .w{font-size:11px;color:var(--ink2);display:block;margin-top:3px}

.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 14px}
input[type=search]{flex:1 1 320px;padding:9px 12px;border:1px solid var(--line);
  border-radius:8px;background:var(--card);font:inherit;color:inherit}
select{padding:9px 10px;border:1px solid var(--line);border-radius:8px;
  background:var(--card);font:inherit;color:inherit}
.count{color:var(--ink2);font-size:13px}
.tabs{display:flex;gap:4px;background:#f1eee8;border-radius:8px;padding:3px}
.tabs button{border:0;background:none;font:inherit;padding:6px 14px;
  border-radius:6px;cursor:pointer;color:var(--ink2)}
.tabs button[aria-selected=true]{background:var(--card);color:var(--ink);
  box-shadow:0 1px 2px rgba(0,0,0,.06);font-weight:600}

.scroll{overflow-x:auto;background:var(--card);border:1px solid var(--line);
  border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13px}
th{position:sticky;top:0;background:#f7f5f1;text-align:left;font-size:11px;
  text-transform:uppercase;letter-spacing:.05em;color:var(--ink2);
  padding:9px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:7px 10px;border-bottom:1px solid #f1eeea;vertical-align:top}
tr:last-child td{border-bottom:0}
tr:hover td{background:#fcfbf8}
td.p{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:12px;word-break:break-all;max-width:34ch}
td.arrow{color:var(--ink2);text-align:center;width:22px}
td.num{text-align:right;font-variant-numeric:tabular-nums;width:60px}
td.rk{color:var(--ink2);font-size:12px;max-width:40ch}
.dim{color:var(--ink2)}
.pill{display:inline-block;padding:1px 8px;border-radius:20px;font-size:11px;
  font-weight:640;color:#fff;white-space:nowrap}
.a-keep{background:var(--keep)} .a-create{background:var(--create)}
.a-skip{background:var(--skip)} .a-rename{background:var(--rename)}
.a-adopt{background:var(--adopt)} .a-ignore{background:var(--ignore)}
.lv{font-size:11px;color:var(--ink2);text-transform:uppercase;
  letter-spacing:.04em}

.legend{display:flex;flex-wrap:wrap;gap:14px;margin:14px 0 0;font-size:12px;
  color:var(--ink2)}
.legend div{display:flex;gap:6px;align-items:baseline}

#tree{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:14px 16px}
details{margin:1px 0}
summary{cursor:pointer;padding:3px 4px;border-radius:6px;list-style:none;
  display:flex;gap:8px;align-items:baseline}
summary::-webkit-details-marker{display:none}
summary:hover{background:#f7f5f1}
summary .tw{color:var(--ink2);width:11px;display:inline-block;font-size:10px}
details>summary .tw::before{content:"▸"}
details[open]>summary .tw::before{content:"▾"}
.nm{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:12.5px}
.ti{color:var(--ink2);font-size:12px}
.kid{margin-left:17px;border-left:1px solid #eeeae3;padding-left:9px}
.leafrow{padding:3px 4px 3px 23px;display:flex;gap:8px;align-items:baseline}
.cnt{font-size:11px;color:var(--ink2);font-variant-numeric:tabular-nums}
"""

JS = """
const NODES = [];
(function flat(list, depth){
  for (const n of list){ n._d = depth; NODES.push(n); flat(n.children || [], depth+1); }
})(DATA.tree, 0);

const $ = s => document.querySelector(s);
const state = { action: null, level: '', q: '', view: 'map' };
const esc = s => (s == null ? '' : String(s));

function match(n){
  if (state.action && n.action !== state.action) return false;
  if (state.level && n.level !== state.level) return false;
  if (state.q){
    const q = state.q.toLowerCase();
    const hay = [n.to_path, n.from_path, n.to_title, n.from_title, n.remark,
                 n.pages_plan_path].map(esc).join(' ').toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

function renderMap(){
  const rows = NODES.filter(match);
  $('#count').textContent = rows.length.toLocaleString() + ' of ' +
    NODES.length.toLocaleString() + ' folders';
  const out = [];
  for (const n of rows){
    const from = n.from_path
      ? '<span class="mono">' + esc(n.from_path) + '</span>'
      : '<span class="dim">— new —</span>';
    const src = esc(n.from_source || 'pages-plan').replace('backend.', '');
    out.push('<tr><td class="p">' + from + '<br><span class="dim">' + src +
      (n.from_title ? ' · ' + esc(n.from_title) : '') + '</span></td>' +
      '<td class="arrow">&rarr;</td>' +
      '<td class="p"><span class="mono">' + esc(n.to_path) + '</span><br>' +
      '<span class="dim">' + esc(n.to_title || '') + '</span></td>' +
      '<td><span class="pill a-' + n.action + '">' + n.action + '</span></td>' +
      '<td class="lv">' + esc(n.level) + '</td>' +
      '<td class="num">' + (n.stories || '') + '</td>' +
      '<td class="num">' + (n.pages_subtree || '') + '</td>' +
      '<td class="rk">' + esc(n.remark) + '</td></tr>');
  }
  $('#rows').innerHTML = out.join('') ||
    '<tr><td colspan="8" class="dim" style="padding:22px">nothing matches</td></tr>';
}

function treeHtml(n){
  const kids = n.children || [];
  const pill = '<span class="pill a-' + n.action + '">' + n.action + '</span>';
  const cnt = [];
  if (n.stories) cnt.push(n.stories.toLocaleString() + ' stories');
  if (n.pages_subtree) cnt.push(n.pages_subtree.toLocaleString() + ' pages');
  const label = '<span class="tw"></span><span class="nm">' +
    esc(n.to_path.split('/').pop()) + '</span>' + pill +
    '<span class="ti">' + esc(n.to_title || '') + '</span>' +
    '<span class="cnt">' + cnt.join(' · ') + '</span>';
  if (!kids.length) return '<div class="leafrow">' + label + '</div>';
  return '<details' + (n._d < 1 ? ' open' : '') + '><summary>' + label +
    '</summary><div class="kid">' + kids.map(treeHtml).join('') +
    '</div></details>';
}

function renderTree(){
  $('#tree').innerHTML = DATA.tree.map(treeHtml).join('');
}

document.querySelectorAll('.tile').forEach(b => b.onclick = () => {
  const a = b.dataset.action || null;
  state.action = (state.action === a) ? null : a;
  document.querySelectorAll('.tile').forEach(x =>
    x.setAttribute('aria-pressed', String(x.dataset.action === state.action)));
  renderMap();
});
$('#q').oninput = e => { state.q = e.target.value.trim(); renderMap(); };
$('#lv').onchange = e => { state.level = e.target.value; renderMap(); };
document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => {
  state.view = b.dataset.view;
  document.querySelectorAll('.tabs button').forEach(x =>
    x.setAttribute('aria-selected', String(x.dataset.view === state.view)));
  $('#mapview').hidden = state.view !== 'map';
  $('#treeview').hidden = state.view !== 'tree';
  if (state.view === 'tree' && !$('#tree').innerHTML) renderTree();
});
renderMap();
"""


def main():
    doc = json.load(open(paths.out('AKU-Hierarchy-Map.json'), encoding='utf-8'))
    meta, e = doc['meta'], html.escape

    counts = meta['by_action']
    tiles = ['<button class="tile" aria-pressed="false" data-action="%s">'
             '<span class="n">%s</span><span class="l">%s</span>'
             '<span class="w">%s</span></button>'
             % (name, '{:,}'.format(counts.get(name, 0)), name, e(does))
             for name, _, does in ACTIONS]

    levels = ''.join('<option value="%s">%s (%d)</option>' % (k, k, v)
                     for k, v in meta['by_level'].items())

    legend = ''.join('<div><span class="pill a-%s">%s</span> %s</div>'
                     % (name, name, e(means)) for name, means, _ in ACTIONS)

    page = f"""<title>AKU folder map — old to new</title>
<style>{CSS}</style>
<div class="wrap">
<h1>AKU folder map — old &rarr; new</h1>
<p class="sub">Every folder in the space today and every folder the pages
migration needs, joined into <b>{meta['nodes']:,} rows</b>. Addresses are
<b>short codes</b>, as the space is named
(<span class="mono">regions/pk/entities/mc</span>); the front end expands them
for the public URL. Region, entity and department folders are created by the
backend, which seeds <span class="mono">news</span>,
<span class="mono">blogs</span> and <span class="mono">events</span> inside each
one. <b>{meta['stories_moved']}</b> stories move, all of them in three renamed
departments; <b>4,591</b> pages are placed. Nothing is deleted.</p>

<div class="tiles">{''.join(tiles)}</div>

<div class="bar">
  <div class="tabs">
    <button data-view="map" aria-selected="true">Map</button>
    <button data-view="tree" aria-selected="false">Hierarchy</button>
  </div>
  <input type="search" id="q" placeholder="filter — path, title or reason (try: fam-med, global2, pathology)">
  <select id="lv"><option value="">every level</option>{levels}</select>
  <span class="count" id="count"></span>
</div>

<div id="mapview">
  <div class="scroll"><table>
    <thead><tr><th>from — where it is now</th><th></th><th>to — where it goes</th>
    <th>action</th><th>level</th><th>stories</th><th>pages</th><th>why</th></tr></thead>
    <tbody id="rows"></tbody>
  </table></div>
  <div class="legend">{legend}</div>
</div>

<div id="treeview" hidden><div id="tree"></div></div>
</div>
<script>const DATA = {json.dumps(doc, ensure_ascii=False)};</script>
<script>{JS}</script>
"""
    with open(paths.out(OUT), 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(page)
    print('out/%s   %.2f MB' % (OUT, len(page.encode('utf-8')) / 1e6))
    print('  %d rows · %s' % (meta['nodes'],
                              ', '.join('%s %d' % (k, v)
                                        for k, v in counts.items())))


if __name__ == '__main__':
    main()
