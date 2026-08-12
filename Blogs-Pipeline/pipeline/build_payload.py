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

## Where this deliberately differs from the demo

**No horizontal rule.** The demo devotes a whole `rich_text` blok to a single
`horizontal_rule` above the disclaimer. A rich_text field holding no text is an
empty field: it costs a blok, and it appears in the editor as something waiting
to be filled. A separator belongs in the component's styling.

**Images are not paired with text in two-column rows.** The demo does that and
it looks better, but it is a hand-built editorial choice — which image, beside
which paragraph — and there is nothing in 83 articles to derive it from. Images
stay inline, where rich_text sizes them to the content width.

**The one embed is paired**, because there the answer is not a judgement: it
goes beside the paragraph that follows the opening one. Alone at the end of the
article it read as though something were missing.
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

from text_clean import clean_document, clean_text, strip_html

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
DISCLAIMER_SPACING = spacing(edges(bottom=56), edges(left=20, right=20),
                             edges(bottom=56), edges(left=80, right=80))
WHITE = {"color": "#ffff", "plugin": "native-color-picker"}

# Copied verbatim from the demo blog, including the accent on the word itself
# and its wording. The demo's copy ends without a full stop; the owner
# confirmed the sentence is complete, so one is added and nothing else.
DISCLAIMER_LABEL = "Disclaimer"
DISCLAIMER_BODY = (": The views and opinions expressed in this article are "
                   "those of the author and do not necessarily reflect the "
                   "official policy.")
DISCLAIMER_COLOUR = "#008F51"

# The 14 pill variants include four that mean something — admissions_open,
# admissions_closed, audience_eligible, audience_restricted — and must not be
# used for a tag. These ten are the editorial palette.
PILL_VARIANTS = ["green", "lime", "brown", "bronze", "terracotta", "rose",
                 "gold", "taupe", "stone", "neutral"]


def pill_palette(all_labels):
    """{tag: variant}. The same tag is the same colour on every blog.

    Assigned by how often a tag is used, most-used first, cycling through the
    ten variants. So the ten commonest tags are always ten different colours,
    which is where a clash actually shows: `Education`, `Students` and
    `Student life` appear together constantly.

    Hashing the label instead — the obvious approach — gave all three of those
    `bronze`, because 47 labels over 10 colours collide wherever they like.
    Ordering is by (count descending, then label) so it does not depend on
    dictionary order, and `hash()` is avoided entirely: Python randomises
    string hashing per process, so it would recolour every tag on every
    rebuild. That is the phantom-diff trap from build_url_lookup.
    """
    from collections import Counter
    counts = Counter(all_labels)
    ordered = sorted(counts, key=lambda label: (-counts[label], label))
    return {label: PILL_VARIANTS[i % len(PILL_VARIANTS)]
            for i, label in enumerate(ordered)}


# The pill palette. `variant` alone does NOT colour a pill — the first upload
# produced pills with the right variant and no colour at all, and the owner
# fixed them by hand by adding these two fields. Only colours AKU has actually
# chosen are used: both come from the demo blog and the owner's own correction.
PILL_COLOURS = ["#06923E96", "#B2CEFF"]
PILL_TEXT_COLOUR = "#000000"


def colour_field(hexcode):
    return {"color": hexcode, "plugin": "native-color-picker"}


