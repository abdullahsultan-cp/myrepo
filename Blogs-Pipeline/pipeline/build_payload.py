#!/usr/bin/env python3
"""build_payload.py — turn each blog into the blog_article Storyblok expects.

    python Blogs-Pipeline/pipeline/build_payload.py
    -> Blogs-Pipeline/data/payloads/<id>.json

Reads `data/stories/*.json` (our own shape) and writes the real thing: the 15
fields of `blog_article`, and a `body` of bloks.

**Every shape here is copied from the signed-off demo blog**,
`blogs/beyond-the-blame-rethinking-pastoralism-and-environmental-impacts`, not
invented — spacing, the pill row, author_section's "About the / Author", the
comment form's wording. Where the demo shows something our 83 cannot supply,
the field is left empty rather than filled with a guess.

## The fields

    title           Blog Title
    description     Summary — 31 of 83 have one; the demo's is empty too
    date            "Nov 28, 2025", from Schedule Start Date
    read_time       "N min read", 238 wpm + 12s an image
    author          AuthorName
    isGlobal        true for the 71 that route to global/blogs
    banner_image    the file on disk; the asset id is filled in at upload
    thumbnail       empty — no source in SharePoint, and the demo leaves it so
    languages       empty — blogs have no language variants
    show_share      true
    show_similar    true
    similar_show_header  true
    category        EMPTY — category-plugin's value format is still unknown
    isFeatured      EMPTY — featured-plugin, same
    body            the bloks below

`category` and `isFeatured` are the only two fields we have the data for and
cannot fill. Nothing in the space has either set, so there is no example of what
the plugin stores. They are left empty deliberately and filled by an update plan
the day the dev shows us one — that is what `pipeline/migrate/update/` is for.

## The body

    rich_text       the article. Images stay INSIDE it, as decided: rich_text
                    already carries the padding and sizes an image to the
                    content width
    quote_banner    the 17 with a pull quote
    row of pills    the tags, 1 to 4 a blog
    media_section   blog 18's YouTube video
    social_embed    blog 18's Facebook post — never a raw iframe
    author_section  76 have a biography, 80 a photograph
    comment_form    on every one

The demo also pairs images with text in two-column rows and ends with a
horizontal rule and a disclaimer. Neither is reproduced: the two-column pairing
is a hand-built editorial layout we cannot derive from 83 articles, and no blog
carries a disclaimer of its own.
"""

import argparse
import copy
import csv
import json
import math
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "pipeline"))
import _bootstrap

_bootstrap.ensure()

from paths_root import ROOT, P

P.use("blogs")

WORDS_PER_MINUTE = 238
SECONDS_AN_IMAGE = 12


# ------------------------------------------------------------------ spacing
def edges(top=None, left=None, right=None, bottom=None):
    return {"top": top, "left": left, "right": right, "bottom": bottom}


def spacing(m_margin, m_pad, d_margin, d_pad):
    return {"unit": "px",
            "mobile": {"margin": m_margin, "padding": m_pad},
            "desktop": {"margin": d_margin, "padding": d_pad}}


# Straight off the demo blog, blok by blok.
RICH_TEXT_SPACING = spacing(edges(bottom=56), edges(left=20, right=20),
                            edges(bottom=56), edges(left=176, right=176))
PILL_ROW_SPACING = spacing(edges(bottom=56), edges(left=20, right=20),
                           edges(bottom=56), edges(left=80, right=80))
QUOTE_SPACING = spacing(edges(), edges(bottom=56), edges(), edges(bottom=56))
WIDE_SPACING = spacing(edges(bottom=56), edges(left=20, right=20),
                       edges(bottom=56), edges(left=80, right=80))
WHITE = {"color": "#ffff", "plugin": "native-color-picker"}


# ------------------------------------------------------------------ helpers
def text_of(node, out=None):
    out = [] if out is None else out
    if isinstance(node, dict):
        if node.get("type") == "text":
            out.append(node.get("text") or "")
        for value in node.values():
            if isinstance(value, (list, dict)):
                text_of(value, out)
    elif isinstance(node, list):
        for child in node:
            text_of(child, out)
    return out


def count_images(node, seen=None):
    seen = [] if seen is None else seen
    if isinstance(node, dict):
        if node.get("type") == "image":
            seen.append(1)
        for value in node.values():
            if isinstance(value, (list, dict)):
                count_images(value, seen)
    elif isinstance(node, list):
        for child in node:
            count_images(child, seen)
    return len(seen)


