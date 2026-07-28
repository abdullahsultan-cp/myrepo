#!/usr/bin/env python3
"""
build_structure.py — the upload tree, from real fields only.

Answers one question: for each news item, WHERE does it go in the backend?

    Entity == "Global"   ->  global/news/<slug>
    otherwise            ->  Regions/<region>/Entities/<entity>/
                             Departments/<dept>/News/<slug>

Nothing here is inferred from body text. Every column is either a SharePoint
lookup value or a one-step derivation of one, so the output is auditable:

    region        <- resolved in priority order, recorded in region_source:
                       1. entity-suffix  a region baked into the entity name,
                          when it names exactly one country ("Medical College,
                          Pakistan" -> Pakistan) — outranks the city, because
                          the tree records who OWNS the item, not where the
                          event happened
                       2. city           City mapped to its country
                          (Nairobi -> Kenya)
                       3. city-global    City "Global" -> region "Global"
                       4. entity-global  no owning entity -> region "Global"
                       5. entity-majority  the entity's own news is >=60% in
                          one region, so its unlocated news goes there too.
                          A GUESS, and flagged as one.
                       6. fallback-global  no country determinable at all
                          (Portugal, Mozambique, West Africa, Asia...) ->
                          "Global", which beats forcing a wrong country
    entity        <- Entity, with the ", Pakistan" / ", East Africa" suffix
                     stripped off so one entity is one node across regions
    entity_region <- that stripped suffix, kept so you can spot mis-filing
    surface_global<- the GlobalNews editorial flag (independent of entity)
    references    <- AdditionalEntity: show-here-too, view-only

department / sub_department / news_type are emitted EMPTY on purpose. There is
no source field for them in the export (LocalApproverGroup is an entity proxy,
not a department one), so they stay blank until the real vocabulary is supplied
rather than being guessed and then trusted.

Usage:
    python build_structure.py <input_dir_with_json> <output_dir> [n|all] [seed]

    n     how many files to sample (default all; e.g. 200 for a spot check)
    seed  RNG seed for a reproducible sample (default 42)

Outputs:
    news_structure.csv      one row per item: the slim column set + upload_path
    _tree.txt               Region > Entity tree with item counts
    _tree_region_entity.csv the same tree as data
    _entities.csv           every entity: which regions and cities it appears in
    _flags.csv              rows needing a human decision before migrating
"""

import csv
import glob
import html
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

# ------------------------------------------------------------------ vocab

# City -> COUNTRY. All 14 cities present in the 3606-item dump are listed.
# "Other" is deliberately UNMAPPED rather than guessed — see _flags.csv.
CITY_TO_REGION = {
    "Karachi": "Pakistan",
    "Islamabad": "Pakistan",
    "Lahore": "Pakistan",
    "Nairobi": "Kenya",
    "Mombasa": "Kenya",
    "Limuru": "Kenya",
    "Dar es Salaam": "Tanzania",
    "Arusha": "Tanzania",
    "Dodoma": "Tanzania",
    "Kampala": "Uganda",
    "Kabul": "Afghanistan",
    "London": "United Kingdom",
    # Handled by rule 3 / rule 4 below rather than mapped to a country:
    "Global": "",         # 204 items -> region "Global"
    "Other": "",          # 56 items  -> unresolvable here, needs hand-coding
}

# Suffixes that encode a region inside the entity name. Longest first.
ENTITY_REGION_SUFFIXES = (", East Africa", ", Pakistan")

# Which countries an entity-name suffix legitimately covers. A suffix naming
# exactly ONE country resolves the region on its own (rule 1 below); a suffix
# naming several only serves as a cross-check against the city.
SUFFIX_COVERS = {
    "Pakistan": {"Pakistan"},
    "East Africa": {"Kenya", "Tanzania", "Uganda"},
}

# City values that name no country. "Global" is a real region node of its own;
# "Other" means "somewhere not in the City list" and cannot be resolved here.
CITY_IS_GLOBAL = "Global"
CITY_IS_OTHER = "Other"