# ------------------------------------------------------------------ helpers
def strip_blank_paragraphs(doc):
    """Drop paragraphs holding nothing but line breaks.

    SharePoint's editor left 79 of them across 30 blogs — one on blog 70 is a
    single paragraph containing seventeen `<br>` and no words. They render as
    a run of empty space, which is what the owner deleted by hand on the first
    three demo stories: blog 70 went from 56 nodes to 36, all 20 of them these.

    A paragraph is only dropped when it has no text AND no image. One holding a
    lone image and nothing else is real content — images live inside the rich
    text here — and removing it would delete a picture.
    """
    if not isinstance(doc, dict):
        return doc
    kept = []
    for node in doc.get("content") or []:
        if isinstance(node, dict) and node.get("type") == "paragraph":
            kids = node.get("content") or []
            has_text = any(isinstance(k, dict) and k.get("type") == "text"
                           and (k.get("text") or "").strip() for k in kids)
            has_image = any(isinstance(k, dict) and k.get("type") == "image"
                            for k in kids)
            if not has_text and not has_image:
                continue
        kept.append(node)
    return {**doc, "content": kept}


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
def pill_row(labels, palette):
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
            # 10px between pills. Set by the owner on one pill as the example
            # and applied to all: without it they run together as one bar.
            "spacing": spacing(edges(), edges(), edges(), edges(left=10)),
            "background_color": dict(WHITE),
            "body": [{"component": "pill", "label": label,
                      "variant": palette.get(label, "green"),
                      "custom_bg_color": colour_field(
                          PILL_COLOURS[i % len(PILL_COLOURS)]),
                      "custom_text_color": colour_field(PILL_TEXT_COLOUR)}],
        } for i, label in enumerate(labels)],
    }


def beside_text(bloks, companion):
    """Put `companion` in a two-column row with the article's second paragraph.

    Returns a new blok list:

        rich_text   the opening paragraph
        row         companion | rich_text of the next paragraph
        rich_text   everything after that

    The split is on paragraph boundaries, so no sentence is cut and the visible
    text is unchanged — only its arrangement. If the article has fewer than
    three paragraphs there is nothing to pair with, and the companion is simply
    appended rather than a layout being forced onto content too short for it.
    """
    first = next((i for i, b in enumerate(bloks)
                  if b.get("component") == "rich_text"), None)
    if first is None:
        return bloks + [companion]
    nodes = ((bloks[first].get("content") or {}).get("content")) or []
    if len(nodes) < 3:
        return bloks + [companion]

    def rich(subset):
        return {**copy.deepcopy(bloks[first]),
                "content": {"type": "doc", "content": subset}}

    row = {"component": "row", "width": "", "height": None, "radius": "",
           "align_items": "center", "justify_content": "center",
           "background_color": dict(WHITE),
           "spacing": copy.deepcopy(WIDE_SPACING),
           "items": [
               {"component": "row_item", "width": "", "radius": "",
                "spacing": "", "background_color": dict(WHITE),
                "body": [companion]},
               {"component": "row_item", "width": "", "radius": "",
                "width_mode": "", "spacing": "",
                "background_color": dict(WHITE),
                "body": [rich(nodes[1:2])]},
           ]}
    return (bloks[:first] + [rich(nodes[:1]), row, rich(nodes[2:])]
            + bloks[first + 1:])


def disclaimer_bloks():
    """The notice that closes every blog.

    **No horizontal rule.** The demo blog has one — `body[7]`, a whole
    `rich_text` blok whose entire content is a `horizontal_rule` — and it was
    copied from there. The owner removed it and the reason is a rule of its own:
    *a rich_text field holding no text is an empty field.* It costs a blok, it
    shows up in the editor as something to fill in, and it exists to draw a
    line. If a separator is wanted above the disclaimer it belongs in the
    component's styling, not in the content.
    """
    notice = {"component": "rich_text", "content": {"type": "doc", "content": [{
        "type": "paragraph", "attrs": {"textAlign": None}, "content": [
            {"type": "text", "text": DISCLAIMER_LABEL,
             "marks": [{"type": "textStyle",
                        "attrs": {"color": DISCLAIMER_COLOUR}}]},
            {"type": "text", "text": DISCLAIMER_BODY}]}]},
        "spacing": copy.deepcopy(DISCLAIMER_SPACING),
        "bg_pattern": {"fieldtype": "asset"},
        "pattern_height": "", "pattern_mobile_height": ""}
    return [notice]


