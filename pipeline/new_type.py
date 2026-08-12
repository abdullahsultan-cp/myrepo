#!/usr/bin/env python3
"""
new_type.py — scaffold a content type, and check its profile against reality.

Adding a type should be filling in a form, not copying a pipeline. This creates
the profile and the folders, then tells you exactly what still has to be
confirmed — because the parts that cannot be guessed are the parts that fail
silently:

    a wrong `fields.body`      every item migrates blank
    a wrong `storyblok`        the upload is rejected, or worse, accepted wrong
    a wrong `hierarchy.leaf`   the upload stops, asking for a folder nobody has

Usage:
    python pipeline/new_type.py articles              # scaffold
    python pipeline/new_type.py articles --check      # profile vs the export
    python pipeline/new_type.py --list                # what exists now
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap

# ensure() is what PUTS paths_root on sys.path, so it has to run before the
# import below. The blank lines keep them in separate blocks, which is what
# stops the import sorter merging and reordering them.
_bootstrap.ensure()

from paths_root import ROOT, TYPES, TYPES_DIR, P

TEMPLATE = os.path.join(TYPES_DIR, "_TEMPLATE.json")


def scaffold(name):
    name = name.strip().lower()
    if not name.isidentifier():
        sys.exit(f"  {name!r} is not a usable type name; use letters and "
                 f"underscores")
    dest = os.path.join(TYPES_DIR, f"{name}.json")
    if os.path.exists(dest):
        sys.exit(f"  config/types/{name}.json already exists — edit it, or "
                 f"delete it first")

    with open(TEMPLATE, encoding="utf-8") as f:
        raw = f.read()

    title = name.capitalize()
    prof = json.loads(raw.replace("TYPE-Pipeline", f"{title}-Pipeline")
                         .replace('"TYPE.json"', f'"{name}.json"')
                         .replace('"TYPE item"', f'"{name[:-1] if name.endswith("s") else name}"')
                         .replace('"assets_dir": "TYPE"', f'"assets_dir": "{title}"')
                         .replace('"leaf": "TYPE"', f'"leaf": "{name}"')
                         .replace('"type": "TYPE"', f'"type": "{name}"'))
    prof.pop("_README", None)
    prof["_comment"] = [
        f"Profile for {name}. Scaffolded from _TEMPLATE.json.",
        "",
        "Every _comment marked CONFIRM is still a guess. Run",
        f"    python pipeline/new_type.py {name} --check",
        "once the export is in place, and read the live schema before the first",
        "upload.",
    ]

    with open(dest, "w", encoding="utf-8", newline="\n") as f:
        json.dump(prof, f, indent=2, ensure_ascii=False)
        f.write("\n")

    pipe = os.path.join(ROOT, prof["folder"])
    for sub in ("data", os.path.join("assets", prof["assets_dir"], "media"),
                os.path.join("backup", "raw"),
                os.path.join("backup", "storyblok")):
        os.makedirs(os.path.join(pipe, sub), exist_ok=True)

    readme = os.path.join(pipe, "README.md")
    if not os.path.exists(readme):
        with open(readme, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"""# {prof['folder']}

The {name} migration. Shares `pipeline/` with every other type; only the data
and the profile are separate.

## What is needed

```
{prof['folder']}/data/{prof['source']}
```

The SharePoint OData export — a bare list or `{{"value": [...]}}`.

## Then

```bash
python pipeline/new_type.py {name} --check        # profile vs the real export
python pipeline/run_pipeline.py all --type {name}
python pipeline/taxonomy/run_taxonomy.py --type {name}
python pipeline/migrate/download/run_media_all.py --type {name}
python pipeline/migrate/upload/run_migration.py --type {name}
```

## Confirm before the first upload

- **`fields`** in `config/types/{name}.json` — the column names are copied from
  the News list and are almost certainly not all right. `--check` compares them
  against the export.
- **`storyblok.component`** — currently `news_article`, which is a placeholder.
  Read the live space with `pipeline/fetch_storyblok_space.py`.
- **`hierarchy.leaf`** — currently `{name}`. The folder must already exist in
  Storyblok; the pipeline will not create one under `regions/` or `global/`.
