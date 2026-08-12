#!/usr/bin/env python3
"""build_portal.py — one HTML file showing every event as Storyblok will hold it.

    python Events-Pipeline/pipeline/build_portal.py
    -> Events-Pipeline/out/events-portal.html      (double-click, no server)

Four views:

    Archive      all 2,710 events as cards
    Event        one event: the blok sequence beside a preview
    Components   every component the migration uses, and how many events fill
                 each of its fields
    Taxonomy     entity, tag, country and city, each with counts

**Everything we do not have is drawn as a labelled box saying what is absent and
why.** Nothing is invented -- no placeholder ever stands in for real data,
because a portal that looks finished when the data is not is worse than none.

## Why this reads the delivery rather than data/stories/

Blogs' portal reads its built payloads. Events has none yet: no pipeline step has
run. So this reads `Metadata.csv` straight from the delivery and puts each body
through the SHARED converter -- normalize_html then storyblok_richtext, the exact
path the pipeline will take. The preview is therefore what Storyblok will really
hold rather than a guess at it, and every conversion warning is surfaced.

That also makes this useful before the profile is written, which is the point: it
is what tells you what to put in the profile.

Source is looked for in this order:

    --source <dir>
    Events-Pipeline/data/source/            where the repo expects it
    ../Events-*/Events/                     the delivery, wherever it landed
"""

import argparse
import csv
import datetime
import glob
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

from normalize_html import normalize_content_html  # noqa: I001
from paths_root import ROOT, P
from storyblok_richtext import html_to_storyblok_richtext
from text_clean import clean_document, clean_text, strip_html

P.use("events")

OUT = os.path.join(P.PIPELINE, "out", "events-portal.html")
TEMPLATE_FILE = os.path.join(HERE, "portal_template.html")

# Country -> the region folder that exists in the live tree. Read off
# storyblok_space/folder_tree.json, which carries 7: af ea ke pk tz ug uk.
# Portugal and Canada are real values in the export and have NO folder, so they
# are reported unresolved rather than forced into one.
REGION = {
    "Pakistan": "pk", "Kenya": "ke", "Tanzania": "tz", "Uganda": "ug",
    "United Kingdom": "uk", "Afghanistan": "af", "Global": "global",
}

# `Aga Khan University` is the events list's equivalent of news's
# `Entity = "Global"` -- the university itself, not a faculty.
NOT_ENTITIES = {"Aga Khan University"}

# City -> country, used only when Country is blank. Straight from news's
# CITY_TO_REGION, plus the one misspelling this export contains: "Dar es Salam"
# is missing an `a` on 2 rows. Recorded here rather than corrected in the export
# -- CODING_STANDARDS section 4: do not edit source data.
CITY_TO_COUNTRY = {
    "Karachi": "Pakistan", "Islamabad": "Pakistan", "Lahore": "Pakistan",
    "Nairobi": "Kenya", "Mombasa": "Kenya", "Limuru": "Kenya",
    "Dar es Salaam": "Tanzania", "Dar es Salam": "Tanzania",
    "Arusha": "Tanzania", "Dodoma": "Tanzania",
    "Kampala": "Uganda", "Kabul": "Afghanistan", "London": "United Kingdom",
}

# Spelling variants of an entity AKU already has a folder for. This is not a new
# entity -- it maps a variant onto an existing one. Both spellings are AKU's own
# and appear in the same export.
ENTITY_ALIAS = {
    "Network of Quality, Teaching and Learning":
        "Networks of Quality, Teaching and Learning",
}

# Filled at run time from the live tree: entity short code -> the regions that
# actually have an /events folder for it. Nothing is ever created; a code with no
# folder simply is not used.
ENTITY_REGIONS = {}
ENTITY_SHORT = {}

# Where each entity's LOCATED events actually sit, filled by a first pass over
# the export. news rule 5: if an entity's located events are >=60% in one region,
# its unlocated ones go there too. 0.60 is news's own threshold, tuned to keep
# Institute for Educational Development in (63% Pakistan) and School of Nursing
# out (54%, with a real presence in four countries).
ENTITY_DIST = {}
MAJORITY = 0.60


def region_from_columns(r):
    """The region the plain columns give, and whether Global was stated outright.

    Returns (region, explicit_global, why). `region` is None when nothing in the
    row locates the event -- which is what makes rule 5 eligible to fire.
    """
    country = clean(r.get("Country") or "")
    city = clean(r.get("City") or "")
    if country == "Global":
        return None, True, "Country = Global"
    if country:
        reg = REGION.get(country)
        if reg:
            return reg, False, ""
        why = f"Country {country!r} is not an AKU region"
    else:
        why = ""
    if city == "Global":
        return None, True, "City = Global"
    by_city = CITY_TO_COUNTRY.get(city) if city else None
    if by_city:
        return (REGION[by_city], False,
                f"region from City {city!r}; Country was blank")
    return None, False, why


def load_entity_distribution(rows):
    """First pass: count where each entity's located events are.

    Two passes are unavoidable, exactly as in news's build_structure.py -- rule 5
    asks a question about the whole corpus, so it cannot be answered while still
    walking it.
    """
    dist = {}
    for r in rows:
        reg, _explicit, _why = region_from_columns(r)
        if not reg or reg == "global":
            continue
        ent = clean(r.get("Entity") or "")
        ent = ENTITY_ALIAS.get(ent, ent)
        if not ent or ent in NOT_ENTITIES:
            continue
        dist.setdefault(ent, Counter())[reg] += 1
    ENTITY_DIST.update(dist)


def entity_majority(entity):
    """(region, share, total) when an entity is >=60% in one region, else None."""
    d = ENTITY_DIST.get(entity)
    if not d:
        return None
    top, n = d.most_common(1)[0]
    total = sum(d.values())
    share = n / total
    return (top, share, total) if share >= MAJORITY else None


