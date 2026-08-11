#!/usr/bin/env python3
"""document_links.py — point the PDF links at the PDFs we uploaded.

    python pipeline/migrate/update/run_update.py document_links --type news
    python pipeline/migrate/update/run_update.py document_links --type news --apply

The PDFs went up with everything else — 102 of 106 are in Storyblok already,
90 uploaded and 12 reused. **The links in the articles never followed them.**
They still read `/news-media/1214-richtext-…-English-Fact-Sheet.PDF`, which is
a SharePoint path, and SharePoint is being switched off. Uploaded but not
attached.

This attaches them: every document link whose file we hold becomes the
`https://a.storyblok.com/…` URL of that asset.

## What it will not do

**Ten document links cannot be fixed, and are left exactly as they are.** Each
was checked against the live site rather than assumed dead:

    404          1779 Sindh-NFE-Policy, 1783 SPARC abstract, 1906 Drug and the
                 Youth, 2075 UNCRC-vrs-ACC, 2105 EGR2019, 2414, and the AKU
                 Publications Catalogue
    HTML, not a PDF   "VOLUME IV KPHC 2019.pdf"
    timed out    Predictions-2020.pdf
    never a link at all   `G:\\AKU - WORK\\UNIVERSITY CENTRE\\…` — somebody
                 pasted a path off their own machine into SharePoint years ago

Four of those have no source URL recorded either, so there is nowhere to fetch
them from even in principle. They are reported, not silently dropped, and they
stay in `data/internal_links.csv` for the record.

## Matching

The link's filename against `asset.source_filename`, case-insensitively —
`English-Fact-Sheet.PDF` in a link is `english-fact-sheet.pdf` in the table.
The name is percent-decoded first: `AKU%20Publications` never matches
`AKU Publications` otherwise. 101 of 115 document links match.

Nothing is guessed. A link whose file is not in the table is left alone.
"""

import os
import re
import sys
from urllib.parse import unquote

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "pipeline", "migrate", "update"))

FIELDS = ["body"]

DESCRIPTION = "101 PDF links -> the Storyblok assets they were uploaded to"

# Documents live in rich_text, so there is no component to narrow on. Reading
# all 3,610 is the price; it is a one-off and the run prints its position.
CONTAINS = None


def setup(source):
    """{story id: [(asset filename, url)]} from the tracking database.

    Keyed by story because the filename in a link and the filename in the
    asset table are not the same string. The uploader renamed every file:

        link in the story   .../news/Documents/English Fact Sheet.PDF
        asset table         1214-richtext-beaea9b014-English-Fact-Sheet.PDF

    `{story id}-richtext-{hash}-{original, spaces turned to hyphens}`. So the
    match is the story's own id plus that hyphenated tail — matching on the
    tail alone would let two stories with a file called `Announcement.pdf`
    take each other's.

    Files shared between stories are named `shared-richtext-…` and have no id
    in front, so they are pooled separately and tried second.

    Matching on the raw filename found nothing at all: the first version of
    this plan reported "0 would change, 117 already correct" and looked like
    success. It was looking up the wrong key.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    sys.path.insert(0, os.path.join(root, "pipeline", "migrate"))
    import db
    with db.connect() as c:
        c.execute("SET search_path TO migration, public")
        rows = c.execute("SELECT sharepoint_id, source_filename, sb_filename "
                         "FROM asset WHERE sb_filename IS NOT NULL").fetchall()
    by_story, shared = {}, []
    for sid, name, url in rows:
        if not name:
            continue
        low = str(name).lower()
        by_story.setdefault(str(sid), []).append((low, url))
        if low.startswith("shared-"):
            shared.append((low, url))
    print(f"    {len(rows)} uploaded asset(s), {len(shared)} shared between stories")
    return {"by_story": by_story, "shared": shared}


def normalise(filename):
    """The filename as the uploader would have written it: spaces to hyphens."""
    return re.sub(r"[\s_]+", "-", unquote(filename)).lower()


def asset_for(href, sid, ctx):
    """The Storyblok URL for this link, or None to leave it alone."""
    if not href or "a.storyblok.com" in href:
        return None
    path = href.split("?")[0]
    if not path.lower().endswith((".pdf", ".doc", ".docx", ".ppt", ".pptx",
                                  ".xls", ".xlsx")):
        return None
    tail = normalise(path.split("/")[-1])
    for pool in (ctx.get("by_story", {}).get(str(sid), []), ctx.get("shared", [])):
        for name, url in pool:
            if name == tail or name.endswith("-" + tail):
                return url
    return None


def relink(node, sid, ctx, changed):
    """Rewrite every document link in a rich-text tree. Mutates in place."""
    if isinstance(node, dict):
        for mark in node.get("marks") or []:
            if mark.get("type") != "link":
                continue
            attrs = mark.get("attrs") or {}
            url = asset_for(attrs.get("href"), sid, ctx)
            if url and attrs.get("href") != url:
                attrs["href"] = url
                # A Storyblok asset is a URL, not a story reference; anything
                # left over from the SharePoint link would contradict it.
                attrs.pop("uuid", None)
                attrs["linktype"] = "url"
                mark["attrs"] = attrs
                changed.append(url)
        for value in node.values():
            if isinstance(value, (list, dict)):
                relink(value, sid, ctx, changed)
    elif isinstance(node, list):
        for child in node:
            relink(child, sid, ctx, changed)


def patch(content, source, ctx):
    import copy
    body = content.get("body")
    if not body:
        return {}
    # A live news_article carries no sharepoint_id, so the id comes from the
    # export row the engine matched through the tracking table. Without it we
    # can still try the shared pool, but not this story's own files.
    sid = (source or {}).get("ID") or content.get("sharepoint_id") or ""
    new = copy.deepcopy(body)
    changed = []
    relink(new, sid, ctx, changed)
    return {"body": new} if changed else {}
