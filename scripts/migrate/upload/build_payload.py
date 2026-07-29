#!/usr/bin/env python3
"""
build_payload.py — map a migrated story onto the LIVE news_article schema.

The migration produced a 45-field news_article whose body is a rich-text
document. The live component has 16 fields and body is a `bloks` field
whitelisting only rich_text, box, video, media_section and quote_banner. This
translates between them.

Nothing here modifies a component or a page: it only produces content that fits
the schema that already exists.

Nothing visual is dropped. The source body is walked in order and split so that
every element keeps its position:

    text / lists / tables / inline images / tweets  -> rich_text blok
    YouTube embed                                   -> media_section (type=video)
    hosted video file                               -> media_section (type=video)
    pull quote                                      -> quote_banner blok
    banner image                                    -> banner_image field
    medium image                                    -> media_section (type=image)

Tweets stay as `twitter_embed` bloks nested inside the rich text, because
`rich_text.content` has no restrict_components and the body whitelist excludes
them. That is the only placement available without a schema change.

Used as a library by upload.py; run directly to inspect one story:

    python scripts/migrate/upload/build_payload.py 2198
"""

import json
import math
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import BASE  # noqa: E402
STORIES = os.path.join(BASE, "data", "storyblok_stories")

# ---------------------------------------------------------------- read time
# 238 wpm is the meta-analytic mean for silent reading of English non-fiction
# (Brysbaert 2019, 190 studies). Medium's 265 assumes skimming; 200 is a
# round number with nothing behind it.
#
# Images cost time too, so each one adds 12s — Medium's convention.
#
# For reference, the demo story's hand-typed "28 min read" is 447 words, i.e.
# 16 wpm. It is a placeholder, not a value to reproduce.
WORDS_PER_MINUTE = 238
SECONDS_PER_IMAGE = 12

EMPTY_ASSET = {"id": None, "alt": "", "name": "", "focus": "", "title": "",
               "source": "", "filename": "", "copyright": "",
               "fieldtype": "asset", "meta_data": {}}

# ---------------------------------------------------------------- spacing
# `spacing` is a spacing-field-plugin value. It is NOT optional in practice:
# every blok in the pixel-perfect demo sets it, and a blok without it renders
# with no vertical rhythm at all. These are the demo's exact values, so the
# migrated articles match the Figma spacing rather than collapsing.
#
# Read from the live demo story:
#   rich_text     mobile mb 24, px 20   | desktop mb 56, px 176
#   media_section mobile mb 24          | desktop mb 56
#   quote_banner  mobile mb 24          | desktop mb 56


def _box(top=None, left=None, right=None, bottom=None):
    return {"top": top, "left": left, "right": right, "bottom": bottom}


def spacing(*, mobile_x=None, desktop_x=None, mobile_mb=24, desktop_mb=56):
    return {
        "unit": "px",
        "mobile": {"margin": _box(bottom=mobile_mb),
                   "padding": _box(left=mobile_x, right=mobile_x)},
        "desktop": {"margin": _box(bottom=desktop_mb),
                    "padding": _box(left=desktop_x, right=desktop_x)},
    }


# The article text column is inset; full-width media is not.
SPACING_RICH_TEXT = spacing(mobile_x=20, desktop_x=176)
SPACING_FULL_WIDTH = spacing()

# rich_text background-pattern defaults, also taken from the demo
PATTERN_HEIGHT = "500"
PATTERN_MOBILE_HEIGHT = "0"


def empty_multilink(url=""):
    return {"id": "", "url": url, "linktype": "url" if url else "story",
            "fieldtype": "multilink", "cached_url": url}


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def uid(*parts):
    """Deterministic _uid so re-running produces an identical payload."""
    import hashlib
    h = hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# ------------------------------------------------------------------ helpers

def plain_text(doc):
    out = []

    def walk(n):
        if isinstance(n, list):
            for x in n:
                walk(x)
        elif isinstance(n, dict):
            if n.get("type") == "text" and n.get("text"):
                out.append(n["text"])
            walk(n.get("content") or [])
    walk((doc or {}).get("content") or [])
    return " ".join(out)


def count_words(text):
    r"""Words, not whitespace-separated tokens.

    \S+ counts "—" and "1." as words and inflates short articles. This wants a
    letter or digit to start, and allows apostrophes and hyphens inside.
    """
    return len(re.findall(r"[^\W\d_][\w'’‐-―-]*|\d[\d.,]*",
                          text or "", re.UNICODE))


def read_time(text, *, images=0, extra_text=""):
    """Minutes to read the prose, plus 12s per image, rounded up."""
    words = count_words(text) + count_words(extra_text)
    seconds = (words / WORDS_PER_MINUTE) * 60 + images * SECONDS_PER_IMAGE
    return f"{max(1, math.ceil(seconds / 60))} min read"


def format_date(iso):
    if not iso:
        return ""
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%b %d, %Y")
    except ValueError:
        return ""


