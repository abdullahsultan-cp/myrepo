#!/usr/bin/env python3
"""build_payload.py — a built story becomes a live `event_article`.

    python Events-Pipeline/pipeline/build_payload.py 8      # inspect one event

Used as a library by the upload. Given one payload from `data/stories/` it
returns the `content` dict for Storyblok, mapped onto the 21 fields
`event_article` really has.

## Why events has its own rather than using the shared one

`pipeline/migrate/upload/build_payload.py` builds a **news_article**: 16 fields,
`entities` as folder ids, `isGlobal`, `languages`, `read_time`, a description
lifted out of paragraph 1, galleries, pull quotes, split sections. `event_article`
shares almost none of that. Bending one builder to serve both would mean a
branch per field, which is what the two rules in ARCHITECTURE.md exist to stop.

## The rules live in one place

Every decision below -- dates, which image is the banner, the registration link,
the opening heading, mode, the four switches -- is imported from
`build_portal.py`, NOT reimplemented. That mapping has already drifted three
times when it existed in two files. The portal is where the rules were developed
and checked against all 2,710 events, so it is the source; if the portal ever
becomes purely a review tool, move them to a `rules.py` that both import.

The reasoning for each is in `config/types/events.json` under `decisions`.

## The body

    rich_text        the opening H1, worded from the tag  ("About this Course")
    rich_text        the converted EventDetail
    media_section    type=video, for the 36 with one

`event_article.body` whitelists box, media_section, quote_banner, rich_text,
social_embed and video. Only two of those are ever used, because the source
bodies contain no images, iframes, tables or headings.

## What this does NOT do

It does not upload. It does not create folders. It returns a dict.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Must follow the path insert above, so the import block cannot be sorted.
# CLAUDE.md 7: `ruff check --fix` has already broken one file this way, by
# hoisting an import above the line that makes it importable.
from build_portal import (  # noqa: I001
    SWITCHES, P, choose_images, clean, dates_for,
    intro_heading, location_for, mode_for, registration_for, strip_html,
)
from text_clean import clean_richtext, looks_encoded

STORIES = P.STORIES

# Copied off events-detail/test. rich_text sits in the mid column here, where
# news uses 176; media_section is full bleed with everything null.
SPACING_TEXT = {
    "unit": "px",
    "mobile": {"margin": {"top": None, "left": None, "right": None, "bottom": 24},
               "padding": {"top": None, "left": 20, "right": 20, "bottom": None}},
    "desktop": {"margin": {"top": None, "left": None, "right": None, "bottom": 56},
                "padding": {"top": None, "left": 80, "right": 80, "bottom": None}},
}
SPACING_FULL = {
    "unit": "px",
    "mobile": {"margin": {"top": None, "left": None, "right": None, "bottom": None},
               "padding": {"top": None, "left": None, "right": None, "bottom": None}},
    "desktop": {"margin": {"top": None, "left": None, "right": None, "bottom": None},
                "padding": {"top": None, "left": None, "right": None, "bottom": None}},
}

# What attach-richtext-media left on every document link at stage 1. The folder
# name is the type's, so this is /events-media/ here and /news-media/ for news.
MEDIA_HREF = re.compile(rf"^/{re.escape(P.type)}-media/", re.I)

EMPTY_ASSET = {"id": None, "alt": "", "name": "", "focus": "", "title": "",
               "source": "", "filename": "", "copyright": "",
               "fieldtype": "asset", "meta_data": {}, "is_external_url": False}


def uid(*parts):
    """Deterministic _uid, so re-running produces an identical payload."""
    import hashlib
    h = hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def multilink(url=""):
    return {"id": "", "url": url, "linktype": "url" if url else "story",
            "fieldtype": "multilink", "cached_url": url}


def as_row(c):
    """The payload's own values, in the shape the shared rules expect.

    dates_for() and registration_for() take an EXPORT row. The payload carries
    the same values under its own keys, so rather than write a second copy of
    either rule this hands them the four columns they read.
    """
    tags = c.get("tags") or []
    label = ""
    if tags and isinstance(tags[0], dict):
        label = tags[0].get("label") or ""
    elif isinstance(tags, str):
        label = tags
    return {
        "StartDate": c.get("start_at") or "",
        "EndDate": c.get("end_at") or "",
        "Registration": c.get("registration") or "",
        "Tags": label,
        "imageurl": c.get("banner") or "",
        "attachment_files": c.get("attachment") or "",
    }


def rich_text(doc, sid, idx):
    return {"_uid": uid(sid, "rt", idx), "component": "rich_text",
            "content": doc, "spacing": SPACING_TEXT,
            "bg_pattern": dict(EMPTY_ASSET), "pattern_height": "",
            "pattern_mobile_height": ""}


def media_section_video(url, sid):
    """type=video, field for field as events-detail/test has it."""
    return {
        "_uid": uid(sid, "video"), "component": "media_section", "type": "video",
        "title": "", "highlight": "", "description": "",
        "cta_label": "", "cta_link": multilink(),
        "gallery_images": [], "gallery_layout": "", "media_cards": [],
        "video_url": multilink(url), "thumbnail": dict(EMPTY_ASSET),
        "video_title": "", "video_description": "",
        "auto_play": False, "show_controls": True,
        "bg_pattern": dict(EMPTY_ASSET),
        "pattern_position": "top", "pattern_opacity": False,
        "spacing": SPACING_FULL,
    }


def image_node(asset, caption=""):
    return {"type": "image",
            "attrs": {"src": asset.get("filename") or "",
                      "alt": asset.get("alt") or "",
                      "title": caption or asset.get("title") or "",
                      "id": asset.get("id")}}


def find_asset(assets, filename):
    """What the uploader actually put in Storyblok for this source file.

    `assets_for()` in the shared uploader keys on (role, source_filename), and
    adds a normalised ("by_key", ...) form for body images whose src was
    rewritten between export and upload. Events records the hero under role
    `banner` and the second image under `attachment` -- exactly the filenames
    from `content.banner` and `content.attachment` -- so the pair matches
    directly. The scan afterwards is the safety net for a renamed role: a miss
    here is silent, and costs the story its image.
    """
    if not filename or not assets:
        return None
    for role in ("banner", "attachment", "richtext"):
        hit = assets.get((role, filename))
        if hit:
            return hit
    for k, v in assets.items():
        if isinstance(k, tuple) and len(k) == 2 and k[1] == filename:
            return v
    return None


def relink_media(node, assets, warn, seen):
    """Point rich-text links at the uploaded asset instead of the local path.

    `attach-richtext-media` rewrote every document link to
    /events-media/<local filename> back at stage 1, when nothing had been
    uploaded and no real URL existed yet. That URL only exists after the asset
    is in Storyblok, which is now -- `assets_for()` has just supplied it.

    Left alone the links 404: 163 documents across 120 events, mostly the
    programmes and registration forms that are the reason those pages exist.
    A file that did not upload keeps its local href and is reported, rather
    than being pointed at a URL Storyblok cannot serve.

    Mutates in place and returns nothing; `seen` collects what was rewritten.
    """
    if isinstance(node, list):
        for v in node:
            relink_media(v, assets, warn, seen)
        return
    if not isinstance(node, dict):
        return
    for mark in (node.get("marks") or []):
        if mark.get("type") != "link":
            continue
        attrs = mark.get("attrs") or {}
        href = attrs.get("href") or ""
        if not MEDIA_HREF.match(href):
            continue
        name = os.path.basename(href.split("?")[0])
        a = find_asset(assets, name)
        if not a:
            warn.append(f"document not uploaded, link left local: {name}")
            continue
        attrs["href"] = a.get("filename") or href
        attrs["linktype"] = "url"
        attrs["target"] = attrs.get("target") or "_blank"
        mark["attrs"] = attrs
        seen.append(name)
    for v in node.values():
        if isinstance(v, (dict, list)):
            relink_media(v, assets, warn, seen)


def build(story, config=None, assets=None, entities=None, is_global=False,
          warn=None):
    """One built payload -> the `content` for a live event_article.

    The signature is the shared uploader's, so `upload.py` can call this or
    `pipeline/migrate/upload/build_payload.py` without knowing which it has.
    `config`, `entities` and `is_global` are accepted and ignored: they belong
    to news_article, and `event_article` has no `entities` and no `isGlobal` --
    `entity` here is plain text, and AdditionalEntity is empty on all 2,710.

    assets: what `assets_for()` returned for this story. An absent file is
        reported and the field left empty rather than pointed at something
        Storyblok cannot serve.

    Returns (content, warnings).
    """
    assets = assets or {}
    warn = warn if warn is not None else []
    c = story.get("content") or {}
    sid = str(c.get("sharepoint_id") or "")
    row = as_row(c)
    d = dates_for(row)

    # ---- body: the opening heading, the converted prose, then any video
    body = [intro_heading(row["Tags"])]
    body[0]["_uid"] = uid(sid, "intro")

    doc = c.get("body") if isinstance(c.get("body"), dict) else {"type": "doc",
                                                                 "content": []}
    # Own a copy, then clean it: entities decoded, markers and invisibles out.
    # 2,353 undecoded entities were reaching these payloads -- see CLAUDE.md 9.
    nodes = clean_richtext(json.loads(json.dumps(doc.get("content") or [])))

    # Document links still point at the stage-1 local path. Now that the files
    # are uploaded, send them at the real asset URL.
    relinked = []
    relink_media(nodes, assets, warn, relinked)

    # The second image, for the 32 events that have both. It goes at the bottom
    # of the rich text, inside it rather than as a standalone image blok.
    _banner, _src, body_img = choose_images(row, set(assets))
    if body_img:
        a = find_asset(assets, body_img)
        if a:
            nodes.append(image_node(a, clean(c.get("image_credit") or "")))
        else:
            warn.append(f"second image not uploaded: {body_img}")

    if nodes:
        body.append(rich_text({"type": "doc", "content": nodes}, sid, 1))
    else:
        warn.append("EventDetail converted to nothing; body is the heading only")

    video = (c.get("video") or "").strip()
    if video:
        body.append(media_section_video(video, sid))

    # ---- banner. imageurl, else the attachment; the uploaded asset or nothing.
    banner_file, banner_src, _ = choose_images(row, set(assets))
    banner = dict(EMPTY_ASSET)
    if banner_file:
        a = find_asset(assets, banner_file)
        if a:
            banner = dict(a, alt=clean(c.get("title") or ""),
                          title=clean(c.get("image_credit") or ""))
        else:
            warn.append(f"banner not uploaded: {banner_file} (from {banner_src})")

    label, link = registration_for(row)

    content = {
        "component": "event_article",
        "_uid": uid(sid, "root"),
        "title": clean(c.get("title") or "") or "(untitled)",
        "description": strip_html(c.get("summary") or ""),
        "event_date": d["event_date"],
        "event_time": d["event_time"],
        "mode": mode_for(c.get("venue") or ""),
        "deadline": d["deadline"],
        "location": location_for(c.get("venue") or ""),
        "event_types": [],          # waiting on the vocabulary; see updates/
        "city": clean(c.get("city") or ""),
        "entity": clean(c.get("entity") or ""),
        "start_at": d["start_at"],
        "end_at": d["end_at"],
        "register_label": label,
        "register_link": multilink(link),
        "banner_image": banner,
        "body": body,
        **SWITCHES,
    }

    if not content["title"] or content["title"] == "(untitled)":
        warn.append("no title on the source item")
    if not content["start_at"]:
        warn.append("no StartDate")
    if not content["location"]:
        warn.append("Venue strips to nothing")
    # Nothing still shaped like markup may reach a page. Reported rather than
    # shipped silently -- this is the check CLAUDE.md 9 asks every type to make.
    left = looks_encoded(json.dumps(content, ensure_ascii=False))
    if left:
        warn.append(f"undecoded entities survived: {sorted(set(left))[:6]}")
    return content, warn


def load_story(sid):
    with open(os.path.join(STORIES, f"{sid}.json"), encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        sys.exit("usage: build_payload.py <event id>\n"
                 "  prints the event_article payload for one event, e.g. 8")
    st = load_story(sys.argv[1])
    content, warns = build(st)
    print(f"title       {content['title'][:70]}")
    print(f"date        {content['event_date']}      time  {content['event_time']}")
    print(f"start_at    {content['start_at']}   end_at  {content['end_at']}")
    print(f"deadline    {content['deadline']}      mode  {content['mode']}")
    print(f"location    {content['location'][:60]}")
    print(f"city        {content['city']}      entity  {content['entity'][:40]}")
    print(f"register    {content['register_label']!r} -> "
          f"{content['register_link']['url'][:60]}")
    print(f"banner      id={content['banner_image']['id']}")
    print("switches    " + "  ".join(f"{k}={v}" for k, v in SWITCHES.items()))
    print(f"\n--- body: {len(content['body'])} bloks ---")
    for b in content["body"]:
        extra = f" type={b['type']}" if b.get("type") else ""
        pad = ((b.get("spacing") or {}).get("desktop", {})
               .get("padding") or {}).get("left")
        n = len((b.get("content") or {}).get("content") or []) if b.get("content") else 0
        print(f"  {b['component']:<16}{extra:<14} desktop-pad-x={pad}"
              + (f"  {n} node(s)" if n else ""))
    print(f"\n--- warnings ({len(warns)}) ---")
    for w in warns:
        print(f"  {w}")
