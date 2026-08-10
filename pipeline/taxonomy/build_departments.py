#!/usr/bin/env python3
"""
build_departments.py — a DERIVED department level, since the export has none.

The 3606-item export has 41 fields and not one of them is a department (verified
by full field inventory). The only usable signal is Tags, populated on every
item. This maps tag labels onto the department vocabulary already defined in
resolve_taxonomy.py, so the vocabulary is yours, not invented here.

Two things make that mapping noisy, and both are handled explicitly:

  1. Many tags are ENTITY names, not departments. "School of Nursing and
     Midwifery" (317 uses) would otherwise match the "nursing" alias and
     re-derive the entity as its own child, producing
     Kenya > SONAM > Nursing when the tag said nothing new. Those tags are
     blocked, so a department only survives if a real department tag fed it.

  2. Tags are a flat, uncontrolled cloud — entity names, country names, diseases
     and generic words ("Research", "aku", "faculty") share one namespace, with
     case-variant duplicates. There is no second level in it, so sub_department
     stays empty: it cannot be derived, only authored.

Everything emitted here is a GUESS. department_source records which tag fired so
you can audit or reject any row.

Usage:
    python build_departments.py <input_dir_with_json> <output_dir>

Outputs:
    taxonomy_derived.csv    region > entity > department > sub_department + counts
    _departments.csv        the candidate department vocabulary + feeding tags
    _items_departments.csv  per item, so you can spot-check any assignment
    _no_department.csv      entities whose items yielded no department at all
"""

import csv
import glob
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from resolve_taxonomy import DEPARTMENTS  # their vocabulary, reused

# Canonical entries in that vocabulary that are actually ENTITIES, so they must
# never become a department. "Office of the President" is an entity with its own
# folder; left in, the "President's Office" tag (39 uses) produced fictional
# nodes such as Pakistan/Office of the President/Departments/Office of the
# President/News.
NOT_A_DEPARTMENT = {"Office of the President"}

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
ENTITY_MAJORITY = 0.60
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


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


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

    # ---- pass 1: read everything, and learn the entity namespace
    raw = []
    entity_names = set()
    for path in files:
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            print(f"!! {os.path.basename(path)}: {e}", file=sys.stderr)
            continue
        ent_raw = lk(d.get("Entity"))
        base, suf = split_entity(ent_raw)
        names = [ent_raw, base]
        for a in d.get("AdditionalEntity") or []:
            t = lk(a)
            if t:
                b, _ = split_entity(t)
                names += [t, b]
        entity_names.update(norm(x) for x in names if x)
        raw.append((d, ent_raw, base, suf))

    # ---- which tag labels are a department, and which are just entity names?
    tag_to_dept, blocked = {}, {}
    all_tags = Counter()
    for d, *_ in raw:
        for t in (d.get("Tags") or []):
            lab = unesc(t.get("Label"))
            if lab:
                all_tags[lab] += 1

    for lab in all_tags:
        low = norm(lab)
        hit = ""
        for canon, aliases in DEPARTMENTS.items():
            if canon in NOT_A_DEPARTMENT:
                continue
            for a in aliases:
                if a in lab.lower():
                    if not hit or len(a) > len(hit[1]):
                        hit = (canon, a)
        if not hit:
            continue
        if low in entity_names:
            blocked[lab] = hit[0]          # the tag IS an entity — not a dept
        else:
            tag_to_dept[lab] = hit[0]

    # ---- pass 2: region, then department per item
    items = []
    for d, ent_raw, base, suf in raw:
        city = lk(d.get("City"))
        city_region = CITY_TO_REGION.get(city, "")
        sc = SUFFIX_COVERS.get(suf, set())
        if len(sc) == 1:
            region = next(iter(sc))
        elif city_region:
            region = city_region
        elif city == "Global":
            region = "Global"
        else:
            region = ""

        labs = [unesc(t.get("Label")) for t in (d.get("Tags") or [])
                if t.get("Label")]
        found = [(tag_to_dept[l], l) for l in labs if l in tag_to_dept]
        # most specific wins when an item carries several department tags
        found.sort(key=lambda x: -len(x[1]))
        dept, src = (found[0][0], f"tag:{found[0][1]}") if found else ("", "")

        items.append({
            "news_id": d.get("Id"), "title": unesc(d.get("Title")),
            "region": region, "entity": base,
            "is_global_entity": ent_raw in NO_OWNER,
            "department": dept, "department_source": src,
            "sub_department": "",
            "other_department_tags": " | ".join(
                sorted({c for c, _ in found[1:]})),
            "all_tags": " | ".join(labs),
        })

    # ---- fill regions left blank, same rules as build_structure.py
    coded = defaultdict(Counter)
    for it in items:
        if it["region"]:
            coded[it["entity"]][it["region"]] += 1
    for it in items:
        if it["region"]:
            continue
        if it["is_global_entity"]:
            it["region"] = "Global"
            continue
        dist = coded.get(it["entity"], Counter())
        top = dist.most_common(1)
        it["region"] = (top[0][0] if top and top[0][1] / sum(dist.values())
                        >= ENTITY_MAJORITY else "Global")

    # ---- roll up the tree (entity "Global" is not a node under Regions/)
    owned = [it for it in items if not it["is_global_entity"]]
    node = Counter()
    for it in owned:
        node[(it["region"], it["entity"], it["department"])] += 1

    w(os.path.join(outdir, "taxonomy_derived.csv"),
      ["region", "entity", "department", "sub_department", "news_count",
       "department_status"],
      [{"region": r, "entity": e, "department": dp or "(none derived)",
        "sub_department": "", "news_count": c,
        "department_status": "derived from tags" if dp else "no tag matched"}
       for (r, e, dp), c in sorted(node.items(),
                                   key=lambda x: (x[0][0], x[0][1], -x[1]))])

    dept_counts = Counter(it["department"] for it in owned if it["department"])
    feeding = defaultdict(list)
    for lab, canon in tag_to_dept.items():
        feeding[canon].append((all_tags[lab], lab))
    w(os.path.join(outdir, "_departments.csv"),
      ["department", "news_count", "feeding_tags"],
      [{"department": dp, "news_count": c,
        "feeding_tags": " | ".join(f"{l}({n})" for n, l
                                   in sorted(feeding[dp], reverse=True))}
       for dp, c in dept_counts.most_common()])

    w(os.path.join(outdir, "_items_departments.csv"),
      ["news_id", "region", "entity", "department", "department_source",
       "sub_department", "other_department_tags", "title", "all_tags"], items)

    none_by_entity = Counter((it["region"], it["entity"])
                             for it in owned if not it["department"])
    w(os.path.join(outdir, "_no_department.csv"),
      ["region", "entity", "items_without_department"],
      [{"region": r, "entity": e, "items_without_department": c}
       for (r, e), c in none_by_entity.most_common()])

    n_owned = len(owned)
    got = sum(1 for it in owned if it["department"])
    print(f"\n{'-'*58}")
    print(f"  entity-owned items       : {n_owned}")
    print(f"  got a derived department : {got}  ({100*got//max(n_owned,1)}%)")
    print(f"  no department            : {n_owned-got}")
    print(f"  distinct departments     : {len(dept_counts)}")
    print(f"  tags used as departments : {len(tag_to_dept)}")
    print(f"  tags BLOCKED (entity, not dept): {len(blocked)}")
    for lab, canon in sorted(blocked.items(), key=lambda x: -all_tags[x[0]]):
        print(f"      {all_tags[lab]:>4}  {lab}  (would have become {canon})")
    print("  sub_department           : 0  (no second level exists in Tags)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
