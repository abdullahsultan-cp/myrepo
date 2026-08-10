#!/usr/bin/env python3
"""
build_crossrefs.py — the clean sheet: who owns each item, and who it is shown on.

AdditionalEntity is the "show this here too, view only" link. This resolves both
ends of that link to a Region > Entity node so you can see, for any item, which
other places reference it.

A reference carries its own region suffix ("Medical College, Pakistan"), so the
connected region is usually resolvable from the reference itself. Where it has no
suffix, the region is inherited from the owning item and marked as such in
ref_region_source — inherited is a guess, entity-suffix is not.

Department is emitted blank at BOTH ends. There is no department field anywhere
in the export, so "which department is it connected to" cannot be answered from
this data at all.

Usage:
    python build_crossrefs.py <input_dir_with_json> <output_dir>

Outputs:
    clean_sheet.csv     one row per news item; references joined into one cell
    connections.csv     one row per news x reference (the long form, for pivots)
    _unresolved.csv     every item with anything still unresolved, + what
"""

import csv
import glob
import html
import json
import os
import sys
from collections import Counter

CITY_TO_REGION = {
    "Karachi": "Pakistan", "Islamabad": "Pakistan", "Lahore": "Pakistan",
    "Nairobi": "Kenya", "Mombasa": "Kenya", "Limuru": "Kenya",
    "Dar es Salaam": "Tanzania", "Arusha": "Tanzania", "Dodoma": "Tanzania",
    "Kampala": "Uganda", "Kabul": "Afghanistan", "London": "United Kingdom",
    "Global": "", "Other": "",
}
ENTITY_REGION_SUFFIXES = (", East Africa", ", Pakistan")
SUFFIX_COVERS = {"Pakistan": {"Pakistan"},
                 "East Africa": {"Kenya", "Tanzania", "Uganda"}}
UNMAPPED = "UNMAPPED"
NO_OWNER = {"Global"}


def unesc(s):
    return html.unescape(html.unescape(s or "")).strip()


def lk(v):
    if not isinstance(v, dict) or v.get("Id") in (-1, None):
        return ""
    return unesc(v.get("Title"))


def split_entity(e):
    for suf in ENTITY_REGION_SUFFIXES:
        if e.endswith(suf):
            return e[:-len(suf)], suf[2:]
    return e, ""


def w(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        cw = csv.DictWriter(f, lineterminator="\n",
                            fieldnames=header, extrasaction="ignore")
        cw.writeheader()
        cw.writerows(rows)
    print(f"  {len(rows):>5}  {os.path.basename(path)}")


def main(indir, outdir):
    os.makedirs(outdir, exist_ok=True)
    files = sorted(glob.glob(os.path.join(indir, "*.json")))
    if not files:
        sys.exit(f"no .json in {indir}")

    sheet, links, unresolved = [], [], []
    ref_pairs = Counter()
    stat = Counter()

    for path in files:
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            print(f"!! {os.path.basename(path)}: {e}", file=sys.stderr)
            continue

        nid = d.get("Id") or d.get("ID")
        title = unesc(d.get("Title"))
        city = lk(d.get("City"))
        raw_entity = lk(d.get("Entity"))
        entity, ent_suffix = split_entity(raw_entity)

        # ---------- owning region: entity suffix, then city, then Global
        city_region = CITY_TO_REGION.get(city, "")
        suffix_countries = SUFFIX_COVERS.get(ent_suffix, set())
        if len(suffix_countries) == 1:
            region = next(iter(suffix_countries))
        elif city_region:
            region = city_region
        elif city == "Global":
            region = "Global"
        else:
            region = UNMAPPED

        is_global_entity = raw_entity in NO_OWNER
        gaps = []
        if region == UNMAPPED:
            gaps.append(f"region unresolved (city '{city}')")

        # ---------- the references
        refs, ref_cells = [], []
        for i, a in enumerate(d.get("AdditionalEntity") or []):
            t = lk(a)
            if not t or t == raw_entity:
                continue
            r_ent, r_suffix = split_entity(t)
            r_countries = SUFFIX_COVERS.get(r_suffix, set())
            if len(r_countries) == 1:
                r_region, r_src = next(iter(r_countries)), "entity-suffix"
            elif r_ent in NO_OWNER:
                r_region, r_src = "Global", "reference-is-global"
            elif region != UNMAPPED:
                r_region, r_src = region, "inherited-from-owner"
            else:
                r_region, r_src = UNMAPPED, "none"
            if r_src == "inherited-from-owner":
                stat["ref region inherited (a guess)"] += 1
            if r_src == "none":
                gaps.append(f"reference '{r_ent}' has no resolvable region")

            refs.append({"entity": r_ent, "region": r_region, "source": r_src})
            ref_cells.append(f"{r_region} > {r_ent}")
            ref_pairs[(f"{region} > {entity}", f"{r_region} > {r_ent}")] += 1

            links.append({
                "news_id": nid, "title": title,
                "owner_region": region, "owner_entity": entity,
                "owner_department": "",
                "ref_index": i + 1,
                "ref_region": r_region, "ref_entity": r_ent,
                "ref_department": "",
                "ref_region_source": r_src,
                "ref_path": (f"Regions/{r_region}/Entities/{r_ent}/"
                             f"Departments/<department>/News/{nid}"),
            })

        row = {
            "news_id": nid,
            "title": title,
            "region": region,
            "entity": entity,
            "department": "",
            "connected_to": " | ".join(ref_cells),
            "connection_count": len(refs),
            "is_global_entity": str(is_global_entity),
            "surface_global": str(bool(d.get("GlobalNews"))),
            "city": city,
            "published_date": (d.get("ScheduleStartDate")
                               or d.get("Created") or "")[:10],
            "unresolved": "; ".join(gaps) or "",
        }
        # department is unresolvable for every single row, by construction
        row["unresolved"] = "; ".join(
            gaps + ["department: no source field in export"])
        sheet.append(row)
        if gaps:
            unresolved.append(row)

        stat["items"] += 1
        if refs:
            stat["items with >=1 reference"] += 1
            if is_global_entity:
                stat["  of those, owned by Global"] += 1
            else:
                stat["  of those, owned by a real entity"] += 1

    if not sheet:
        sys.exit("no rows parsed")

    sheet.sort(key=lambda r: (-r["connection_count"], r["region"], r["entity"]))
    w(os.path.join(outdir, "clean_sheet.csv"), list(sheet[0].keys()), sheet)
    if links:
        w(os.path.join(outdir, "connections.csv"), list(links[0].keys()), links)
    w(os.path.join(outdir, "_unresolved.csv"), list(sheet[0].keys()), unresolved)

    print("\n" + "-" * 58)
    for k, v in stat.items():
        print(f"  {v:>5}  {k}")
    print(f"  {len(links):>5}  total connections")
    print(f"  {len(ref_pairs):>5}  distinct owner -> reference pairs")
    print("-" * 58 + "\n  top 10 connections:")
    for (a, b), c in ref_pairs.most_common(10):
        print(f"  {c:>5}  {a}   ->   {b}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