def read_time(body):
    """"N min read" — 238 words a minute plus 12 seconds an image.

    The demo's own "28 min read" is for 447 words, which is 16 wpm. That is a
    placeholder somebody typed, not a specification, so it is not copied.
    """
    words = len(" ".join(text_of(body)).split())
    seconds = (words / WORDS_PER_MINUTE) * 60 + count_images(body) * SECONDS_AN_IMAGE
    return f"{max(1, math.ceil(seconds / 60))} min read"


def pretty_date(content):
    """"Nov 28, 2025", the demo's format. Falls back through what we hold."""
    for key in ("schedule_start_date", "sharepoint_created", "sharepoint_modified"):
        raw = str(content.get(key) or "").strip()
        if not raw:
            continue
        # SharePoint writes "4/27/2022 12:00:00 PM" — twelve-hour with a
        # meridiem. %H:%M:%S silently matches none of the 83 and the field
        # comes out empty, which is exactly what the first run did.
        for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y",
                    "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt).strftime("%b %d, %Y")
            except ValueError:
                continue
    return ""


def asset_field(filename):
    """An asset the uploader will fill in. `_local` is ours, stripped on upload.

    An empty asset is `{"fieldtype": "asset"}` in Storyblok — that is what the
    demo's untouched `thumbnail` looks like — so an unfilled one is written the
    same way rather than as null.
    """
    if not filename:
        return {"fieldtype": "asset"}
    return {"fieldtype": "asset", "_local": filename}


# -------------------------------------------------------------------- bloks
def pill_row(labels):
    """The tags, as the demo's row of pills.

    One `row_item` a pill, `width_mode: fit` so each hugs its label. Colour is
    left to `variant`; the demo overrides it per pill with a hand-picked
    background, which is an editorial choice and not something to invent 47
    times.
    """
    return {
        "component": "row", "width": "", "height": None, "radius": "",
        "align_items": "", "justify_content": "",
        "background_color": dict(WHITE), "spacing": PILL_ROW_SPACING,
        "items": [{
            "component": "row_item", "width": "", "height": "", "radius": "",
            "width_mode": "fit", "align_items": "", "justify_content": "",
            "spacing": "", "background_color": dict(WHITE),
            "body": [{"component": "pill", "label": label, "variant": "green"}],
        } for label in labels],
    }


