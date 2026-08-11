#!/usr/bin/env python3
"""helpers.py — things most update plans need. Imported, never run.

Kept deliberately small. A helper here is shared by every type, so it earns its
place only by being needed twice.
"""


def walk_bloks(bloks, fn):
    """Rebuild a blok list with `fn` applied to every blok, at any depth.

    `fn(blok)` returns the replacement — one blok, a list of bloks to splice in
    at that position, or None to drop it. Return the blok unchanged to keep it.

    Nested blok lists (a `row` holding columns, a `media_section` holding
    `media_card`s) are walked too, so a plan does not have to know the shape of
    the tree it is editing.
    """
    out = []
    for blok in bloks or []:
        if isinstance(blok, dict):
            for key, value in list(blok.items()):
                if isinstance(value, list) and any(
                        isinstance(x, dict) and "component" in x for x in value):
                    blok[key] = walk_bloks(value, fn)
        new = fn(blok)
        if new is None:
            continue
        out.extend(new if isinstance(new, list) else [new])
    return out


def spacing(mobile_x=20, desktop_x=80, mobile_b=24, desktop_b=56):
    """A spacing-field-plugin value.

    `spacing` is not optional — it is on every blok, and a blok without it
    renders wrong. The defaults here are the common case; rich_text wants
    desktop_x=176, and quote_banner, media_section (video) and brand_banner
    want no horizontal padding at all. See CLAUDE.md for the table.
    """
    return {
        "plugin": "spacing-field-plugin",
        "mobile": {"paddingX": mobile_x, "marginBottom": mobile_b},
        "desktop": {"paddingX": desktop_x, "marginBottom": desktop_b},
        "unit": "px",
    }


def find_bloks(bloks, component):
    """Every blok of a given component, at any depth. For counting first."""
    found = []

    def visit(blok):
        if isinstance(blok, dict):
            if blok.get("component") == component:
                found.append(blok)
            for value in blok.values():
                if isinstance(value, list):
                    for child in value:
                        visit(child)

    for blok in bloks or []:
        visit(blok)
    return found