def load_entity_lookup(tree):
    """Entity long name -> short code, and which regions each code exists in.

    The codes come from the news taxonomy (they are recovered from AKU's own
    approver-group names) plus the hand-authored overrides. The REGIONS come from
    the live folder tree, so an entity we have a code for but no folder for is
    correctly treated as absent.
    """
    for rel in ("News-Pipeline/data/taxonomy/intermediate/entity_abbrev.csv",
                "config/entity_abbrev_overrides.csv"):
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("entity_short"):
                    ENTITY_SHORT[clean(row["entity_long"])] = re.sub(
                        r"\s+", "-", row["entity_short"].strip()).lower()
    for full in tree:
        p = full.split("/")
        if len(p) == 5 and p[0] == "regions" and p[2] == "entities" and p[4] == "events":
            ENTITY_REGIONS.setdefault(p[3], set()).add(p[1])

ZW = dict.fromkeys(map(ord, "​﻿­"), None)

# Where the media sits relative to out/. Set at run time from --source so the
# preview shows the real images without embedding a single byte.
MEDIA_REL = ""


def clean(s):
    """Invisibles out, entities decoded, line breaks kept.

    Was a bare `.translate(ZW)`. It is now the shared cleaner, because the same
    fault turns up in every type and CLAUDE.md 9 says so: the events export
    holds 79,495 HTML entities, and 2,353 of them were reaching the built
    payloads -- `&quot;` 1,420 times, `&nbsp;` 795 -- to publish as literal
    text mid-sentence. 606 U+200B still come out, which is why this existed.
    """
    return clean_text(s, collapse=False)


# --------------------------------------------------------------- location
# The words a venue uses when there is no venue. "online" alone was tried first
# and left 208 events reading "Zoom" (73), "Via Zoom" (19), "Virtual" (18),
# "Zoom Live" (8) or a bare meeting URL -- the same kind of venue, differently
# worded. Extended 2026-08-12.
ONLINE_WORD = re.compile(
    r"\b(online|zoom|virtual|ms ?teams|microsoft ?teams|webex|google ?meet"
    r"|livestream|live ?stream)\b", re.I)
PLACE_WORD = re.compile(
    r"\b(hall|room|campus|auditorium|centre|center|building|floor|street|road"
    r"|hotel|university|college|hospital|library|theatre|theater|lab|block"
    r"|wing|club|ground|karachi|nairobi|london|kampala|dar es|arusha|mombasa"
    r"|kabul)\b", re.I)


def location_for(venue):
    """Venue -> the `location` field on event_article.

    Decided 2026-08-12, measured over all 2,710:

        says online, names no place   -> "Online"      715 events
        says online AND names a room  -> unchanged      67 events
        no "online", CTA junk         -> unchanged     423 events
        everything else               -> unchanged   1,504 events

    A venue reading "The session will be conducted online." or "Online via
    Zoom. Free and Open to All. Sign up required" IS online, and the one word
    is what a reader wants. But on 67 events the word arrives inside "Register
    online" beside a real room, and replacing "Lecture Hall 3 & CIME PBL Rooms,
    Medical College" with "Online" would state something untrue -- so a venue
    naming any physical place keeps its text.

    The 423 carrying CTA blocks but no "online" are left exactly as SharePoint
    has them, also by decision: a cut-at-first-marker rule was written and
    measured (231 of 423 shortened, none emptied) and NOT adopted.
    """
    t = strip_html(venue or "")
    if ONLINE_WORD.search(t) and not PLACE_WORD.search(t):
        return "Online"
    return t


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", clean(s).lower()).strip("-")


# --------------------------------------------------------------- rich text
def render_richtext(doc):
    """Storyblok rich text -> HTML, for the preview only."""
    if not isinstance(doc, dict):
        return ""

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
                text = f'<a href="{href}" rel="noopener">{text}</a>'
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
            a = n.get("attrs") or {}
            src = html.escape(a.get("src") or "")
            cap = html.escape(a.get("title") or a.get("alt") or "")
            return (f'<figure class="img"><img src="{src}" alt="" loading="lazy">'
                    f"<figcaption>{cap}</figcaption></figure>")
        return kids

    return "".join(node(n) for n in (doc.get("content") or []))


def convert(raw_html):
    """The exact path the pipeline takes: normalise, convert, clean.

    The clean matters and is not decoration. `pipeline/content/convert_richtext.py`
    now calls `clean_document` inside the shared step, so what the pipeline
    writes is cleaned. This function reaches for the converter directly, so
    without the same call the portal would preview UNCLEANED text while the
    payload publishes cleaned -- the portal-and-builder disagreement that put 88
    literal `&#160;` on published blog pages, only pointing the other way.
    """
    if not (raw_html or "").strip():
        return {"type": "doc", "content": []}, []
    normalised, _stats, _w = normalize_content_html(raw_html)
    result = html_to_storyblok_richtext(normalised)
    return clean_document(result.document), result.warnings


def dates_for(r):
    """The five date fields on event_article, from StartDate and EndDate.

    Two are real Storyblok `datetime` fields and are filled exactly; three are
    plain `text` and are composed here, which is also what lets them be left
    BLANK rather than made up.

        start_at    datetime   StartDate, seconds trimmed. The source carries
                               '2015-03-09 14:30:00'; the field wants
                               '2015-03-09 14:30'.
        end_at      datetime   EndDate, same. 124 events have none.
        event_date  text       'Mar 09, 2015', or 'Mar 09 - Jul 10, 2015' when
                               the event spans days. 871 of 2,710 do, and 195 of
                               those run over a month -- they are courses. A
                               single date on a 16-week course reads as a bug.
        event_time  text       '2:30 PM - 6:30 PM'. The clock times on StartDate
                               and EndDate are the DAILY session, including on a
                               multi-day course: 626 of the 670 multi-day events
                               with times have a start earlier in the day than
                               the end, which is what a class slot looks like.
                               #8 is a 16-week course running 14:30-18:30 daily.
                               Filled wherever SharePoint records a time; blank
                               only for the 246 whose start time is 00:00,
                               because there is nothing to import.
        deadline    text       StartDate, formatted the same way as event_date.
                               The export has no deadline column, so this is a
                               decision rather than source data: deadline carries
                               the event's start date. Filled on all 2,710.
    """
    def parse(v):
        v = (v or "").strip()
        return v[:16] if len(v) >= 16 else ""      # 'YYYY-MM-DD HH:MM'

    def pretty(d):
        try:
            return datetime.datetime.strptime(d[:10], "%Y-%m-%d").strftime("%b %d, %Y")
        except ValueError:
            return ""

    def clock(d):
        try:
            t = datetime.datetime.strptime(d[11:16], "%H:%M")
        except ValueError:
            return ""
        return t.strftime("%I:%M %p").lstrip("0")

    s, e = parse(r.get("StartDate")), parse(r.get("EndDate"))
    same_day = bool(s and e and s[:10] == e[:10])
    has_time = bool(s) and s[11:16] != "00:00"

    # The START DATE alone, never a range -- decided 2026-08-12. An earlier
    # version rendered multi-day events as 'Mar 09 - Jul 10, 2015'. The span is
    # not lost: start_at and end_at carry both ends exactly, and the front end
    # can show the range from those if it ever wants to.
    event_date = pretty(s)

    # Import what SharePoint has. The times are the daily session whether the
    # event runs one day or sixteen weeks, so multi-day is not a special case.
    # Where there is no EndDate, or its time is 00:00, the start time alone is
    # still true and still SharePoint's.
    event_time = ""
    if has_time:
        a = clock(s)
        b = clock(e) if e and e[11:16] != "00:00" else ""
        event_time = f"{a} - {b}" if b and b != a else a

    return {"start_at": s, "end_at": e, "event_date": event_date,
            "event_time": event_time, "deadline": pretty(s),
            "same_day": same_day, "has_time": has_time}


