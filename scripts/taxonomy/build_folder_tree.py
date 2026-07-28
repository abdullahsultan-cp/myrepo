#!/usr/bin/env python3
"""
build_folder_tree.py — the definitive Storyblok folder list.

Consolidates the four earlier passes into one answer: which folders to create,
and which folder each of the 3606 news items goes into.

Inputs (produced by the other scripts, so each rule stays auditable; locations
come from paths.py):
    data/taxonomy/intermediate/news_structure.csv      region + region_source
    data/taxonomy/intermediate/recovered_entities.csv  entity for no-owner items
    data/taxonomy/intermediate/_items_departments.csv  department from tags
    data/taxonomy/intermediate/entity_abbrev.csv       short form per entity
    data/taxonomy/intermediate/connections.csv         cross-entity references
    config/region_overrides.csv                        hand corrections

Rules, as decided:
    1. region resolves to Global      -> global/news/                (flat)
    2. country + entity + department  -> Regions/R/Entities/E/Departments/D/News/
    3. country + entity, no dept      -> Regions/R/Entities/E/News/
    4. country, no entity             -> Regions/R/News/             (flat)

Entity recovery uses only the two trustworthy rules — an explicit
AdditionalEntity lookup, or a tag whose whole label is an entity name. Recovery
never changes the region: Karachi stays Pakistan.

Departments exist only under an entity. Region-level news is flat, so the
parent -> child -> child rule is never broken.

Usage:
    python build_folder_tree.py <output_dir>

Outputs:
    folder_structure.csv   every folder to create: level, path, counts
    folder_tree.txt        the same as an indented tree
    news_routing.csv       3606 rows: news_id -> final folder path
"""

import csv
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths

SRC_STRUCT = paths.NEWS_STRUCTURE
SRC_RECOVER = paths.RECOVERED_ENTITIES
SRC_DEPT = paths.ITEMS_DEPARTMENTS
SRC_ABBREV = paths.ENTITY_ABBREV
SRC_REFS = paths.CONNECTIONS
# Hand corrections, applied last. Only ever used to fix a region that was
# INFERRED (region_source = entity-majority); a region taken from the City field
# is real source data and is never overridden here.
SRC_OVERRIDE = paths.REGION_OVERRIDES

# Recovery rules used to give a no-owner item an entity. The two "-of-many" /
# "-ambiguous" rules name several candidates; the FIRST becomes the owning
# entity and the rest stay in the share list, so nothing is lost. Prose rules are
# excluded — roughly half are wrong (see MIGRATION_DECISIONS.md §4.2).
USED_RECOVERY = {
    "additional-entity",
    "tag-exact",
    "additional-entity-first-of-many",
    "tag-exact-ambiguous",
}
GLOBAL_REGION = "Global"

# Values that sit in the SharePoint Entity column but are not entities. Their
# news goes to global/news, and a reference to one is a share to global/news.
NOT_ENTITIES = {
    "Global",
    "News training",
    "Student Affairs and Services",
    "Office of the Provost",
    "Office of the President",
    "Office of the Registrar",
    "Data Office",
    "Research",
    "Library",
}

GLOBAL_NEWS = "global/news"


def read(path):
    if not os.path.exists(path):
        sys.exit(f"missing input: {path}")
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def slug_path(path):
    """Slugify each folder name in a path, keeping the separators.

    Entity folders use the FULL entity name, not the abbreviation, so
    'Regions/Pakistan/Entities/Medical College/News' becomes
    'regions/pakistan/entities/medical-college/news'.
    """
    return "/".join(slugify(part) for part in path.split("/"))


