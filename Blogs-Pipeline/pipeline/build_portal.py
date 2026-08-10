#!/usr/bin/env python3
"""build_portal.py — one HTML file showing every blog as Storyblok will hold it.

    python Blogs-Pipeline/pipeline/build_portal.py
    -> Blogs-Pipeline/out/blogs-portal.html      (double-click, no server)

For each of the 83 blogs it shows two things side by side:

    the blok sequence     rich_text, quote_banner, image ... in order, with the
                          Storyblok component name and whether we can fill it
    a preview             what that will look like once uploaded

**Everything we do not have is drawn as a labelled box saying what is absent and
why.** Nothing is invented. A blog whose banner cell reads `DOWNLOAD_FAILED`
shows a box saying exactly that, not a placeholder image, because a portal that
looks finished when the data is not is worse than no portal.

The layout follows the signed-off reference story
`blogs/beyond-the-blame-rethinking-pastoralism-and-environmental-impacts`. Where
the design calls for something the export cannot supply -- an author biography,
a photo of the quoted person -- the box says so, and the dev can tell us what to
put there instead.

Self-contained on purpose: the data is baked in as JSON, so the file opens
offline, survives being emailed, and needs no npm.
"""

import html
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "pipeline"))
import _bootstrap

_bootstrap.ensure()

from fields import F
from paths_root import ROOT, P

P.use("blogs")

OUT = os.path.join(P.PIPELINE, "out", "blogs-portal.html")


# --------------------------------------------------------------- rich text
def render_richtext(doc):
    """Storyblok rich text -> HTML, for the preview only."""
    if not isinstance(doc, dict):
        return ""
    out = []

    def marks(text, ms):
        for m in ms or []:
            t = m.get("type")
            if t == "bold":
                text = f"<strong>{text}</strong>"
            elif t == "italic":
                text = f"<em>{text}</em>"
            elif t == "underline":
                text = f"<u>{text}</u>"
            elif t == "link":
                href = html.escape((m.get("attrs") or {}).get("href") or "")
                text = f'<a href="{href}">{text}</a>'
        return text

    def node(n):
        t = n.get("type")
        kids = "".join(node(c) for c in (n.get("content") or []))
        if t == "text":
            return marks(html.escape(n.get("text") or ""), n.get("marks"))
        if t == "paragraph":
            return f"<p>{kids}</p>" if kids.strip() else ""
        if t == "heading":
            lvl = (n.get("attrs") or {}).get("level", 2)
            return f"<h{lvl}>{kids}</h{lvl}>"
        if t in ("bullet_list", "bulletList"):
            return f"<ul>{kids}</ul>"
        if t in ("ordered_list", "orderedList"):
            return f"<ol>{kids}</ol>"
        if t in ("list_item", "listItem"):
            return f"<li>{kids}</li>"
        if t == "blockquote":
            return f"<blockquote>{kids}</blockquote>"
        if t == "hard_break":
            return "<br>"
        if t == "image":
            src = (n.get("attrs") or {}).get("src") or ""
            return ('<div class="miss inline"><b>MISSING IMAGE</b>'
                    f'<span>{html.escape(src)}</span>'
                    "<span>still on aku.edu — not downloaded</span></div>")
        return kids

    for n in doc.get("content") or []:
        out.append(node(n))
    return "".join(out)


def text_of(doc):
    if not isinstance(doc, dict):
        return ""
    buf = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "text":
                buf.append(n.get("text") or "")
            for c in n.get("content") or []:
                walk(c)
    walk(doc)
    return " ".join(buf)


