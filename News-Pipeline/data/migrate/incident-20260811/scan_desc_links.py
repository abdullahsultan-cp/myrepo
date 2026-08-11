#!/usr/bin/env python3
"""Local only. How many hyperlinks disappear because paragraph 1 becomes the
plain-text `description` field?

Uses build_payload's OWN helpers and repeats its own first-paragraph rule
(build_payload.py:510-525) so this measures the real behaviour rather than a
paraphrase of it. Validated against the 184 stories we already know about.
"""
import csv
import gzip
import json
import os
import sys

REPO = r"d:\AKU News\aku-data-transformation-pipeline-news-master"
HERE = os.path.dirname(os.path.abspath(__file__))
STORIES = os.path.join(REPO, r"News-Pipeline\data\stories")
SNAP = os.path.join(REPO, r"News-Pipeline\backup\storyblok\news_20260809-160355.json.gz")

sys.path.insert(0, os.path.join(REPO, r"pipeline\migrate\upload"))
sys.path.insert(0, os.path.join(REPO, r"pipeline\core"))
from build_payload import plain_text, doc_of, count_words  # noqa: E402

with gzip.open(SNAP, "rb") as f:
    snap = json.loads(f.read().decode("utf-8"))["stories"]
slug_of = {sid: st.get("full_slug") for sid, st in snap.items()}


def links_in(node):
    found = []

    def w(n, txt_owner=None):
        if isinstance(n, dict):
            if n.get("type") == "text":
                for m in n.get("marks") or []:
                    if m.get("type") == "link":
                        a = m.get("attrs") or {}
                        found.append((a.get("href"), n.get("text") or "",
                                      a.get("target")))
            for v in n.values():
                w(v)
        elif isinstance(n, list):
            for v in n:
                w(v)
    w(node)
    return found


rows = []
taken_total = not_taken = 0
for fn in sorted(os.listdir(STORIES)):
    if not fn.endswith(".json"):
        continue
    sid = fn[:-5]
    with open(os.path.join(STORIES, fn), encoding="utf-8") as f:
        c = json.load(f)["content"]
    src = c.get("body") if isinstance(c.get("body"), dict) else {}
    nodes = list(src.get("content") or [])
    if not nodes:
        continue

    # build_payload's rule, applied to the first prose paragraph
    for i, node in enumerate(nodes):
        if node.get("type") != "paragraph":
            break
        candidate = plain_text(doc_of([node])).strip()
        more_follows = any(n.get("type") != "paragraph"
                           or plain_text(doc_of([n])).strip()
                           for n in nodes[i + 1:])
        if len(candidate) >= 40 and count_words(candidate) >= 6 and more_follows:
            taken_total += 1
            for href, text, target in links_in(node):
                rows.append({"sharepoint_id": sid,
                             "full_slug": slug_of.get(sid, ""),
                             "href": href, "link_text": text,
                             "target": target or "",
                             "kind": "internal" if (href or "").startswith("/")
                                     or "aku.edu" in (href or "") else "external"})
            break
        not_taken += 1
        break

stories = {r["sharepoint_id"] for r in rows}
ext = [r for r in rows if r["kind"] == "external"]
inte = [r for r in rows if r["kind"] == "internal"]
print(f"  stories scanned                        : "
      f"{len(os.listdir(STORIES))}")
print(f"  paragraph 1 taken as description       : {taken_total}")
print(f"  paragraph 1 left in the body           : {not_taken}")
print(f"\n  LINKS LOST TO THE DESCRIPTION MOVE     : {len(rows)}")
print(f"    across stories                       : {len(stories)}")
print(f"    external                             : {len(ext)}")
print(f"    internal (aku.edu or /...)           : {len(inte)}")

out = os.path.join(HERE, "description_links.csv")
with open(out, "w", encoding="utf-8", newline="") as f:
    wr = csv.DictWriter(f, fieldnames=["sharepoint_id", "full_slug", "href",
                                       "link_text", "target", "kind"])
    wr.writeheader()
    wr.writerows(sorted(rows, key=lambda r: int(r["sharepoint_id"])))
print(f"\n  wrote {out}")

with open(os.path.join(HERE, "affected.json"), encoding="utf-8") as f:
    known = {r["sharepoint_id"] for r in json.load(f)["found"]}
overlap = stories & known
print(f"  of the 184 stories in the CSV, {len(overlap)} are in this list "
      f"-- {len([r for r in rows if r['sharepoint_id'] in known])} links")

print("\n  a few examples:")
for r in sorted(rows, key=lambda r: int(r["sharepoint_id"]))[:8]:
    print(f"    {r['sharepoint_id']:>5}  {r['link_text'][:34]:<34} -> "
          f"{(r['href'] or '')[:70]}")