# Rule 6 threshold: how one-sided an entity's located news must be before its
# usual region is applied to its unlocated news. 0.60 keeps Institute for
# Educational Development (63% Pakistan) in and leaves School of Nursing and
# Midwifery (54% Pakistan, but real presence in four countries) out.
ENTITY_MAJORITY = 0.60

# Entity values that are not really an owning entity.
NO_OWNER = {"Global"}

UNMAPPED = "UNMAPPED"

# ------------------------------------------------------------------ helpers

TAG_RE = re.compile(r"<[^>]+>")


def unesc(s):
    return html.unescape(html.unescape(s or "")).strip()


def lk(v, f="Title"):
    """A SharePoint lookup with Id -1 or null is an empty value, not a real one."""
    if not isinstance(v, dict) or v.get("Id") in (-1, None):
        return ""
    return unesc(v.get(f))


def slugify(s, maxlen=80):
    s = re.sub(r"[^a-z0-9]+", "-", unesc(s).lower()).strip("-")
    return s[:maxlen].rstrip("-")


def split_entity(e):
    """'Medical College, East Africa' -> ('Medical College', 'East Africa')"""
    for suf in ENTITY_REGION_SUFFIXES:
        if e.endswith(suf):
            return e[:-len(suf)], suf[2:]
    return e, ""


