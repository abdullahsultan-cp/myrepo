#!/usr/bin/env python3
"""
harvest_lookups.py — build complete Region / Entity / Tag maps from the JSON dump.

No network, no auth. Tells you exactly what your 3360 items actually reference.

Usage:
    python harvest_lookups.py <input_dir_with_json> <output_dir>

Outputs:
    lk_cities.csv       every City Id+Title seen, usage count, suggested region
    lk_entities.csv     every Entity Id+Title seen, usage as primary vs additional
    lk_tags.csv         every Tag label, TermGuid variants, usage count
    lk_approvers.csv    LocalApproverGroup values (proxy for owning department)
    region_map.csv      EDIT THIS -> city,region pairs to feed back into the converter
    _drift.txt          Id/Title inconsistencies you must resolve before migrating
"""

import csv
import glob
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict

# Candidate city -> region. VERIFY against lk_cities.csv; anything unseen here
# lands in region_map.csv as "REVIEW" for you to fill in.
CITY_TO_REGION = {
    # Pakistan
    "Karachi": "Pakistan", "Islamabad": "Pakistan", "Hyderabad": "Pakistan",
    "Gilgit": "Pakistan", "Chitral": "Pakistan", "Lahore": "Pakistan",
    "Sindh": "Pakistan", "Gilgit-Baltistan": "Pakistan",
    # Kenya
    "Nairobi": "Kenya", "Mombasa": "Kenya", "Kisumu": "Kenya",
    # Tanzania
    "Dar es Salaam": "Tanzania", "Dar-es-Salaam": "Tanzania",
    "Mwanza": "Tanzania", "Arusha": "Tanzania",
    # Uganda
    "Kampala": "Uganda",
    # Rest
    "Kabul": "Afghanistan", "Bamyan": "Afghanistan",
    "London": "United Kingdom", "Dubai": "UAE", "Lisbon": "Portugal",
    "Global": "Global",
}


def unesc(s):
    return html.unescape(html.unescape(s or "")).strip()


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", unesc(s).lower()).strip("-")


