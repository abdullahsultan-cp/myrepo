#!/usr/bin/env python3
"""build_portal.py — one HTML file showing all 3,606 news stories as they are live.

    python News-Pipeline/pipeline/build_portal.py
    python News-Pipeline/pipeline/build_portal.py --offline   # skip the slug refresh
    -> News-Pipeline/out/news-portal.html    (double-click, no server)

News is finished, so this is not a "what will it look like" portal like blogs'.
It is a **review surface over what is already published**: find a story, see
where it went, what it is made of, and what is still outstanding on it.

## It must open from a clone

That is the rule in CONTRIBUTING.md §3b and it is the whole design constraint
here. So:

    the data      baked into the HTML as JSON, not fetched
    the images    every one an a.storyblok.com URL, never a path under assets/
    css and js    inlined
    the source    data/migrate/sb_snapshot/, which is COMMITTED — 3,606 stories
                  read back from the API, so nothing has to be re-run

3,606 full stories would be 47 MB of HTML. What is baked in is an index — title,
slug, route, date, read time, banner, blok sequence, flags — around 1 MB. The
body text is not included; the editor link is one click away.

## Slugs are read live, once, at build time

`sb_snapshot` was taken before the dev renamed every folder to a short code:
its `full_slug` still says `regions/kenya/news/...` where the space now says
`regions/ke/news/...`. The build refreshes them from the API so the portal is
accurate, and falls back to the snapshot with a warning when offline. **The
build may use the network; the portal it produces never does.**

## What the flags mean

    no banner        the story has no hero image
    iframe           an embed the dev's social_embed has not replaced
    aku.edu link     a link that dies when SharePoint is switched off
    no entities      legitimately empty for 1,575 stories — not a fault
"""

import argparse
import json
import os
import subprocess
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "pipeline"))
import _bootstrap

_bootstrap.ensure()

from paths_root import ROOT, P

P.use("news")

OUT = os.path.join(P.PIPELINE, "out", "news-portal.html")
SNAPSHOT = os.path.join(P.DATA, "migrate", "sb_snapshot")


def live_slugs():
    """{story id: current full_slug}, read once from the space."""
    try:
        import requests

        from storyblok_config import load_config, management_api_base
        cfg = load_config()
        api = f"{management_api_base(cfg)}/spaces/{cfg['space_id']}"
        head = {"Authorization": cfg["management_token"]}
        out, page = {}, 1
        while True:
            r = requests.get(f"{api}/stories", headers=head, timeout=90,
                             params={"per_page": 100, "page": page,
                                     "story_only": 1})
            if r.status_code != 200:
                print(f"    slug refresh got {r.status_code}; using the snapshot")
                return out
            chunk = r.json().get("stories", [])
            for s in chunk:
                out[s["id"]] = s.get("full_slug") or ""
            if len(chunk) < 100:
                print(f"    {len(out)} live slug(s) refreshed")
                return out
            page += 1
    except Exception as exc:
        print(f"    no slug refresh ({type(exc).__name__}); using the snapshot")
        return {}


def walk(node, fn):
    if isinstance(node, dict):
        fn(node)
        for value in node.values():
            if isinstance(value, (list, dict)):
                walk(value, fn)
    elif isinstance(node, list):
        for child in node:
            walk(child, fn)