# The export has no `mode` column at all. event_article's own description reads
# "e.g. In-Person, Online, Hybrid", and the field is plain text with no fixed
# options -- checked against the live schema, not assumed.
MODE = "In-Person"
MODE_ONLINE = "Online"


def mode_for(venue):
    """In-Person, unless the venue itself says there is no venue.

    Decided 2026-08-12. `mode` was a flat "In-Person" on all 2,710 while the
    location beside it said "Online", which contradicted itself on the same
    card. The two now come from one reading of Venue, so they cannot disagree.

    Hybrid is never emitted: an event whose venue names both a room and a
    platform keeps its room, so it reads In-Person. The export does not say
    which is the primary mode and there is nothing to derive it from.
    """
    return MODE_ONLINE if location_for(venue) == MODE_ONLINE else MODE

# The four display switches on event_article. All true, by decision. Their
# defaults in the schema are all true too, but they are written explicitly
# rather than left to the component -- a default can change under us, a written
# value cannot.
#
#   show_calendar        the Add to Calendar button, driven by start_at/end_at
#   show_share           the share row
#   show_events          the Similar Events band of related cards
#   show_events_header   that band's title, highlight and description
SWITCHES = {"show_calendar": True, "show_share": True,
            "show_events": True, "show_events_header": True}

# The heading every event page opens with, copied field for field off
# events-detail/test: an H1 reading "About this <Tag>", with the tag word in the
# brand green as a textStyle mark. That mark is the one storyblok_richtext never
# emits -- it is hand-authored because it is design, not content.
#
# The word comes from the SharePoint Tags column, which is single-valued and
# clean. `Other` (268 events) and the one untagged event both read "Event".
GREEN = "#008F51"

# tag -> (plain prefix, the word carrying the green). The default is
# ("About this ", <the tag>), so only the ones that do not read as English are
# listed. `40 years of AKU` drops "this" entirely, which is why this is a pair
# rather than just a word.
HEADING = {
    "Other":           ("About this ", "Event"),
    "":                ("About this ", "Event"),
    "40 years of AKU": ("About ",      "40 Years of AKU"),
    "Grand Rounds":    ("About this ", "Grand Round"),
    "Open day":        ("About this ", "Open Day"),
}


def heading_parts(tag):
    """(prefix, green word) for this event's opening H1."""
    t = (tag or "").strip()
    return HEADING.get(t, ("About this ", t or "Event"))


def heading_text(tag):
    prefix, word = heading_parts(tag)
    return prefix + word


def intro_heading(tag):
    """The constant-shaped opening blok, worded from this event's tag."""
    prefix, word = heading_parts(tag)
    return {
        "component": "rich_text",
        "content": {
            "type": "doc",
            "content": [{
                "type": "heading",
                "attrs": {"level": 1, "textAlign": None},
                "content": [
                    {"type": "text", "text": prefix},
                    {"type": "text", "text": word,
                     "marks": [{"type": "textStyle", "attrs": {"color": GREEN}}]},
                ],
            }],
        },
        "spacing": {
            "unit": "px",
            "mobile": {"margin": {"top": None, "left": None, "right": None,
                                  "bottom": 24},
                       "padding": {"top": None, "left": 20, "right": 20,
                                   "bottom": None}},
            "desktop": {"margin": {"top": None, "left": None, "right": None,
                                   "bottom": 56},
                        "padding": {"top": None, "left": 80, "right": 80,
                                    "bottom": None}},
        },
        "bg_pattern": {"id": None, "alt": None, "name": "", "focus": None,
                       "title": None, "source": None, "filename": "",
                       "copyright": None, "fieldtype": "asset", "meta_data": {}},
        "pattern_height": "",
        "pattern_mobile_height": "",
    }


def intro_html(tag):
    """The same heading, for the portal preview."""
    prefix, word = heading_parts(tag)
    return (f'<div class="prev"><h1>{html.escape(prefix)}'
            f'<span style="color:{GREEN}">{html.escape(word)}'
            '</span></h1></div>')


# SharePoint escapes the colon in hrefs, so a raw value reads `http&#58;//...`.
HREF = re.compile(r'href="([^"]+)"', re.I)
BARE_URL = re.compile(r"""https?://[^\s<>"']+""", re.I)


