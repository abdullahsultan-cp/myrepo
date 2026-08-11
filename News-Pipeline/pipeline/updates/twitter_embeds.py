#!/usr/bin/env python3
"""twitter_embeds.py — the Twitter iframes become social_embed bloks.

    python pipeline/migrate/update/run_update.py twitter_embeds --type news
    python pipeline/migrate/update/run_update.py twitter_embeds --type news --apply

News went live with tweets rendered as raw `iframe` bloks, because at the time
that was the only thing in the space that could hold one. They do not work —
Twitter stopped allowing itself to be framed — and the dev has since added a
**`social_embed`** component whose variants are `twitter`, `facebook` and
`instagram`. This swaps one for the other, in place.

## Only tweets

38 of the 43 live iframes point at twitter.com. The rest are left exactly as
they are, and deliberately:

    3   www.youtube.com     a real embed that works; media_section would be
                            the tidier home but that is a separate decision
    1   localhost:3010      the dev's test story, not ours to touch
    1   aku-dev.vercel.app  likewise

So the test is the host, not "is it an iframe". A rule that converted every
iframe would rewrite two of the dev's own stories.

## The shape comes from the dev, not from a guess

`news/strengthening-akus-next-generation-of-researchers` already carries a
hand-built one, and it is copied field for field — including `align: "right"`
and `spacing: ""`, which is an empty string here rather than the usual
spacing-field-plugin object. If that turns out to be wrong it is wrong in the
dev's own story too, which is the right place for it to be found.

`show_text: true` keeps the tweet's text visible, matching that example.

The tweet URL carries over untouched: `https://twitter.com/i/status/<id>` is
what the iframes hold, and x.com serves it.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "pipeline", "migrate", "update"))
from helpers import find_bloks, walk_bloks

FIELDS = ["body"]

DESCRIPTION = "38 Twitter iframes -> social_embed, the component the dev added"

# Only stories that hold an iframe are worth reading. Without this the engine
# reads all 3,610 news stories one at a time to find 38.
CONTAINS = "iframe"

# Hosts that are a tweet. Everything else keeps its iframe.
TWITTER_HOSTS = ("twitter.com", "www.twitter.com", "x.com", "www.x.com")


def is_tweet(src):
    src = (src or "").lower()
    if "//" not in src:
        return False
    host = src.split("//", 1)[1].split("/", 1)[0]
    return host in TWITTER_HOSTS


def to_social(blok):
    if not isinstance(blok, dict) or blok.get("component") != "iframe":
        return blok
    src = blok.get("src") or ""
    if not is_tweet(src):
        return blok
    return {
        "component": "social_embed",
        "variant": "twitter",
        "url": src,
        "align": "right",
        "show_text": True,
        # The dev's example has an empty string here, not a plugin object.
        "spacing": blok.get("spacing") if isinstance(blok.get("spacing"), dict)
                   else "",
    }


def patch(content, source, ctx):
    body = content.get("body")
    if not body:
        return {}
    if not [b for b in find_bloks(body, "iframe") if is_tweet(b.get("src"))]:
        return {}
    return {"body": walk_bloks(body, to_social)}
