#!/usr/bin/env python3
"""fetch_authors.py — the author biographies and photos AKU did not send.

    python Blogs-Pipeline/pipeline/fetch_authors.py

The delivered export names an author and gives an id, and nothing else. The
`author_section` block was written off as impossible on that basis — until
someone looked at a live AKU blog page and saw a biography and a photograph
sitting in it.

They are real. SharePoint holds them in a list called **AuthorManagement**,
which was simply not part of what AKU sent alongside `categories.json` and
`entities.json`. Asking the site which lists it has finds it in one call:

    /blogs/_api/web/lists?$select=Title,ItemCount

That is worth remembering for events: **ask the site what it holds before
concluding something does not exist.**

Writes two files:

    data/source/authors.json        56 authors, 54 with a Description
    data/source/author_photos.json  author id -> local photo filename

## Photos are matched, not guessed

Only six author photographs exist on the whole site, and their filenames are
inconsistent — "Dr Faisal Ismail - Blog - Author picture.png" beside
"Moneypenny Blog - Author picture.png". A photo is attached to an author only
when every word of their name appears as a whole word in the filename, or when
their surname is unique across all 56 and appears in it.

A looser substring test paired "Didar Ali" with Salim Surani's photograph,
because "ali" hides inside "sALIm". Putting the wrong face on an article is
worse than putting none.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter

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

# Words that are not part of anybody's name.
NOISE = {"dr", "prof", "professor", "mr", "mrs", "ms", "and",
         "blog", "author", "picture", "the"}


def name_words(text):
    return [w for w in re.split(r"[^A-Za-z]+", (text or "").lower())
            if len(w) > 2 and w not in NOISE]


def safe(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-photos", action="store_true")
    a = ap.parse_args()

    session = requests.Session()
    src = os.path.join(P.DATA, "source")
    os.makedirs(src, exist_ok=True)

    r = session.get(f"{BASE}/blogs/_api/web/lists/getbytitle('AuthorManagement')"
                    f"/items?$top=500", headers=UA, timeout=60)
    if r.status_code != 200:
        sys.exit(f"  AuthorManagement returned {r.status_code}. The site may be "
                 f"down, or the list renamed — ask it what it has:\n"
                 f"    {BASE}/blogs/_api/web/lists?$select=Title,ItemCount")
    authors = r.json().get("value", [])
    with open(os.path.join(src, "authors.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump({"value": authors}, f, ensure_ascii=False, indent=2)
    with_bio = sum(1 for x in authors if (x.get("Description") or "").strip())
    print(f"  {len(authors)} authors, {with_bio} with a biography "
          f"-> data/source/authors.json")

    if a.no_photos:
        return 0

    r = session.get(f"{BASE}/blogs/_api/web/GetFolderByServerRelativeUrl"
                    f"('/blogs/PublishingImages')/Files"
                    f"?$select=Name,ServerRelativeUrl&$top=1000",
                    headers=UA, timeout=60)
    files = [x for x in r.json().get("value", [])
             if "author" in (x.get("Name") or "").lower()]
    print(f"  {len(files)} author photo(s) on the site")

    surnames = Counter(name_words(x.get("Title"))[-1] for x in authors
                       if name_words(x.get("Title")))
    media = P.MEDIA_DIR
    os.makedirs(media, exist_ok=True)
    index, got = {}, 0

    for author in authors:
        words = name_words(author.get("Title"))
        if not words:
            continue
        for entry in files:
            in_file = set(name_words(entry["Name"]))
            full = all(w in in_file for w in words)
            unique_surname = words[-1] in in_file and surnames[words[-1]] == 1
            if not (full or unique_surname):
                continue
            local = "author-" + safe(entry["Name"])
            dest = os.path.join(media, local)
            if not os.path.exists(dest):
                got_it = session.get(BASE + entry["ServerRelativeUrl"].replace(" ", "%20"),
                                     headers={"User-Agent": UA["User-Agent"]}, timeout=45)
                if got_it.status_code == 200 and got_it.content:
                    with open(dest, "wb") as f:
                        f.write(got_it.content)
                    got += 1
                else:
                    print(f"    {got_it.status_code}  {entry['Name'][:56]}")
                    break
            index[str(author["ID"])] = local
            print(f"    {author['Title'][:32]:<34}{local.replace('author-', '')[:46]}")
            break

    with open(os.path.join(src, "author_photos.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    unmatched = [x["Name"] for x in files
                 if ("author-" + safe(x["Name"])) not in index.values()]
    print(f"\n  {len(index)} author(s) have a photo; {got} newly downloaded")
    if unmatched:
        print(f"  {len(unmatched)} photo(s) matched nobody confidently — left alone:")
        for n in unmatched:
            print(f"    {n[:66]}")

    with open(P.SOURCE_JSON, encoding="utf-8") as f:
        blogs = json.load(f)
    by_id = {str(x["ID"]): x for x in authors}
    bios = sum(1 for b in blogs
               if (by_id.get(str(b.get("Author Name_id") or ""), {})
                   .get("Description") or "").strip())
    pics = sum(1 for b in blogs if str(b.get("Author Name_id") or "") in index)
    print(f"\n  of {len(blogs)} blogs: {bios} have an author biography, "
          f"{pics} have a photo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
