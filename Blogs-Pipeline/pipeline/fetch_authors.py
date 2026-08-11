#!/usr/bin/env python3
"""fetch_authors.py — the author biographies and photographs.

    python Blogs-Pipeline/pipeline/fetch_authors.py

The delivered blogs export names an author and gives an id, and nothing else.
The `author_section` block was written off as impossible on that basis — until
someone looked at a live AKU blog page and saw a biography and a photograph
sitting in it.

They are real. SharePoint holds them in a list called **AuthorManagement**,
which was simply not part of the first delivery. Asking the site which lists it
has finds it in one call:

    /blogs/_api/web/lists?$select=Title,ItemCount

That is worth remembering for events: **ask the site what it holds before
concluding something does not exist.**

## Two sources, and the export wins on photos

`backup/raw/AuthorManagement/` is AKU's own export of that list, delivered
later, and it is authoritative for photographs: every row carries an
**`AuthorImage`** column naming its file, and the `media/` folder beside it
holds all 52. There is nothing to infer.

That matters, because inference here was bad. Matching photos to authors by
name — the only option before this export arrived — reached 7 authors out of 56
and paired **"Didar Ali" with Salim Surani's photograph**, since "ali" hides
inside "sALIm". Tightening it to whole words did not help much: the filenames
disagree with each other, `Dr Faisal Ismail - Blog - Author picture.png` beside
`Moneypenny Blog - Author picture.png`. An explicit column beats a clever rule.
The guessing code is gone; if the export is missing, this exits rather than
falling back to it.

The **live API** is still read, for two reasons: it has four authors added
after the export was cut (ids 60-63), and it is the check that the export is
current. Where both hold a biography they agree, 48 times out of 50.

## Filenames arrive percent-encoded

`AuthorImage` reads `Didar%20Ali1786380536.png` while the file on disk is
`Didar_20Ali1786380536.png` — the zip replaced `%` with `_`. Twelve of the 52
look missing until that is undone, which is why the mapping normalises before
it despairs.

Writes:

    data/source/authors.json        the live list, bios included
    data/source/author_photos.json  author id -> local photo filename
    assets/Blogs/media/author-*     the photographs themselves
"""

import argparse
import csv
import json
import os
import shutil
import sys

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "pipeline"))
import _bootstrap

_bootstrap.ensure()

from paths_root import P

P.use("blogs")

BASE = "https://www.aku.edu"
UA = {"User-Agent": "Mozilla/5.0 (compatible; AKU-migration/1.0)",
      "Accept": "application/json;odata=nometadata"}


def export_dir():
    return os.path.join(P.PIPELINE, "backup", "raw", "AuthorManagement")


def on_disk_name(author_image):
    """The delivered filename, undoing the zip's percent-mangling."""
    return (author_image or "").strip().replace("%", "_")


def read_export():
    """[(id, name, image filename, bio)] from AKU's AuthorManagement export."""
    path = os.path.join(export_dir(), "Metadata.csv")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-photos", action="store_true")
    ap.add_argument("--offline", action="store_true",
                    help="use only the delivered export; do not call aku.edu")
    a = ap.parse_args()

    src = os.path.join(P.DATA, "source")
    os.makedirs(src, exist_ok=True)
    rows = read_export()
    print(f"  {len(rows)} author(s) in backup/raw/AuthorManagement/Metadata.csv")

    # ---- the live list, for the authors added after the export was cut -----
    authors = []
    if not a.offline:
        r = requests.get(f"{BASE}/blogs/_api/web/lists/getbytitle('AuthorManagement')"
                         f"/items?$top=500", headers=UA, timeout=60)
        if r.status_code == 200:
            authors = r.json().get("value", [])
            extra = {str(x["ID"]) for x in authors} - {r_["ID"] for r_ in rows}
            print(f"  {len(authors)} on the live list"
                  + (f"; {len(extra)} newer than the export: "
                     f"{sorted(extra, key=int)}" if extra else "; same set"))
        else:
            print(f"  live list returned {r.status_code}; export only")
    if not authors:
        authors = [{"ID": int(x["ID"]), "Title": x["Title"],
                    "Description": x.get("Description") or "",
                    "IsActive": x.get("IsActive")} for x in rows]
    with open(os.path.join(src, "authors.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump({"value": authors}, f, ensure_ascii=False, indent=2)
    with_bio = sum(1 for x in authors if (x.get("Description") or "").strip())
    print(f"  {with_bio} of {len(authors)} have a biography "
          f"-> data/source/authors.json")

    if a.no_photos:
        return 0

    # ---- photographs, named explicitly by the export ----------------------
    if not rows:
        sys.exit("  no AuthorManagement export, and photos are not guessable.\n"
                 "  Put AKU's export in Blogs-Pipeline/backup/raw/AuthorManagement/\n"
                 "  (Metadata.csv plus its media/ folder).")

    media_src = os.path.join(export_dir(), "media")
    delivered = set(os.listdir(media_src)) if os.path.isdir(media_src) else set()
    dest_dir = P.MEDIA_DIR
    os.makedirs(dest_dir, exist_ok=True)

    index, copied, absent = {}, 0, []
    for row in rows:
        want = on_disk_name(row.get("AuthorImage"))
        if not want:
            continue
        if want not in delivered:
            absent.append((row["ID"], row.get("AuthorImage")))
            continue
        local = "author-" + want
        dest = os.path.join(dest_dir, local)
        if not os.path.exists(dest):
            shutil.copy2(os.path.join(media_src, want), dest)
            copied += 1
        index[str(row["ID"])] = local

    with open(os.path.join(src, "author_photos.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"\n  {len(index)} of {len(rows)} authors have a photograph "
          f"({copied} newly copied)")
    if absent:
        print(f"  {len(absent)} named a file the export did not ship:")
        for aid, name in absent:
            print(f"    {aid:<5}{name[:64]}")
    unused = delivered - {v[len("author-"):] for v in index.values()}
    if unused:
        print(f"  {len(unused)} media file(s) belong to no row: "
              f"{sorted(unused)[:4]}")

    # ---- what that means for the 83 blogs ---------------------------------
    with open(P.SOURCE_JSON, encoding="utf-8") as f:
        blogs = json.load(f)
    by_id = {str(x["ID"]): x for x in authors}
    bios = sum(1 for b in blogs
               if (by_id.get(str(b.get("Author Name_id") or ""), {})
                   .get("Description") or "").strip())
    pics = sum(1 for b in blogs if str(b.get("Author Name_id") or "") in index)
    orphan = sorted({str(b.get("Author Name_id") or "") for b in blogs
                     if str(b.get("Author Name_id") or "") not in by_id
                     and b.get("Author Name_id")}, key=int)
    print(f"\n  of {len(blogs)} blogs: {bios} have an author biography, "
          f"{pics} have a photograph")
    if orphan:
        n = sum(1 for b in blogs
                if str(b.get("Author Name_id") or "") in orphan)
        print(f"  author id(s) {orphan} are in neither source — {n} blog(s); "
              f"the live list 404s on them")
    return 0


if __name__ == "__main__":
    sys.exit(main())