# ------------------------------------------------------------ the blok plan
def plan_for(content, routing, on_disk):
    """The bloks this blog becomes, in order, each with whether we can fill it.

    Follows the reference story. `state` is one of:
        ok       we have everything this blok needs
        missing  the design calls for it and the export cannot supply it
        blocked  we have the data but something outside us is in the way
    """
    bloks = []

    banner = (content.get("banner") or "").strip()
    if banner == "DOWNLOAD_FAILED":
        bloks.append(dict(component="banner_image", state="missing", field="banner_image",
                          note="the export wrote DOWNLOAD_FAILED — the file was never captured",
                          fix="fetch from aku.edu before the site is switched off"))
    elif not banner:
        bloks.append(dict(component="banner_image", state="missing", field="banner_image",
                          note="no Banner value in the export",
                          fix="ask AKU, or publish without a hero"))
    elif banner not in on_disk:
        bloks.append(dict(component="banner_image", state="missing", field="banner_image",
                          note=f"{banner} named but not on disk", fix="re-download"))
    else:
        bloks.append(dict(component="banner_image", state="ok", field="banner_image",
                          note=banner, fix=""))

    body = content.get("body")
    chars = len(text_of(body))
    bloks.append(dict(component="rich_text", state="ok",
                      note=f"{chars:,} characters of prose", fix="",
                      html=render_richtext(body)))

    imgs = []

    def find(n):
        if isinstance(n, dict):
            if n.get("type") == "image":
                imgs.append((n.get("attrs") or {}).get("src") or "")
            for c in n.get("content") or []:
                find(c)
    find(body or {})
    for src in imgs:
        bloks.append(dict(component="image", state="missing",
                          note=f"inline: {src}",
                          fix="download from aku.edu; it is a SharePoint path, not a local file"))

    q = (content.get("pull_quote") or "")
    if isinstance(q, dict):
        q = text_of(q.get("content")) or json.dumps(q)[:200]
    q = str(q).strip()
    if q:
        author = (content.get("pull_quote_author") or "").strip()
        bloks.append(dict(component="quote_banner", state="ok",
                          note=q[:180] + ("…" if len(q) > 180 else ""),
                          fix="", extra=f"— {author}" if author else "",
                          warn="" if author else "no attribution in the export"))

    if (content.get("embed_video") or "").strip():
        bloks.append(dict(component="media_section", state="ok",
                          note="type=video · " + (content.get("embed_video") or "")[:110], fix=""))
    if (content.get("embed_code") or "").strip():
        bloks.append(dict(component="iframe", state="ok",
                          note="embed · " + (content.get("embed_code") or "")[:110], fix=""))

    cat = (content.get("category") or "").strip()
    tags = [t.get("label") for t in (content.get("tags") or []) if isinstance(t, dict) and t.get("label")]
    bloks.append(dict(component="row → pill", state="undecided",
                      note=(f"Category: {cat}" if cat else "no category")
                           + (f" · {len(tags)} tags" if tags else ""),
                      fix="not yet decided which becomes a pill — the reference is only a demo"))

    bloks.append(dict(component="author_section", state="missing",
                      note=f"author is {content.get('author') or '(none)'}",
                      fix="the export has a NAME only — no biography and no photo for any of the 52 authors"))

    # Fields the dev added on 10 Aug. We have the data for all four; two of them
    # are custom plugins whose value format nothing in the space demonstrates.
    cat = (content.get("category") or "").strip()
    bloks.append(dict(component="field: category", state="undecided" if cat else "missing",
                      note=f"we have '{cat}'" if cat else "no category on this post",
                      fix="category-plugin — no story in the space has it filled, so the "
                          "value format is unknown. Ask the dev." if cat else ""))
    feat = str(content.get("is_featured") or "").lower() in ("true", "1")
    bloks.append(dict(component="field: isFeatured", state="undecided",
                      note=f"we have {feat}" + (f", order {content.get('feature_sequence')}"
                                                if content.get("feature_sequence") else ""),
                      fix="featured-plugin — same: format unknown, and there is still no "
                          "field for FeatureSequence"))
    ent = (content.get("entity") or "").strip()
    bloks.append(dict(component="field: entities", state="blocked",
                      note=f"we have '{ent}'" if ent else "no entity",
                      fix="blog_article still has no `entities` field — news has one. "
                          "This is the last schema gap."))

    closed = str(content.get("close_comments") or "").lower() in ("true", "1", "yes")
    bloks.append(dict(component="comment_form", state="blocked" if closed else "ok",
                      note="comments were CLOSED on this post in SharePoint" if closed
                           else "the design appends this to every article",
                      fix="blog_article has no field to suppress it" if closed else ""))

    return bloks


