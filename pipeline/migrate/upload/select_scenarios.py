#!/usr/bin/env python3
"""
select_scenarios.py — pick a small set of stories that exercises every feature.

Uploading 3606 stories to validate the mapping is wasteful; uploading 20 random
ones proves nothing. This scores every story against the features that can break
(GIF, gallery, video, tables, PDFs, Urdu, replacement characters, inline images,
links, pull quotes, ...) then greedily picks the smallest set that covers all of
them, so a 20-story test run leaves nothing untested.

Usage:
    python scripts/migrate/upload/select_scenarios.py [--count 20] [--json out.json]

Reads  data/storyblok_stories/ and data/taxonomy/routing/news_routing.csv
Writes a table to stdout and, with --json, the chosen ids plus a coverage matrix.
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import BASE  # noqa: E402

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from paths_root import P  # noqa: E402
STORIES = P.STORIES
ROUTING = os.path.join(P.TAXONOMY, "routing", "news_routing.csv")

# Characters that must survive the round trip. Grouped so one story can prove a
# whole class rather than needing one story per codepoint.
CHAR_CLASSES = {
    "char_curly_quotes": "‘’“”",
    "char_dashes": "–—―‐",
    "char_zero_width": "​﻿­   ",
    "char_accented": "éèöüçñáíó",
    "char_transliteration": "āīūʿʾḥṣṭ",
    "char_ligature": "ﬁﬂ",
    "char_arabic_urdu": "ء-يٰ-ە",
    "char_cjk": "一-鿿",
    "char_currency_symbol": "£€°™®",
    "char_greek": "α-ω",
    "char_replacement": "�",
    "char_emoji": "\U0001f300-\U0001faff",
    "char_bullet_ellipsis": "•…·",
}


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def rich_text_of(doc):
    """Flatten a richtext document to text, and collect node/mark/link facts."""
    text, nodes, marks, links, images = [], Counter(), Counter(), [], []

    def walk(n):
        if isinstance(n, list):
            for x in n:
                walk(x)
            return
        if not isinstance(n, dict):
            return
        t = n.get("type")
        if t:
            nodes[t] += 1
        if t == "text" and n.get("text"):
            text.append(n["text"])
        if t == "image":
            images.append((n.get("attrs") or {}).get("src") or "")
        for m in n.get("marks") or []:
            if isinstance(m, dict):
                marks[m.get("type")] += 1
                if m.get("type") == "link":
                    a = m.get("attrs") or {}
                    links.append({"href": a.get("href") or "",
                                  "linktype": a.get("linktype"),
                                  "target": a.get("target"),
                                  "uuid": a.get("uuid"),
                                  "anchor": a.get("anchor")})
        walk(n.get("content") or [])

    walk(doc.get("content") or [])
    return "\n".join(text), nodes, marks, links, images


def classify_link(href):
    h = (href or "").strip()
    if not h:
        return "empty"
    low = h.lower()
    if low.startswith("mailto:"):
        return "email"
    if low.startswith("#"):
        return "anchor"
    if low.startswith("tel:"):
        return "tel"
    if re.search(r"\.(pdf|docx?|xlsx?|pptx?|zip)(\?|$)", low):
        return "document"
    if low.startswith("/") or "aku.edu" in low:
        return "internal"
    if low.startswith("http"):
        return "external"
    return "other"


def features_for(story, route):
    """Every scenario flag this one story satisfies."""
    c = story.get("content") or {}
    f = set()
    body = c.get("body") if isinstance(c.get("body"), dict) else {}
    text, nodes, marks, links, images = rich_text_of(body)
    blob = "\n".join([c.get("title") or "", c.get("summary") or "", text])

    # ---- media
    media = c.get("media") or []
    roles = {m.get("role") for m in media}
    types = {m.get("media_type") for m in media}
    if not media:
        f.add("media_none")
    if "banner" in roles:
        f.add("media_banner")
    if "medium" in roles:
        f.add("media_medium")
    if "thumbnail" in roles:
        f.add("media_thumbnail")
    if any(str(r).startswith("video") for r in roles):
        f.add("media_video_file")
    if "gif" in types:
        f.add("media_gif")
    if len([m for m in media if m.get("media_type") in ("image", "gif")]) >= 3:
        f.add("media_gallery")           # enough images to need media_section
    if c.get("richtext_media"):
        f.add("media_richtext")
    for m in (c.get("richtext_media") or []) + media:
        fn = (m.get("filename") or "").lower().split("?")[0]
        if fn.endswith(".pdf"):
            f.add("media_pdf")
        if fn.endswith((".doc", ".docx")):
            f.add("media_doc")

    # ---- embeds and quotes
    def walk_bloks(o):
        if isinstance(o, list):
            for x in o:
                walk_bloks(x)
        elif isinstance(o, dict):
            comp = o.get("component")
            if comp == "video_embed":
                f.add("embed_video")
            if comp == "twitter_embed":
                f.add("embed_twitter")
            for v in o.values():
                if isinstance(v, (dict, list)):
                    walk_bloks(v)
    walk_bloks(c)
    pq = c.get("pull_quote")
    if isinstance(pq, dict):
        f.add("pull_quote_" + (pq.get("type") or "?"))

    # ---- rich-text structure
    if nodes.get("heading"):
        f.add("rt_heading")
    if nodes.get("bullet_list"):
        f.add("rt_bullet_list")
    if nodes.get("ordered_list"):
        f.add("rt_ordered_list")
    if nodes.get("table"):
        f.add("rt_table")
    if nodes.get("blockquote"):
        f.add("rt_blockquote")
    if nodes.get("image"):
        f.add("rt_inline_image")
    if nodes.get("hard_break", 0) >= 5:
        f.add("rt_hard_breaks")
    if marks.get("bold"):
        f.add("rt_bold")
    if marks.get("italic"):
        f.add("rt_italic")
    if marks.get("superscript"):
        f.add("rt_superscript")
    if marks.get("link"):
        f.add("rt_link")

    # ---- links
    kinds = Counter(classify_link(l["href"]) for l in links)
    for k in ("internal", "external", "anchor", "email", "document"):
        if kinds.get(k):
            f.add(f"link_{k}")

    # ---- characters
    for name, ranges in CHAR_CLASSES.items():
        pat = f"[{ranges}]" if "-" in ranges else f"[{re.escape(ranges)}]"
        try:
            if re.search(pat, blob):
                f.add(name)
        except re.error:
            pass

    # ---- taxonomy placement
    if route:
        f.add("place_" + (route.get("level") or "?"))
        if route.get("department"):
            f.add("has_department")
        if route.get("surface_global") == "True":
            f.add("flag_global")
        if route.get("entity_source") == "recovered":
            f.add("entity_recovered")
    if c.get("news_in_urdu"):
        f.add("lang_urdu")
    if c.get("category"):
        f.add("has_category")
    if c.get("additional_entities"):
        f.add("has_share_targets")
    if c.get("subtitle"):
        f.add("has_subtitle")
    if c.get("banner_caption"):
        f.add("has_banner_caption")

    # ---- size extremes
    n = len(text)
    if n > 12000:
        f.add("size_very_long")
    elif n < 400:
        f.add("size_very_short")

    return f, {"chars": len(text), "media": len(media), "links": len(links),
               "nodes": dict(nodes), "marks": dict(marks),
               "link_kinds": dict(kinds), "images": images}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--json")
    a = ap.parse_args()

    routes = {}
    if os.path.exists(ROUTING):
        with open(ROUTING, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                routes[r["news_id"]] = r

    per_story, feature_index = {}, defaultdict(list)
    stats = {}
    for name in sorted(os.listdir(STORIES)):
        if not name.endswith(".json"):
            continue
        sid = name[:-5]
        st = load(os.path.join(STORIES, name))
        feats, meta = features_for(st, routes.get(sid))
        per_story[sid] = feats
        stats[sid] = meta
        for fe in feats:
            feature_index[fe].append(sid)

    all_features = sorted(feature_index)
    print(f"stories: {len(per_story)}   distinct features: {len(all_features)}\n")
    print(f"{'feature':<26} {'stories':>8}   rarity")
    print("-" * 58)
    for fe in sorted(all_features, key=lambda x: len(feature_index[x])):
        n = len(feature_index[fe])
        flag = "  <-- RARE" if n <= 3 else ""
        print(f"  {fe:<26} {n:>6}{flag}")

    # ---- greedy set cover, rarest feature first
    uncovered = set(all_features)
    chosen = []
    while uncovered and len(chosen) < a.count:
        best, gain = None, 0
        for sid, feats in per_story.items():
            if sid in chosen:
                continue
            g = len(feats & uncovered)
            # tie-break toward richer stories so the sample is representative
            if g > gain or (g == gain and g > 0 and best
                            and len(per_story[sid]) > len(per_story[best])):
                best, gain = sid, g
        if not best or gain == 0:
            break
        chosen.append(best)
        uncovered -= per_story[best]

    # ---- pad to --count with SECOND examples of the riskiest features.
    # One story per feature proves the mapping runs; it does not prove the
    # mapping is right. Rare, structurally awkward features get a second
    # witness so a single odd story cannot mask a systemic bug.
    RISKY = {"rt_table", "media_gallery", "media_gif", "media_video_file",
             "embed_video", "media_pdf", "rt_inline_image", "media_richtext",
             "lang_urdu", "rt_ordered_list", "media_thumbnail",
             "char_replacement", "char_arabic_urdu", "rt_blockquote",
             "pull_quote_embed", "char_transliteration", "link_internal"}
    covered_times = Counter()
    for sid in chosen:
        covered_times.update(per_story[sid] & RISKY)
    while len(chosen) < a.count:
        best, score = None, 0
        for sid, feats in per_story.items():
            if sid in chosen:
                continue
            # value a story by how many risky features it would give a 2nd or
            # 3rd witness to, weighted toward the least-witnessed
            s = sum(1.0 / (1 + covered_times[f]) for f in feats & RISKY)
            if s > score:
                best, score = sid, s
        if not best or score == 0:
            break
        chosen.append(best)
        covered_times.update(per_story[best] & RISKY)

    print(f"\n{'=' * 74}\n  {len(chosen)} STORIES COVER "
          f"{len(all_features) - len(uncovered)}/{len(all_features)} FEATURES"
          f"\n{'=' * 74}")
    for i, sid in enumerate(chosen, 1):
        r = routes.get(sid, {})
        m = stats[sid]
        print(f"\n  {i:>2}. id {sid:<5} {len(per_story[sid]):>2} features  "
              f"{m['chars']:>6} chars  {m['media']} media  {m['links']} links")
        print(f"      {r.get('title', '')[:70]}")
        print(f"      -> {r.get('folder_path', '?')}")
        notable = sorted(f for f in per_story[sid]
                         if len(feature_index[f]) <= 40)
        if notable:
            print(f"      proves: {', '.join(notable[:9])}")

    if uncovered:
        print(f"\n  NOT COVERED ({len(uncovered)}): {', '.join(sorted(uncovered))}")
        for fe in sorted(uncovered):
            print(f"      {fe}: only in {feature_index[fe][:5]}")

    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        with open(a.json, "w", encoding="utf-8", newline="\n") as f:
            json.dump({
                "chosen": chosen,
                "feature_counts": {k: len(v) for k, v in feature_index.items()},
                "coverage": {sid: sorted(per_story[sid]) for sid in chosen},
                "uncovered": sorted(uncovered),
                "stats": {sid: stats[sid] for sid in chosen},
            }, f, indent=2, ensure_ascii=False)
        print(f"\n  -> {a.json}")


if __name__ == "__main__":
    main()