def w(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        cw = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        cw.writeheader()
        cw.writerows(rows)
    print(f"  {len(rows):>5}  {os.path.basename(path)}")


# ------------------------------------------------------------------ main

def main(indir, outdir, sample=0, seed=42):
    os.makedirs(outdir, exist_ok=True)
    files = sorted(glob.glob(os.path.join(indir, "*.json")))
    if not files:
        sys.exit(f"no .json in {indir}")

    population = len(files)
    if sample and sample < population:
        files = sorted(random.Random(seed).sample(files, sample))
        print(f"sampling {len(files)} of {population} files (seed={seed})\n")
    else:
        print(f"scoring all {population} files\n")

    rows, flags = [], []
    tree = defaultdict(Counter)                       # region -> entity -> n
    ent_regions = defaultdict(Counter)                # entity -> region -> n
    ent_cities = defaultdict(Counter)                 # entity -> city  -> n
    ent_suffix = defaultdict(Counter)                 # entity -> suffix -> n

    for path in files:
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            print(f"!! {os.path.basename(path)}: {e}", file=sys.stderr)
            continue

        note = []
        title = unesc(d.get("Title"))
        city = lk(d.get("City"))

        # ---------- ENTITY, region suffix lifted out of the name
        raw_entity = lk(d.get("Entity"))
        entity, entity_region = split_entity(raw_entity)
        if not entity:
            note.append("no entity on the item")
            entity = UNMAPPED

        # ---------- REGION, in priority order
        # The tree records who OWNS the news, not where the event happened, so a
        # region baked into the entity name outranks the city. "Medical College,
        # Pakistan" is Pakistan's even when the workshop was held in Arusha.
        city_region = CITY_TO_REGION.get(city, "")
        suffix_countries = SUFFIX_COVERS.get(entity_region, set())

        if len(suffix_countries) == 1:                      # 1. entity name
            region = next(iter(suffix_countries))
            region_source = "entity-suffix"
            if city_region and city_region != region:
                note.append(f"entity says '{entity_region}' but city "
                            f"'{city}' is {city_region}")
        elif city_region:                                   # 2. city -> country
            region, region_source = city_region, "city"
            if suffix_countries and city_region not in suffix_countries:
                note.append(f"entity says '{entity_region}' but city "
                            f"'{city}' is {city_region}")
        elif city == CITY_IS_GLOBAL:                        # 3. Global region
            region, region_source = "Global", "city-global"
            if entity_region:
                note.append(f"region Global, but entity name says "
                            f"'{entity_region}'")
        else:                                               # 4. unresolvable
            region, region_source = UNMAPPED, "none"
            if city == CITY_IS_OTHER:
                note.append("city 'Other' — region needs hand-coding")
            else:
                note.append(f"city '{city or '(blank)'}' has no country mapping")

        # ---------- the two independent global signals
        is_global_entity = raw_entity in NO_OWNER
        surface_global = bool(d.get("GlobalNews"))

        # ---------- view-only cross-references
        refs = []
        for a in d.get("AdditionalEntity") or []:
            t = lk(a)
            if t and t != raw_entity:
                base, _ = split_entity(t)
                if base not in refs:
                    refs.append(base)

        if is_global_entity and not surface_global:
            note.append("no owning entity AND not flagged global news")

        rows.append({
            "_note": note,
            "_slug": slugify(title) or f"news-{d.get('Id')}",
            "news_id": d.get("Id") or d.get("ID"),
            "published_date": (d.get("ScheduleStartDate")
                               or d.get("Created") or "")[:10],
            "title": title,
            "region": region,
            "region_source": region_source,
            "entity": entity,
            "department": "",          # no source field — see module docstring
            "sub_department": "",      # no source field
            "news_type": "",           # no source field agreed yet
            "city": city,
            "entity_region": entity_region,
            "is_global_entity": str(is_global_entity),
            "surface_global": str(surface_global),
            "references": " | ".join(refs),
            "status": d.get("IsPulished") or "",
            "upload_path": "",
            "flags": "",
        })

    if not rows:
        sys.exit("no rows parsed — nothing to write")

    # ------------------------------------------------------------------
    # SECOND PASS — rules 1-4 leave some rows UNMAPPED (City "Other"). Those
    # can only be settled by looking at the entity across the whole corpus,
    # which needs pass 1 finished first.
    # ------------------------------------------------------------------
    coded = defaultdict(Counter)                    # entity -> region -> n
    for r in rows:
        if r["region"] != UNMAPPED:
            coded[r["entity"]][r["region"]] += 1

    for r in rows:
        if r["region"] != UNMAPPED:
            continue
        ent = r["entity"]
        if r["is_global_entity"] == "True":         # 5. no owner -> Global
            r["region"], r["region_source"] = "Global", "entity-global"
            continue
        dist = coded.get(ent, Counter())
        if dist:
            top, n = dist.most_common(1)[0]
            share = n / sum(dist.values())
            if share >= ENTITY_MAJORITY:            # 6. entity's usual region
                r["region"], r["region_source"] = top, "entity-majority"
                r["_note"].append(
                    f"region inferred: {ent} is {top} in {share:.0%} of its "
                    f"{sum(dist.values())} located items")
                continue
        # 7. genuinely not tied to one country (Portugal, West Africa, Asia...)
        r["region"], r["region_source"] = "Global", "fallback-global"
        r["_note"].append(
            f"no country determinable — {ent} splits across "
            + (" | ".join(f"{k}({v})" for k, v in dist.most_common(4)) or "nothing")
            + "; filed under Global")

    # ---------- paths and rollups, now that every region is final
    for r in rows:
        if r["is_global_entity"] == "True":
            r["upload_path"] = f"global/news/{r['_slug']}"
        else:
            reg = r["region"] if r["region"] != UNMAPPED else "<region>"
            r["upload_path"] = (f"Regions/{reg}/Entities/{r['entity']}/"
                                f"Departments/<department>/News/{r['_slug']}")
        r["flags"] = "; ".join(r["_note"])
        if r["_note"]:
            flags.append(r)
        tree[r["region"]][r["entity"]] += 1
        ent_regions[r["entity"]][r["region"]] += 1
        if r["city"]:
            ent_cities[r["entity"]][r["city"]] += 1
        ent_suffix[r["entity"]][r["entity_region"] or "(none)"] += 1

    for r in rows:                                  # drop the scratch keys
        del r["_note"], r["_slug"]

    rows.sort(key=lambda r: (r["region"], r["entity"], r["published_date"]))
    w(os.path.join(outdir, "news_structure.csv"), list(rows[0].keys()), rows)

    # ---------- the tree, as data
    w(os.path.join(outdir, "_tree_region_entity.csv"),
      ["region", "entity", "item_count"],
      [{"region": r, "entity": e, "item_count": c}
       for r, ents in sorted(tree.items(), key=lambda x: -sum(x[1].values()))
       for e, c in ents.most_common()])

    # ---------- one row per entity: where does it live?
    w(os.path.join(outdir, "_entities.csv"),
      ["entity", "item_count", "region_count", "regions",
       "name_suffixes", "top_cities"],
      [{"entity": e,
        "item_count": sum(regs.values()),
        "region_count": len(regs),
        "regions": " | ".join(f"{k}({v})" for k, v in regs.most_common()),
        "name_suffixes": " | ".join(f"{k}({v})"
                                    for k, v in ent_suffix[e].most_common()),
        "top_cities": " | ".join(f"{k}({v})"
                                 for k, v in ent_cities[e].most_common(4))}
       for e, regs in sorted(ent_regions.items(),
                             key=lambda x: -sum(x[1].values()))])

    w(os.path.join(outdir, "_flags.csv"), list(rows[0].keys()), flags)

    # ---------- readable tree
    n = len(rows)
    n_global = sum(r["is_global_entity"] == "True" for r in rows)
    n_surface = sum(r["surface_global"] == "True" for r in rows)
    n_refs = sum(bool(r["references"]) for r in rows)

    with open(os.path.join(outdir, "_tree.txt"), "w", encoding="utf-8") as f:
        f.write(f"items: {n}   (of {population} files)\n")
        f.write(f"regions: {len(tree)}   entities: {len(ent_regions)}\n\n")
        f.write(f"{'-'*60}\nROUTING\n{'-'*60}\n")
        f.write(f"  {n_global:>5}  ->  global/news/          "
                f"(Entity = Global, no owner)\n")
        f.write(f"  {n - n_global:>5}  ->  Regions/.../News/     "
                f"(has an owning entity)\n")
        f.write(f"  {n_surface:>5}      also surface on the global site "
                f"(GlobalNews flag)\n")
        f.write(f"  {n_refs:>5}      carry view-only cross-references\n")

        # The two global signals are independent, so all four combinations
        # occur. The awkward cell is no-owner + not-global-news.
        f.write(f"\n  Entity=Global x GlobalNews (they disagree on "
                f"{sum(1 for r in rows if (r['is_global_entity'] == 'True') != (r['surface_global'] == 'True'))}"
                f" items)\n")
        combo = Counter((r["is_global_entity"], r["surface_global"]) for r in rows)
        for (ge, sg), c in sorted(combo.items()):
            f.write(f"  {c:>5}      Entity=Global:{ge:<5}  GlobalNews:{sg}\n")

        f.write(f"\n{'-'*60}\nREGION > ENTITY\n{'-'*60}\n")
        for r, ents in sorted(tree.items(), key=lambda x: -sum(x[1].values())):
            f.write(f"\n{r}  [{sum(ents.values())} items, "
                    f"{len(ents)} entities]\n")
            for e, c in ents.most_common():
                f.write(f"    {c:>5}  {e}\n")

        multi = [(e, regs) for e, regs in ent_regions.items() if len(regs) > 1]
        f.write(f"\n{'-'*60}\nENTITIES SPANNING >1 REGION ({len(multi)})\n"
                f"{'-'*60}\n")
        for e, regs in sorted(multi, key=lambda x: -sum(x[1].values())):
            f.write(f"  {sum(regs.values()):>5}  {e}\n")
            for k, v in regs.most_common():
                f.write(f"           {v:>5}  {k}\n")

        f.write(f"\n{'-'*60}\nNEEDS A DECISION ({len(flags)})\n{'-'*60}\n")
        for k, c in Counter(r["flags"] for r in flags).most_common():
            f.write(f"  {c:>5}  {k}\n")

    print(f"\ntree -> {os.path.join(outdir, '_tree.txt')}")


if __name__ == "__main__":
    if not 3 <= len(sys.argv) <= 5:
        sys.exit(__doc__)
    arg_n = sys.argv[3] if len(sys.argv) > 3 else 0
    n_sample = 0 if str(arg_n).lower() == "all" else int(arg_n)
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 42
    main(sys.argv[1], sys.argv[2], n_sample, seed)