def w(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        cw = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        cw.writeheader()
        cw.writerows(rows)
    print(f"  {len(rows):>5}  {os.path.basename(path)}")


def main(outdir):
    os.makedirs(outdir, exist_ok=True)

    struct = read(SRC_STRUCT)
    dept_of = {r["news_id"]: (r.get("department") or "") for r in read(SRC_DEPT)}
    short_of = {r["entity_long"]: (r.get("entity_short") or "")
                for r in read(SRC_ABBREV)}
    recovered = {r["news_id"]: r["recovered_entity"]
                 for r in read(SRC_RECOVER)
                 if r["recovery_rule"] in USED_RECOVERY
                 and r["recovered_entity"] not in NOT_ENTITIES}
    # every share target named per item, from the cross-reference pass
    refs_of = defaultdict(list)
    for r in read(SRC_REFS):
        refs_of[r["news_id"]].append((r["ref_entity"], r["ref_region"]))

    override = {}
    if os.path.exists(SRC_OVERRIDE):
        override = {r["news_id"]: r["region"] for r in read(SRC_OVERRIDE)}
        print(f"  region overrides loaded: {len(override)}")

    # Countries that actually resolved, so a share target carrying a stale or
    # unresolved region (the cross-reference pass predates the final region
    # rules) falls back to global/news instead of emitting Regions/UNMAPPED/.
    COUNTRIES = {r["region"] for r in struct} - {GLOBAL_REGION, "UNMAPPED"}

    routing = []
    # counts keyed by the folder that directly holds the news
    news_folder = Counter()
    # region/entity nodes that exist only because something is shared into them
    share_targets = set()
    # structural sets
    region_entities = defaultdict(set)
    entity_depts = defaultdict(set)
    regions = set()
    entity_source = Counter()
    share_count = Counter()
    max_shares = [0]

    # Storyblok requires a unique slug within a folder. Two stories with the
    # same title in the same folder collide, so the SharePoint id is appended to
    # the later one — the same tie-break the existing pipeline uses.
    used_slugs = set()
    slug_collisions = []

    def reserve(folder, title, nid):
        base = slugify(title) or f"news-{nid}"
        key = f"{folder}/{base}"
        if key not in used_slugs:
            used_slugs.add(key)
            return base
        candidate = f"{base}-{nid}"
        n = 2
        while f"{folder}/{candidate}" in used_slugs:
            candidate = f"{base}-{nid}-{n}"
            n += 1
        used_slugs.add(f"{folder}/{candidate}")
        slug_collisions.append({"news_id": nid, "folder": folder,
                                "wanted": base, "assigned": candidate,
                                "title": title})
        return candidate

    n_overridden = 0
    for r in struct:
        nid = r["news_id"]
        region = r["region"]
        entity = r["entity"]
        src = "original"
        region_src = r["region_source"]

        if nid in override and override[nid] != region:
            region, region_src = override[nid], "hand-corrected"
            n_overridden += 1

        if r["is_global_entity"] == "True":
            rec = recovered.get(nid)
            if rec:
                entity, src = rec, "recovered"
            else:
                entity, src = "", "none"
        elif entity in NOT_ENTITIES:
            entity, src = "", "not-an-entity"
        entity_source[src] += 1

        dept = dept_of.get(nid, "")

        # rule 0: the Entity value was not an entity at all -> global/news
        if src == "not-an-entity":
            folder, level, dept = GLOBAL_NEWS, "global", ""
        elif region == GLOBAL_REGION:                     # rule 1
            folder = GLOBAL_NEWS
            level = "global"
            entity, dept = "", ""
        elif entity and dept:                             # rule 2
            folder = (f"Regions/{region}/Entities/{entity}/"
                      f"Departments/{dept}/News")
            level = "entity-department"
        elif entity:                                      # rule 3
            folder = f"Regions/{region}/Entities/{entity}/News"
            level = "entity"
        else:                                             # rule 4
            folder = f"Regions/{region}/News"
            level = "region"
            dept = ""

        regions.add(region)
        if entity and level != "global":
            region_entities[region].add(entity)
            if dept:
                entity_depts[(region, entity)].add(dept)

        # ---- share targets: where else this story is displayed, view only.
        # A reference that became the owner is dropped — a story is not shared
        # with itself.
        shares = []
        for ref_ent, ref_reg in refs_of.get(nid, ()):
            if ref_ent == entity:
                continue
            if ref_ent in NOT_ENTITIES or ref_reg not in COUNTRIES:
                p = GLOBAL_NEWS
            else:
                p = f"Regions/{ref_reg}/Entities/{ref_ent}/News"
                share_targets.add((ref_reg, ref_ent))
            sp = slug_path(p)
            if p != folder and sp not in shares:
                shares.append(sp)
        share_count[len(shares)] += 1
        max_shares[0] = max(max_shares[0], len(shares))

        news_folder[folder] += 1
        routing.append({
            "_shares": shares,
            "news_id": nid,
            "published_date": r["published_date"],
            "title": r["title"],
            "region": region,
            "entity": entity,
            "entity_short": short_of.get(entity, ""),
            "department": dept,
            "level": level,
            "entity_source": src,
            "region_source": region_src,
            "surface_global": r["surface_global"],
            "folder_path": folder,
            "sb_path": f"{slug_path(folder)}/{reserve(folder, r['title'], nid)}",
        })

    # A folder something is shared into must exist even if it owns no news.
    for reg, ent in share_targets:
        region_entities[reg].add(ent)

    # flatten shares into shared_path_1..N, widest item decides the column count
    n_share_cols = max(max_shares[0], 1)
    for row in routing:
        for i in range(n_share_cols):
            row[f"shared_path_{i + 1}"] = (row["_shares"][i]
                                           if i < len(row["_shares"]) else "")
        del row["_shares"]

    w(os.path.join(outdir, "news_routing.csv"), list(routing[0].keys()), routing)

    # the sheet asked for: story id, name, SB path, shared paths
    w(os.path.join(outdir, "story_paths.csv"),
      ["story_id", "name", "sb_path"]
      + [f"shared_path_{i + 1}" for i in range(n_share_cols)],
      [dict({"story_id": r["news_id"], "name": r["title"],
             "sb_path": r["sb_path"]},
            **{f"shared_path_{i + 1}": r[f"shared_path_{i + 1}"]
               for i in range(n_share_cols)})
       for r in routing])

    if slug_collisions:
        w(os.path.join(outdir, "_slug_collisions.csv"),
          ["news_id", "folder", "wanted", "assigned", "title"], slug_collisions)

    # ---------------- the folder list -------------------------------------
    folders = []

    def add(level, path, region="", entity="", dept=""):
        folders.append({
            "level": level,
            "path": path,
            "sb_path": slug_path(path),
            "folder_name": path.rsplit("/", 1)[-1],
            "folder_slug": slugify(path.rsplit("/", 1)[-1]),
            "region": region, "entity": entity,
            "entity_short": short_of.get(entity, "") if entity else "",
            "department": dept,
            "news_count": news_folder.get(path, 0),
        })

    add("root", "global")
    add("news", "global/news")
    add("root", "Regions")

    countries = sorted(x for x in regions if x != GLOBAL_REGION)
    for reg in countries:
        add("region", f"Regions/{reg}", reg)
        if news_folder.get(f"Regions/{reg}/News"):
            add("news", f"Regions/{reg}/News", reg)
        ents = sorted(region_entities.get(reg, ()))
        if ents:
            add("entities-root", f"Regions/{reg}/Entities", reg)
        for ent in ents:
            add("entity", f"Regions/{reg}/Entities/{ent}", reg, ent)
            if (news_folder.get(f"Regions/{reg}/Entities/{ent}/News")
                    or (reg, ent) in share_targets):
                add("news", f"Regions/{reg}/Entities/{ent}/News", reg, ent)
            depts = sorted(entity_depts.get((reg, ent), ()))
            if depts:
                add("departments-root",
                    f"Regions/{reg}/Entities/{ent}/Departments", reg, ent)
            for dp in depts:
                base = f"Regions/{reg}/Entities/{ent}/Departments/{dp}"
                add("department", base, reg, ent, dp)
                add("news", f"{base}/News", reg, ent, dp)

    w(os.path.join(outdir, "folder_structure.csv"),
      ["level", "path", "sb_path", "folder_name", "folder_slug", "region",
       "entity", "entity_short", "department", "news_count"], folders)

    # ---------------- readable tree ---------------------------------------
    tp = os.path.join(outdir, "folder_tree.txt")
    with open(tp, "w", encoding="utf-8") as f:
        f.write("AKU NEWS — STORYBLOK FOLDER STRUCTURE\n")
        f.write("=" * 66 + "\n")
        f.write(f"items: {len(routing)}   folders to create: {len(folders)}\n\n")

        f.write(f"global/\n  news/{'':<38}[{news_folder.get('global/news', 0)}]\n\n")
        f.write("Regions/\n")
        for reg in countries:
            ents = sorted(region_entities.get(reg, ()))
            tot = sum(v for k, v in news_folder.items()
                      if k.startswith(f"Regions/{reg}/"))
            f.write(f"  {reg}/{'':<30}[{tot} items, {len(ents)} entities]\n")
            n = news_folder.get(f"Regions/{reg}/News", 0)
            if n:
                f.write(f"    News/{'':<32}[{n}]\n")
            if not ents:
                continue
            f.write("    Entities/\n")
            for ent in ents:
                short = short_of.get(ent, "")
                label = f"{ent} ({short})" if short else ent
                f.write(f"      {label}/\n")
                n = news_folder.get(f"Regions/{reg}/Entities/{ent}/News", 0)
                if n:
                    f.write(f"        News/{'':<24}[{n}]\n")
                depts = sorted(entity_depts.get((reg, ent), ()))
                if depts:
                    f.write("        Departments/\n")
                for dp in depts:
                    n = news_folder.get(
                        f"Regions/{reg}/Entities/{ent}/Departments/{dp}/News", 0)
                    f.write(f"          {dp}/News/{'':<10}[{n}]\n")
            f.write("\n")

    print(f"\ntree -> {tp}")
    print("-" * 62)
    lv = Counter(f["level"] for f in folders)
    print(f"  folders to create : {len(folders)}")
    for k, v in lv.most_common():
        print(f"      {v:>4}  {k}")
    print(f"\n  news placement:")
    for k, v in Counter(r["level"] for r in routing).most_common():
        print(f"      {v:>4}  {k}")
    print(f"\n  entity source:")
    for k, v in entity_source.most_common():
        print(f"      {v:>4}  {k}")
    print(f"\n  share targets per story (max {max_shares[0]}):")
    for k, v in sorted(share_count.items()):
        print(f"      {v:>4}  {k} shared path(s)")
    print(f"\n  regions: {len(countries)} + global")
    print(f"  distinct entities: "
          f"{len({e for s in region_entities.values() for e in s})}")
    print(f"  region x entity nodes: "
          f"{sum(len(v) for v in region_entities.values())}")
    print(f"  department folders: {sum(len(v) for v in entity_depts.values())}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