def main():
    with open(P.SOURCE_JSON, encoding="utf-8") as f:
        source = {str(F.get(i, "id")): i for i in json.load(f)}
    routing = {}
    rp = os.path.join(P.DATA, "taxonomy", "routing.csv")
    if os.path.exists(rp):
        import csv
        for r in csv.DictReader(open(rp, encoding="utf-8-sig")):
            routing[str(r["id"])] = r
    on_disk = set(os.listdir(P.MEDIA_DIR)) if os.path.isdir(P.MEDIA_DIR) else set()

    blogs = []
    import glob
    for path in sorted(glob.glob(os.path.join(P.STORIES, "*.json")),
                       key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)) or 0)):
        story = json.load(open(path, encoding="utf-8"))
        c = story.get("content", {})
        sid = str(c.get("sharepoint_id") or os.path.basename(path)[:-5])
        r = routing.get(sid, {})
        bloks = plan_for(c, r, on_disk)
        blogs.append({
            "id": sid,
            "title": c.get("title") or "(untitled)",
            "slug": story.get("slug") or "",
            "author": c.get("author") or "",
            "date": c.get("schedule_start_date") or "",
            "category": c.get("category") or "",
            "entity": c.get("entity") or "",
            "tags": [t.get("label") for t in (c.get("tags") or [])
                     if isinstance(t, dict) and t.get("label")],
            "target": r.get("target_full_slug") or "",
            "target_exists": r.get("target_exists") or "",
            "placement": r.get("placement") or "",
            "reason": r.get("reason") or "",
            "featured": str(c.get("is_featured") or "").lower() in ("true", "1"),
            "bloks": bloks,
            "missing": sum(1 for b in bloks if b["state"] == "missing"),
            "blocked": sum(1 for b in bloks if b["state"] == "blocked"),
        })

    stats = {
        "blogs": len(blogs),
        "with_banner": sum(1 for b in blogs
                           if any(x["component"] == "banner_image" and x["state"] == "ok"
                                  for x in b["bloks"])),
        "missing_images": sum(1 for b in blogs for x in b["bloks"]
                              if x["component"] == "image"),
        "with_quote": sum(1 for b in blogs if any(x["component"] == "quote_banner"
                                                  for x in b["bloks"])),
        "target_missing": sum(1 for b in blogs if b["target_exists"] == "no"),
        "categories": len({b["category"] for b in blogs if b["category"]}),
        "tags": len({t for b in blogs for t in b["tags"]}),
        "entities": len({b["entity"] for b in blogs if b["entity"]}),
        "components": dict(Counter(x["component"] for b in blogs for x in b["bloks"])),
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8", newline="\n").write(
        TEMPLATE.replace("__DATA__", json.dumps({"blogs": blogs, "stats": stats},
                                                ensure_ascii=False)))
    size = os.path.getsize(OUT) / 1024 / 1024
    print(f"  {len(blogs)} blogs -> {os.path.relpath(OUT, ROOT)}  ({size:.1f} MB)")
    print(f"    banners we have      {stats['with_banner']}/{len(blogs)}")
    print(f"    inline images missing {stats['missing_images']}")
    print(f"    destination missing   {stats['target_missing']}")
    print("\n  open it by double-clicking; no server needed")
    return 0


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AKU Blogs — Storyblok layout review</title>
<style>
:root{--ink:#15201c;--mut:#5d6b64;--line:#dfe5e1;--bg:#f6f8f7;--card:#fff;
--ok:#0f7b52;--okbg:#e8f5ef;--miss:#a8352a;--missbg:#fdecea;--warn:#8a6100;--warnbg:#fdf4e3;
--und:#4a5bb8;--undbg:#eef0fc}
*{box-sizing:border-box}
body{margin:0;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
color:var(--ink);background:var(--bg)}
header{background:var(--card);border-bottom:1px solid var(--line);padding:20px 28px;position:sticky;top:0;z-index:9}
h1{margin:0 0 4px;font-size:19px}
.sub{color:var(--mut);font-size:13px}
.wrap{max-width:1500px;margin:0 auto;padding:0 28px}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;min-width:118px}
.stat b{display:block;font-size:21px;line-height:1.2}
.stat span{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.stat.bad b{color:var(--miss)}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:14px 0 20px}
input,select{font:inherit;padding:8px 11px;border:1px solid var(--line);border-radius:8px;background:var(--card)}
input{min-width:260px}
.layout{display:grid;grid-template-columns:340px 1fr;gap:20px;align-items:start}
.list{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;
max-height:calc(100vh - 260px);overflow-y:auto;position:sticky;top:190px}
.row{padding:10px 14px;border-bottom:1px solid var(--line);cursor:pointer}
.row:hover{background:var(--bg)}
.row.on{background:#e8f0ee;border-left:3px solid var(--ok);padding-left:11px}
.row .t{font-weight:600;font-size:13px;line-height:1.35}
.row .m{color:var(--mut);font-size:11px;margin-top:3px;display:flex;gap:7px;flex-wrap:wrap}
.pill{display:inline-block;padding:1px 7px;border-radius:20px;font-size:10px;font-weight:600}
.pill.miss{background:var(--missbg);color:var(--miss)}
.pill.ok{background:var(--okbg);color:var(--ok)}
.pill.warn{background:var(--warnbg);color:var(--warn)}
.panel{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px}
.card h2{margin:0 0 3px;font-size:16px}
.card h3{margin:0 0 12px;font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut)}
.meta{color:var(--mut);font-size:12px;margin-bottom:14px;line-height:1.7}
.meta code{background:var(--bg);padding:1px 5px;border-radius:4px;font-size:11px}
.blok{border:1px solid var(--line);border-left:4px solid var(--ok);border-radius:8px;
padding:10px 13px;margin-bottom:9px;background:#fbfdfc}
.blok.missing{border-left-color:var(--miss);background:var(--missbg)}
.blok.blocked{border-left-color:var(--warn);background:var(--warnbg)}
.blok.undecided{border-left-color:var(--und);background:var(--undbg)}
.blok .c{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;font-weight:700}
.blok .n{font-size:12px;color:var(--mut);margin-top:4px;word-break:break-word}
.blok .f{font-size:11px;margin-top:6px;padding-top:6px;border-top:1px dashed rgba(0,0,0,.13)}
.blok.missing .f{color:var(--miss)}
.blok.blocked .f{color:var(--warn)}
.blok.undecided .f{color:var(--und)}
.prev{font-size:14px;line-height:1.75}
.prev h2,.prev h3{margin:18px 0 8px;font-size:16px;text-transform:none;letter-spacing:0;color:var(--ink)}
.prev p{margin:0 0 12px}
.prev blockquote{margin:14px 0;padding:10px 16px;border-left:3px solid var(--ok);
background:var(--bg);font-style:italic}
.prev a{color:#0a6b8a}
.miss{border:2px dashed var(--miss);background:var(--missbg);border-radius:8px;
padding:14px;margin:12px 0;text-align:center}
.miss b{display:block;color:var(--miss);font-size:11px;letter-spacing:.06em;text-transform:uppercase}
.miss span{display:block;color:var(--mut);font-size:11px;margin-top:4px;word-break:break-all}
.hero{border:2px dashed var(--line);border-radius:8px;padding:26px;text-align:center;
color:var(--mut);font-size:12px;background:var(--bg);margin-bottom:14px}
.quote{border-left:3px solid var(--ok);padding:12px 18px;margin:16px 0;background:var(--bg);
font-size:16px;font-style:italic}
.quote .att{display:block;font-style:normal;font-size:12px;color:var(--mut);margin-top:8px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--mut);margin:10px 0 0}
.legend i{width:11px;height:11px;border-radius:3px;display:inline-block;vertical-align:-1px;margin-right:4px}
@media(max-width:1200px){.layout{grid-template-columns:1fr}.panel{grid-template-columns:1fr}
.list{position:static;max-height:340px}}
</style></head><body>
<header><div class="wrap">
<h1>AKU Blogs — Storyblok layout review</h1>
<div class="sub">83 posts, as Storyblok will hold them. <strong>Nothing here is invented</strong> —
anything we cannot supply is drawn as a red box saying what is absent and why.</div>
<div class="legend">
<span><i style="background:var(--ok)"></i>we have it</span>
<span><i style="background:var(--miss)"></i>missing — cannot fill from the export</span>
<span><i style="background:var(--warn)"></i>blocked — data exists, no field for it</span>
<span><i style="background:var(--und)"></i>undecided — awaiting a design call</span>
</div>
</div></header>
<div class="wrap">
<div class="stats" id="stats"></div>
<div class="bar">
<input id="q" placeholder="search title, author, category, tag…">
<select id="filter">
<option value="">all 83</option>
<option value="missing">has something missing</option>
<option value="nobanner">no banner</option>
<option value="images">has inline images</option>
<option value="quote">has a pull quote</option>
<option value="nofolder">destination folder does not exist</option>
</select>
<span class="sub" id="count"></span>
</div>
<div class="layout">
<div class="list" id="list"></div>
<div class="panel" id="panel"></div>
</div>
<p class="sub" style="margin:26px 0 40px">
Generated by <code>Blogs-Pipeline/pipeline/build_portal.py</code>. Re-run it after any pipeline change.
</p>
</div>
<script>
const D = __DATA__;
const S = D.stats, B = D.blogs;
document.getElementById('stats').innerHTML = [
  ['blogs', S.blogs, ''], ['banners we have', S.with_banner + '/' + S.blogs, S.with_banner < S.blogs ? 'bad' : ''],
  ['inline images missing', S.missing_images, S.missing_images ? 'bad' : ''],
  ['pull quotes', S.with_quote, ''], ['categories', S.categories, ''],
  ['tags', S.tags, ''], ['entities', S.entities, ''],
  ['no destination folder', S.target_missing, S.target_missing ? 'bad' : '']
].map(([l,v,c]) => `<div class="stat ${c}"><b>${v}</b><span>${l}</span></div>`).join('');

const esc = s => String(s||'').replace(/[&<>"]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
let cur = B[0] && B[0].id;

function match(b){
  const q = document.getElementById('q').value.toLowerCase().trim();
  const f = document.getElementById('filter').value;
  if (q && !((b.title+' '+b.author+' '+b.category+' '+b.tags.join(' ')+' '+b.id).toLowerCase().includes(q))) return false;
  if (f === 'missing' && !b.missing) return false;
  if (f === 'nobanner' && !b.bloks.some(x => x.component === 'banner_image' && x.state === 'missing')) return false;
  if (f === 'images' && !b.bloks.some(x => x.component === 'image')) return false;
  if (f === 'quote' && !b.bloks.some(x => x.component === 'quote_banner')) return false;
  if (f === 'nofolder' && b.target_exists !== 'no') return false;
  return true;
}

function renderList(){
  const rows = B.filter(match);
  document.getElementById('count').textContent = rows.length + ' shown';
  document.getElementById('list').innerHTML = rows.map(b => `
    <div class="row ${b.id===cur?'on':''}" onclick="pick('${b.id}')">
      <div class="t">${esc(b.title)}</div>
      <div class="m"><span>#${b.id}</span>
        ${b.category ? `<span>${esc(b.category)}</span>` : ''}
        ${b.missing ? `<span class="pill miss">${b.missing} missing</span>` : '<span class="pill ok">complete</span>'}
        ${b.target_exists === 'no' ? '<span class="pill warn">no folder</span>' : ''}
      </div></div>`).join('') || '<div class="row"><div class="m">nothing matches</div></div>';
}

function renderPanel(){
  const b = B.find(x => x.id === cur); if (!b) return;
  const bloks = b.bloks.map(x => `
    <div class="blok ${x.state}">
      <div class="c">${esc(x.component)}</div>
      <div class="n">${esc(x.note)}${x.extra ? ' <em>'+esc(x.extra)+'</em>' : ''}</div>
      ${x.fix ? `<div class="f">${esc(x.fix)}</div>` : ''}
      ${x.warn ? `<div class="f">${esc(x.warn)}</div>` : ''}
    </div>`).join('');

  let prev = '';
  for (const x of b.bloks){
    if (x.component === 'banner_image')
      prev += x.state === 'ok'
        ? `<div class="hero">banner_image · ${esc(x.note)}</div>`
        : `<div class="miss"><b>no banner</b><span>${esc(x.note)}</span><span>${esc(x.fix)}</span></div>`;
    else if (x.component === 'rich_text') prev += `<div class="prev">${x.html||''}</div>`;
    else if (x.component === 'quote_banner')
      prev += `<div class="quote">${esc(x.note)}<span class="att">${esc(x.extra||'no attribution')}</span></div>`;
    else if (x.component === 'image')
      prev += `<div class="miss"><b>missing image</b><span>${esc(x.note)}</span><span>${esc(x.fix)}</span></div>`;
    else if (x.state !== 'ok')
      prev += `<div class="miss" style="border-color:${x.state==='undecided'?'var(--und)':'var(--warn)'};background:${x.state==='undecided'?'var(--undbg)':'var(--warnbg)'}">
        <b style="color:${x.state==='undecided'?'var(--und)':'var(--warn)'}">${esc(x.component)} — ${esc(x.state)}</b>
        <span>${esc(x.note)}</span><span>${esc(x.fix)}</span></div>`;
    else prev += `<div class="hero">${esc(x.component)} · ${esc(x.note)}</div>`;
  }

  document.getElementById('panel').innerHTML = `
   <div class="card">
     <h2>${esc(b.title)}</h2>
     <div class="meta">
       #${b.id} · ${esc(b.author||'no author')} · ${esc(b.date||'no date')}<br>
       entity <code>${esc(b.entity||'—')}</code> · category <code>${esc(b.category||'—')}</code><br>
       lands in <code>${esc(b.target||'unresolved')}</code>
       ${b.target_exists==='no' ? '<span class="pill warn">folder does not exist</span>' : ''}
       ${b.reason ? `<br><span style="font-size:11px">${esc(b.reason)}</span>` : ''}
       ${b.tags.length ? `<br>tags: ${b.tags.map(t=>esc(t)).join(' · ')}` : ''}
     </div>
     <h3>blok sequence — what Storyblok will hold</h3>
     ${bloks}
   </div>
   <div class="card"><h3>preview</h3>${prev}</div>`;
}

function pick(id){ cur = id; renderList(); renderPanel(); window.scrollTo({top:0,behavior:'smooth'}); }
document.getElementById('q').oninput = renderList;
document.getElementById('filter').onchange = renderList;
renderList(); renderPanel();
</script></body></html>
"""


if __name__ == "__main__":
    sys.exit(main())
