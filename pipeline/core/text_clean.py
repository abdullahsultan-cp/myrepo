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

# Every hidden character actually present in the two exports, counted:
#
#   U+200B  8,187  zero width space          delete
#   U+202F     79  narrow no-break space     becomes a normal space
#   U+00A0     47  no-break space            becomes a normal space
#   U+2028      6  line separator            becomes a newline
#   U+00AD      5  soft hyphen               delete
#   U+2009      1  thin space                becomes a normal space
#   U+FEFF      1  zero width no-break space delete
#
# The rest of each block is included so the next export cannot introduce a
# variant nobody thought of — every other Unicode space becomes a space, every
# other zero-width goes.
#
# **U+200C and U+200D are deliberately NOT here.** Zero-width non-joiner and
# joiner are not decoration: they change how Urdu, Arabic and Indic scripts
# render, and 44 news stories carry Arabic and Urdu. Neither appears in either
# export today; if one arrives it must survive. Filtering by Unicode category
# `Cf` — the obvious way to catch zero-width spaces — sweeps both away with
# them, which is why this is an explicit list and not a category test.
#
# Written as code points on purpose. The first version used the characters
# themselves and was unreviewable: nobody can see that a string of invisibles
# has picked up a plain space and LOST U+00A0, which is exactly what happened.
# A test caught it only because clean_href skips the whitespace collapse that
# was hiding it.
DELETE = "".join(map(chr, (
    0x200B,   # zero width space           8,187 in the exports
    0xFEFF,   # zero width no-break space      1
    0x00AD,   # soft hyphen                    5
    0x180E,   # Mongolian vowel separator      0 — invisible, never content
    0x2060,   # word joiner                    0
    0x061C,   # Arabic letter mark             0
)))
TO_SPACE = "".join(map(chr, (
    0x00A0,   # no-break space                47
    0x202F,   # narrow no-break space         79
    0x2009,   # thin space                     1
    0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007,
    0x2008, 0x200A, 0x205F, 0x3000, 0x1680,   # the rest of the space block
)))
TO_NEWLINE = "".join(map(chr, (
    0x2028,   # line separator                 6
    0x2029,   # paragraph separator            0
)))

# Bidirectional controls. Present in neither export, and stripped if they ever
# arrive: they reorder the characters around them and are invisible while doing
# it, so a pasted one can silently reverse part of a sentence.
DELETE += "".join(map(chr, (0x200E, 0x200F, 0x202A, 0x202B, 0x202C,
                            0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069)))

INVISIBLES = {
    **dict.fromkeys(map(ord, DELETE), None),
    **dict.fromkeys(map(ord, TO_SPACE), " "),
    **dict.fromkeys(map(ord, TO_NEWLINE), chr(10)),
}

# Anything still shaped like an entity after cleaning.
ENTITY = re.compile(r"&[a-zA-Z][a-zA-Z0-9]{1,10};|&#x?[0-9a-fA-F]{1,6};")


def looks_encoded(text):
    """What survived cleaning and still reads as markup. Empty when clean.

    Decoding happens **once**, deliberately. `&amp;#160;` decodes to `&#160;`,
    which is still visible on the page — so why not decode until stable? Because
    text that legitimately talks about markup would be destroyed: a sentence
    containing `&amp;amp;` means to show `&amp;`, and a second pass turns it
    into a bare `&`.

    Neither export has a single double-encoded entity — that was counted, not
    assumed — so looping would fix nothing real and risk something real. If one
    ever appears, this reports it and a person decides. The payload guard in
    tests/test_text_clean.py fails on anything this returns.
    """
    return ENTITY.findall(text or "")


def clean_text(value, *, collapse=True):
    """Decode entities, drop markers and invisibles. Never transliterates.

    `collapse=True` folds runs of whitespace into one space and trims the ends.
    That is right for a whole field — a biography, a summary, a quote pulled out
    of HTML — where the value stands alone.

    **`collapse=False` also stops it trimming, and that matters more than it
    looks.** Inside rich text a text node is a *fragment*: the renderer
    concatenates it with its neighbours, so the space at its edge is the space
    between two sentences. Trimming there deletes it.

    That was measured, not imagined. Wiring this into the shared conversion with
    an unconditional `.strip()` rewrote **2,449 of 3,606 news stories**, turning

        ...Conference programme. This year's SCCA Conference...
        ...Conference programme.This year's SCCA Conference...

    across every article where a sentence happened to start a new text node.
    """
    if not value:
        return ""
    text = html.unescape(str(value))
    text = MARKERS.sub("", text)
    # After unescaping, because &#160; only becomes U+00A0 at that point and is
    # invisible to this table — and to the whitespace collapse — until it does.
    text = text.translate(INVISIBLES)
    if not collapse:
        return text
    return re.sub(r"\s+", " ", text).strip()


def strip_html(value, *, collapse=True):
    """Tags out, then `clean_text`. For a field that holds a fragment of HTML."""
    if not value:
        return ""
    return clean_text(re.sub(r"<[^>]+>", " ", str(value)), collapse=collapse)


def clean_href(href):
    """Trim what cannot belong in a URL. Nothing else is touched.

    An invisible character in an href is not cosmetic — it breaks the link,
    because the browser asks for a host that does not exist. Four live news
    stories carry one at the end of theirs:

        .../profile.aspx?ProfileID=43&Name=Stephen Lyon<U+200B>
        https://www.aku.edu/cneaaccreditation@nln.org<U+200B>

    Three of those are also wrong in a way this does NOT fix — an email address
    glued onto the site URL where somebody meant `mailto:`. Guessing that is a
    content decision, not a cleanup, so only the invisible goes and the rest is
    left for a person to look at.

    Note the deletions only: a no-break space becomes a normal space in prose,
    but inside a URL it is a fault either way, and turning it into a space would
    hide it from the next person looking for broken links.
    """
    if not isinstance(href, str):
        return href
    out = href
    for ch in DELETE + TO_SPACE + TO_NEWLINE:
        out = out.replace(ch, "")
    return out.strip()


def clean_links(node):
    """Every link href in a rich-text tree, cleaned. Returns a copy."""
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


def clean_document(doc):
    """Text and links in one call — what a payload builder actually wants."""
    return clean_links(clean_richtext(doc))


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