def build(story, routing, authors, photos, palette):
    content = story["content"]
    sid = str(content.get("sharepoint_id") or "")
    body_doc = strip_blank_paragraphs(
        clean_document(content.get("body") or {}))
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
    quote = clean_text(quote)
    if quote:
        # variant is centered | attributed | event. The demo uses `event`
        # because its quote is from a convocation; a blog's is somebody
        # speaking, so `attributed` when we know who and `centered` when we do
        # not. `category` and `date` belong to the event variant and are left
        # out of the other two rather than filled with the blog's own.
        said_by = (content.get("pull_quote_author") or "").strip()
        # **A quote with no portrait is centered.** The owner's rule, and it
        # applies to all 17: `attributed` lays out around a picture of the
        # speaker, and SharePoint has none for any blog. The name still goes in
        # `attribution` — it is displayed either way.
        blok = {"component": "quote_banner", "quote": quote,
                "variant": "centered",
                "attribution": said_by,
                "portrait": {"fieldtype": "asset"},
                "background_image": {"fieldtype": "asset"},
                "bg_pattern": {"fieldtype": "asset"},
                "spacing": copy.deepcopy(QUOTE_SPACING)}
        bloks.append(blok)

    labels = [t["label"] for t in (content.get("tags") or [])
              if isinstance(t, dict) and t.get("label")]
    if labels:
        bloks.append(pill_row(labels, palette))

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
            embed_blok = {"component": "social_embed", "variant": "facebook",
                          "url": unquote(plain.group(1)) if plain else url,
                          "align": "center", "show_text": True, "spacing": ""}
            # Beside the prose, not stranded after it. Left alone at the end of
            # the article it read as though something were missing, which is
            # what the owner rebuilt by hand: opening paragraph, then the embed
            # in a two-column row with the paragraph that follows, then the
            # rest. Splitting on paragraph boundaries reproduced their layout
            # exactly — 466 / 717 / 2,051 characters — with the visible text
            # unchanged.
            bloks = beside_text(bloks, embed_blok)

    # The demo closes with a rule and the disclaimer, then the author, then the
    # comment form. Same order here.
    bloks.extend(disclaimer_bloks())

    author_id = str(content.get("author_id") or "").strip()
    bio = (authors.get(author_id, {}).get("Description") or "").strip()
    if bio:
        # strip_html decodes entities too. Stripping tags alone shipped 88
        # literal "&#160;" into published biographies.
        bio = strip_html(bio)
    photo = photos.get(author_id)
    if bio or photo:
        # With a biography the heading is the demo's generic "About the
        # Author". With only a name and a photograph — four blogs — that
        # heading sits over a blank space and reads as a fault, so the heading
        # becomes the person instead: "Author : Ayesha Mansoor".
        who = clean_text(content.get("author"))
        title, highlight = (("About the", "Author") if bio or not who
                            else ("Author : ", who))
        bloks.append({"component": "author_section", "title": title,
                      "highlight": highlight, "bio": bio,
                      "photo": asset_field(photo), "social_links": []})

    bloks.append({"component": "comment_form", "title": "Add a",
                  "highlight": "Comment",
                  "description": "Enter your details for adding comment.",
                  "submit_label": "Submit"})

    return {
        "component": "blog_article",
        # Kept deliberately: the update engine matches a live blog to its
        # export row on this, and dropping it left every blogs update plan
        # with source=None and no way to find the story it was looking at.
        "sharepoint_id": str(content.get("sharepoint_id") or "").strip(),
        "title": clean_text(content.get("title")),
        "description": clean_text(content.get("summary")),
        "date": pretty_date(content),
        "read_time": read_time(body_doc),
        "author": clean_text(content.get("author")),
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
    # The palette needs every tag in the set before it can order them, so it
    # is built in one pass first rather than per story.
    all_labels = []
    for name in sorted(os.listdir(P.STORIES)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(P.STORIES, name), encoding="utf-8") as f:
            tags = json.load(f).get("content", {}).get("tags") or []
        all_labels += [t["label"] for t in tags
                       if isinstance(t, dict) and t.get("label")]
    palette = pill_palette(all_labels)

    for name in sorted(os.listdir(P.STORIES)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(P.STORIES, name), encoding="utf-8") as f:
            story = json.load(f)
        payload = build(story, routing, authors, photos, palette)
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