def registration_for(r):
    """(register_label, register_link_url) from the Registration column.

    Where Registration carries a URL the label is 'Register Now' and the link is
    that URL, written as an EXTERNAL multilink.

    931 events have Registration. 768 carry a real <a href>; of the 163 that do
    not, 31 have a bare URL sitting in the text, which is still SharePoint's
    link and is taken. That leaves 132 whose Registration is prose --
    'Registration is Free', 'Registration closes on February 28'. Those get
    NEITHER field: no link means no button, so a label on its own is dead
    weight. Both are returned empty together.

    93 events carry more than one link (up to 7). The FIRST is taken -- the one
    the registration sentence leads with; the rest stay in the body text.
    """
    raw = (r.get("Registration") or "").strip()
    if not raw:
        return "", ""
    text = html.unescape(raw).replace("&#58;", ":")
    m = HREF.search(text)
    url = m.group(1).strip() if m else ""
    if not url:
        m = BARE_URL.search(re.sub(r"<[^>]+>", " ", text))
        url = m.group(0).strip() if m else ""
    if not url:
        return "", ""
    return "Register Now", html.unescape(url).replace("&amp;", "&")


def choose_images(r, on_disk):
    """Which file is the banner, and what happens to the attachment.

    The rule, as decided:

        imageurl present                 -> banner. The attachment, if any, goes
                                            at the BOTTOM of the rich text.
        imageurl absent, attachment      -> the attachment IS the banner. 933
                                            events would otherwise publish with
                                            no hero while holding an unused image.
        neither                          -> no banner. 12 events.

    Returns (banner_filename, banner_source, body_image_filename).
    """
    img = (r.get("imageurl") or "").strip()
    att = (r.get("attachment_files") or "").strip()
    if img:
        return img, "imageurl", (att or "")
    if att:
        return att, "attachment_files", ""
    return "", "", ""


def place_attachment(doc, filename, on_disk, caption=""):
    """Insert the attachment as an image node inside the rich text.

    It goes at the BOTTOM of the rich text, and only when a banner already exists
    -- 32 events. This is a house convention, not anything the export says:
    `attachment_files` is a SharePoint list attachment, a file clipped to the
    record, and SharePoint stores no position for it. All 2,710 bodies contain
    zero <img> and none names the file, so there is no source position to honour.

    An earlier version put it after the first paragraph. Measured across the 965,
    that landed it between two paragraphs only 51% of the time -- 33% before a
    bullet list and 16% stranded at the end anyway, because 194 of those bodies
    have a single paragraph. The bottom is at least consistent.

    A lone image lives INSIDE the rich text rather than becoming a standalone
    blok, the same rule news follows: the standalone `image` blok renders far too
    large for what is really a mid-article illustration.
    """
    content = list(doc.get("content") or [])
    content.append({
        "type": "image",
        "attrs": {"src": (MEDIA_REL + filename) if filename in on_disk else "",
                  "alt": "", "title": caption or filename, "id": None}})
    return {**doc, "content": content}, "at the bottom of the rich text"


def census(doc, nodes, marks):
    def walk(n):
        if isinstance(n, list):
            for x in n:
                walk(x)
            return
        if not isinstance(n, dict):
            return
        if n.get("type"):
            nodes[n["type"]] += 1
        for m in n.get("marks") or []:
            if isinstance(m, dict) and m.get("type"):
                marks[m["type"]] += 1
        walk(n.get("content") or [])
    walk(doc.get("content") or [])