def find_embeds(node):
    """Return the component names of any bloks nested in this top-level node."""
    found = []

    def walk(n):
        if isinstance(n, list):
            for x in n:
                walk(x)
        elif isinstance(n, dict):
            if n.get("component"):
                found.append(n)
            walk(n.get("attrs", {}).get("body") or [])
            walk(n.get("content") or [])
    walk(node)
    return found


def doc_of(nodes):
    return {"type": "doc", "content": nodes}


def has_visible_content(nodes):
    """A paragraph holding only hard_breaks is not worth its own blok."""
    return bool(plain_text(doc_of(nodes)).strip()) or any(
        n.get("type") in ("image", "table", "bullet_list", "ordered_list",
                          "blockquote", "heading", "blok")
        for n in nodes if isinstance(n, dict))


# ------------------------------------------------------------------ bloks

def rich_text_blok(sid, idx, nodes):
    return {"_uid": uid(sid, "rt", idx), "component": "rich_text",
            "content": doc_of(nodes),
            "bg_pattern": dict(EMPTY_ASSET),
            "pattern_height": PATTERN_HEIGHT,
            "pattern_mobile_height": PATTERN_MOBILE_HEIGHT,
            "spacing": SPACING_RICH_TEXT}


def media_section_video(sid, idx, *, video_url="", thumbnail=None, title="",
                        description=""):
    return {
        "_uid": uid(sid, "ms-video", idx), "component": "media_section",
        "type": "video",
        "title": "", "highlight": "", "description": "",
        "cta_label": "", "cta_link": empty_multilink(),
        "gallery_images": [], "media_cards": [],
        "video_url": empty_multilink(video_url),
        "thumbnail": thumbnail or dict(EMPTY_ASSET),
        "video_title": title, "video_description": description,
        "auto_play": False, "show_controls": True,
        "bg_pattern": dict(EMPTY_ASSET),
        "pattern_position": "top", "pattern_opacity": False,
        "spacing": SPACING_FULL_WIDTH,
    }


def media_section_images(sid, idx, assets, *, title="", description=""):
    """type=image for a single asset, type=gallery for several."""
    return {
        "_uid": uid(sid, "ms-img", idx), "component": "media_section",
        "type": "gallery" if len(assets) > 1 else "image",
        "title": title, "highlight": "", "description": description,
        "cta_label": "", "cta_link": empty_multilink(),
        "gallery_images": assets, "media_cards": [],
        "video_url": empty_multilink(),
        "thumbnail": dict(EMPTY_ASSET),
        "video_title": "", "video_description": "",
        "auto_play": False, "show_controls": True,
        "bg_pattern": dict(EMPTY_ASSET),
        "pattern_position": "top", "pattern_opacity": False,
        "spacing": SPACING_FULL_WIDTH,
    }


def quote_banner_blok(sid, quote, attribution, date, category):
    return {
        "_uid": uid(sid, "quote"), "component": "quote_banner",
        "variant": "attributed" if attribution else "centered",
        "quote": quote, "attribution": attribution or "",
        "date": date or "", "category": category or "",
        "portrait": dict(EMPTY_ASSET),
        "background_image": dict(EMPTY_ASSET),
        "spacing": SPACING_FULL_WIDTH,
    }


# ------------------------------------------------------------------ main map

