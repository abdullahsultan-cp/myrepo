#!/usr/bin/env python3
"""
build_payload.py — map a migrated story onto the LIVE news_article schema.

The layout below is the signed-off one, read field by field off the reference
story (news/strengthening-akus-next-generation-of-researchers). Nothing here
modifies a component: it only produces content that fits the schema that exists.

Article fields
    thumbnail      only when the source has one; otherwise empty so the front
                   end can fall back
    description    PARAGRAPH 1, moved out of the body. It appears once, as the
                   intro, and the body starts at paragraph 2
    banner_image   the banner role
    entities       entity FOLDER IDS -- the story's own entity plus the
                   AdditionalEntity share targets. Empty when it owns none
    isGlobal       the story surfaces on global as well as its own entity
    languages      article_language_link per real alternate language, pointing
                   at the uploaded PDF on Storyblok

Body, in document order from paragraph 2
    rich_text      prose, lists, headings, links, bold/italic/underline. No
                   colour or style is altered. TABLES ARE SKIPPED (2 stories;
                   they are rebuilt by hand)
    image          exactly one body image -> its own blok, in place, so the
                   sequence reads text / image / text and never side by side
    iframe         a tweet or other embed, in place, same rule
    quote_banner   every pull quote
    split_section  a quote that comes WITH an image
    media_section  type=video for YouTube and for hosted video
                   type=gallery for TWO OR MORE images, appended AT THE END,
                   before the featured-news section

Spacing is mandatory on every blok, and there are exactly three values. A blok
without one renders with no vertical rhythm at all.

Used as a library by upload.py; run directly to inspect one story:

    python scripts/migrate/upload/build_payload.py 2198
"""

import hashlib
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
# (Brysbaert 2019, 190 studies). Each image adds 12s.
#
# The reference story's hand-typed "28 min read" is 447 words, i.e. 16 wpm. It
# is a placeholder, not a value to reproduce.
WORDS_PER_MINUTE = 238
SECONDS_PER_IMAGE = 12

EMPTY_ASSET = {"id": None, "alt": "", "name": "", "focus": "", "title": "",
               "source": "", "filename": "", "copyright": "",
               "fieldtype": "asset", "meta_data": {}}

# Shared assets, already in the space. Every article uses the same pattern, and
# every quote the same backdrop, so these are ids rather than per-story uploads.
BG_PATTERN = {
    "id": 202607823391189, "alt": "", "name": "", "focus": "", "title": "",
    "source": "", "copyright": "", "fieldtype": "asset", "meta_data": {},
    "filename": "https://a.storyblok.com/f/289824742951963/1440x811/"
                "0305b10066/web-pattern.png",
    "is_external_url": False,
}
QUOTE_BG = {
    "id": 202908142091464, "alt": "", "name": "", "focus": "", "title": "",
    "source": "", "copyright": "", "fieldtype": "asset",
    "meta_data": {"size": "375x184"},
    "filename": "https://a.storyblok.com/f/289824742951963/375x184/"
                "c65753b5c0/quote-backgroung.png",
    "is_external_url": False,
}

# ---------------------------------------------------------------- spacing


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


# The three values the reference story uses, and which blok takes which.
#   TEXT  the narrow reading column
#   FULL  edge to edge
#   MID   inset, but wider than the text column
SPACING_TEXT = spacing(mobile_x=20, desktop_x=176)
SPACING_FULL = spacing()
SPACING_MID = spacing(mobile_x=20, desktop_x=80)

# rich_text background-pattern defaults, also from the reference story
PATTERN_HEIGHT = "500"
PATTERN_MOBILE_HEIGHT = "0"

# Labels that are genuinely a language. Everything else in the
# secondary_language columns is a related link ("Photo gallery", "Speech by the
# chief guest") and is dropped rather than mislabelled as a translation.
LANGUAGES = {"urdu", "sindhi", "arabic", "french", "portuguese", "swahili",
             "farsi", "persian", "pashto", "dari", "gujarati", "hindi"}


