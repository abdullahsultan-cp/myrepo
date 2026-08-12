#!/usr/bin/env python3
"""contact.py — fill the contact field, once the dev has added one.

    python pipeline/migrate/update/run_update.py contact --type events
    python pipeline/migrate/update/run_update.py contact --type events --apply

**This plan cannot run yet.** `event_article` has 21 fields and none of them
holds contact details. It is written now, while the data is fresh in hand, so
that the day the field lands this is one command rather than a fortnight of
re-deriving what `Contact` contained.

## Why this is the largest gap in the events migration

`Contact` is populated on **all 2,710 events** -- the only column besides
EventTitle, EventDetail, Entity, Venue and StartDate that is. It carries
**2,046 links across 1,251 events**: registration mailboxes, department phone
numbers, organiser pages. Dropping it would lose the single thing a reader most
wants from an archived event page, which is who to ask about it.

    <div>Professional Development Centre, Karachi</div>
    <div>Tel&#58; +92 21 36347611-4 or +92 21 36347612</div>
    <div><a href="mailto&#58;pdc@aku.edu">pdc@aku.edu</a></div>

Note `Tel&#58;` -- SharePoint escapes the colon, so a raw value reads
`mailto&#58;...`. Unescaped here, or every address is broken.

## Two things to confirm before the first run

**1 · The field name.** `FIELD` below is a guess. Set it to whatever the dev
actually calls it and update `FIELDS` to match -- the engine treats `FIELDS` as
a whitelist and errors on anything else, which is the point.

**2 · The field type**, which decides `patch()`:

    richtext   the right answer. 2,046 links survive as real links.
               AS_RICHTEXT = True below.
    textarea   the links flatten to text. 1,251 events lose them.
    text       same, and the multi-line addresses collapse onto one line.

The HTML in `Contact` is nine tag types at most -- div, br, a, p, strong, em,
li, ul -- all of which `storyblok_richtext` already handles, because it is the
same converter the body goes through. So richtext costs nothing extra.
"""

import html
import os
import re
import sys

# the shared pipeline, for the same converter the body uses
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_ROOT, "pipeline"))
import _bootstrap

_bootstrap.ensure()

# Both must follow _bootstrap.ensure(), so this block cannot be sorted.
from normalize_html import normalize_content_html      # noqa: I001
from storyblok_richtext import html_to_storyblok_richtext

# CONFIRM BOTH with the dev before running.
FIELD = "contact"
AS_RICHTEXT = True

FIELDS = [FIELD]

DESCRIPTION = "Contact -> the contact field; populated on all 2,710 events"

# Optional, and worth setting: it makes the engine read only stories that could
# possibly change. Left None because a brand-new field is empty everywhere, so
# nothing would match.
CONTAINS = None


def _text(raw):
    """Contact as plain text, with SharePoint's escaped colons repaired."""
    s = html.unescape(raw or "").replace("&#58;", ":")
    s = re.sub(r"<br\s*/?>|</div>|</p>|</li>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    lines = [re.sub(r"[ \t]+", " ", x).strip() for x in s.split("\n")]
    return "\n".join(x for x in lines if x)


def _richtext(raw):
    """Contact as a Storyblok richtext document, links intact.

    The same path the body takes -- normalize_html then storyblok_richtext --
    so the 2,046 `mailto:` and `tel:` links come through as real link marks
    rather than as text that looks like a link.
    """
    s = (raw or "").replace("&#58;", ":")
    normalised, _stats, _warn = normalize_content_html(s)
    return html_to_storyblok_richtext(normalised).document


def patch(content, source, ctx):
    """Return {FIELD: value}, or {} to leave this story alone."""
    if source is None:
        # No export row. For events this means the tracking database is not
        # reachable -- event_article carries no sharepoint_id, so the story
        # table is the only link back. See Events-Pipeline/CLAUDE.md.
        return {}
    raw = (source.get("Contact") or "").strip()
    if not raw:
        return {}
    if content.get(FIELD):
        return {}                       # already set; never overwrite an edit
    return {FIELD: _richtext(raw) if AS_RICHTEXT else _text(raw)}