def w(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        cw = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        cw.writeheader()
        cw.writerows(rows)
    print(f"  {len(rows):>5}  {os.path.basename(path)}")


def main(indir, outdir):
    os.makedirs(outdir, exist_ok=True)
    files = sorted(glob.glob(os.path.join(indir, "*.json")))
    if not files:
        sys.exit(f"no .json in {indir}")

    # id -> {title -> count}, so a renamed lookup shows up as two titles on one id
    cities = defaultdict(Counter)
    ents_primary = defaultdict(Counter)
    ents_addl = defaultdict(Counter)
    tags = defaultdict(lambda: {"labels": Counter(), "guids": Counter()})
    approvers = Counter()
    approver_by_entity = defaultdict(Counter)
    city_by_entity = defaultdict(Counter)
    n = 0

    for path in files:
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            print(f"!! unreadable {os.path.basename(path)}: {e}", file=sys.stderr)
            continue
        n += 1

        c = d.get("City") or {}
        ct = unesc(c.get("Title"))
        if ct:
            cities[c.get("Id")][ct] += 1

        e = d.get("Entity") or {}
        et = unesc(e.get("Title"))
        if et:
            ents_primary[e.get("Id")][et] += 1
            if ct:
                city_by_entity[et][ct] += 1

        for a in d.get("AdditionalEntity") or []:
            at = unesc(a.get("Title"))
            if at:
                ents_addl[a.get("Id")][at] += 1

        for t in d.get("Tags") or []:
            lab = unesc(t.get("Label"))
            if lab:
                s = slugify(lab)
                tags[s]["labels"][lab] += 1
                if t.get("TermGuid"):
                    tags[s]["guids"][t["TermGuid"]] += 1

        g = d.get("LocalApproverGroup")
        if g:
            approvers[g] += 1
            if et:
                approver_by_entity[g][et] += 1

    print(f"parsed {n} files\n")

    # ---- cities
    rows = []
    for cid, titles in sorted(cities.items(), key=lambda x: str(x[0])):
        main_t = titles.most_common(1)[0][0]
        rows.append({
            "city_id": cid,
            "city": main_t,
            "usage_count": sum(titles.values()),
            "suggested_region": CITY_TO_REGION.get(main_t, "REVIEW"),
            "title_variants": " | ".join(f"{k}({v})" for k, v in titles.most_common()) if len(titles) > 1 else "",
        })
    w(os.path.join(outdir, "lk_cities.csv"),
      ["city_id", "city", "usage_count", "suggested_region", "title_variants"], rows)

    # editable map to feed back into sp_news_to_csv.py
    w(os.path.join(outdir, "region_map.csv"), ["city", "region"],
      [{"city": r["city"], "region": r["suggested_region"]} for r in rows])

    # ---- entities
    all_ids = set(ents_primary) | set(ents_addl)
    erows = []
    for eid in sorted(all_ids, key=lambda x: str(x)):
        titles = ents_primary[eid] + ents_addl[eid]
        main_t = titles.most_common(1)[0][0]
        erows.append({
            "entity_id": eid,
            "entity": main_t,
            "used_as_primary": sum(ents_primary[eid].values()),
            "used_as_additional": sum(ents_addl[eid].values()),
            "top_cities": " | ".join(f"{k}({v})" for k, v in city_by_entity[main_t].most_common(3)),
            "title_variants": " | ".join(f"{k}({v})" for k, v in titles.most_common()) if len(titles) > 1 else "",
        })
    erows.sort(key=lambda r: -(r["used_as_primary"] + r["used_as_additional"]))
    w(os.path.join(outdir, "lk_entities.csv"),
      ["entity_id", "entity", "used_as_primary", "used_as_additional",
       "top_cities", "title_variants"], erows)

    # ---- tags
    w(os.path.join(outdir, "lk_tags.csv"),
      ["tag_slug", "tag_label", "usage_count", "guid_count", "term_guids", "label_variants"],
      [{"tag_slug": s,
        "tag_label": v["labels"].most_common(1)[0][0],
        "usage_count": sum(v["labels"].values()),
        "guid_count": len(v["guids"]),
        "term_guids": " | ".join(g for g, _ in v["guids"].most_common()),
        "label_variants": " | ".join(f"{k}({c})" for k, c in v["labels"].most_common())
                          if len(v["labels"]) > 1 else ""}
       for s, v in sorted(tags.items(), key=lambda x: -sum(x[1]["labels"].values()))])

    # ---- approver groups (department proxy)
    w(os.path.join(outdir, "lk_approvers.csv"),
      ["approver_group", "usage_count", "entities"],
      [{"approver_group": g, "usage_count": c,
        "entities": " | ".join(f"{k}({v})" for k, v in approver_by_entity[g].most_common(5))}
       for g, c in approvers.most_common()])

    # ---- drift report
    with open(os.path.join(outdir, "_drift.txt"), "w", encoding="utf-8") as f:
        def block(title, items):
            f.write(f"\n{title}\n" + ("-" * len(title)) + "\n")
            f.write("  none\n" if not items else "")
            for line in items:
                f.write(f"  {line}\n")

        block("SAME Id, DIFFERENT Title (lookup renamed over time)",
              [f"City Id {i}: {dict(t)}" for i, t in cities.items() if len(t) > 1]
              + [f"Entity Id {i}: {dict(ents_primary[i] + ents_addl[i])}"
                 for i in all_ids if len(ents_primary[i] + ents_addl[i]) > 1])

        by_title = defaultdict(set)
        for i, t in cities.items():
            for k in t:
                by_title[("city", k)].add(i)
        for i in all_ids:
            for k in (ents_primary[i] + ents_addl[i]):
                by_title[("entity", k)].add(i)
        block("SAME Title, DIFFERENT Id (duplicate lookup rows)",
              [f"{kind} '{name}' -> Ids {sorted(ids, key=str)}"
               for (kind, name), ids in by_title.items() if len(ids) > 1])

        block("TAG LABELS WITH MULTIPLE TermGuids (dedupe by label, not guid)",
              [f"{s}: {len(v['guids'])} guids {list(v['guids'])}"
               for s, v in tags.items() if len(v["guids"]) > 1])

        block("CITIES NEEDING A REGION DECISION",
              [f"Id {r['city_id']} '{r['city']}' ({r['usage_count']} items)"
               for r in rows if r["suggested_region"] == "REVIEW"])

    print(f"\ndrift report -> {os.path.join(outdir, '_drift.txt')}")
    print(f"EDIT {os.path.join(outdir, 'region_map.csv')} then re-run the converter")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
