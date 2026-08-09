#!/usr/bin/env python3
"""
build_viewer_index.py — static data for the review viewer.

Emits a compact facet index over all 3606 stories plus one detail file each, so
the viewer can filter 3606 records client-side and load full content on demand.

The point is to answer "what components do we actually need?" without opening the
AKU site: every structural element is counted per story, so the facet counts are
the component inventory.

Usage:
    python scripts/migrate/review/build_viewer_index.py [viewer_dir]

Outputs (default storyblok-viewer/public/data/):
    index.json          one compact record per story + facet vocabularies
    stories/{id}.json   full detail: richtext, media, links, taxonomy, SB links
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _bootstrap  # noqa: F401,E402  -- paths_root now lives in pipeline/core/
from paths import BASE  # noqa: E402

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from paths_root import P  # noqa: E402
STORIES = P.STORIES
RAW = P.RAW
ROUTING = os.path.join(P.TAXONOMY, "routing", "news_routing.csv")
PATHS = os.path.join(P.TAXONOMY, "routing", "story_paths.csv")

SHAREPOINT = "https://www.aku.edu/news/Pages/news_details.aspx?nid={nid}"
EDITOR = "https://app.storyblok.com/#/me/spaces/{space}/stories/0/0/{story}"

# Structural elements worth a facet. Key -> human label.
ELEMENTS = {
    "video_embed": "Video embed (YouTube)",
    "video_file": "Video file (hosted)",
    "twitter_embed": "Tweet embed",
    "iframe_embed": "Iframe embed",
    "gallery": "Gallery (3+ images)",
    "gif": "GIF",
    "banner_image": "Banner image",
    "medium_image": "Medium image",
    "thumbnail": "Thumbnail image",
    "inline_image": "Inline image in body",
    "pdf": "PDF attachment",
    "doc": "Word/other document",
    "table": "Table",
    "bullet_list": "Bullet list",
    "ordered_list": "Numbered list",
    "heading": "Heading",
    "blockquote": "Blockquote",
    "pull_quote": "Pull quote",
    "bold": "Bold text",
    "italic": "Italic text",
    "superscript": "Superscript",
    "link_internal": "Internal link (aku.edu)",
    "link_external": "External link",
    "link_document": "Link to a document",
    "link_email": "Email link",
    "link_anchor": "Anchor link",
    "urdu": "Urdu / alternate language",
    "no_media": "No media at all",
}


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def classify_link(href):
    h = (href or "").strip().lower()
    if not h:
        return None
    if h.startswith("mailto:"):
        return "link_email"
    if h.startswith("#"):
        return "link_anchor"
    if re.search(r"\.(pdf|docx?|xlsx?|pptx?|zip)(\?|$)", h):
        return "link_document"
    if h.startswith("/") or "aku.edu" in h:
        return "link_internal"
    if h.startswith("http"):
        return "link_external"
    return None


def analyse(doc):
    """Walk a richtext document: node counts, marks, links, text, images."""
    nodes, marks = Counter(), Counter()
    links, images, text = [], [], []
    bloks = Counter()

    def walk(n, href=None):
        if isinstance(n, list):
            for x in n:
                walk(x, href)
            return
        if not isinstance(n, dict):
            return
        t = n.get("type")
        if t:
            nodes[t] += 1
        if n.get("component"):
            bloks[n["component"]] += 1
        cur = href
        for m in n.get("marks") or []:
            if isinstance(m, dict):
                marks[m.get("type")] += 1
                if m.get("type") == "link":
                    a = m.get("attrs") or {}
                    cur = a.get("href") or a.get("url") or ""
        if t == "text" and n.get("text"):
            text.append(n["text"])
            if cur:
                links.append({"href": cur, "text": n["text"][:160]})
        if t == "image":
            a = n.get("attrs") or {}
            images.append({"src": a.get("src") or "", "alt": a.get("alt") or ""})
        walk(n.get("attrs", {}).get("body") or [], cur)
        walk(n.get("content") or [], cur)

    walk((doc or {}).get("content") or [])
    return nodes, marks, links, images, " ".join(text), bloks


def main():
    ap = argparse.ArgumentParser(
        description="Build the static data files for the review viewer.")
    # argparse rather than sys.argv[1]: a bare positional happily accepted
    # "--help" as a directory name and wrote 31 MB into a folder called --help.
    ap.add_argument("viewer_dir", nargs="?",
                    default=os.path.join(BASE, "storyblok-viewer", "public",
                                         "data"),
                    help="output directory (default: the viewer's public/data)")
    out_root = ap.parse_args().viewer_dir
    os.makedirs(os.path.join(out_root, "stories"), exist_ok=True)

    routes = {}
    if os.path.exists(ROUTING):
        with open(ROUTING, encoding="utf-8-sig") as f:
            routes = {r["news_id"]: r for r in csv.DictReader(f)}
    shares = defaultdict(list)
    if os.path.exists(PATHS):
        with open(PATHS, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                shares[r["story_id"]] = [r[k] for k in r
                                         if k.startswith("shared_path_") and r[k]]

    # live state from the tracking DB, if it is reachable
    live = {}
    space = ""
    try:
        # db lives beside this file; storyblok_config one level up in scripts/
        import db as tracking
        from storyblok_config import load_config
        space = load_config().get("space_id") or ""
        with tracking.connect() as c:
            c.execute("SET search_path TO migration, public")
            for r in c.execute("""SELECT sharepoint_id, status, sb_story_id,
                                         upload_full_slug
                                  FROM story""").fetchall():
                live[str(r[0])] = {"status": r[1], "sb_story_id": r[2],
                                   "sb_slug": r[3]}
    except Exception as e:              # viewer must build without Postgres
        print(f"  (tracking DB unavailable: {type(e).__name__}) — "
              f"status columns will be blank")

    # live SharePoint URLs, resolved by resolve_media_urls.py
    media_urls = {}
    mu_path = os.path.join(P.MIGRATE, "media_urls.json")
    if os.path.exists(mu_path):
        media_urls = load(mu_path)
        n = sum(1 for v in media_urls.values() if v.get("fetched"))
        print(f"  media URLs available for {n} stories")
    else:
        print("  (no media_urls.json — run resolve_media_urls.py to show images)")

    index, facets = [], defaultdict(Counter)
    files = sorted(n for n in os.listdir(STORIES) if n.endswith(".json"))
    for name in files:
        sid = name[:-5]
        st = load(os.path.join(STORIES, name))
        c = st.get("content") or {}
        r = routes.get(sid, {})
        body = c.get("body") if isinstance(c.get("body"), dict) else {}
        nodes, marks, links, images, text, bloks = analyse(body)

        media = c.get("media") or []
        rt_media = c.get("richtext_media") or []
        roles = Counter(m.get("role") for m in media)
        types = Counter(m.get("media_type") for m in media)
        exts = Counter()
        for m in media + rt_media:
            fn = (m.get("filename") or m.get("local_filename") or "").lower()
            exts[os.path.splitext(fn.split("?")[0])[1] or "(none)"] += 1

        el = set()
        if bloks.get("video_embed"):
            el.add("video_embed")
        if bloks.get("twitter_embed"):
            el.add("twitter_embed")
        pq = c.get("pull_quote")
        if isinstance(pq, dict):
            el.add("pull_quote")
            if pq.get("component_type") == "iframe_embed":
                el.add("iframe_embed")
            if pq.get("component_type") == "twitter_embed":
                el.add("twitter_embed")
        if any(str(k).startswith("video") for k in roles):
            el.add("video_file")
        if types.get("gif"):
            el.add("gif")
        if roles.get("banner"):
            el.add("banner_image")
        if roles.get("medium"):
            el.add("medium_image")
        if roles.get("thumbnail"):
            el.add("thumbnail")
        if len([m for m in media
                if m.get("media_type") in ("image", "gif")]) >= 3:
            el.add("gallery")
        if nodes.get("image"):
            el.add("inline_image")
        if ".pdf" in exts:
            el.add("pdf")
        if ".doc" in exts or ".docx" in exts:
            el.add("doc")
        for n_, e_ in (("table", "table"), ("bullet_list", "bullet_list"),
                       ("ordered_list", "ordered_list"),
                       ("heading", "heading"), ("blockquote", "blockquote")):
            if nodes.get(n_):
                el.add(e_)
        for m_, e_ in (("bold", "bold"), ("italic", "italic"),
                       ("superscript", "superscript")):
            if marks.get(m_):
                el.add(e_)
        link_kinds = Counter()
        for l in links:
            k = classify_link(l["href"])
            if k:
                el.add(k)
                link_kinds[k] += 1
        if c.get("news_in_urdu"):
            el.add("urdu")
        if not media and not rt_media:
            el.add("no_media")

        writer = ((c.get("content_writer") or {}).get("title")
                  or (c.get("author") or {}).get("title") or "")
        author = (c.get("author") or {}).get("title") or ""
        date = (c.get("schedule_start_date") or c.get("sharepoint_created")
                or "")[:10]
        lv = live.get(sid, {})

        rec = {
            "id": int(sid),
            "seq": c.get("sequence_number") or "",
            "title": c.get("title") or "(untitled)",
            "date": date,
            "year": date[:4],
            "writer": writer,
            "author": author,
            "category": (c.get("category") or {}).get("title") or "",
            "region": r.get("region") or "",
            "entity": r.get("entity") or "",
            "department": r.get("department") or "",
            "placement": r.get("level") or "",
            "folder": r.get("folder_path") or "",
            "is_global": r.get("surface_global") == "True",
            "elements": sorted(el),
            "counts": {
                "chars": len(text), "words": len(re.findall(r"\S+", text)),
                "media": len(media), "richtext_media": len(rt_media),
                "links": len(links), "images_inline": len(images),
                "shares": len(shares.get(sid, [])),
            },
            "status": lv.get("status") or "",
            "sb_story_id": lv.get("sb_story_id"),
            "sb_slug": lv.get("sb_slug") or "",
            "excerpt": (c.get("summary") or text)[:220],
        }
        index.append(rec)

        for k in ("region", "entity", "department", "placement", "writer",
                  "category", "year", "status"):
            if rec[k]:
                facets[k][rec[k]] += 1
        for e in el:
            facets["elements"][e] += 1

        # ---- attach live URLs so the viewer shows real pictures
        mu = media_urls.get(sid) or {}
        by_role = mu.get("by_role") or {}
        url_by_file = {e.get("filename"): e.get("url")
                       for lst in by_role.values() for e in lst
                       if e.get("filename") and e.get("url")}
        url_by_srckey = {}
        for m in media + rt_media:
            sk = m.get("source_key")
            if sk:
                url_by_srckey[m.get("filename") or ""] = "https://www.aku.edu" + \
                    re.sub(r" ", "%20", sk)

        def live_url(m):
            fn = m.get("filename") or m.get("local_filename") or ""
            return url_by_file.get(fn) or url_by_srckey.get(fn) or ""

        media_out = [{**m, "live_url": live_url(m)} for m in media]
        rtm_out = [{**m, "live_url": live_url(m)} for m in rt_media]
        # inline <image> nodes: map their local src to a live URL by filename
        src_to_live = {}
        for m in media + rt_media:
            s = m.get("src") or m.get("local_src") or ""
            u = live_url(m)
            if s and u:
                src_to_live[s] = u

        rec["hero"] = next((m["live_url"] for m in media_out
                            if m.get("role") == "banner" and m["live_url"]), "")
        rec["thumb"] = rec["hero"] or next(
            (m["live_url"] for m in media_out if m["live_url"]), "")

        detail = {
            **rec,
            "media_urls_fetched": bool(mu.get("fetched")),
            "sharepoint_page": mu.get("page") or "",
            "page_iframes": mu.get("iframes") or [],
            "unmatched_page_images": mu.get("unmatched_page_images") or [],
            "src_to_live": src_to_live,
            "summary": c.get("summary") or "",
            "subtitle": c.get("subtitle") or "",
            "banner_caption": c.get("banner_caption") or "",
            "sharepoint_url": (SHAREPOINT.format(nid=rec["seq"].upper())
                               if rec["seq"] else ""),
            "sb_editor_url": (EDITOR.format(space=space,
                                            story=rec["sb_story_id"])
                              if rec["sb_story_id"] else ""),
            "richtext": body,
            "media": media_out,
            "richtext_media": rtm_out,
            "links": links,
            "shares": shares.get(sid, []),
            "node_counts": dict(nodes),
            "mark_counts": dict(marks),
            "blok_counts": dict(bloks),
            "extensions": dict(exts),
            "pull_quote": pq if isinstance(pq, dict) else None,
        }
        with open(os.path.join(out_root, "stories", f"{sid}.json"), "w",
                  encoding="utf-8") as f:
            json.dump(detail, f, ensure_ascii=False, separators=(",", ":"))

    index.sort(key=lambda x: (x["date"] or "0000"), reverse=True)
    payload = {
        "generated_for": "AKU news migration review",
        "story_count": len(index),
        "element_labels": ELEMENTS,
        "facets": {k: dict(v.most_common()) for k, v in facets.items()},
        "stories": index,
    }
    p = os.path.join(out_root, "index.json")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    # ---- folder tree, for the structure page
    # After the repo reorg this lives under data/taxonomy/seed/; the other two
    # are where it was before, kept as fallbacks.
    folders_src = next(
        (p for p in (
            os.path.join(P.TAXONOMY, "seed", "folders.json"),
            os.path.join(BASE, "out_folders", "folders.json"),
            os.path.join(os.path.dirname(BASE), "out_folders", "folders.json"),
        ) if os.path.exists(p)),
        "")
    if folders_src:
        tree = load(folders_src)
        counts = Counter()
        for s in index:
            if s["folder"]:
                counts[s["folder"]] += 1
        for f_ in tree.get("folders", []):
            f_["story_count"] = counts.get(f_.get("display_path"), 0)
        with open(os.path.join(out_root, "folders.json"), "w",
                  encoding="utf-8") as f:
            json.dump(tree, f, ensure_ascii=False, separators=(",", ":"))
        print(f"  folder tree -> {len(tree.get('folders', []))} folders")
    else:
        print("  (no out_folders/folders.json — structure page will be empty)")

    print(f"  {len(index)} stories -> {p}  "
          f"({os.path.getsize(p) / 1024 / 1024:.1f} MB)")
    print(f"  detail files -> {os.path.join(out_root, 'stories')}")
    print("\n  element facets:")
    for k, n in facets["elements"].most_common():
        print(f"    {n:>5}  {ELEMENTS.get(k, k)}")
    print(f"\n  writers: {len(facets['writer'])}   "
          f"years: {len(facets['year'])}   "
          f"entities: {len(facets['entity'])}")


if __name__ == "__main__":
    main()
