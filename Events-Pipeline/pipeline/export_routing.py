#!/usr/bin/env python3
"""export_routing.py — where every event lands and what it carries, as a sheet.

    python Events-Pipeline/pipeline/export_routing.py

    -> Events-Pipeline/data/taxonomy/routing.csv    one row per event
    -> Events-Pipeline/data/taxonomy/folders.csv    one row per destination folder

Nothing here is reimplemented. The routing, the date derivation and the image
choice are all imported from build_portal.py, so this sheet and the portal can
never disagree -- the same mapping lived in two places three times already and
drifted every time.

Every row carries `reason`, the rule that produced the placement, so a disputed
folder is traced to the data or to a decision rather than argued about. That is
news's convention: region_source / entity_source on every row.

Columns
    event_id .. venue          straight off the export, unchanged
    start_at .. deadline       the five event_article date fields, as they will
                               be written. start_at/end_at are Storyblok
                               `datetime`; the other three are display text
    region                     region short code, or (global)
    entity_short               AKU's own short code, blank at region level
    placement                  entity | region | global
    folder_path                the full Storyblok slug this event goes in
    folder_exists              checked against the live tree snapshot
    reason                     which rule fired
    banner_source              imageurl | attachment_files | (none)
    body_image                 the attachment, when it is not the banner
"""

import csv
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from build_portal import (  # noqa: I001  the import must follow the path insert
    ROOT, P, choose_images, clean, dates_for, load_entity_distribution,
    load_entity_lookup, route, strip_html,
)

OUT_DIR = os.path.join(P.DATA, "taxonomy")
ROUTING = os.path.join(OUT_DIR, "routing.csv")
FOLDERS = os.path.join(OUT_DIR, "folders.csv")

COLS = ["event_id", "title",
        "start_at", "end_at", "event_date", "event_time", "deadline",
        "tag", "entity_source", "country_source", "city_source", "venue",
        "region", "entity_short", "placement", "folder_path", "folder_exists",
        "reason", "banner_source", "body_image"]


def write(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # utf-8-sig so Excel opens the Arabic and Urdu titles correctly; \n endings
    # so the file does not read as wholly rewritten on another machine.
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n",
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  {len(rows):>5}  {os.path.relpath(path, ROOT)}")


def main():
    src = os.path.join(P.PIPELINE, "data", "source", "Metadata.csv")
    if not os.path.exists(src):
        sys.exit(f"  no export at {os.path.relpath(src, ROOT)}")
    csv.field_size_limit(10 ** 9)
    with open(src, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    tree = set()
    if os.path.exists(P.SPACE_TREE):
        with open(P.SPACE_TREE, encoding="utf-8") as f:
            tree = {x["full_slug"] for x in json.load(f)["folders"]}
    load_entity_lookup(tree)
    load_entity_distribution(rows)

    on_disk = set(os.listdir(P.MEDIA_DIR)) if os.path.isdir(P.MEDIA_DIR) else set()
    print(f"  {len(rows)} events, {len(tree)} folders in the space snapshot")

    out = []
    for r in rows:
        target, placement, why = route(r, tree)
        banner, banner_src, body_img = choose_images(r, on_disk)
        d = dates_for(r)
        parts = target.split("/")
        out.append({
            "event_id": r.get("ID") or "",
            "title": clean(r.get("EventTitle") or r.get("Title") or ""),
            "start_at": d["start_at"], "end_at": d["end_at"],
            "event_date": d["event_date"], "event_time": d["event_time"],
            "deadline": d["deadline"],
            "tag": clean(r.get("Tags") or ""),
            "entity_source": clean(r.get("Entity") or ""),
            "country_source": clean(r.get("Country") or ""),
            "city_source": clean(r.get("City") or ""),
            "venue": strip_html(r.get("Venue") or "")[:120],
            "region": ("(global)" if placement == "global"
                       else parts[1] if len(parts) > 1 else "(unresolved)"),
            "entity_short": parts[3] if placement == "entity" and len(parts) > 3 else "",
            "placement": placement,
            "folder_path": target,
            "folder_exists": "yes" if target in tree else "no",
            "reason": why,
            "banner_source": banner_src or "(none)",
            "body_image": body_img,
        })

    out.sort(key=lambda x: (x["folder_path"], x["start_at"], x["event_id"]))
    write(ROUTING, COLS, out)

    # ---- one row per destination folder
    by = {}
    for x in out:
        b = by.setdefault(x["folder_path"], {
            "folder_path": x["folder_path"], "placement": x["placement"],
            "region": x["region"], "entity_short": x["entity_short"],
            "events": 0, "folder_exists": x["folder_exists"],
            "with_banner": 0, "with_body_image": 0,
            "with_event_time": 0, "earliest": "", "latest": ""})
        b["events"] += 1
        if x["banner_source"] != "(none)":
            b["with_banner"] += 1
        if x["body_image"]:
            b["with_body_image"] += 1
        if x["event_time"]:
            b["with_event_time"] += 1
        for k, pick in (("earliest", min), ("latest", max)):
            if x["start_at"]:
                b[k] = pick(b[k] or x["start_at"], x["start_at"])
    folders = sorted(by.values(), key=lambda b: (-b["events"], b["folder_path"]))
    write(FOLDERS, ["folder_path", "placement", "region", "entity_short",
                    "events", "with_banner", "with_body_image",
                    "with_event_time", "folder_exists", "earliest", "latest"],
          folders)

    print()
    for k, v in Counter(x["placement"] for x in out).most_common():
        print(f"    {v:>5}  {k}")
    missing = {x["folder_path"] for x in out if x["folder_exists"] == "no"}
    print(f"    {len(missing):>5}  destination folders NOT in the space"
          + (f"  {sorted(missing)}" if missing else ""))
    print()
    for f in ("start_at", "end_at", "event_date", "event_time", "deadline"):
        n = sum(1 for x in out if x[f])
        print(f"    {n:>5}  {f} filled  ({100 * n / len(out):.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