# ------------------------------------------------------------ the blok plan
def plan_for(r, doc, warns, on_disk, where=""):
    """The bloks and fields this event becomes, each with whether we can fill it.

    state is one of:
        ok         we have everything it needs
        missing    it exists on aku.edu and is not on disk. Ours, and urgent
        blocked    we have the data; event_article has no field for it
        undecided  we have it and somewhere to put it; nobody has said how
        skipped    deliberately dropped -- the data exists nowhere
    """
    bloks = []
    img, src_col, body_img = choose_images(r, on_disk)
    from_att = src_col == "attachment_files"

    # ---- banner
    if not img:
        bloks.append(dict(component="banner_image", state="skipped",
                          note="no imageurl and no attachment in the export",
                          fix="none - 12 of 2,710 have neither; publishes with no hero"))
    elif img.lower().startswith("http"):
        bloks.append(dict(component="banner_image", state="missing", note=img,
                          fix="the cell holds a URL, not a filename - fetch from "
                              "aku.edu while it is still up"))
    elif img in on_disk:
        bloks.append(dict(
            component="banner_image", state="ok",
            note=img + ("   (from attachment_files - this event has no imageurl)"
                        if from_att else ""),
            img=MEDIA_REL + img))
    elif img.replace("%", "_") in on_disk:
        # %2C/%20 in the cell became _2C/_20 when the bundle was written
        alt = img.replace("%", "_")
        bloks.append(dict(component="banner_image", state="ok",
                          note=f"{img}   (on disk as {alt})", img=MEDIA_REL + alt))
    else:
        bloks.append(dict(component="banner_image", state="missing", note=img,
                          fix="named in the export but not on disk"))

    # ---- the constant opening heading, on every event
    _tag = clean(r.get("Tags") or "")
    _prefix, _word = heading_parts(_tag)
    bloks.append(dict(component="rich_text (opening heading)", state="ok",
                      note=f'{_prefix}{_word}  ·  H1, "{_word}" in {GREEN}',
                      html=intro_html(_tag),
                      fix=f"worded from the tag {_tag or '(none)'}"
                          + ("; reworded so it reads as English"
                             if _tag in HEADING and _tag else "")))

    # ---- body
    src_len = len(r.get("EventDetail") or "")
    kinds = Counter(n.get("type") for n in (doc.get("content") or []))
    bloks.append(dict(
        component="rich_text", state="ok",
        note=f"{sum(kinds.values())} block(s) from {src_len:,} characters of source HTML"
             + (f"  ({', '.join(f'{v}x {k}' for k, v in kinds.most_common(4))})"
                if kinds else ""),
        warn="; ".join(sorted({w.split(':')[0] for w in warns})[:4]),
        html=render_richtext(doc)))

    # ---- video
    vid = (r.get("Video") or "").strip()
    if vid:
        bloks.append(dict(component="media_section", state="ok",
                          note="type=video  ·  " + vid[:96], embed=vid))

    # ---- the attachment, when it is NOT the banner: inside the rich text above
    if body_img:
        on = body_img in on_disk
        bloks.append(dict(
            component="image node (in rich_text)", state="ok" if on else "missing",
            note=f"{body_img}  ·  {where or 'not placed'}",
            img=(MEDIA_REL + body_img) if on else "",
            fix="" if on else "named in the export but not on disk",
            warn="this event has BOTH an imageurl and an attachment, so the "
                 "attachment goes in the body. Its position is a house convention "
                 "- SharePoint records none: all 2,710 bodies contain zero <img> "
                 "and never name the file"))

    # ---- fields event_article really has
    def field(label, value, empty_note, fix=""):
        v = clean(value or "")
        bloks.append(dict(component="field: " + label,
                          state="ok" if v else "skipped",
                          note=v[:160] if v else empty_note,
                          fix=fix if v else "nothing to migrate"))

    field("title", r.get("EventTitle") or r.get("Title"), "no title")
    field("description", strip_html(r.get("EventSummary") or ""),
          "EventSummary is empty - 353 events have none")
    D = dates_for(r)
    bloks.append(dict(component="field: start_at / end_at",
                      state="ok" if D["start_at"] else "skipped",
                      note=f"{D['start_at'] or '(none)'}   ->   "
                           f"{D['end_at'] or '(no end date)'}",
                      fix="" if D["end_at"] else "124 events have no EndDate"))
    bloks.append(dict(component="field: event_date", state="ok" if D["event_date"] else "skipped",
                      note=D["event_date"] or "no StartDate",
                      fix="" if D["same_day"] or not D["end_at"]
                          else "spans days, so a range rather than one date"))
    bloks.append(dict(component="field: event_time",
                      state="ok" if D["event_time"] else "skipped",
                      note=D["event_time"] or "left blank",
                      fix="" if D["event_time"]
                          else "SharePoint records no time - StartDate is 00:00"))
    bloks.append(dict(component="field: deadline", state="ok" if D["deadline"] else "skipped",
                      note=D["deadline"] or "no StartDate",
                      fix="the export has no deadline column; this is StartDate, "
                          "by decision"))
    field("city", r.get("City"), "no City - 91 events have none")
    field("entity", r.get("Entity"), "no Entity")

    # location <- Venue, not Country. Every one of the 2,710 events has a venue,
    # and "where is it" on an event page means the room, not the country -- the
    # country is already said by the folder the event lands in.
    raw_venue = r.get("Venue") or ""
    venue = strip_html(raw_venue)
    nlinks = len(re.findall(r"<a ", raw_venue, re.I))
    warn = []
    if nlinks:
        warn.append(f"{nlinks} link(s) in the source Venue are flattened to text - "
                    f"location is a plain text field")
    if len(venue) > 255:
        warn.append(f"{len(venue)} characters; 51 events exceed 255")
    bloks.append(dict(component="field: location", state="ok" if venue else "skipped",
                      note=venue[:200] if venue else "Venue is markup only, no text",
                      fix="; ".join(warn) if venue
                          else "1 of 2,710 strips to nothing"))

    # Country is not lost -- it is what chooses the region folder. It simply has
    # no visible field now that location carries the venue.
    country = clean(r.get("Country") or "")
    bloks.append(dict(component="Country", state="ok" if country else "skipped",
                      note=f"{country} -> routes to the region folder" if country
                           else "no Country",
                      fix="routing only; no visible field on event_article"
                          if country else "68 events have none - unroutable"))

    bloks.append(dict(component="field: mode", state="ok", note=MODE,
                      fix="the export has no mode column; In-Person by decision"))
    bloks.append(dict(
        component="fields: the four switches", state="ok",
        note="  ".join(f"{k}=true" for k in SWITCHES),
        fix="constants, by decision - not from the export"))

    label, link = registration_for(r)
    if (r.get("Registration") or "").strip():
        bloks.append(dict(
            component="field: register_label / register_link",
            state="ok" if link else "skipped",
            note=f"{label}  ->  {link}" if link
                 else "Registration is prose with no URL - both fields left empty",
            fix="" if link else
                "132 events say things like 'Registration is Free'. No link "
                "means no button, so the label is left empty too"))

    tag = clean(r.get("Tags") or "")
    bloks.append(dict(component="field: event_types",
                      state="undecided" if tag else "skipped",
                      note=f"Tags = {tag}" if tag else "this event has no tag",
                      fix="event-types-plugin. The 16 SharePoint tags do not map 1:1 "
                          "to the plugin's slugs - the one known value, conf-workshop, "
                          "reads as Conference AND Workshop merged. Ask the dev for the "
                          "vocabulary." if tag else "1 of 2,710 has no tag"))

    # ---- real data with nowhere to put it
    for label, col, why in (
            ("Contact", "Contact",
             "populated on ALL 2,710 events - 2,046 links across 1,251 of them. "
             "event_article has no contact field at all"),
            ("Registration", "Registration",
             "rich HTML with 901 links across 774 events, and a table in 5. "
             "register_link holds exactly one URL"),
            ("EventSubTitle", "EventSubTitle", "no subtitle field on event_article"),
            ("ImageCredit", "ImageCredit", "no field; 1,538 events name a credit"),
            ("EventSite", "EventSite", "no field; links the event's own microsite"),
            ("EventSubsite", "EventSubsite", "no field"),
            ("OtherCity", "OtherCity", "no field; free text for cities not in the lookup"),
            ("SocialMedia", "SocialMedia", "no field"),
    ):
        v = (r.get(col) or "").strip()
        if not v:
            continue
        bloks.append(dict(component="field: " + label, state="blocked",
                          note=strip_html(v)[:170] or v[:170], fix=why,
                          raw=v if col in ("Venue", "Contact", "Registration") else ""))
    return bloks


# --------------------------------------------------- the SharePoint side
# Every structural thing the source can contain, and what it becomes. The point
# of listing it here rather than deriving it is that a source element with no
# destination is the interesting case, and it has to be spelled out to be seen.
#
#   kind   html   an element inside a rich-text field
#          field  a column on the events list
HTML_MAP = [
    ("p", "paragraph node"), ("div", "paragraph node (converted from div)"),
    ("br", "hard_break, or a paragraph split where doubled"),
    ("strong", "bold mark"), ("em", "italic mark"),
    ("ul", "bullet_list"), ("ol", "ordered_list"), ("li", "list_item"),
    ("a", "link mark"), ("span", "unwrapped, marks kept"),
    ("h1", "heading"), ("h2", "heading"), ("h3", "heading"),
    ("img", "image node"), ("table", "table node"), ("iframe", "embed blok"),
    ("sup", "superscript mark"), ("sub", "subscript mark"),
    ("u", "underline mark"), ("blockquote", "blockquote"),
    ("style", "STRIPPED — presentation only"),
    ("xml", "STRIPPED — Word paste artefact"),
    ("o", "STRIPPED — Word paste artefact"),
    ("w", "STRIPPED — Word paste artefact"),
    ("m", "STRIPPED — Word paste artefact"),
]
HTML_TO = dict(HTML_MAP)

