#!/usr/bin/env python3
"""build_portal.py — one HTML file showing every blog as Storyblok will hold it.

    python Blogs-Pipeline/pipeline/build_portal.py
    -> Blogs-Pipeline/out/blogs-portal.html      (double-click, no server)

For each of the 83 blogs it shows two things side by side:

    the blok sequence     rich_text, quote_banner, image ... in order, with the
                          Storyblok component name and whether we can fill it
    a preview             what that will look like once uploaded

**Everything we do not have is drawn as a labelled box saying what is absent and
why.** Nothing is invented — no placeholder image ever stands in for a real one,
because a portal that looks finished when the data is not is worse than no
portal.

A box is only red while something can still be done about it. The 13 blogs with
no banner are marked `skipped`, not `missing`: SharePoint records no banner for
them anywhere, and guessing one from the 73 unclaimed files in
`/blogs/PublishingImages` was measured and rejected. `fetch_missing_media.py`
carries the evidence.

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

from paths_root import ROOT, P

P.use("blogs")

OUT = os.path.join(P.PIPELINE, "out", "blogs-portal.html")


# --------------------------------------------------------------- rich text
_ON_DISK = set()
_AUTHORS = {}        # SharePoint AuthorManagement, id -> record
_AUTHOR_PICS = {}    # author id -> local photo filename


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
            name = os.path.basename(src.split("?")[0])
            if name in _ON_DISK:
                # Relative from out/ to the media folder. Opened from disk the
                # browser resolves it and the real image appears; nothing is
                # embedded, so the file stays small.
                rel = "../assets/Blogs/media/" + name
                return (f'<figure class="img"><img src="{html.escape(rel)}" '
                        f'alt="" loading="lazy">'
                        f'<figcaption>{html.escape(name)}</figcaption></figure>')
            return ('<div class="gap get"><b>GO GET IT — image</b>'
                    f'<span>{html.escape(src)}</span>'
                    "<span>not on disk; aku.edu did not return it</span></div>")
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
    if banner in ("DOWNLOAD_FAILED", ""):
        # Closed, not outstanding. SharePoint records no banner for these 13
        # anywhere — the field is null on all 89 posts, there are no
        # attachments, and the detail page renders client-side. Guessing from
        # the 73 unclaimed files was measured at 94% precision and abstains on
        # every one of the 13. See fetch_missing_media.py and
        # data/banners_absent.json.
        cell = "the export wrote DOWNLOAD_FAILED" if banner else "the Banner cell is empty"
        bloks.append(dict(component="banner_image", state="skipped", field="banner_image",
                          note=f"{cell}; no banner is recorded anywhere in SharePoint",
                          fix="none — verified absent at source, publishes without a hero"))
    elif banner not in on_disk:
        bloks.append(dict(component="banner_image", state="missing", field="banner_image",
                          note=f"{banner} named but not on disk", fix="re-download"))
    else:
        bloks.append(dict(component="banner_image", state="ok", field="banner_image",
                          note=banner, fix="",
                          img="../assets/Blogs/media/" + banner))

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
        # The rich text still carries the SharePoint path; whether we HAVE the
        # file is a separate question, answered by looking on disk.
        name = os.path.basename(src.split("?")[0])
        if name in on_disk:
            bloks.append(dict(component="image", state="ok",
                              note=f"{name}  (from {src})", fix=""))
        else:
            bloks.append(dict(component="image", state="missing",
                              note=f"inline: {src}",
                              fix="not on disk — fetch from aku.edu while it is still up"))

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

    vid = (content.get("embed_video") or "").strip()
    if vid:
        # The column holds the same URL twice, comma separated, in the one blog
        # that has it. Take the first.
        first = vid.split(",")[0].strip()
        bloks.append(dict(component="media_section", state="ok",
                          note="type=video · " + first[:100], fix="", embed=first))
    code = (content.get("embed_code") or "").strip()
    if code:
        bloks.append(dict(component="iframe", state="ok",
                          note="embed · " + code[:100], fix="", raw=code))

    cat = (content.get("category") or "").strip()
    tags = [t.get("label") for t in (content.get("tags") or []) if isinstance(t, dict) and t.get("label")]
    bloks.append(dict(component="row → pill", state="undecided",
                      note=(f"Category: {cat}" if cat else "no category")
                           + (f" · {len(tags)} tags" if tags else ""),
                      fix="not yet decided which becomes a pill — the reference is only a demo"))

    # This was marked "dropped, no bio exists anywhere" until someone looked at
    # a live AKU page and saw an author section on it. The bios are real: they
    # live in a SharePoint list called AuthorManagement that was not part of the
    # delivered export. 76 of the 83 posts have one.
    aid = str(content.get("author_id") or "").strip()
    bio_html = (_AUTHORS.get(aid, {}).get("Description") or "").strip()
    pic = _AUTHOR_PICS.get(aid)
    if bio_html:
        # unescape too: SharePoint stores &#160; and friends, and a raw entity
        # in a preview reads as a typo rather than as a space.
        plain = html.unescape(re.sub(r"<[^>]+>", " ", bio_html))
        plain = re.sub(r"[\s ​]+", " ", plain).strip()
        bloks.append(dict(
            component="author_section", state="ok",
            note=f"{content.get('author') or '(no name)'} — {plain[:150]}"
                 + ("…" if len(plain) > 150 else ""),
            fix="" if pic else "bio yes, photo no — only 6 author photos exist on aku.edu",
            img=("../assets/Blogs/media/" + pic) if pic else "",
            bio=plain))
    else:
        # Closed, not outstanding. Ids 4 and 5 were deleted from
        # AuthorManagement — the live list 404s on both — and the remaining
        # entries simply have an empty Description. The name still migrates.
        who = content.get("author") or "(none)"
        bloks.append(dict(
            component="author_section", state="skipped",
            note=f"{who} — name only; no biography exists"
                 + (f" (author id {aid} is not in AuthorManagement)" if aid else ""),
            fix="none — verified absent at source; renders with the name alone"))

    # Fields the dev added on 10 Aug. We have the data for all four; two of them
    # are custom plugins whose value format nothing in the space demonstrates.
    cat = (content.get("category") or "").strip()
    bloks.append(dict(component="field: category", state="undecided" if cat else "skipped",
                      note=f"we have '{cat}'" if cat else "this post has no category in the export",
                      fix=("category-plugin — no story in the space has it filled, so the value "
                           "format is unknown. Ask the dev.") if cat
                          else "nothing to migrate; 3 of the 83 have no category"))
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


def verify(path):
    """Run the page's own JavaScript and check it produced something.

    Written after the portal shipped blank: a mangled quote in one onclick made
    the whole script a SyntaxError, so nothing ran and the page was empty. The
    build reported success, because writing a file had worked.

    Node is optional -- if it is not installed this says so and moves on rather
    than blocking a build over a check.
    """
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    if not node:
        print("  (node not found — skipping the render check)")
        return

    with open(path, encoding="utf-8") as f:
        page = f.read()
    js = page.split("<script>", 1)[1].rsplit("</script>", 1)[0]

    probe = """