def empty_multilink(url=""):
    return {"id": "", "url": url, "linktype": "url" if url else "story",
            "fieldtype": "multilink", "cached_url": url}


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def uid(*parts):
    """Deterministic _uid so re-running produces an identical payload."""
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


def bloks_in(node):
    """Any component bloks nested inside this top-level node."""
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
        n.get("type") in ("bullet_list", "ordered_list", "blockquote",
                          "heading")
        for n in nodes if isinstance(n, dict))


def strip_tables(nodes):
    """Drop table nodes. Two stories have one; both are rebuilt by hand."""
    kept, dropped = [], 0
    for n in nodes:
        if isinstance(n, dict) and n.get("type") == "table":
            dropped += 1
            continue
        kept.append(n)
    return kept, dropped


# ------------------------------------------------------------------ bloks

def rich_text_blok(sid, idx, nodes):
    return {"_uid": uid(sid, "rt", idx), "component": "rich_text",
            "content": doc_of(nodes),
            "bg_pattern": dict(EMPTY_ASSET),
            "pattern_height": PATTERN_HEIGHT,
            "pattern_mobile_height": PATTERN_MOBILE_HEIGHT,
            "spacing": SPACING_TEXT}


def image_blok(sid, idx, asset, *, description="", title=""):
    """A single body image, in place: text / image / text."""
    return {"_uid": uid(sid, "img", idx), "component": "image",
            "image": asset, "variant": "image",
            "title": title, "description": description,
            "link": empty_multilink(), "cta_label": "",
            "spacing": SPACING_MID}


def iframe_blok(sid, idx, src, *, title="", caption=""):
    """A tweet or other embed. In place, never beside the text."""
    return {"_uid": uid(sid, "iframe", idx), "component": "iframe",
            "src": src, "title": title, "caption": caption,
            "heading": "", "description": doc_of([]),
            "display_mode": "inline", "content_align": "left",
            "aspect_ratio": "16:9", "height": "",
            "rounded": True, "loading": "lazy",
            "allow_fullscreen": True, "allow": "", "sandbox": "",
            "referrer_policy": "", "show_play_overlay": True,
            "show_external_link": False, "external_link_label": "",
            "cta_label": "", "thumbnail": dict(EMPTY_ASSET),
            "spacing": SPACING_MID}


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
        "spacing": SPACING_FULL,
    }


def media_section_gallery(sid, idx, assets):
    """Two or more images. Appended at the end, before featured news."""
    return {
        "_uid": uid(sid, "gallery", idx), "component": "media_section",
        "type": "gallery", "gallery_layout": "simple",
        "title": "", "highlight": "", "description": "",
        "cta_label": "", "cta_link": empty_multilink(),
        "gallery_images": assets, "media_cards": [],
        "video_url": empty_multilink(),
        "thumbnail": dict(EMPTY_ASSET),
        "video_title": "", "video_description": "",
        "auto_play": False, "show_controls": True,
        "bg_pattern": dict(EMPTY_ASSET),
        "pattern_position": "top", "pattern_opacity": False,
        "pattern_height": "", "pattern_mobile_height": "",
        "spacing": SPACING_MID,
    }


def quote_banner_blok(sid, quote, attribution, date, category):
    return {
        "_uid": uid(sid, "quote"), "component": "quote_banner",
        "variant": "centered",
        "quote": quote, "attribution": attribution or "",
        "date": date or "", "category": category or "",
        "portrait": dict(EMPTY_ASSET),
        "background_image": dict(QUOTE_BG),
        "spacing": SPACING_FULL,
    }


