#!/usr/bin/env python3
"""text_entities.py — decode the HTML entities that reached published text.

    python pipeline/migrate/update/run_update.py text_entities --type news --only 1278,1279
    python pipeline/migrate/update/run_update.py text_entities --type news --only 1278,1279 --apply

SharePoint stores `&#160;` for a non-breaking space and `&amp;` for an
ampersand. Where a field was built by stripping tags and nothing else, those
survive as literal characters and the reader sees them:

    Aga Khan University&#160;General Office

**News is not currently affected, and this was checked rather than assumed.**
Two news stories, 1278 and 1279, carry `&#160;` in their local intermediate
file — but both were read back from the space and are clean: the news upload
path decodes on the way out. Blogs did not, which is how 88 of them reached
published author biographies.

So this plan is a net, not a repair. It is here because the fault is one line
of code away from returning, and because the next type to be built will reach
for it. Run it after any change to how text is derived from HTML.

**Pass `--only 1278,1279`.** Without it the engine reads all 3,610 stories one
at a time to change two, which takes twenty minutes. Entities live in rich
text, so there is no component to narrow on.

Nothing is transliterated. 711 non-ASCII characters across 98 code points are
legitimate content — accented names, Arabic, Urdu, `£`, `°`. Only entities are
decoded, markers removed, and the three invisibles dropped.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT_DIR, "pipeline"))
import _bootstrap

_bootstrap.ensure()

from text_clean import clean_richtext, clean_text

FIELDS = ["body", "description", "title"]

DESCRIPTION = "strip invisibles from link hrefs, and decode any stray entity"

# The three characters that are never content. A zero-width space is invisible
# in the editor and in the source, and at the end of a URL it breaks the link
# outright — the browser asks for a host that does not exist.
INVISIBLE = "​﻿­"


def clean_href(href):
    """Trim what cannot belong in a URL. Nothing else is touched.

    Four live news stories carry a zero-width space at the end of an href:

        .../profile.aspx?ProfileID=43&Name=Stephen Lyon<U+200B>
        https://www.aku.edu/cneaaccreditation@nln.org<U+200B>

    Three of those are also wrong in a way this does NOT fix — an email
    address glued onto the site URL, where somebody meant `mailto:`. Guessing
    that is a content decision, not a cleanup, so they are left for a person
    and only the invisible character goes.
    """
    if not isinstance(href, str):
        return href
    out = href
    for ch in INVISIBLE:
        out = out.replace(ch, "")
    return out.strip()


def clean_links(node):
    """Every link href in a rich-text tree, cleaned in place on a copy."""
    if isinstance(node, list):
        return [clean_links(child) for child in node]
    if not isinstance(node, dict):
        return node
    out = dict(node)
    marks = out.get("marks")
    if isinstance(marks, list):
        fixed = []
        for mark in marks:
            if isinstance(mark, dict) and mark.get("type") == "link":
                attrs = dict(mark.get("attrs") or {})
                attrs["href"] = clean_href(attrs.get("href"))
                mark = {**mark, "attrs": attrs}
            fixed.append(mark)
        out["marks"] = fixed
    for key, value in out.items():
        if isinstance(value, (list, dict)) and key != "marks":
            out[key] = clean_links(value)
    return out


def patch(content, source, ctx):
    out = {}
    for field in ("title", "description"):
        before = content.get(field)
        if isinstance(before, str):
            after = clean_text(before)
            if after != before:
                out[field] = after
    body = content.get("body")
    if isinstance(body, list):
        after = [clean_links(clean_richtext(blok)) for blok in body]
        if after != body:
            out["body"] = after
    return out
