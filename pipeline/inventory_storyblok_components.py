#!/usr/bin/env python3
"""
inventory_storyblok_components.py — what the 3606 story payloads actually contain.

Everything you need to define before creating stories in Storyblok: which
components appear, which rich-text nodes and marks are used, which media roles
exist, and which non-ASCII characters survive into the content.

Read from the built payloads rather than from the converter source, so the answer
is what will actually be uploaded — not what the code is capable of emitting.

Usage:
    python scripts/inventory_storyblok_components.py [output_json]

Outputs (stdout, plus an optional JSON report):
    components         every "component" value at any depth, with counts
    richtext nodes     every node type, its attrs, and counts
    richtext marks     every mark type, its attrs, and counts
    content fields     every content.* field and how often it is populated
    media roles        banner / medium / thumbnail / video / richtext media
    special characters non-ASCII survivors, grouped by category
"""

import json
import os
import sys
import unicodedata
from collections import Counter, defaultdict

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(BASE, "data")
STORIES = os.path.join(DATA, "storyblok_stories")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def maybe(name):
    p = os.path.join(DATA, name)
    return load(p) if os.path.exists(p) else None


# ------------------------------------------------------------------ walkers

components = Counter()
component_fields = defaultdict(Counter)
node_types = Counter()
node_attrs = defaultdict(Counter)
mark_types = Counter()
mark_attrs = defaultdict(Counter)
embed_kinds = Counter()


def walk_richtext(node, depth=0):
    if isinstance(node, list):
        for n in node:
            walk_richtext(n, depth)
        return
    if not isinstance(node, dict):
        return
    t = node.get("type")
    if t:
        node_types[t] += 1
        for k in node.get("attrs") or {}:
            node_attrs[t][k] += 1
    for m in node.get("marks") or []:
        if isinstance(m, dict) and m.get("type"):
            mark_types[m["type"]] += 1
            for k in m.get("attrs") or {}:
                mark_attrs[m["type"]][k] += 1
    # Bloks nested inside rich text are NOT counted here: walk_bloks() already
    # recurses through content.body, so counting them again double-counts every
    # video_embed and twitter_embed.
    walk_richtext(node.get("content") or [], depth + 1)


def walk_bloks(obj):
    """Any dict carrying a 'component' key is a Storyblok blok."""
    if isinstance(obj, list):
        for o in obj:
            walk_bloks(o)
        return
    if not isinstance(obj, dict):
        return
    comp = obj.get("component")
    if comp:
        components[comp] += 1
        for k, v in obj.items():
            if k not in ("component", "_uid") and v not in (None, "", [], {}):
                component_fields[comp][k] += 1
    for v in obj.values():
        if isinstance(v, (dict, list)):
            walk_bloks(v)


# ------------------------------------------------------------------ main