def summarise(story, slug_now):
    content = story.get("content") or {}
    slug = slug_now.get(story.get("id")) or story.get("full_slug") or ""
    parts = slug.split("/")
    region = parts[1] if len(parts) > 2 and parts[0] == "regions" else "global"
    entity = parts[3] if len(parts) > 4 and parts[2] == "entities" else ""
    dept = parts[5] if len(parts) > 6 and parts[4] == "departments" else ""

    comps, flags = Counter(), []
    hrefs = []

    def visit(n):
        name = n.get("component")
        if name:
            comps[name] += 1
        for mark in n.get("marks") or []:
            if mark.get("type") == "link":
                hrefs.append((mark.get("attrs") or {}).get("href") or "")
        if n.get("component") == "iframe":
            flags.append("iframe")

    walk(content.get("body") or [], visit)
    if any("aku.edu" in h or h.startswith("/") for h in hrefs):
        flags.append("aku.edu link")
    banner = (content.get("banner_image") or {}).get("filename") or ""
    if not banner:
        flags.append("no banner")

    images = []

    def pics(n):
        if n.get("type") == "image":
            src = (n.get("attrs") or {}).get("src") or ""
            if src:
                images.append(src)
    walk(content.get("body") or [], pics)

    return {
        "id": story.get("id"),
        "t": (content.get("title") or story.get("name") or "")[:160],
        "s": slug,
        "r": region, "e": entity, "d": dept,
        "dt": content.get("date") or "",
        "rt": content.get("read_time") or "",
        "au": (content.get("author") or "")[:80],
        "b": banner,
        "im": images[:6],
        "n": len(images),
        "bl": [f"{k}x{v}" if v > 1 else k for k, v in comps.most_common()],
        "en": len(content.get("entities") or []),
        "g": bool(content.get("isGlobal")),
        "f": sorted(set(flags)),
    }