def build(story, routing, authors, photos):
    content = story["content"]
    sid = str(content.get("sharepoint_id") or "")
    body_doc = content.get("body") or {}
    route = routing.get(sid, {})

    bloks = [{"component": "rich_text", "content": body_doc,
              "spacing": copy.deepcopy(RICH_TEXT_SPACING),
              "bg_pattern": {"fieldtype": "asset"},
              "pattern_height": None, "pattern_mobile_height": None}]

    # The pull quote arrives as {"type": "richtext", "content": {doc}}, not a
    # string — reading it as one gave 0 quote_banners on the first run.
    # quote_banner's `quote` field is plain text, so the doc is flattened.
    raw_quote = content.get("pull_quote")
    quote = ""
    if isinstance(raw_quote, dict):
        quote = " ".join(text_of(raw_quote.get("content") or raw_quote)).strip()
    elif raw_quote:
        quote = str(raw_quote).strip()
    quote = re.sub(r"\s+", " ", quote).strip()
    if quote:
        # variant is centered | attributed | event. The demo uses `event`
        # because its quote is from a convocation; a blog's is somebody
        # speaking, so `attributed` when we know who and `centered` when we do
        # not. `category` and `date` belong to the event variant and are left
        # out of the other two rather than filled with the blog's own.
        said_by = (content.get("pull_quote_author") or "").strip()
        blok = {"component": "quote_banner", "quote": quote,
                "variant": "attributed" if said_by else "centered",
                "attribution": said_by,
                "portrait": {"fieldtype": "asset"},
                "background_image": {"fieldtype": "asset"},
                "bg_pattern": {"fieldtype": "asset"},
                "spacing": copy.deepcopy(QUOTE_SPACING)}
        bloks.append(blok)

    labels = [t["label"] for t in (content.get("tags") or [])
              if isinstance(t, dict) and t.get("label")]
    if labels:
        bloks.append(pill_row(labels))

    video = (content.get("embed_video") or "").strip()
    if video:
        # The cell holds the same URL twice, comma separated, on the one blog
        # that has it. Take the first and do not repeat it.
        first = video.split(",")[0].strip()
        bloks.append({
            "component": "media_section", "type": "video",
            "video_url": {"url": first, "linktype": "url",
                          "fieldtype": "multilink", "cached_url": first},
            "thumbnail": {"fieldtype": "asset"}, "auto_play": False,
            "show_controls": True, "spacing": copy.deepcopy(WIDE_SPACING)})

    embed = (content.get("embed_code") or "").strip()
    if embed:
        found = re.search(r'src="([^"]+)"', embed)
        url = found.group(1) if found else ""
        if "facebook.com" in url:
            # Never a raw iframe: social_embed is the component for this.
            plain = re.search(r"href=([^&\"]+)", url)
            from urllib.parse import unquote
            bloks.append({"component": "social_embed", "variant": "facebook",
                          "url": unquote(plain.group(1)) if plain else url,
                          "align": "center", "show_text": True, "spacing": ""})

    author_id = str(content.get("author_id") or "").strip()
    bio = (authors.get(author_id, {}).get("Description") or "").strip()
    if bio:
        bio = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", bio)).strip()
    photo = photos.get(author_id)
    if bio or photo:
        bloks.append({"component": "author_section", "title": "About the",
                      "highlight": "Author", "bio": bio,
                      "photo": asset_field(photo), "social_links": []})

    bloks.append({"component": "comment_form", "title": "Add a",
                  "highlight": "Comment",
                  "description": "Enter your details for adding comment.",
                  "submit_label": "Submit"})

    return {
        "component": "blog_article",
        "title": (content.get("title") or "").strip(),
        "description": (content.get("summary") or "").strip(),
        "date": pretty_date(content),
        "read_time": read_time(body_doc),
        "author": (content.get("author") or "").strip(),
        "isGlobal": route.get("placement") == "global",
        "banner_image": asset_field((content.get("banner") or "").strip()
                                    if (content.get("banner") or "").strip()
                                    not in ("", "DOWNLOAD_FAILED") else ""),
        "thumbnail": {"fieldtype": "asset"},
        "languages": [],
        "show_share": True,
        "show_similar": True,
        "similar_show_header": True,
        # Deliberately empty. See the module docstring.
        "category": "",
        "isFeatured": None,
        "body": bloks,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out")
    a = ap.parse_args()

    routing = {}
    rp = os.path.join(P.DATA, "taxonomy", "routing.csv")
    if os.path.exists(rp):
        with open(rp, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                routing[str(row["id"])] = row

    src = os.path.join(P.DATA, "source")
    authors, photos = {}, {}
    ap_path = os.path.join(src, "authors.json")
    if os.path.exists(ap_path):
        with open(ap_path, encoding="utf-8") as f:
            authors = {str(x["ID"]): x for x in json.load(f).get("value", [])}
    pp_path = os.path.join(src, "author_photos.json")
    if os.path.exists(pp_path):
        with open(pp_path, encoding="utf-8") as f:
            photos = json.load(f)

    out_dir = a.out or os.path.join(P.DATA, "payloads")
    os.makedirs(out_dir, exist_ok=True)
    from collections import Counter
    counts, made = Counter(), 0
    for name in sorted(os.listdir(P.STORIES)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(P.STORIES, name), encoding="utf-8") as f:
            story = json.load(f)
        payload = build(story, routing, authors, photos)
        counts.update(b["component"] for b in payload["body"])
        for field in ("description", "date", "read_time", "author"):
            if payload[field]:
                counts["field:" + field] += 1
        counts["isGlobal true"] += bool(payload["isGlobal"])
        counts["banner set"] += "_local" in payload["banner_image"]
        with open(os.path.join(out_dir, name), "w",
                  encoding="utf-8", newline="\n") as f:
            json.dump({"story": {**story, "content": payload}}, f,
                      ensure_ascii=False, indent=2)
        made += 1

    print(f"  {made} payload(s) -> {os.path.relpath(out_dir, ROOT)}\n")
    print("  fields filled:")
    for key in ("field:description", "field:date", "field:read_time",
                "field:author", "isGlobal true", "banner set"):
        print(f"    {key.replace('field:', ''):<22}{counts[key]:>3}/{made}")
    print("\n  bloks built:")
    for comp, n in counts.most_common():
        if not comp.startswith(("field:", "isGlobal", "banner")):
            print(f"    {comp:<22}{n:>3}")
    print("\n  category and isFeatured are EMPTY on all "
          f"{made} — the plugin formats are still unknown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