def split_section_blok(sid, quote, speaker, asset):
    """A quote that comes with an image: quote left, portrait right."""
    return {
        "_uid": uid(sid, "split"), "component": "split_section",
        "layout": "default",
        "image": asset,
        "title": "", "highlight": "",
        "description": quote,
        "cta_label": speaker or "", "cta_link": empty_multilink(),
        "bg_color": {"_uid": uid(sid, "split-bg"), "color": "",
                     "plugin": "storyblok-colorpicker"},
        "spacing": SPACING_MID,
    }


# ------------------------------------------------------------------ main map

def build(story, route, *, assets=None, entities=None, is_global=None,
          warn=None):
    """assets: {(role, filename): <storyblok asset object>} for uploaded media.

    entities: list of entity FOLDER IDS this story is filed under or shared to.
    is_global: the taxonomy's surface_global. Falls back to the source flag when
        not supplied, so running this file directly still produces something.
    """
    assets = assets or {}
    entities = entities or []
    warn = warn if warn is not None else []
    c = story.get("content") or {}
    sid = str(c.get("sharepoint_id") or "")

    src_body = c.get("body") if isinstance(c.get("body"), dict) else {}
    nodes = list(src_body.get("content") or [])

    nodes, n_tables = strip_tables(nodes)
    if n_tables:
        warn.append(f"{n_tables} table(s) skipped, as agreed")

    # ---- media by role
    by_role = {}
    for m in c.get("media") or []:
        by_role.setdefault(m.get("role"), []).append(m)

    def asset_for(role, filename, *, quiet=False):
        a = assets.get((role, filename))
        if a:
            return a
        if not quiet:
            warn.append(f"asset not uploaded: {role}/{filename}")
        return None

    def decorate(a, m):
        """Carry the source caption/alt onto the asset object."""
        if not a:
            return a
        return dict(a, alt=m.get("alt") or a.get("alt") or "",
                    title=m.get("caption") or a.get("title") or "")

    banner = None
    for m in by_role.get("banner", []):
        banner = decorate(asset_for("banner", m.get("filename")), m)
        break

    thumb = None
    for m in by_role.get("thumbnail", []):
        thumb = decorate(asset_for("thumbnail", m.get("filename"),
                                   quiet=True), m)
        break

    # ---- every body image, in document order, resolved to an uploaded asset.
    # A body image node carries attrs.src = "/news-media/<local_filename>",
    # which is the same local_filename the richtext_media entry records, and the
    # asset rows are keyed by it.
    rtm_by_src = {}
    for m in c.get("richtext_media") or []:
        if m.get("local_src"):
            rtm_by_src[m["local_src"]] = m

    def resolve_body_image(node):
        src = (node.get("attrs") or {}).get("src") or ""
        m = rtm_by_src.get(src) or {}
        fn = m.get("local_filename") or os.path.basename(src)
        a = asset_for("richtext", fn)
        return decorate(a, {"alt": (node.get("attrs") or {}).get("alt") or "",
                            "caption": m.get("caption") or ""}) if a else None

    placed = [n for n in nodes if n.get("type") == "image"]

    # Images the export declares but never positions: the medium role, and any
    # richtext image with no node referencing it. They have no source position,
    # so they cannot be placed "under their paragraph" -- they join the gallery.
    unplaced = []
    for m in by_role.get("medium", []):
        a = decorate(asset_for("medium", m.get("filename")), m)
        if a:
            unplaced.append(a)
    placed_srcs = {(n.get("attrs") or {}).get("src") for n in placed}
    for src, m in rtm_by_src.items():
        if src in placed_srcs or m.get("media_type") not in ("image", "gif"):
            continue
        a = asset_for("richtext", m.get("local_filename") or "", quiet=True)
        if a:
            unplaced.append(decorate(a, m))

    total_images = len(placed) + len(unplaced)
    # ONE image -> its own blok in place. TWO OR MORE -> a single gallery at the
    # end, so nothing ever sits side by side mid-article.
    as_gallery = total_images >= 2

    # ---- walk the body, splitting where a blok must stand on its own
    body, buf, idx = [], [], 0
    gallery = []

    def flush():
        nonlocal buf, idx
        if has_visible_content(buf):
            body.append(rich_text_blok(sid, idx, buf))
            idx += 1
        buf = []

    first_para_taken = False
    description = ""

    for node in nodes:
        # paragraph 1 becomes `description` and leaves the body entirely
        if (not first_para_taken and node.get("type") == "paragraph"
                and plain_text(doc_of([node])).strip()):
            description = plain_text(doc_of([node])).strip()
            first_para_taken = True
            continue

        if node.get("type") == "image":
            a = resolve_body_image(node)
            if not a:
                continue
            if as_gallery:
                gallery.append(a)          # pulled to the end
            else:
                flush()
                body.append(image_blok(
                    sid, idx, a,
                    description=(rtm_by_src.get(
                        (node.get("attrs") or {}).get("src"), {})
                        .get("caption") or "")))
                idx += 1
            continue

        embeds = bloks_in(node)
        videos = [e for e in embeds if e.get("component") == "video_embed"]
        frames = [e for e in embeds
                  if e.get("component") in ("twitter_embed", "iframe_embed")]
        if videos or frames:
            flush()
            for e in videos:
                url = e.get("embed_url") or ""
                if not url and e.get("video_id"):
                    url = f"https://www.youtube.com/watch?v={e['video_id']}"
                body.append(media_section_video(sid, idx, video_url=url))
                idx += 1
            for e in frames:
                src = (e.get("embed_url") or e.get("src")
                       or e.get("tweet_url") or "")
                if src:
                    body.append(iframe_blok(sid, idx, src))
                    idx += 1
                else:
                    warn.append(f"{e.get('component')} had no src; dropped")
            continue

        buf.append(node)
    flush()

    # ---- pull quote. The source records no position, so it follows the
    # opening text. With an image it becomes a split_section, otherwise a
    # quote_banner.
    pq = c.get("pull_quote")
    if isinstance(pq, dict):
        if pq.get("type") == "richtext":
            qtext = plain_text(pq.get("content") or {}).strip()
            if qtext:
                speaker = c.get("pull_quote_author") or ""
                portrait = None
                for m in by_role.get("medium", []):
                    portrait = assets.get(("medium", m.get("filename")))
                    break
                at = 1 if len(body) > 1 else len(body)
                if portrait:
                    body.insert(at, split_section_blok(sid, qtext, speaker,
                                                       portrait))
                    # it is the quote's image now, not a gallery member
                    unplaced = [a for a in unplaced
                                if a.get("id") != portrait.get("id")]
                    gallery = [a for a in gallery
                               if a.get("id") != portrait.get("id")]
                else:
                    body.insert(at, quote_banner_blok(
                        sid, qtext, speaker,
                        format_date(c.get("schedule_start_date")), None))
        elif pq.get("type") == "embed":
            node = pq.get("content")
            src = ""
            for e in bloks_in(node if isinstance(node, dict) else {}):
                src = (e.get("embed_url") or e.get("src")
                       or e.get("tweet_url") or "")
                if src:
                    break
            if src:
                body.append(iframe_blok(sid, f"pq-{idx}", src))
                idx += 1
            else:
                warn.append("pull_quote embed had no src; dropped")

    # ---- hosted video files, uploaded to Storyblok and played from there
    for role, items in by_role.items():
        if not str(role).startswith("video"):
            continue
        for m in items:
            a = asset_for(role, m.get("filename"))
            if not a:
                continue
            body.append(media_section_video(
                sid, idx, video_url=a.get("filename", ""),
                title=m.get("caption") or ""))
            idx += 1

    # ---- the gallery goes LAST, before the featured-news section
    if as_gallery:
        imgs = gallery + unplaced
        if len(imgs) >= 2:
            body.append(media_section_gallery(sid, idx, imgs))
            idx += 1
        elif imgs:
            body.append(image_blok(sid, idx, imgs[0]))
            idx += 1
    elif unplaced:
        # a single unpositioned image: put it under the opening text rather
        # than at the very end, which is where the legacy page shows it
        at = 1 if len(body) > 1 else len(body)
        body.insert(at, image_blok(sid, idx, unplaced[0]))
        idx += 1

    if not body:
        body.append(rich_text_blok(sid, 0, [
            {"type": "paragraph",
             "content": [{"type": "text", "text": c.get("summary") or ""}]}]))
        warn.append("body was empty; fell back to the summary")

    # ---- description: paragraph 1, or the summary if the body had no prose
    if not description:
        description = (c.get("summary") or "").strip()
        if description:
            warn.append("no first paragraph; used the summary as description")

    n_images = len([m for m in (c.get("media") or [])
                    + (c.get("richtext_media") or [])
                    if m.get("media_type") in ("image", "gif")])

    content = {
        "component": "news_article",
        "_uid": uid(sid, "root"),
        "title": c.get("title") or "(untitled)",
        "date": format_date(c.get("schedule_start_date")
                            or c.get("sharepoint_created")),
        "author": ((c.get("author") or {}).get("title") or ""),
        "read_time": read_time(plain_text(src_body), images=n_images),
        "description": description,
        "body": body,
        "thumbnail": thumb or dict(EMPTY_ASSET),
        "banner_image": banner or dict(EMPTY_ASSET),
        "background_pattern": dict(BG_PATTERN),
        "languages": [],
        "entities": [str(e) for e in entities],
        "isGlobal": bool(c.get("global_news") if is_global is None
                         else is_global),
        "show_share": True,
        "show_similar": True,
        "similar_show_header": True,
        "show_social": False,
        "social_show_header": False,
    }

    # ---- alternate languages. The PDF is uploaded to Storyblok and linked
    # there, because the SharePoint site is being retired.
    langs = []
    for key in ("news_in_urdu", "secondary_language_2", "secondary_language_3"):
        v = c.get(key)
        if not isinstance(v, dict):
            continue
        label = (v.get("description") or v.get("Description") or "").strip()
        url = (v.get("url") or v.get("Url") or "").strip()
        if not label or not url:
            continue
        # only real languages; "Photo gallery" and friends are dropped
        if not any(w in label.lower() for w in LANGUAGES):
            warn.append(f"{key} {label!r} is not a language; dropped")
            continue
        a = assets.get(("language", os.path.basename(url.split("?")[0])))
        langs.append({
            "_uid": uid(sid, "lang", key),
            "component": "article_language_link",
            "label": label,
            "link": empty_multilink(a["filename"] if a else url),
        })
        if not a:
            warn.append(f"{label} file not uploaded; linked the legacy URL")
    content["languages"] = langs

    if not content["date"]:
        warn.append("no date on the source item")
    if not content["author"]:
        warn.append("no author on the source item")
    if not entities:
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
    content, warns = build(st, None)
    print(f"title       {content['title'][:70]}")
    print(f"date        {content['date']}      read_time  "
          f"{content['read_time']}")
    print(f"description {content['description'][:90]}")
    print(f"thumbnail   {content['thumbnail']['id']}    banner  "
          f"{content['banner_image']['id']}")
    print(f"isGlobal    {content['isGlobal']}   entities {len(content['entities'])}"
          f"   languages {len(content['languages'])}")
    print(f"\n--- body: {len(content['body'])} bloks ---")
    for b in content["body"]:
        sp = b.get("spacing") or b.get("Spacing") or {}
        pad = (sp.get("desktop", {}).get("padding") or {}).get("left")
        extra = f" type={b['type']}" if b.get("type") else ""
        print(f"  {b['component']:<16}{extra:<16} desktop-pad-x={pad}")
    print(f"\n--- warnings ({len(warns)}) ---")
    for w in warns:
        print(f"  {w}")