TEMPLATE = """<meta charset="utf-8"><title>AKU news — 3,606 live stories</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--line:#262b36;--tx:#e6e9ef;--dim:#98a1b3;
--ok:#3fb950;--warn:#d29922;--bad:#f85149;--acc:#58a6ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);
font:14px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{padding:18px 22px;border-bottom:1px solid var(--line);position:sticky;top:0;
background:var(--bg);z-index:5}
h1{margin:0 0 4px;font-size:17px}.sub{color:var(--dim);font-size:12px}
.stats{display:flex;gap:18px;flex-wrap:wrap;margin-top:10px}
.stat b{font-size:17px}.stat span{color:var(--dim);font-size:11px;display:block}
.bar{display:flex;gap:8px;flex-wrap:wrap;padding:12px 22px;border-bottom:1px solid var(--line)}
input,select{background:var(--card);color:var(--tx);border:1px solid var(--line);
border-radius:6px;padding:7px 10px;font:inherit}
input{min-width:260px}
main{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:0;height:calc(100vh - 150px)}
#list{overflow:auto;border-right:1px solid var(--line)}
#detail{overflow:auto;padding:20px 24px}
.row{display:flex;gap:12px;padding:11px 18px;border-bottom:1px solid var(--line);cursor:pointer}
.row:hover{background:var(--card)}.row.sel{background:#1d2230}
.thumb{width:74px;height:52px;object-fit:cover;border-radius:5px;background:#222;flex:none}
.thumb.none{display:flex;align-items:center;justify-content:center;color:var(--dim);font-size:10px}
.row h3{margin:0 0 3px;font-size:13px;font-weight:600}
.meta{color:var(--dim);font-size:11px}
.tag{display:inline-block;padding:1px 7px;border-radius:99px;font-size:10px;
border:1px solid var(--line);margin-right:4px}
.tag.bad{color:var(--bad);border-color:#5c2b2b}.tag.warn{color:var(--warn);border-color:#5c4a22}
.tag.ok{color:var(--ok);border-color:#2b5c33}
#detail h2{margin:0 0 6px;font-size:18px}
.kv{display:grid;grid-template-columns:130px 1fr;gap:6px 14px;margin:14px 0;font-size:13px}
.kv div:nth-child(odd){color:var(--dim)}
.bloks{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}
.blok{background:var(--card);border:1px solid var(--line);border-radius:5px;padding:3px 9px;font-size:11px}
a{color:var(--acc)}img.big{max-width:100%;border-radius:8px;margin:10px 0}
.gal{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px}
.gal img{width:100%;border-radius:6px}
.empty{color:var(--dim);padding:40px 24px;text-align:center}
</style>
<header>
  <h1>AKU news — <span id="count"></span> stories, live in Storyblok</h1>
  <div class="sub">Read back from the space. Every image is a Storyblok URL, so this
  file works from a clone with nothing else installed.</div>
  <div class="stats" id="stats"></div>
</header>
<div class="bar">
  <input id="q" placeholder="search title, slug, author…">
  <select id="region"></select><select id="entity"></select><select id="flag"></select>
</div>
<main><div id="list"></div><div id="detail" class="empty">Pick a story on the left.</div></main>
<script>
const D = __DATA__;
const SPACE = "__SPACE__";
const esc = s => String(s==null?"":s).replace(/[&<>"]/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const el = id => document.getElementById(id);

function fill(sel, values, label){
  sel.innerHTML = '<option value="">'+label+'</option>' +
    values.map(v => '<option>'+esc(v)+'</option>').join("");
}
fill(el("region"), [...new Set(D.stories.map(s=>s.r))].sort(), "all regions");
fill(el("entity"), [...new Set(D.stories.map(s=>s.e).filter(Boolean))].sort(), "all entities");
fill(el("flag"), [...new Set(D.stories.flatMap(s=>s.f))].sort(), "any flag");

el("stats").innerHTML = D.stats.map(s =>
  '<div class="stat"><b>'+esc(s[1])+'</b><span>'+esc(s[0])+'</span></div>').join("");

let shown = [];
function draw(){
  const q = el("q").value.toLowerCase().trim();
  const r = el("region").value, e = el("entity").value, f = el("flag").value;
  shown = D.stories.filter(s =>
    (!r || s.r===r) && (!e || s.e===e) && (!f || s.f.includes(f)) &&
    (!q || (s.t+" "+s.s+" "+s.au).toLowerCase().includes(q)));
  el("count").textContent = shown.length.toLocaleString();
  el("list").innerHTML = shown.slice(0,400).map((s,i) =>
    '<div class="row" data-i="'+i+'">' +
    (s.b ? '<img class="thumb" loading="lazy" src="'+esc(s.b)+'">'
         : '<div class="thumb none">no banner</div>') +
    '<div><h3>'+esc(s.t)+'</h3>' +
    '<div class="meta">'+esc(s.r)+(s.e?" · "+esc(s.e):"")+" · "+esc(s.dt)+
    " · "+esc(s.rt)+'</div><div style="margin-top:4px">' +
    s.f.map(x=>'<span class="tag '+(x==="no banner"?"warn":"bad")+'">'+esc(x)+'</span>').join("") +
    (s.f.length?"":'<span class="tag ok">clean</span>') +
    '</div></div></div>').join("") ||
    '<div class="empty">Nothing matches.</div>';
}
function detail(s){
  el("detail").className = "";
  el("detail").innerHTML =
    '<h2>'+esc(s.t)+'</h2>' +
    '<div class="meta">'+esc(s.s)+'</div>' +
    (s.b ? '<img class="big" src="'+esc(s.b)+'">' : "") +
    '<div class="kv">' +
    '<div>author</div><div>'+esc(s.au||"—")+'</div>' +
    '<div>date</div><div>'+esc(s.dt||"—")+'</div>' +
    '<div>read time</div><div>'+esc(s.rt||"—")+'</div>' +
    '<div>route</div><div>'+esc(s.r)+(s.e?" / "+esc(s.e):"")+(s.d?" / "+esc(s.d):"")+'</div>' +
    '<div>isGlobal</div><div>'+(s.g?"true":"false")+'</div>' +
    '<div>entities</div><div>'+s.en+' folder id(s)</div>' +
    '<div>inline images</div><div>'+s.n+'</div>' +
    '</div>' +
    '<div class="bloks">'+s.bl.map(b=>'<span class="blok">'+esc(b)+'</span>').join("")+'</div>' +
    (s.f.length ? '<div>'+s.f.map(x=>'<span class="tag bad">'+esc(x)+'</span>').join("")+'</div>' : "") +
    '<p><a target="_blank" href="https://app.storyblok.com/#/me/spaces/'+SPACE+
    '/stories/0/0/'+s.id+'">open in Storyblok →</a></p>' +
    (s.im.length ? '<div class="gal">'+s.im.map(u=>'<img loading="lazy" src="'+esc(u)+'">').join("")+'</div>' : "");
}
el("list").addEventListener("click", ev => {
  const row = ev.target.closest(".row"); if(!row) return;
  [...document.querySelectorAll(".row.sel")].forEach(r=>r.classList.remove("sel"));
  row.classList.add("sel");
  detail(shown[+row.dataset.i]);
});
["q","region","entity","flag"].forEach(id => el(id).addEventListener("input", draw));
draw();
</script>"""