FIELD_MAP = [
    ("EventTitle", "title", "ok"), ("Title", "title (duplicate column)", "skip"),
    ("EventSummary", "description", "ok"),
    ("EventDetail", "body -> rich_text", "ok"),
    ("StartDate", "start_at + event_date", "ok"),
    ("EndDate", "end_at", "ok"),
    ("City", "city", "ok"),
    ("Country", "the region folder — routing only, no visible field", "ok"),
    # `mapped`, not a decision: the destination is settled. The 639 links that
    # flatten are a consequence of location being a plain text field, and they
    # are reported per event rather than held against the whole column -- 2,206
    # of the 2,710 venues contain no link at all.
    ("Venue", "location  (2,206 clean; 504 flatten, losing 639 links)", "ok"),
    ("Entity", "entity", "ok"),
    ("Tags", "event_types", "you"),
    ("imageurl", "banner_image  (1,765 events)", "ok"),
    ("Video", "media_section type=video", "ok"),
    ("attachment_files",
     "banner_image when imageurl is empty (933), else an image node at the "
     "bottom of the rich text (32)", "ok"),
    ("Registration", "register_link — but only ONE url fits", "dev"),
    ("Contact", "NO FIELD", "dev"),
    ("EventSubTitle", "NO FIELD", "dev"),
    ("ImageCredit", "NO FIELD", "dev"),
    ("EventSite", "NO FIELD", "dev"),
    ("EventSubsite", "NO FIELD", "dev"),
    ("OtherCity", "NO FIELD", "dev"),
    ("SocialMedia", "NO FIELD", "dev"),
    ("OnGoingEvent", "no field; 123 events set it", "dev"),
    ("Is Active", "publish state?", "you"),
    ("EventURL", "the SharePoint page, for review only", "skip"),
]

RICH_FIELDS = ("EventDetail", "Venue", "Contact", "Registration")

# The live component schemas, and what fills each field. This lived in the HTML
# template as a second copy and immediately drifted: `location` went on saying
# "Country" for a build after the mapping had moved to Venue. One definition,
# emitted into the page, so the two cannot disagree again.
TARGET_SCHEMA = {
    "event_article": {
        "id": "205403637499544",
        "kind": 'root content type · display name "Event" · ungrouped',
        "note": "Read off the live space. 20 fields — it gained 13 between 4 and "
                "10 August, so re-read it before the first upload.",
        "fields": [
            ("title", "text", "yes", "EventTitle"),
            ("description", "textarea", "", "EventSummary"),
            ("event_date", "text", "", "derived from StartDate"),
            ("event_time", "text", "", "derived from StartDate + EndDate"),
            ("mode", "text", "", "NO SOURCE COLUMN"),
            ("deadline", "text", "", "NO SOURCE COLUMN"),
            ("location", "text", "", "Venue  (HTML flattened to text)"),
            ("event_types", "custom · event-types-plugin", "", "Tags — vocabulary unknown"),
            ("city", "text", "", "City"),
            ("entity", "text", "", "Entity"),
            ("start_at", "datetime", "", "StartDate"),
            ("end_at", "datetime", "", "EndDate"),
            ("register_label", "text", "", "a constant"),
            ("register_link", "multilink", "", "Registration — but it holds 901 links "
                                               "across 774 events and this takes one"),
            ("show_calendar", "boolean", "", "a constant"),
            ("show_share", "boolean", "", "a constant"),
            ("banner_image", "asset · images", "",
             "imageurl, else attachment_files — 2,667 of 2,710 filled"),
            ("body", "bloks", "", "EventDetail"),
            ("show_events", "boolean", "", "a constant"),
            ("show_events_header", "boolean", "", "a constant"),
        ],
    },
    "rich_text": {
        "id": "200451354824924", "kind": 'nestable · group "common"',
        "note": "Carries the whole body. Its spacing is desktop padding-x 80 on the "
                "event page, where news uses 176.",
        "fields": [
            ("content", "richtext", "yes", "the converted EventDetail"),
            ("spacing", "custom · spacing-field-plugin", "",
             "mobile 20 / desktop 80, margin-bottom 24 / 56"),
            ("bg_pattern", "asset · images", "", "left empty on the reference page"),
            ("pattern_height", "number", "", "left empty"),
            ("pattern_mobile_height", "number", "", "left empty"),
        ],
    },
    "media_section": {
        "id": "198318013739056", "kind": 'nestable · group "sections"',
        "note": "type=video for the 36 events with one; type=image is the proposed "
                "home for the 965 second images. No new component needed either way.",
        "fields": [
            ("type", "option · gallery|video|image", "", "video, or image"),
            ("video_url", "multilink", "", "Video"),
            ("gallery_images", "multiasset · images", "", "—"),
            ("thumbnail", "asset · images", "", "—"),
            ("auto_play", "boolean", "", "false"),
            ("show_controls", "boolean", "", "true"),
            ("pattern_position", "option · top|bottom", "", "top"),
            ("spacing", "NOT IN SCHEMA", "",
             "written by every page anyway — ask the dev"),
        ],
    },
}


def source_inventory(r):
    """Every SharePoint element and column this one event actually carries."""
    out = []
    for col in RICH_FIELDS:
        v = r.get(col) or ""
        if not v.strip():
            continue
        tags = Counter(t.lower() for t in re.findall(r"<\s*([a-zA-Z][a-zA-Z0-9]*)", v))
        for t, n in tags.most_common():
            out.append({"n": f"<{t}>", "c": n, "k": "html", "in": col,
                        "to": HTML_TO.get(t, "unmapped — check it")})
    for col, to, state in FIELD_MAP:
        v = (r.get(col) or "").strip()
        if v:
            out.append({"n": col, "c": 1, "k": "field", "in": "", "to": to,
                        "state": state})
    return out


