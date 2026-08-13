#!/usr/bin/env python3
"""
sb_portal.py — build assets-portal.html for a backup. Imported, never run.

One self-contained HTML file per backup repo, showing the asset folder tree as it
exists in Storyblok, what is in each folder, where every file landed in the
bucket, and its checksum. Same idea as Blogs-Pipeline/out/blogs-portal.html: the
artefact a person actually opens, rather than a JSON tree nobody reads.

It answers the question the manifests answer, but visually: is the structure what
I expect, and is every file actually stored?

No external requests are needed to read the structure. Thumbnails, where shown,
point at Storyblok's public asset URLs -- useful while the space is alive, and
they simply fail to load once it is gone, which is honest: this is a map of the
backup, not a copy of the images.
"""

import html
import json
import os

# Deliberately not an f-string or .format() template: the CSS and JS are full of
# braces, and escaping every one of them is how a template like this rots.
_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --ground:#f5f7f8; --surface:#fff; --surface2:#eaeff1; --ink:#16232a;
  --ink2:#4a5a62; --ink3:#71838b; --rule:#d5dde0; --accent:#0e5c6e;
  --accentSoft:#dbeaed; --good:#2c6350; --warn:#a65e11; --warnSoft:#f6e8d6;
  --mono:ui-monospace,"SF Mono","Cascadia Mono",Consolas,monospace;
  --sans:"Helvetica Neue",Helvetica,"Segoe UI",Arial,sans-serif;
}
@media (prefers-color-scheme:dark){:root{
  --ground:#10171b; --surface:#161f24; --surface2:#1e292f; --ink:#e6edef;
  --ink2:#a7b7bd; --ink3:#7e9098; --rule:#2a373e; --accent:#63bace;
  --accentSoft:#16323a; --good:#6fbf9c; --warn:#d99a4e; --warnSoft:#33261a;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font:14px/1.5 var(--sans)}
header{padding:22px 26px;border-bottom:1px solid var(--rule);background:var(--surface)}
h1{margin:0 0 4px;font-size:19px;letter-spacing:-.02em}
.sub{color:var(--ink3);font-size:12.5px}
.stats{display:flex;flex-wrap:wrap;gap:6px 26px;margin-top:14px}
.stat b{display:block;font-size:10px;text-transform:uppercase;letter-spacing:.09em;color:var(--ink3);font-weight:700}
.stat span{font:600 17px/1.2 var(--mono);font-variant-numeric:tabular-nums}
.where{margin-top:14px;padding:9px 12px;background:var(--accentSoft);border-radius:4px;
  font:12px/1.45 var(--mono);word-break:break-all}
.warn{background:var(--warnSoft);color:var(--warn);font-weight:600;font-family:var(--sans)}
main{display:grid;grid-template-columns:320px 1fr;min-height:calc(100vh - 150px)}
@media (max-width:900px){main{grid-template-columns:1fr}}
#tree{border-right:1px solid var(--rule);padding:14px 10px;overflow:auto;background:var(--surface)}
#tree ul{list-style:none;margin:0;padding-left:14px}
#tree>ul{padding-left:0}
.node{display:flex;align-items:center;gap:6px;padding:3px 6px;border-radius:4px;cursor:pointer;
  font-size:13px;white-space:nowrap}
.node:hover{background:var(--surface2)}
.node.sel{background:var(--accent);color:#fff}
.node.sel .n{color:#fff}
.tw{width:12px;color:var(--ink3);font-size:10px;flex:none}
.node .n{flex:none;color:var(--ink3);font:11px/1 var(--mono);margin-left:auto;padding-left:10px}
.pane{padding:16px 20px;overflow:auto}
.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
input[type=search]{flex:1;min-width:200px;padding:7px 10px;border:1px solid var(--rule);
  border-radius:4px;background:var(--surface);color:var(--ink);font:13px var(--sans)}
label.chk{font-size:12.5px;color:var(--ink2);display:flex;align-items:center;gap:5px;cursor:pointer}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--ink3);
  padding:6px 8px;border-bottom:1px solid var(--rule);position:sticky;top:0;background:var(--ground)}
td{padding:6px 8px;border-bottom:1px solid var(--rule);vertical-align:middle}
td.num{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums;white-space:nowrap}
td.mono{font-family:var(--mono);font-size:11.5px;word-break:break-all}
tr:hover td{background:var(--surface2)}
.thumb{width:40px;height:40px;object-fit:cover;border-radius:3px;background:var(--surface2);flex:none}
.ph{width:40px;height:40px;border-radius:3px;background:var(--surface2);display:flex;
  align-items:center;justify-content:center;font:9px var(--mono);color:var(--ink3)}
.pill{display:inline-block;padding:1px 6px;border-radius:3px;font:600 10px var(--sans);
  letter-spacing:.04em;text-transform:uppercase}
.pill.y{background:var(--accentSoft);color:var(--accent)}
.pill.n{background:var(--warnSoft);color:var(--warn)}
.empty{padding:30px;color:var(--ink3);text-align:center}
.crumb{font:12px var(--mono);color:var(--ink3);margin-bottom:10px;word-break:break-all}
footer{padding:14px 26px;border-top:1px solid var(--rule);color:var(--ink3);font-size:11.5px}
</style></head><body>
<header>
  <h1>__H1__</h1>
  <div class="sub">__SUB__</div>
  <div class="stats">__STATS__</div>
  <div class="where">__WHERE__</div>
</header>
<main>
  <div id="tree"></div>
  <div class="pane">
    <div class="bar">
      <input type="search" id="q" placeholder="Filter by filename, folder, type or id…">
      <label class="chk"><input type="checkbox" id="sub" checked> include subfolders</label>
      <label class="chk"><input type="checkbox" id="miss"> only missing from storage</label>
      <label class="chk"><input type="checkbox" id="thumbs"> thumbnails</label>
    </div>
    <div class="crumb" id="crumb"></div>
    <div id="out"></div>
  </div>
</main>
<footer>__FOOT__</footer>
<script>
const D = __DATA__;
const folders = D.folders, assets = D.assets;
const kids = {}; folders.forEach(f => (kids[f.parent] = kids[f.parent] || []).push(f));
Object.values(kids).forEach(a => a.sort((x, y) => x.name.localeCompare(y.name)));
const byId = {}; folders.forEach(f => byId[f.id] = f);
let sel = "*", open = new Set(["*"]);

function descendants(id){
  const out = new Set([id]);
  (function walk(i){ (kids[i] || []).forEach(c => { out.add(c.id); walk(c.id); }); })(id);
  return out;
}
function fmt(b){
  if (b === null || b === undefined || b === "") return "—";
  b = +b; if (!b) return "0";
  const u = ["B","KB","MB","GB"]; let i = 0;
  while (b >= 1024 && i < u.length - 1){ b /= 1024; i++; }
  return b.toFixed(i ? 1 : 0) + " " + u[i];
}
function count(id){
  const set = descendants(id);
  let n = 0, sz = 0;
  assets.forEach(a => { if (set.has(a.folder)){ n++; sz += (+a.bytes || 0); } });
  return [n, sz];
}
function drawTree(){
  const root = document.createElement("ul");
  const all = document.createElement("li");
  const [an, asz] = [assets.length, assets.reduce((s,a)=>s+(+a.bytes||0),0)];
  all.appendChild(nodeEl({id:"*", name:"All assets"}, an, asz, false));
  root.appendChild(all);
  const build = (parent, ul) => {
    (kids[parent] || []).forEach(f => {
      const li = document.createElement("li");
      const [n, sz] = count(f.id);
      const hasKids = (kids[f.id] || []).length > 0;
      li.appendChild(nodeEl(f, n, sz, hasKids));
      if (hasKids && open.has(f.id)){ const sub = document.createElement("ul"); build(f.id, sub); li.appendChild(sub); }
      ul.appendChild(li);
    });
  };
  const top = document.createElement("ul"); build(0, top);
  all.appendChild(top);
  const t = document.getElementById("tree"); t.innerHTML = ""; t.appendChild(root);
}
function nodeEl(f, n, sz, hasKids){
  const d = document.createElement("div");
  d.className = "node" + (sel === f.id ? " sel" : "");
  const tw = document.createElement("span"); tw.className = "tw";
  tw.textContent = hasKids ? (open.has(f.id) ? "▾" : "▸") : "";
  if (hasKids) tw.onclick = e => { e.stopPropagation(); open.has(f.id) ? open.delete(f.id) : open.add(f.id); drawTree(); };
  const nm = document.createElement("span"); nm.textContent = f.name;
  const ct = document.createElement("span"); ct.className = "n"; ct.textContent = n + " · " + fmt(sz);
  d.append(tw, nm, ct);
  d.onclick = () => { sel = f.id; drawTree(); draw(); };
  return d;
}
function draw(){
  const q = document.getElementById("q").value.toLowerCase().trim();
  const withSub = document.getElementById("sub").checked;
  const onlyMissing = document.getElementById("miss").checked;
  const thumbs = document.getElementById("thumbs").checked;
  const set = sel === "*" ? null : (withSub ? descendants(sel) : new Set([sel]));
  let rows = assets.filter(a => {
    if (set && !set.has(a.folder)) return false;
    if (onlyMissing && a.stored) return false;
    if (!q) return true;
    return (a.name + " " + (a.path||"") + " " + (a.type||"") + " " + a.id + " " + (byId[a.folder]?.path||"")).toLowerCase().includes(q);
  });
  document.getElementById("crumb").textContent =
    (sel === "*" ? "All assets" : (byId[sel]?.path || "?")) +
    "   —   " + rows.length + " file(s), " + fmt(rows.reduce((s,a)=>s+(+a.bytes||0),0));
  if (!rows.length){ document.getElementById("out").innerHTML = '<div class="empty">Nothing matches.</div>'; return; }
  rows.sort((a,b) => (b.bytes||0) - (a.bytes||0));
  const cap = 1500, shown = rows.slice(0, cap);
  let h = "<table><thead><tr>" +
    (thumbs ? "<th></th>" : "") +
    "<th>File</th><th>Folder in Storyblok</th><th>Type</th><th>Size</th>" +
    "<th>Stored</th><th>Path in storage</th><th>sha256</th><th>Id</th></tr></thead><tbody>";
  shown.forEach(a => {
    h += "<tr>";
    if (thumbs) h += (a.url && /^image\\//.test(a.type||"")
      ? '<td><img class="thumb" loading="lazy" src="' + a.url + '" alt=""></td>'
      : '<td><div class="ph">' + ((a.type||"?").split("/")[1]||"?").slice(0,4) + '</div></td>');
    h += "<td>" + a.name + "</td>" +
      '<td class="mono">' + (byId[a.folder]?.path || "(root)") + "</td>" +
      "<td>" + (a.type || "—") + "</td>" +
      '<td class="num">' + fmt(a.bytes) + "</td>" +
      '<td><span class="pill ' + (a.stored ? "y" : "n") + '">' + (a.stored ? "yes" : "no") + "</span></td>" +
      '<td class="mono">' + (a.path || "—") + "</td>" +
      '<td class="mono">' + (a.sha ? a.sha.slice(0,12) : "—") + "</td>" +
      '<td class="num">' + a.id + "</td></tr>";
  });
  h += "</tbody></table>";
  if (rows.length > cap) h += '<div class="empty">Showing the ' + cap +
    " largest of " + rows.length + " — narrow the filter to see the rest.</div>";
  document.getElementById("out").innerHTML = h;
}
["q","sub","miss","thumbs"].forEach(id =>
  document.getElementById(id).addEventListener(id === "q" ? "input" : "change", draw));
drawTree(); draw();
</script></body></html>
"""


def _stat(label, value):
    return (f'<div class="stat"><b>{html.escape(label)}</b>'
            f'<span>{html.escape(str(value))}</span></div>')


def _human(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def build_assets_portal(path, site, space_name, assets, asset_folders,
                        folder_paths, rows_by_id, store_label, external):
    """Write the portal. `rows_by_id` is {asset id: manifest row dict}."""
    folders = [{"id": f["id"], "parent": f.get("parent_id") or 0,
                "name": str(f.get("name") or f["id"]),
                "path": folder_paths.get(f["id"], str(f.get("name") or ""))}
               for f in (asset_folders or [])]

    out, total, missing, unsized = [], 0, 0, 0
    for a in assets:
        row = rows_by_id.get(str(a.get("id")), {})
        try:
            size = int(a.get("content_length") or 0)
        except (TypeError, ValueError):
            size = 0
        if not size:
            unsized += 1
        total += size
        stored = row.get("file_present") == "yes"
        if not stored:
            missing += 1
        out.append({
            "id": a.get("id"),
            "name": os.path.basename(a.get("filename") or "") or "(no name)",
            "folder": a.get("asset_folder_id") or 0,
            "type": a.get("content_type") or "",
            "bytes": size,
            "stored": stored,
            "path": row.get("backup_file") or "",
            "sha": row.get("sha256") or "",
            "url": a.get("filename") or "",
        })

    stats = "".join([
        _stat("files", f"{len(assets):,}"),
        _stat("folders", f"{len(folders):,}"),
        _stat("total size", _human(total)),
        _stat("stored", f"{len(assets) - missing:,}"),
        _stat("not stored", f"{missing:,}"),
        _stat("no size reported", f"{unsized:,}"),
    ])
    where = (f'Media is stored <strong>outside the repository</strong> at '
             f'<code>{html.escape(store_label)}</code>. '
             f'The "Path in storage" column is relative to that.'
             if external else
             'Media is committed <strong>inside this repository</strong> under '
             '<code>storyblok/assets/</code>, via Git LFS.')
    if missing:
        where += (f'<div class="where warn" style="margin-top:8px">'
                  f'{missing:,} file(s) have metadata but no stored bytes — '
                  f'tick "only missing from storage" to list them. A rebuild '
                  f'would recreate these as empty assets.</div>')

    page = (_PAGE
            .replace("__TITLE__", html.escape(f"{site['name']} assets"))
            .replace("__H1__", html.escape(
                f"{site['name']} — asset folder structure"))
            .replace("__SUB__", html.escape(
                f"Storyblok space {space_name or ''} ({site['space_id']}), "
                f"region {site.get('region', 'eu')}. "
                f"Folder tree as it exists in the space; sizes are the sum of "
                f"each folder and everything under it."))
            .replace("__STATS__", stats)
            .replace("__WHERE__", where)
            .replace("__FOOT__", html.escape(
                "Generated by pipeline/migrate/spaces/sb_portal.py from "
                "assets.json, asset_folders.json and manifest_assets.csv. "
                "Thumbnails load from Storyblok's public URLs and will stop "
                "resolving if the space is deleted — the structure, paths and "
                "checksums here do not depend on them."))
            .replace("__DATA__", json.dumps({"folders": folders,
                                             "assets": out},
                                            ensure_ascii=False)))

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)
    return len(out)