def verify(path):
    """Run the page's own JavaScript and check it rendered something.

    A portal that ships blank looks fine in git and is useless when opened. The
    blogs one did exactly that: a mangled quote made the whole script a
    SyntaxError. Node is optional — if it is not installed the build says so
    rather than failing.
    """
    src = open(path, encoding="utf-8").read()
    script = src.split("<script>")[-1].rsplit("</script>", 1)[0]
    stub = """
globalThis.__rows=[];
const mk=()=>({innerHTML:"",textContent:"",value:"",className:"",
  addEventListener(){},classList:{add(){},remove(){}},
  closest(){return null},dataset:{}});
globalThis.document={getElementById:mk,querySelectorAll:()=>[],
  addEventListener(){}};
"""
    probe = "\nif(!shown.length) throw new Error('no stories rendered');\n"
    # shutil.which, not a bare "node": on Windows the shell resolves it from
    # PATH but subprocess does not always, and the check then reports "node not
    # available" on a machine that has it — a verification that quietly stops
    # verifying is worse than none.
    import shutil
    node = shutil.which("node") or shutil.which(
        "node.exe", path=r"C:\Program Files\nodejs")
    if not node:
        print("    node not installed — page not verified")
        return
    # Via a file, never `node -e`. The script carries the whole 1.6 MB data
    # blob, and Windows caps a command line at about 32 KB — which surfaces as
    # FileNotFoundError, i.e. it looks exactly like "node is not installed".
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), "aku_news_portal_check.js")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(stub + script + probe)
    try:
        r = subprocess.run([node, tmp], capture_output=True, text=True,
                           timeout=90)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"    node could not run ({type(exc).__name__}) — not verified")
        return
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if r.returncode != 0:
        sys.exit(f"    the page does not run:\n{(r.stderr or '')[:400]}")
    print("    page runs and renders")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline", action="store_true",
                    help="skip the live slug refresh")
    a = ap.parse_args()

    if not os.path.isdir(SNAPSHOT):
        sys.exit(f"  no snapshot at {os.path.relpath(SNAPSHOT, ROOT)} — it is "
                 f"committed, so a clone has it; run backup.py to refresh")

    slug_now = {} if a.offline else live_slugs()
    stories = []
    for name in sorted(os.listdir(SNAPSHOT)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(SNAPSHOT, name), encoding="utf-8") as f:
            raw = json.load(f)
        stories.append(summarise(raw.get("story", raw), slug_now))
    stories.sort(key=lambda s: (s["r"], s["e"], s["t"]))

    flags = Counter(f for s in stories for f in s["f"])
    stats = [
        ("stories", f"{len(stories):,}"),
        ("with a banner", f"{sum(1 for s in stories if s['b']):,}"),
        ("inline images", f"{sum(s['n'] for s in stories):,}"),
        ("regions", len({s["r"] for s in stories})),
        ("entities", len({s["e"] for s in stories if s["e"]})),
        ("no banner", f"{flags['no banner']:,}"),
        ("aku.edu links", f"{flags['aku.edu link']:,}"),
        ("iframes left", flags["iframe"]),
    ]

    try:
        from storyblok_config import load_config
        space = str(load_config().get("space_id") or "")
    except Exception:
        space = ""

    page = (TEMPLATE
            .replace("__DATA__", json.dumps({"stories": stories,
                                             "stats": stats},
                                            ensure_ascii=False,
                                            separators=(",", ":")))
            .replace("__SPACE__", space))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)

    local = [u for s in stories for u in ([s["b"]] + s["im"])
             if u and not u.startswith("http")]
    print(f"\n  {len(stories):,} stories -> {os.path.relpath(OUT, ROOT)}  "
          f"({os.path.getsize(OUT)/1e6:.2f} MB)")
    for label, value in stats:
        print(f"    {label:<18}{value}")
    print(f"    images not on a URL  {len(local)}   <- must be 0 to work from a clone")
    verify(OUT)
    return 1 if local else 0


if __name__ == "__main__":
    sys.exit(main())
