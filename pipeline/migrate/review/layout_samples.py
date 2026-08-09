#!/usr/bin/env python3
"""
layout_samples.py — the fewest SharePoint pages that show every layout.

For a designer review the question is not "which stories are interesting" but
"what visual arrangements exist". So this scores stories on layout-bearing
features only — hero, secondary image, gallery, inline images, video, tweet,
iframe, table, lists, pull quote, attachments, RTL — and greedy set-covers them.

The result is a handful of live SharePoint URLs that between them contain every
arrangement the design has to handle, so nothing is discovered late.

Usage:
    python scripts/migrate/review/layout_samples.py [--max 12] [--csv]
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
OUT = os.path.join(P.MIGRATE, "layout_samples.csv")
PAGE = "https://www.aku.edu/news/Pages/news_details.aspx?nid={nid}"

# Only things a designer must lay out. Ordered so the label reads well.
LAYOUT = {
    "hero_image": "Hero / banner image",
    "second_image": "Second (medium) image",
    "gallery_3plus": "Gallery — 3+ images",
    "inline_images": "Image inside the body text",
    "video_youtube": "YouTube / iframe video",
    "video_hosted": "Hosted video file",
    "tweet": "Embedded tweet",
    "iframe_other": "Other iframe embed",
    "pull_quote": "Pull quote",
    "table": "Table",
    "bullet_list": "Bulleted list",
    "numbered_list": "Numbered list",
    "headings": "Sub-headings",
    "blockquote": "Block quote",
    "attachment_pdf": "PDF / document attachment",
    "gif": "Animated GIF",
    "rtl_urdu": "Urdu / right-to-left",
    "superscript": "Superscript (citations)",
    "long_read": "Very long article",
    "short_stub": "Very short article",
    "no_media": "No media at all",
}


def analyse(sid, c):
    body = c.get("body") if isinstance(c.get("body"), dict) else {}
    nodes, marks, bloks = Counter(), Counter(), Counter()
    text = []

    def walk(n):
        if isinstance(n, list):
            for x in n:
                walk(x)
        elif isinstance(n, dict):
            if n.get("type"):
                nodes[n["type"]] += 1
            if n.get("component"):
                bloks[n["component"]] += 1
            if n.get("type") == "text" and n.get("text"):
                text.append(n["text"])
            for m in n.get("marks") or []:
                if isinstance(m, dict):
                    marks[m.get("type")] += 1
            walk((n.get("attrs") or {}).get("body") or [])
            walk(n.get("content") or [])
    walk(body.get("content") or [])

    media = c.get("media") or []
    rtm = c.get("richtext_media") or []
    roles = Counter(m.get("role") for m in media)
    types = Counter(m.get("media_type") for m in media)
    exts = Counter(
        os.path.splitext((m.get("filename") or "").lower().split("?")[0])[1]
        for m in media + rtm)
    words = len(re.findall(r"\S+", " ".join(text)))

    f = set()
    if roles.get("banner"):
        f.add("hero_image")
    if roles.get("medium"):
        f.add("second_image")
    if len([m for m in media if m.get("media_type") in ("image", "gif")]) >= 3:
        f.add("gallery_3plus")
    if nodes.get("image"):
        f.add("inline_images")
    if bloks.get("video_embed"):
        f.add("video_youtube")
    if any(str(r).startswith("video") for r in roles):
        f.add("video_hosted")
    if bloks.get("twitter_embed"):
        f.add("tweet")
    pq = c.get("pull_quote")
    if isinstance(pq, dict):
        f.add("pull_quote")
        if pq.get("component_type") == "iframe_embed":
            f.add("iframe_other")
        if pq.get("component_type") == "twitter_embed":
            f.add("tweet")
    if nodes.get("table"):
        f.add("table")
    if nodes.get("bullet_list"):
        f.add("bullet_list")
    if nodes.get("ordered_list"):
        f.add("numbered_list")
    if nodes.get("heading"):
        f.add("headings")
    if nodes.get("blockquote"):
        f.add("blockquote")
    if ".pdf" in exts or ".doc" in exts or ".docx" in exts:
        f.add("attachment_pdf")
    if types.get("gif"):
        f.add("gif")
    if c.get("news_in_urdu"):
        f.add("rtl_urdu")
    if marks.get("superscript"):
        f.add("superscript")
    if words > 2000:
        f.add("long_read")
    if words < 120:
        f.add("short_stub")
    if not media and not rtm:
        f.add("no_media")
    return f, words, len(media) + len(rtm)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=12)
    ap.add_argument("--csv", action="store_true")
    a = ap.parse_args()

    feats, meta = {}, {}
    index = defaultdict(list)
    for name in sorted(os.listdir(STORIES)):
        if not name.endswith(".json"):
            continue
        sid = name[:-5]
        with open(os.path.join(STORIES, name), encoding="utf-8") as f:
            c = json.load(f)["content"]
        fs, words, nmedia = analyse(sid, c)
        feats[sid] = fs
        meta[sid] = {"title": c.get("title") or "", "words": words,
                     "media": nmedia,
                     "seq": c.get("sequence_number") or "",
                     "date": (c.get("schedule_start_date") or "")[:10]}
        for x in fs:
            index[x].append(sid)

    print(f"{'feature':<26} {'stories':>8}")
    print("-" * 40)
    for k in LAYOUT:
        print(f"  {LAYOUT[k]:<26} {len(index.get(k, [])):>6}")

    # greedy cover, rarest feature first, richest story as tie-break
    want = {k for k in LAYOUT if index.get(k)}
    chosen, uncovered = [], set(want)
    while uncovered and len(chosen) < a.max:
        best, gain = None, 0
        for sid, fs in feats.items():
            if sid in chosen:
                continue
            g = len(fs & uncovered)
            if g > gain or (g == gain and g and best
                            and len(feats[sid]) > len(feats[best])):
                best, gain = sid, g
        if not best or not gain:
            break
        chosen.append(best)
        uncovered -= feats[best]

    print(f"\n{'=' * 78}")
    print(f"  {len(chosen)} pages cover {len(want) - len(uncovered)}"
          f"/{len(want)} layouts")
    print(f"{'=' * 78}")
    rows = []
    for i, sid in enumerate(chosen, 1):
        m = meta[sid]
        url = PAGE.format(nid=m["seq"].upper())
        shown = sorted(feats[sid] & want, key=list(LAYOUT).index)
        print(f"\n{i:>2}. story {sid}   {m['date']}   {m['words']} words, "
              f"{m['media']} media")
        print(f"    {m['title'][:84]}")
        print(f"    {url}")
        print(f"    shows: {', '.join(LAYOUT[x] for x in shown)}")
        rows.append({"n": i, "sharepoint_id": sid, "date": m["date"],
                     "title": m["title"], "sharepoint_url": url,
                     "words": m["words"], "media_count": m["media"],
                     "layouts": "; ".join(LAYOUT[x] for x in shown)})

    if uncovered:
        print(f"\n  not covered: {', '.join(LAYOUT[x] for x in sorted(uncovered))}")

    if a.csv:
        with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, lineterminator="\n",
                               fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\n  -> {OUT}")


if __name__ == "__main__":
    main()
