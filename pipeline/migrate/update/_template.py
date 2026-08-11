#!/usr/bin/env python3
"""_template.py — copy this into <Type>-Pipeline/pipeline/updates/<name>.py.

Leading underscore keeps it out of `--list`. Two worked examples follow: one
fills a field, one replaces a blok. Delete the one you do not need.

Run it, read the diff, then run it again with --apply:

    python pipeline/migrate/update/run_update.py <name> --type <type>
    python pipeline/migrate/update/run_update.py <name> --type <type> --apply
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "update"))
from helpers import find_bloks, spacing, walk_bloks  # noqa: F401

# The ONLY keys patch() may return. Anything else is a hard error — this is
# what stops an update from quietly rewriting a field someone hand-edited.
FIELDS = ["category"]

DESCRIPTION = "one line; shown by --list"


def setup(source):
    """Optional. Runs once. Whatever it returns is passed to patch() as ctx.

    Load lookups here, not in patch() — patch() runs once per story.
    """
    return {}


def patch(content, source, ctx):
    """Return {field: new value}, or {} to leave this story alone.

    content   the story as it is live RIGHT NOW, not what we uploaded
    source    the matching export row (matched on sharepoint_id), or None
    ctx       whatever setup() returned

    Return {} when there is nothing to do. Returning a value equal to what is
    already there is harmless — the engine drops no-op changes — but checking
    first makes the dry run easier to read.
    """
    # ---- example 1 · fill a field the dev has just added ------------------
    if content.get("category"):
        return {}                       # already set; leave it alone
    cat = (source or {}).get("Category")
    if not cat:
        return {}
    return {"category": ctx["by_name"][cat]}

    # ---- example 2 · replace a blok with the component that supersedes it --
    # FIELDS must contain "body" for this.
    #
    # def to_social(blok):
    #     if blok.get("component") != "iframe":
    #         return blok
    #     src = blok.get("src") or ""
    #     if "twitter.com" not in src and "x.com" not in src:
    #         return blok             # not a tweet; leave the iframe alone
    #     return {"component": "social_embed", "variant": "twitter",
    #             "url": src, "align": "center", "show_text": True,
    #             "spacing": blok.get("spacing") or spacing()}
    #
    # if not find_bloks(content.get("body"), "iframe"):
    #     return {}
    # return {"body": walk_bloks(content.get("body"), to_social)}