def route(r, tree):
    """Where this event lands. Entity, else region, else global.

        1  the entity's own folder, when it exists for this event's region
        2  the region folder, when the entity has none
        3  global/events

    Nothing is ever created. Every candidate is checked against the live tree, so
    an entity AKU has not made a folder for simply falls through to the region --
    the tree belongs to the front-end developer and this only reads it.
    """
    entity = clean(r.get("Entity") or "")
    entity = ENTITY_ALIAS.get(entity, entity)
    reg, explicit_global, why = region_from_columns(r)

    code = ENTITY_SHORT.get(entity) if entity not in NOT_ENTITIES else None
    has = ENTITY_REGIONS.get(code, set()) if code else set()

    def at(region):
        """The deepest folder that exists for this region: entity, else region."""
        if code and region in has:
            return f"regions/{region}/entities/{code}/events", "entity"
        cand = f"regions/{region}/events"
        return (cand, "region") if cand in tree else ("global/events", "global")

    # ---- an explicit Global wins outright. news orders city-global and
    # entity-global (rules 3 and 4) AHEAD of entity-majority, so a row AKU
    # labelled Global is never second-guessed by an inference.
    if explicit_global:
        return "global/events", "global", why
    if entity in NOT_ENTITIES and not reg:
        return ("global/events", "global",
                "Entity is the university itself, not a faculty")

    # ---- 1 · the region is known: entity folder, else region folder
    if reg:
        target, kind = at(reg)
        if kind == "entity":
            return target, kind, why
        if entity and not code:
            why = (why + "; " if why else "") + \
                  f"{entity!r} has no folder in Storyblok, so it files at region level"
        elif code and reg not in has:
            why = (why + "; " if why else "") + \
                  f"{code} has no folder under regions/{reg} " \
                  f"(only {','.join(sorted(has))})"
        return target, kind, why

    # ---- 2 · no region. If the entity has a folder in exactly ONE region there
    # is only one candidate, which is not an inference.
    if code and len(has) == 1:
        only = next(iter(has))
        return (f"regions/{only}/entities/{code}/events", "entity",
                (why + "; " if why else "")
                + f"no region in the export, and {code} exists only under regions/{only}")

    # ---- 3 · news rule 5, entity-majority. The tree records who OWNS an item,
    # not where it happened, so an entity whose located events are overwhelmingly
    # in one region takes its unlocated ones there too. Recorded as provenance:
    # every placement has to be traceable to the data or to a rule.
    if code:
        m = entity_majority(entity)
        if m:
            top, share, total = m
            target, kind = at(top)
            if kind != "global":
                return (target, kind, (why + "; " if why else "")
                        + f"entity-majority: {entity} is {top} in {share:.0%} of its "
                          f"{total} located events")

    # ---- 4 · nothing locates it
    return "global/events", "global", why or "no Country and no usable City"


def find_source(explicit):
    cands = [explicit, os.path.join(P.PIPELINE, "data", "source")]
    cands += sorted(glob.glob(os.path.join(os.path.dirname(ROOT), "Events-*", "Events")),
                    reverse=True)
    for c in filter(None, cands):
        if os.path.isfile(os.path.join(c, "Metadata.csv")):
            return c
    sys.exit("  no Metadata.csv found. Pass --source <dir>.")