def build(story, route, *, assets=None, entity_slug=None, warn=None):
    """assets: {(role, filename): <storyblok asset object>} for uploaded media."""
    assets = assets or {}
    warn = warn if warn is not None else []
    c = story.get("content") or {}
    sid = str(c.get("sharepoint_id") or "")

    src_body = c.get("body") if isinstance(c.get("body"), dict) else {}
    text = plain_text(src_body)

    # ---- media by role
    by_role = {}
    for m in c.get("media") or []:
        by_role.setdefault(m.get("role"), []).append(m)

    def asset_for(m):
        key = (m.get("role"), m.get("filename"))
        a = assets.get(key)
        if a:
            return a
        warn.append(f"asset not uploaded: {m.get('role')}/{m.get('filename')}")
        return None

    banner = None
    for m in by_role.get("banner", []):
        banner = asset_for(m)
        if banner:
            # captions have no field on news_article; the asset carries them
            banner = dict(banner,
                          alt=m.get("alt") or banner.get("alt") or "",
                          title=m.get("caption") or banner.get("title") or "")
        break

    # ---- walk the body in order, splitting out what must become its own blok
    body, buf, idx = [], [], 0
    for node in (src_body.get("content") or []):
        embeds = [e for e in find_embeds(node)
                  if e.get("component") == "video_embed"]
        if embeds:
            if has_visible_content(buf):
                body.append(rich_text_blok(sid, idx, buf))
                idx += 1
            buf = []
            for e in embeds:
                url = e.get("embed_url") or ""
                if not url and e.get("video_id"):
                    url = f"https://www.youtube.com/watch?v={e['video_id']}"
                body.append(media_section_video(sid, idx, video_url=url))
                idx += 1
            continue
        buf.append(node)
    if has_visible_content(buf):
        body.append(rich_text_blok(sid, idx, buf))
        idx += 1

    if not body:                       # never ship an article with no body
        body.append(rich_text_blok(sid, 0, [
            {"type": "paragraph",
             "content": [{"type": "text", "text": c.get("summary") or ""}]}]))
        warn.append("body was empty; fell back to the summary")

    # ---- pull quote: source records no position, so it follows the opening text
    pq = c.get("pull_quote")
    if isinstance(pq, dict):
        if pq.get("type") == "richtext":
            qtext = plain_text(pq.get("content") or {}).strip()
            if qtext:
                body.insert(1 if len(body) > 1 else len(body),
                            quote_banner_blok(sid, qtext,
                                              c.get("pull_quote_author"),
                                              format_date(c.get(
                                                  "schedule_start_date")),
                                              None))
        elif pq.get("type") == "embed":
            # A tweet or iframe. quote_banner cannot hold it and the body
            # whitelist excludes twitter_embed / iframe_embed, so the blok is
            # nested inside a rich_text — rich_text.content sets no
            # restrict_components, which is the only placement available
            # without a schema change. Dropping it would lose a visible
            # element, which is not acceptable.
            blok_node = pq.get("content")
            if isinstance(blok_node, dict) and blok_node.get("type") == "blok":
                body.append(rich_text_blok(sid, f"embed-{idx}", [blok_node]))
                idx += 1
                warn.append(
                    f"pull_quote {pq.get('component_type')} nested inside "
                    "rich_text; ask the dev to whitelist it on news_article."
                    "body for a cleaner placement")
            else:
                warn.append("pull_quote embed had no blok payload; dropped")

    # ---- hosted video files
    for role, items in by_role.items():
        if not str(role).startswith("video"):
            continue
        for m in items:
            a = asset_for(m)
            body.append(media_section_video(
                sid, idx, video_url=(a or {}).get("filename", ""),
                title=m.get("caption") or ""))
            idx += 1

    # ---- medium image: no field of its own, so it becomes a media_section
    med = [a for a in (asset_for(m) for m in by_role.get("medium", [])) if a]
    if med:
        body.append(media_section_images(
            sid, idx, med,
            description=(c.get("medium_image_caption") or "")))
        idx += 1

    if by_role.get("thumbnail"):
        warn.append("thumbnail image has no field on news_article; skipped")

    content = {
        "component": "news_article",
        "_uid": uid(sid, "root"),
        "title": c.get("title") or "(untitled)",
        "date": format_date(c.get("schedule_start_date")
                            or c.get("sharepoint_created")),
        "author": ((c.get("author") or {}).get("title") or ""),
        "read_time": read_time(
            text,
            # the lede is on the page, so it counts toward the read
            extra_text=c.get("summary") or "",
            # inline images + banner/medium; each adds 12s
            images=len([m for m in (c.get("media") or [])
                        if m.get("media_type") in ("image", "gif")])),
        "description": (c.get("summary") or "").strip(),
        "body": body,
        "banner_image": banner or dict(EMPTY_ASSET),
        "background_pattern": dict(EMPTY_ASSET),
        "languages": [],
        "entities": entity_slug or "",
        "isGlobal": bool(c.get("global_news")),
        "show_share": True,
        "show_similar": True,
        "similar_show_header": True,
        "show_social": True,
        "social_show_header": True,
    }

    # ---- the 44 Urdu stories carry an alternate-language URL
    urdu = c.get("news_in_urdu")
    if isinstance(urdu, dict) and (urdu.get("url") or urdu.get("description")):
        content["languages"] = [{
            "_uid": uid(sid, "lang-ur"),
            "component": "article_language_link",
            "label": urdu.get("description") or "اردو",
            "link": empty_multilink(urdu.get("url") or ""),
        }]

    if not content["date"]:
        warn.append("no date on the source item")
    if not content["author"]:
        warn.append("no author on the source item")
    if not entity_slug:
        warn.append("no entity: 'entities' left empty")

    return content, warn


def load_story(sid):
    with open(os.path.join(STORIES, f"{sid}.json"), encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        sys.exit("usage: build_payload.py <sharepoint_id>\n"
                 "  prints the news_article payload for one story, e.g. 2198")
    sid = sys.argv[1]
    st = load_story(sid)
    content, warns = build(st, None, entity_slug="medical-college")
    print(json.dumps(content, indent=2, ensure_ascii=False)[:4000])
    print(f"\n--- body: {len(content['body'])} bloks ---")
    for b in content["body"]:
        extra = f" type={b['type']}" if b.get("type") else ""
        print(f"  {b['component']}{extra}")
    print(f"\n--- warnings ({len(warns)}) ---")
    for w in warns:
        print(f"  {w}")