def main(out_json=None):
    files = sorted(f for f in os.listdir(STORIES) if f.endswith(".json"))
    print(f"stories scanned: {len(files)}\n")

    story_keys = Counter()
    content_keys = Counter()
    content_populated = Counter()
    pull_quote_modes = Counter()

    for name in files:
        s = load(os.path.join(STORIES, name))
        for k in s:
            story_keys[k] += 1
        c = s.get("content") or {}
        for k, v in c.items():
            content_keys[k] += 1
            if v not in (None, "", [], {}, False):
                content_populated[k] += 1

        walk_bloks(c)
        body = c.get("body")
        if isinstance(body, dict):
            walk_richtext(body.get("content") or [])

        pq = c.get("pull_quote")
        if isinstance(pq, dict):
            pull_quote_modes[pq.get("type") or "?"] += 1
            if pq.get("component_type"):
                embed_kinds[pq["component_type"]] += 1

    def block(title, counter, extra=None):
        print(f"\n{'=' * 74}\n  {title}\n{'=' * 74}")
        if not counter:
            print("  (none)")
            return
        for k, v in counter.most_common():
            line = f"  {v:>7,}  {k}"
            if extra and extra.get(k):
                line += ("  [" + ", ".join(sorted(extra[k])) + "]")
            print(line)

    block("COMPONENTS (blok types)", components,
          {k: set(v) for k, v in component_fields.items()})
    block("RICH-TEXT NODE TYPES", node_types,
          {k: set(v) for k, v in node_attrs.items()})
    block("RICH-TEXT MARKS", mark_types, {k: set(v) for k, v in mark_attrs.items()})
    block("PULL QUOTE MODES", pull_quote_modes)
    block("EMBED KINDS", embed_kinds)

    print(f"\n{'=' * 74}\n  CONTENT FIELDS (populated / total)\n{'=' * 74}")
    for k, total in content_keys.most_common():
        pct = 100 * content_populated[k] // max(total, 1)
        print(f"  {content_populated[k]:>7,} / {total:<6,} {pct:>3}%  {k}")

    # ---------------------------------------------------------- media roles
    print(f"\n{'=' * 74}\n  MEDIA\n{'=' * 74}")
    media = {}
    nmr = maybe("news_media_report.json")
    if nmr:
        print("  news_media_report.summary:")
        for k, v in nmr["summary"].items():
            if not isinstance(v, (dict, list)):
                print(f"    {v!s:>8}  {k}")
        media["news_media_summary"] = nmr["summary"]

    cls = maybe("story_media_classification_report.json")
    if cls:
        print("\n  media-type buckets (story_media_classification_report):")
        for k, v in cls["buckets"].items():
            n = len(v) if isinstance(v, list) else v
            print(f"    {n!s:>8}  {k}")
        print("\n  definitions:")
        for k, v in cls.get("definitions", {}).items():
            print(f"    {k}: {v}")
        media["buckets"] = {k: (len(v) if isinstance(v, list) else v)
                            for k, v in cls["buckets"].items()}

    rmc = maybe("richtext_media_catalog.json")
    if rmc:
        print("\n  rich-text embedded media (richtext_media_catalog):")
        for k, v in rmc["summary"].items():
            if not isinstance(v, (dict, list)):
                print(f"    {v!s:>8}  {k}")
        exts = Counter()
        for a in rmc.get("assets") or []:
            u = (a.get("url") or a.get("source_url") or "")
            ext = os.path.splitext(u.split("?")[0])[1].lower()
            exts[ext or "(none)"] += 1
        print("    extensions:", dict(exts.most_common()))
        media["richtext_media_summary"] = rmc["summary"]
        media["richtext_media_extensions"] = dict(exts)

    ac = maybe("storyblok_asset_catalog.json")
    if ac:
        print("\n  inline content images (storyblok_asset_catalog):")
        for k, v in ac["summary"].items():
            if not isinstance(v, (dict, list)):
                print(f"    {v!s:>8}  {k}")

    # ----------------------------------------------------- special characters
    print(f"\n{'=' * 74}\n  SPECIAL CHARACTERS\n{'=' * 74}")
    ur = maybe("unicode_report.json")
    chars = []
    if ur:
        for k, v in ur["summary"].items():
            if not isinstance(v, (dict, list)):
                print(f"    {v!s:>8}  {k}")

        by_class = defaultdict(list)
        for c in ur.get("characters") or []:
            ch = c.get("character") or ""
            entry = {
                "codepoint": (c.get("code") or "").replace("\\u", "U+").upper()
                             or (f"U+{ord(ch):04X}" if ch else "?"),
                "char": ch,
                "name": c.get("name") or "?",
                "unicode_category": c.get("unicode_category") or "",
                "classification": c.get("classification") or "unclassified",
                "total_count": c.get("total_count") or 0,
                "file_count": c.get("file_count") or 0,
                "normalize_recommended": bool(c.get("normalize_recommended")),
                "ascii_replacement": c.get("ascii_replacement"),
                "fields": c.get("fields") or [],
            }
            chars.append(entry)
            by_class[entry["classification"]].append(entry)

        total = sum(c["total_count"] for c in chars)
        norm = [c for c in chars if c["normalize_recommended"]]
        print(f"\n  {len(chars)} distinct non-ASCII characters, "
              f"{total:,} occurrences")
        print(f"  {len(norm)} flagged normalize_recommended "
              f"({sum(c['total_count'] for c in norm):,} occurrences)")

        guide = ur["summary"].get("classification_guide") or {}
        for cls, items in sorted(by_class.items(),
                                 key=lambda x: -sum(i["total_count"]
                                                    for i in x[1])):
            tot = sum(i["total_count"] for i in items)
            print(f"\n    {cls} — {len(items)} chars, {tot:,} occurrences")
            if guide.get(cls):
                print(f"      {guide[cls]}")
            for c in sorted(items, key=lambda x: -x["total_count"])[:14]:
                vis = c["char"]
                if c["unicode_category"][:1] in ("C", "Z"):
                    vis = "□"          # placeholder for invisibles
                repl = c["ascii_replacement"]
                arrow = (f" -> {repl!r}" if c["normalize_recommended"]
                         and repl is not None else "")
                print(f"      {c['total_count']:>7,} in {c['file_count']:>4} "
                      f"files  {c['codepoint']:<8} {vis}  "
                      f"{c['name']}{arrow}")

    tags = maybe("newscontent_tags_report.json")
    html_tags = []
    if tags:
        print(f"\n{'=' * 74}\n  HTML TAGS IN SOURCE CONTENT\n{'=' * 74}")
        by_cls = defaultdict(list)
        for t in tags.get("tags") or []:
            e = {"tag": t.get("tag"),
                 "total_count": t.get("total_count") or 0,
                 "file_count": t.get("file_count") or 0,
                 "classification": t.get("classification") or "unclassified",
                 "attributes": t.get("attributes") or []}
            html_tags.append(e)
            by_cls[e["classification"]].append(e)
        for cls, items in sorted(by_cls.items(),
                                 key=lambda x: -sum(i["total_count"]
                                                    for i in x[1])):
            tot = sum(i["total_count"] for i in items)
            print(f"\n    {cls} — {len(items)} tags, {tot:,} occurrences")
            for e in sorted(items, key=lambda x: -x["total_count"]):
                attrs = (f"  attrs: {', '.join(e['attributes'][:6])}"
                         if e["attributes"] else "")
                print(f"      {e['total_count']:>7,} in {e['file_count']:>4} "
                      f"files  <{e['tag']}>{attrs}")

    if out_json:
        report = {
            "stories_scanned": len(files),
            "components": dict(components.most_common()),
            "component_fields": {k: dict(v.most_common())
                                 for k, v in component_fields.items()},
            "richtext_node_types": dict(node_types.most_common()),
            "richtext_node_attrs": {k: dict(v) for k, v in node_attrs.items()},
            "richtext_marks": dict(mark_types.most_common()),
            "richtext_mark_attrs": {k: dict(v) for k, v in mark_attrs.items()},
            "pull_quote_modes": dict(pull_quote_modes),
            "embed_kinds": dict(embed_kinds),
            "content_fields": {k: {"total": v,
                                   "populated": content_populated[k]}
                               for k, v in content_keys.most_common()},
            "media": media,
            "special_characters": sorted(chars,
                                         key=lambda c: -c["total_count"]),
            "html_tags_in_source": sorted(html_tags,
                                          key=lambda t: -t["total_count"]),
        }
        with open(out_json, "w", encoding="utf-8", newline="\n") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n  report -> {out_json}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
