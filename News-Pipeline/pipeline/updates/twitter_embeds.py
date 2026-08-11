#!/usr/bin/env python3
"""twitter_embeds.py — the Twitter iframes become social_embed bloks, in a row.

    python pipeline/migrate/update/run_update.py twitter_embeds --type news
    python pipeline/migrate/update/run_update.py twitter_embeds --type news --apply

News went live with tweets rendered as raw `iframe` bloks, because at the time
that was the only thing in the space that could hold one. They do not work —
Twitter stopped allowing itself to be framed — and the dev has since added
**`social_embed`**, variants `twitter`, `facebook` and `instagram`.

## Only tweets

38 of the 43 live iframes point at twitter.com. The rest are left alone, and
deliberately:

    3   www.youtube.com     a real embed that works
    1   localhost:3010      the dev's test story, not ours to touch
    1   aku-dev.vercel.app  likewise

So the test is the **host**, not "is it an iframe" and not "does the string
contain twitter" — `https://example.com/twitter.com/x` is not a tweet. A rule
that converted every iframe would rewrite two of the dev's own stories.

## The container, and why it is one column and not two

The dev's hand-built example lives at
`news/strengthening-akus-next-generation-of-researchers`, and the reason it
sits so neatly against the text is that it is **not a bare blok**: it is inside
a `row`, in a `row_item`, with a second `row_item` holding a short paragraph
beside it. Every value below — the row's padding of 20/80, its margin-bottom of
24/56, `align_items` and `justify_content` centre, the white background, the
empty `width` and `radius`, and the row_item's all-null spacing — is copied from
that story rather than invented.

**The second column is not reproduced, because our 38 have nothing to put in
it.** Measured, rather than assumed:

    all 38      the tweet is the LAST blok in the story
    all 38      preceded by a rich_text, median 3,503 characters
    34 of 38    whose final paragraph is under 500 characters — median 61

The dev paired their embed with a 391-character testimonial. Ours would be
paired either with the entire article body, or with a 61-character orphan line
that would leave the column looking broken. Neither is better than a clean
single column, and moving text between bloks to manufacture a pairing is the
kind of tree-regrouping that destroyed six stories once already.

So: same container, same spacing, same alignment treatment, one column. If a
particular article would genuinely read better as two, that is an editorial
call per story and the editor can drag a paragraph across in Storyblok.

`align` is **center** here rather than the dev's `right`. Theirs is right
because it is the left column of a pair and hugs the text beside it; a single
full-width column aligned right would strand the tweet against the margin.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "pipeline", "migrate", "update"))
from helpers import find_bloks, walk_bloks

FIELDS = ["body"]

DESCRIPTION = "38 Twitter iframes -> social_embed inside a row, as the dev built it"

# Only stories holding an iframe are worth reading. Without this the engine
# reads all 3,610 news stories one at a time to find 38.
CONTAINS = "iframe"

TWITTER_HOSTS = ("twitter.com", "www.twitter.com", "x.com", "www.x.com")

WHITE = {"color": "#FFFF", "plugin": "native-color-picker"}


def _edges(top=None, left=None, right=None, bottom=None):
    return {"top": top, "left": left, "right": right, "bottom": bottom}


def _spacing(mobile_margin, mobile_padding, desktop_margin, desktop_padding):
    return {"unit": "px",
            "mobile": {"margin": mobile_margin, "padding": mobile_padding},
            "desktop": {"margin": desktop_margin, "padding": desktop_padding}}


# Copied field for field from the dev's row.
ROW_SPACING = _spacing(_edges(bottom=24), _edges(left=20, right=20),
                       _edges(bottom=56), _edges(left=80, right=80))
# The row_item carries none of its own; the row does the spacing.
ITEM_SPACING = _spacing(_edges(), _edges(), _edges(), _edges())


def is_tweet(src):
    """True only when the URL's HOST is Twitter, not merely mentions it."""
    src = (src or "").lower()
    if "//" not in src:
        return False
    host = src.split("//", 1)[1].split("/", 1)[0].split("?")[0]
    return host in TWITTER_HOSTS


def wrap(url):
    """A tweet in the same container the dev used, with one column."""
    return {
        "component": "row",
        "width": "",
        "height": None,
        "radius": "",
        "align_items": "center",
        "justify_content": "center",
        "background_color": dict(WHITE),
        "spacing": ROW_SPACING,
        "items": [{
            "component": "row_item",
            "width": "",
            "radius": "",
            "background_color": dict(WHITE),
            "spacing": ITEM_SPACING,
            "body": [{
                "component": "social_embed",
                "variant": "twitter",
                "url": url,
                "align": "center",
                "show_text": True,
                # An empty string, as in the dev's own blok — the row holds the
                # spacing, so the embed carries none of its own.
                "spacing": "",
            }],
        }],
    }


def to_social(blok):
    if not isinstance(blok, dict) or blok.get("component") != "iframe":
        return blok
    src = blok.get("src") or ""
    return wrap(src) if is_tweet(src) else blok


def patch(content, source, ctx):
    body = content.get("body")
    if not body:
        return {}
    if not [b for b in find_bloks(body, "iframe") if is_tweet(b.get("src"))]:
        return {}
    return {"body": walk_bloks(body, to_social)}