const els = {};
const mk = () => ({ set innerHTML(v){this._h=v}, get innerHTML(){return this._h||''},
  textContent:'', value:'', set oninput(v){}, set onchange(v){}, set onclick(v){} });
global.document = { getElementById: id => (els[id] = els[id] || mk()) };
global.window = { scrollTo(){} };
__JS__
const view = (els['view']||{}).innerHTML || '';
if (!view.length) { console.error('the page rendered nothing'); process.exit(1); }
console.log(JSON.stringify({
  chars: view.length,
  cards: (view.match(/class="gc"/g)||[]).length,
  images: (view.match(/<img /g)||[]).length,
}));
"""
    tmp = os.path.join(tempfile.gettempdir(), "aku_portal_probe.js")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(probe.replace("__JS__", js))
    done = subprocess.run([node, tmp], capture_output=True, text=True,
                          encoding="utf-8")
    os.remove(tmp)
    if done.returncode != 0:
        raise SystemExit("  the portal does not run:\n"
                         + (done.stderr or done.stdout).strip()[-700:])
    import json as _json
    got = _json.loads(done.stdout.strip().splitlines()[-1])
    print(f"  renders: {got['cards']} cards, {got['images']} images")


def main():
    routing = {}
    rp = os.path.join(P.DATA, "taxonomy", "routing.csv")
    if os.path.exists(rp):
        import csv
        for r in csv.DictReader(open(rp, encoding="utf-8-sig")):
            routing[str(r["id"])] = r
    on_disk = set(os.listdir(P.MEDIA_DIR)) if os.path.isdir(P.MEDIA_DIR) else set()
    _ON_DISK.update(on_disk)
    for name, target in (("authors.json", _AUTHORS), ("author_photos.json", _AUTHOR_PICS)):
        path = os.path.join(P.DATA, "source", name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            if name == "authors.json":
                target.update({str(a["ID"]): a for a in raw.get("value", [])})
            else:
                target.update(raw)

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
            "author_id": str(c.get("author_id") or ""),
            "date": c.get("schedule_start_date") or "",
            "category": c.get("category") or "",
            "entity": c.get("entity") or "",
            "tags": [t.get("label") for t in (c.get("tags") or [])
                     if isinstance(t, dict) and t.get("label")],
            "target": r.get("target_full_slug") or "",
            "target_exists": r.get("target_exists") or "",
            "placement": r.get("placement") or "",
            "reason": r.get("reason") or "",
            "share_entity": r.get("share_entity") or "",
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
        "images_have": sum(1 for b in blogs for x in b["bloks"]
                           if x["component"] == "image" and x["state"] == "ok"),
        "images_missing": sum(1 for b in blogs for x in b["bloks"]
                              if x["component"] == "image" and x["state"] != "ok"),
        "with_quote": sum(1 for b in blogs if any(x["component"] == "quote_banner"
                                                  for x in b["bloks"])),
        "target_missing": sum(1 for b in blogs if b["target_exists"] == "no"),
        "categories": len({b["category"] for b in blogs if b["category"]}),
        "tags": len({t for b in blogs for t in b["tags"]}),
        "entities": len({b["entity"] for b in blogs if b["entity"]}),
        "components": dict(Counter(x["component"] for b in blogs for x in b["bloks"])),
    }

    import datetime
    stamp = datetime.datetime.now().strftime("%d %b %H:%M")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8", newline="\n").write(
        template()
        .replace("__DATA__", json.dumps({"blogs": blogs, "stats": stats},
                                        ensure_ascii=False))
        # A stale copy in a browser cache is indistinguishable from a broken
        # build unless the page says which build it is.
        .replace("__BUILD__", stamp))
    verify(OUT)
    size = os.path.getsize(OUT) / 1024 / 1024
    print(f"  {len(blogs)} blogs -> {os.path.relpath(OUT, ROOT)}  ({size:.1f} MB)")
    print(f"    banners we have      {stats['with_banner']}/{len(blogs)}")
    print(f"    inline images         {stats['images_have']} have, "
          f"{stats['images_missing']} missing")
    print(f"    destination missing   {stats['target_missing']}")
    print("\n  open it by double-clicking; no server needed")
    return 0


# The page itself lives beside this file, so the HTML/CSS/JS can be edited as
# HTML rather than as a Python string with escaping rules of its own.
TEMPLATE_FILE = os.path.join(HERE, "portal_template.html")


def template():
    with open(TEMPLATE_FILE, encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    sys.exit(main())
