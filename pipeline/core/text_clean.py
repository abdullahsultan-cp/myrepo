#!/usr/bin/env python3
"""text_clean.py — turning SharePoint HTML into text a reader should see.

Imported, never run. Shared by every content type, because the same two faults
turn up in all of them.

## 1 · Entities must be decoded

SharePoint stores `&#160;` for a non-breaking space, `&amp;` for an ampersand,
`&quot;` for a quote. Strip the tags and leave those alone and the reader sees
the literal characters `&#160;` in the middle of a sentence:

    Dr&#160;Asad I Mian, Professor of Emergency Medicine

That shipped. 88 `&#160;`, 12 `&amp;`, 2 `&quot;` and 1 `&#58;` across 34 blog
author biographies, and 2 news stories. The portal decoded them and the payload
builder did not, which is the whole reason for putting it here instead: one
function, so a fix cannot land in one path and miss the other.

## 2 · Position markers are not content

SharePoint marks where a component belongs with a token in the body text:

    {pullquote}      14 across 13 blogs — where the pull quote goes
    {EmbeddedCode}   1 — where the embed goes

They are instructions to the renderer, not words. Once the quote is a
`quote_banner` blok and the embed is a `social_embed`, the marker has done its
job and must come out, or the reader sees `{pullquote}` in the prose.

## 3 · Invisibles, and only these

U+200B zero-width space, U+FEFF byte-order mark, U+00AD soft hyphen. They serve
no purpose and break searching and slugs. **Nothing else is stripped.** 711
non-ASCII characters across 98 distinct code points are legitimate content —
accented names, Arabic, Urdu, `£`, `°` — and transliterating them is data loss.
"""

import html
import re

# Instructions to SharePoint's renderer, left behind in the prose.
MARKERS = re.compile(r"\{(?:pullquote|EmbeddedCode|embeddedcode|PullQuote)\}")

# The only characters safe to delete outright.
INVISIBLES = dict.fromkeys(map(ord, "​﻿­"), None)


def clean_text(value, *, collapse=True):
    """Decode entities, drop markers and invisibles. Never transliterates.

    `collapse` folds runs of whitespace into one space, which is right for a
    biography or a quote pulled out of HTML. Pass False where the line breaks
    carry meaning.
    """
    if not value:
        return ""
    text = html.unescape(str(value))
    # After unescaping, because &#160; only becomes a non-breaking space here
    # and is otherwise invisible to the whitespace collapse below.
    text = text.replace(" ", " ")
    text = MARKERS.sub("", text)
    text = text.translate(INVISIBLES)
    if collapse:
        text = re.sub(r"\s+", " ", text)
    return text.strip()


def strip_html(value, *, collapse=True):
    """Tags out, then `clean_text`. For a field that holds a fragment of HTML."""
    if not value:
        return ""
    return clean_text(re.sub(r"<[^>]+>", " ", str(value)), collapse=collapse)


def clean_richtext(doc):
    """Run `clean_text` over every text node of a Storyblok rich-text doc.

    Whitespace is NOT collapsed: a rich-text node's spacing is already
    deliberate, and folding it would join words across a line break.

    A text node emptied by this — one that held only `{pullquote}` — is
    dropped, and a paragraph left with no children is dropped with it. Leaving
    an empty node behind renders as a stray blank line, which is the same fault
    the blank-paragraph strip exists to fix.
    """
    if not isinstance(doc, (dict, list)):
        return doc
    if isinstance(doc, list):
        return [clean_richtext(node) for node in doc]

    node = dict(doc)
    if node.get("type") == "text":
        node["text"] = clean_text(node.get("text"), collapse=False)
    children = node.get("content")
    if isinstance(children, list):
        cleaned = []
        for child in children:
            done = clean_richtext(child)
            if isinstance(done, dict):
                if done.get("type") == "text" and not done.get("text"):
                    continue
                if (done.get("type") in ("paragraph", "heading")
                        and isinstance(done.get("content"), list)
                        and not done["content"]):
                    continue
            cleaned.append(done)
        node["content"] = cleaned
    return node