""")

    print(f"  created  config/types/{name}.json")
    print(f"  created  {prof['folder']}/  (data, assets, backup, README)")
    print("\n  Next:")
    print(f"    1. put the export at {prof['folder']}/data/{prof['source']}")
    print(f"    2. python pipeline/new_type.py {name} --check")
    print("    3. confirm storyblok.component against the live space")
    return 0


def check(name):
    """Compare the profile's assumptions against the actual export."""
    if name not in TYPES:
        sys.exit(f"  no profile for {name!r}; run: python pipeline/new_type.py "
                 f"{name}")
    P.use(name)
    prof = P.spec
    print(f"\n  {name} — profile vs the real export")
    print(f"  {'=' * 66}")

    src = P.SOURCE_JSON
    if not os.path.exists(src):
        print(f"  no export at {os.path.relpath(src, ROOT)}")
        print("  Nothing can be checked until it is there.")
        return 1
    with open(src, encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("value") if isinstance(data, dict) else data
    if not items:
        print("  the export is empty")
        return 1
    present = set()
    for it in items[:200]:
        present.update(it.keys())
    print(f"  {len(items)} items, {len(present)} distinct columns\n")

    fields = {k: v for k, v in (prof.get("fields") or {}).items()
              if not k.startswith("_")}
    bad = []
    print(f"  {'profile key':<20}{'column':<26}found?")
    for key, col in sorted(fields.items()):
        # `null` is a DECLARED ABSENCE, not a mistake: blogs has no City column
        # and events has no author, pull quote or approver group. Those entries
        # are kept as null so the gap is visible in the profile -- so they are
        # reported as "absent" rather than counted as a wrong column name, and
        # never joined into a string. `", ".join([None])` raised a TypeError and
        # took this whole command down, for blogs as well as events, which also
        # meant the `--check` job in CI was failing.
        if col is None:
            print(f"  {key:<20}{'(declared absent)':<26}n/a")
            continue
        cols = [c for c in (col if isinstance(col, list) else [col]) if c]
        hits = [c for c in cols if c in present]
        ok = "yes" if hits else "NO"
        if not hits:
            bad.append((key, cols))
        shown = ", ".join(cols)[:24]
        print(f"  {key:<20}{shown:<26}{ok}")

    if bad:
        print(f"\n  {len(bad)} field(s) name a column the export does not have.")
        print("  These yield EMPTY values silently -- nothing errors.")
        for key, cols in bad:
            near = [c for c in sorted(present)
                    if any(w and w.lower() in c.lower()
                           for w in (cols[0][:6],))][:4]
            print(f"    {key:<18} {cols}")
            if near:
                print(f"        maybe: {near}")
        print(f"\n  Fix them in config/types/{name}.json")
    else:
        print("\n  every field maps to a real column")

    body_col = fields.get("body")
    if body_col in present:
        empty = sum(1 for it in items if not (it.get(body_col) or "").strip())
        print(f"\n  body column {body_col!r}: {len(items) - empty} of "
              f"{len(items)} items have content"
              + (f", {empty} are EMPTY" if empty else ""))

    # source_urls cannot be checked against a column, but it CAN be checked
    # against the links the export actually contains -- which is the only thing
    # that matters. A wrong detail_page means every internal cross-link stays
    # pointing at aku.edu, silently, and aku.edu is being switched off.
    su = P.source_urls
    body_col = fields.get("body")
    if body_col in present:
        import re as _re
        hrefs = []
        for it in items:
            hrefs += _re.findall(r'href="([^"]+)"', it.get(body_col) or "")
        page = su["detail_page"].lower()
        hits = sum(1 for h in hrefs if page in h.lower())
        prefix = su["prefix"].rstrip("/").lower() + "/"
        pre_hits = sum(1 for h in hrefs if h.lower().startswith(prefix))
        print(f"\n  source_urls, checked against the {len(hrefs):,} links in the export")
        print(f"    detail_page {su['detail_page']:<22} {hits:,} link(s) match")
        print(f"    prefix      {su['prefix']:<22} {pre_hits:,} link(s) match")
        if not hits and not pre_hits:
            bad.append(("source_urls", [su["detail_page"], su["prefix"]]))
            print("    NOTHING MATCHES. Internal cross-links will not resolve and")
            print("    will be left pointing at aku.edu. Open a body field, find a")
            print("    real internal link, and set these from it.")

    print(f"\n  hierarchy leaf : {P.leaf}   (where it lands in Storyblok)")
    print(f"  source prefix  : {su['prefix']}   (where it came from on aku.edu)")
    print(f"  component      : {P.component}   "
          f"{'<- still the news placeholder' if P.component == 'news_article' and name != 'news' else ''}")
    print(f"  example target : "
          f"{P.folder_for('entity', region='Kenya', entity='Medical College')}")
    return 1 if bad else 0


def listing():
    print(f"\n  {'type':<10}{'folder':<20}{'leaf':<9}{'component':<15}export")
    for t in sorted(TYPES):
        P.use(t)
        has = "present" if os.path.exists(P.SOURCE_JSON) else "MISSING"
        print(f"  {t:<10}{P.spec['folder']:<20}{P.leaf:<9}{P.component:<15}{has}")
    print("\n  profiles live in config/types/; _TEMPLATE.json is the boilerplate")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?", help="the content type, e.g. articles")
    ap.add_argument("--check", action="store_true",
                    help="compare an existing profile against its export")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list or not a.name:
        return listing()
    if a.check:
        return check(a.name.strip().lower())
    return scaffold(a.name)


if __name__ == "__main__":
    sys.exit(main())
