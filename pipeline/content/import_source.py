#!/usr/bin/env python3
"""import_source.py — turn whatever the export arrived as into the type's JSON.

News arrived as `news.json`, a SharePoint OData response. Blogs arrived as
`Metadata.csv`. The rest of the pipeline reads one file, `P.SOURCE_JSON`, so
this step is where that difference stops.

    python pipeline/import_source.py --type blogs
    python pipeline/import_source.py --type blogs --dry-run

Declared per type in `config/types/<type>.json`:

    "source_format": "csv",
    "source_file":   "data/source/Metadata.csv",

A type whose export is already the right shape declares nothing and this step
does nothing — news passes straight through.

## What it normalises, and what it deliberately does not

SharePoint encodes lookup columns and multi-value fields in its own way, and
those encodings are an artefact of the export rather than content:

    "My Story [ID: 4]"   a lookup -- the label, with the row id appended
    "string;#2025"       a single-valued multi-field
    "string;#a;#b"       a genuinely multi-valued one

Left as-is they end up in slugs, in folder names and on the page. This strips
them into `Category` -> "My Story" and keeps the id in `Category_id`, so nothing
is lost and the common case is clean. Everything else is copied verbatim: no
trimming of HTML, no case changes, no dropping of empty columns. The original
export stays untouched in `data/source/` either way.
"""

import argparse
import csv
import json
import os
import os as _os
import re
import sys
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import _bootstrap

_bootstrap.ensure()

from paths_root import ROOT, P, add_type_argument, apply_type_argument

# "Label [ID: 4]" -- a SharePoint lookup rendered for humans.
LOOKUP = re.compile(r"^(.*?)\s*\[ID:\s*(\d+)\]\s*$", re.S)
# "string;#2025" or "string;#a;#b" -- SharePoint's multi-value encoding.
MULTI_PREFIX = re.compile(r"^(?:string|int|float|datetime|boolean);#", re.I)


def decode_cell(value):
    """Return (clean_value, lookup_id_or_None) for one exported cell."""
    if not isinstance(value, str):
        return value, None
    v = value.strip()
    if not v:
        return v, None

    if MULTI_PREFIX.match(v):
        # ;# separates entries; the leading type token is not one of them.
        parts = [p for p in re.split(r";#", v)[1:] if p != ""]
        v = "; ".join(parts) if len(parts) > 1 else (parts[0] if parts else "")

    m = LOOKUP.match(v)
    if m:
        return m.group(1).strip(), m.group(2)
    return v, None


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_json(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("value") or data.get("items") or []
    return data


def normalise(rows):
    """Decode SharePoint's encodings, keeping the id alongside the label."""
    out, decoded = [], 0
    for row in rows:
        item = {}
        for k, v in row.items():
            if k is None:
                continue
            clean, lookup_id = decode_cell(v)
            item[k] = clean
            if lookup_id is not None:
                item[f"{k}_id"] = lookup_id
                decoded += 1
            elif clean != (v.strip() if isinstance(v, str) else v):
                decoded += 1
        out.append(item)
    return out, decoded


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_type_argument(ap)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be written, write nothing")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing export JSON")
    a = ap.parse_args()
    apply_type_argument(a)

    spec = P.spec
    fmt = (spec.get("source_format") or "json").lower()
    rel = spec.get("source_file")
    dest = P.SOURCE_JSON

    if fmt == "json" and not rel:
        print(f"  {P.type}: source_format is json and no source_file is set —")
        print(f"  the export is already {os.path.relpath(dest, ROOT)}; nothing to do.")
        return 0 if os.path.exists(dest) else 1

    src = os.path.join(P.PIPELINE, rel) if rel else dest
    if not os.path.exists(src):
        sys.exit(f"  no source at {os.path.relpath(src, ROOT)}")

    rows = read_csv(src) if fmt == "csv" else read_json(src)
    if not rows:
        sys.exit(f"  {os.path.relpath(src, ROOT)} is empty")

    items, decoded = normalise(rows)
    cols = sorted({k for it in items for k in it})

    print(f"  {P.type}: {os.path.relpath(src, ROOT)}  ({fmt})")
    print(f"    {len(items)} items, {len(cols)} columns")
    print(f"    {decoded} SharePoint lookup/multi-value cells decoded")

    id_col = (P.fields or {}).get("id", "Id")
    ids = [str(it.get(id_col, "")).strip() for it in items]
    blank = sum(1 for i in ids if not i)
    dupes = len(ids) - len(set(ids))
    print(f"    id column {id_col!r}: {len(set(ids))} distinct"
          + (f", {blank} BLANK" if blank else "")
          + (f", {dupes} DUPLICATE" if dupes else ""))
    if blank or dupes:
        print("    ids must be unique and present — every later stage keys on them")
        return 1

    body_col = (P.fields or {}).get("body")
    if body_col:
        empty = sum(1 for it in items if not str(it.get(body_col) or "").strip())
        print(f"    body column {body_col!r}: {len(items) - empty} with content"
              + (f", {empty} EMPTY" if empty else ""))
        if empty == len(items):
            print(f"    every body is empty — {body_col!r} is almost certainly the")
            print(f"    wrong column. Check: python pipeline/new_type.py {P.type} --check")
            return 1

    if a.dry_run:
        print(f"\n  --dry-run: would write {os.path.relpath(dest, ROOT)}")
        return 0
    if os.path.exists(dest) and not a.force:
        sys.exit(f"  {os.path.relpath(dest, ROOT)} exists; pass --force to replace it")

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8", newline="\n") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n  wrote {os.path.relpath(dest, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