def main():
    global MEDIA_REL
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="folder holding Metadata.csv and media/")
    ap.add_argument("--limit", type=int, help="only the first N, for a quick look")
    a = ap.parse_args()

    src = find_source(a.source)
    print(f"  source  {src}")
    csv.field_size_limit(10 ** 9)
    with open(os.path.join(src, "Metadata.csv"), encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if a.limit:
        rows = rows[:a.limit]
    # Once the export is filed where the repo expects it, the media does not sit
    # beside Metadata.csv -- it goes to assets/Events/media/, which is what
    # P.MEDIA_DIR resolves to. Before that it is still in the delivery folder.
    media_dir = P.MEDIA_DIR if os.path.isdir(P.MEDIA_DIR) else os.path.join(src, "media")
    on_disk = set(os.listdir(media_dir)) if os.path.isdir(media_dir) else set()
    print(f"  media   {media_dir}")
    # Relative, not embedded: opened from disk the browser resolves it and the
    # real image appears, and the HTML stays small.
    MEDIA_REL = os.path.relpath(media_dir, os.path.dirname(OUT)).replace("\\", "/") + "/"
    print(f"  {len(rows)} events, {len(on_disk)} media files")

    tree = set()
    if os.path.exists(P.SPACE_TREE):
        with open(P.SPACE_TREE, encoding="utf-8") as f:
            tree = {x["full_slug"] for x in json.load(f)["folders"]}
    print(f"  {len(tree)} folders in the space snapshot"
          + ("" if "global/events" in tree else "    global/events does NOT exist"))
    load_entity_lookup(tree)
    load_entity_distribution(rows)
    print(f"  {len(ENTITY_SHORT)} entity short codes known, "
          f"{len(ENTITY_REGIONS)} have an /events folder in the space")
    print(f"  {len(ENTITY_DIST)} entities have located events; "
          f"{sum(1 for e in ENTITY_DIST if entity_majority(e))} reach the "
          f"{MAJORITY:.0%} majority threshold")

    nodes, marks, warncount, placed = Counter(), Counter(), Counter(), Counter()
    banner_from = Counter()
    events = []
    for i, r in enumerate(rows, 1):
        if i % 500 == 0:
            print(f"    converted {i}/{len(rows)}")
        doc, warns = convert(r.get("EventDetail") or "")
        _bn, _srccol, body_img = choose_images(r, on_disk)
        where = ""
        if body_img:
            doc, where = place_attachment(
                doc, body_img, on_disk, caption=clean(r.get("ImageCredit") or ""))
            placed[where] += 1
        banner_from[_srccol or "(none)"] += 1
        census(doc, nodes, marks)
        warncount.update(w.split(":")[0] for w in warns)
        bloks = plan_for(r, doc, warns, on_disk, where)
        target, placement, why = route(r, tree)
        src = source_inventory(r)
        events.append({
            "src": src,
            "srcnames": sorted({x["n"] for x in src}),
            "id": r.get("ID") or "",
            "title": clean(r.get("EventTitle") or r.get("Title") or "(untitled)"),
            "subtitle": clean(r.get("EventSubTitle") or ""),
            "summary": strip_html(r.get("EventSummary") or "")[:400],
            "start": (r.get("StartDate") or "")[:16],
            "end": (r.get("EndDate") or "")[:16],
            "event_date": dates_for(r)["event_date"],
            "event_time": dates_for(r)["event_time"],
            "year": (r.get("StartDate") or "")[:4],
            "entity": clean(r.get("Entity") or ""),
            "country": clean(r.get("Country") or ""),
            "city": clean(r.get("City") or ""),
            "tag": clean(r.get("Tags") or ""),
            "venue": strip_html(r.get("Venue") or "")[:200],
            "ongoing": (r.get("OnGoingEvent") or "").strip() == "True",
            "active": (r.get("Is Active") or "").strip() == "True",
            "url": (r.get("EventURL") or "").strip(),
            "target": target, "placement": placement, "why": why,
            # Three states, not two. "no" must mean ONE thing: we worked out
            # where this event goes and that folder is not in the space -- a
            # dev problem. An event we could not route at all has no folder to
            # look for, so it is "n/a" and counts as unrouted instead. Conflating
            # them made the portal report 72 missing folders when the real
            # number was zero.
            "target_exists": ("yes" if target in tree else "no") if target else "n/a",
            "bloks": bloks,
        })

    for e in events:
        e["n"] = {st: sum(1 for b in e["bloks"] if b["state"] == st)
                  for st in ("ok", "missing", "blocked", "undecided", "skipped")}

    def per_field(state=None):
        c = Counter()
        for e in events:
            for b in e["bloks"]:
                if b["component"].startswith("field:") and (
                        state is None or b["state"] == state):
                    c[b["component"][7:]] += 1
        return dict(c.most_common())

    # SharePoint-side census: how many EVENTS carry each element, and how many
    # times in total. Both matter -- <ol> appears 63 times but in only 55 events,
    # and a thing present in one event is a different problem from one in 2,710.
    src_events, src_total, src_where = Counter(), Counter(), {}
    for e in events:
        for x in e["src"]:
            src_total[x["n"]] += x["c"]
            src_where[x["n"]] = x
        for n in e["srcnames"]:
            src_events[n] += 1

    stats = {
        "schema": {k: {"id": v["id"], "kind": v["kind"], "note": v["note"],
                       "fields": [list(f) for f in v["fields"]]}
                   for k, v in TARGET_SCHEMA.items()},
        "source": [
            {"name": n, "events": src_events[n], "total": src_total[n],
             "kind": src_where[n]["k"], "field": src_where[n].get("in", ""),
             "to": src_where[n]["to"], "state": src_where[n].get("state", "")}
            for n in sorted(src_events, key=lambda k: -src_events[k])
        ],
        "source_declared": [
            {"name": n, "to": to, "state": st, "events": src_events.get(n, 0)}
            for n, to, st in FIELD_MAP
        ] + [
            {"name": f"<{t}>", "to": to, "state": "", "events": src_events.get(f"<{t}>", 0)}
            for t, to in HTML_MAP
        ],
        "events": len(events),
        "with_banner": sum(1 for e in events if any(
            b["component"] == "banner_image" and b["state"] == "ok" for b in e["bloks"])),
        "banner_missing": sum(1 for e in events if any(
            b["component"] == "banner_image" and b["state"] == "missing"
            for b in e["bloks"])),
        "with_video": sum(1 for e in events if any(b.get("embed") for b in e["bloks"])),
        "with_attachment": sum(1 for e in events if any(
            b["component"].startswith("image node") for b in e["bloks"])),
        "target_missing": sum(1 for e in events if e["target_exists"] == "no"),
        "unresolved": sum(1 for e in events if e["placement"] == "unresolved"),
        "entities": len({e["entity"] for e in events if e["entity"]}),
        "tags": len({e["tag"] for e in events if e["tag"]}),
        "countries": len({e["country"] for e in events if e["country"]}),
        "cities": len({e["city"] for e in events if e["city"]}),
        "attachment_placement": dict(placed.most_common()),
        "banner_source": dict(banner_from.most_common()),
        "richtext_nodes": dict(nodes.most_common()),
        "richtext_marks": dict(marks.most_common()) or {"(none)": 0},
        "conversion_warnings": dict(warncount.most_common()),
        "components": dict(Counter(
            b["component"] for e in events for b in e["bloks"]
            if not b["component"].startswith("field:")).most_common()),
        "fields": per_field(),
        "fields_ok": per_field("ok"),
        "fields_blocked": per_field("blocked"),
        "fields_undecided": per_field("undecided"),
    }

    stamp = datetime.datetime.now().strftime("%d %b %H:%M")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(TEMPLATE_FILE, encoding="utf-8") as f:
        page = f.read()
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(page
                .replace("__DATA__", json.dumps({"events": events, "stats": stats},
                                                ensure_ascii=False))
                .replace("__BUILD__", stamp))

    size = os.path.getsize(OUT) / 1024 / 1024
    print(f"\n  {len(events)} events -> {os.path.relpath(OUT, ROOT)}   ({size:.1f} MB)")
    print(f"    banners on disk        {stats['with_banner']}")
    print(f"    banners missing        {stats['banner_missing']}")
    print(f"    videos                 {stats['with_video']}")
    print("    banner source:")
    for k, v in banner_from.most_common():
        print(f"        {v:>5}  {k}")
    print(f"    2nd image in rich_text {sum(placed.values())}")
    for k, v in placed.most_common():
        print(f"        {v:>5}  {k}")
    print(f"    no destination folder  {stats['target_missing']}")
    print(f"    richtext nodes         {stats['richtext_nodes']}")
    print("\n  open it by double-clicking; no server needed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
