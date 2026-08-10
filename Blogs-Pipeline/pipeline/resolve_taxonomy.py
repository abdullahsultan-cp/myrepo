#!/usr/bin/env python3
"""resolve_taxonomy.py — where each blog belongs, and every taxonomy it uses.

Blogs cannot use the news taxonomy stage, for one concrete reason: **there is no
City column.** News read the region straight out of it. Blogs have nothing of the
kind, so region has to come from somewhere else.

It comes from the entity name. AKU's blogs list writes the region into it --
"Medical College, Pakistan", "Institute for Educational Development, East
Africa" -- so the entity string carries both halves and splitting it is honest
rather than a guess.

What this writes, all under Blogs-Pipeline/data/taxonomy/:

    entities.csv     every entity, how many blogs, and the folder it maps to
    categories.csv   every category, its blog count and its parent entity
    tags.csv         every tag and its blog count
    regions.csv      every region and its blog count
    routing.csv      ONE ROW PER BLOG: id, title, entity, category, tags,
                     region, placement, target folder, and why
    summary.json     the counts, and everything that did not resolve

Nothing here writes to Storyblok and nothing creates a folder. A destination
that does not exist is reported, not invented -- the tree belongs to the
front-end developer.
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(HERE)), "pipeline"))
import _bootstrap

_bootstrap.ensure()

from fields import F
from paths_root import ROOT, P

P.use("blogs")

# The live folder tree, refreshed by pipeline/migrate/review/dump_sb_tree.py.
# Read-only: it is the front-end developer's, and the answer to "can this blog
# land anywhere?" has to come from what is really there.
TREE = P.SPACE_TREE

# The bridge between AKU's entity names and the folder slugs. The front-end
# developer renamed every folder to a short code -- regions/pk/entities/ied, not
# regions/pakistan/entities/institute-for-educational-development -- so the
# blogs export's "Institute for Educational Development, Pakistan" matches
# nothing in the tree by name. The news taxonomy already holds both halves.
SEED = os.path.join(ROOT, "News-Pipeline", "data", "taxonomy", "seed", "folders.json")

# Entity values that are not entities. The same list news uses, plus the three
# the blogs list adds. Each routes to global rather than inventing a folder.
NOT_ENTITIES = {
    "global", "news training", "student affairs and services",
    "office of the provost", "office of the president", "office of the registrar",
    "data office", "research", "library",
    # blogs-only
    "training", "data innovation office", "critical creative innovative thinking",
    "networks of quality, teaching and learning",
    "network of english language enhancement", "environmental responsibility",
    "office of the dean of students",
}

# "East Africa" is not a region in the tree; it spans three. A blog owned by an
# East Africa entity has no single region, so it stays at the entity's own
# folder wherever the tree puts it, and the ambiguity is reported.
REGION_WORDS = {
    "pakistan": "pakistan", "kenya": "kenya", "tanzania": "tanzania",
    "uganda": "uganda", "united kingdom": "united kingdom", "uk": "united kingdom",
    "afghanistan": "afghanistan", "east africa": None,   # spans three regions
}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def load_shortcodes():
    """entity name -> short code, and region name -> short code."""
    with open(SEED, encoding="utf-8") as f:
        data = json.load(f)
    folders = data.get("folders") or data
    ents, regions = {}, {}
    for fo in folders:
        if fo.get("entity") and fo.get("entity_short"):
            ents[fo["entity"].strip().lower()] = slug(fo["entity_short"])
        if fo.get("region") and fo.get("region_short"):
            regions[fo["region"].strip().lower()] = slug(fo["region_short"])
    return ents, regions


def load_tree():
    with open(TREE, encoding="utf-8") as f:
        data = json.load(f)
    folders = data.get("folders") or data
    if isinstance(folders, dict):
        folders = list(folders.values())
    by_slug = {}
    entities = defaultdict(list)          # entity slug -> [region slug]
    for fo in folders:
        s = fo.get("full_slug") or ""
        by_slug[s] = fo
        m = re.match(r"^regions/([^/]+)/entities/([^/]+)$", s)
        if m:
            entities[m.group(2)].append(m.group(1))
    return by_slug, entities


def split_entity(raw):
    """'Medical College, Pakistan' -> ('Medical College', 'pakistan').

    Returns (name, region_or_None). The region is only taken when the trailing
    part is a region we actually have a folder for -- 'School of Nursing and
    Midwifery, East Africa' yields no region, which is the truth rather than a
    guess between Kenya, Tanzania and Uganda.
    """
    raw = (raw or "").strip()
    if "," not in raw:
        return raw, None
    head, _, tail = raw.rpartition(",")
    return head.strip(), REGION_WORDS.get(tail.strip().lower())


def resolve(item, by_slug, tree_entities, ent_short, region_short):
    """Where one blog goes, and why.

    Everything is expressed in the tree's own short codes, because that is what
    the folders are actually called: regions/pk/entities/ied.
    """
    raw_entity = (F.get(item, "entity") or "").strip()
    name, region_name = split_entity(raw_entity)
    reason = []

    if not raw_entity or name.lower() in NOT_ENTITIES or raw_entity.lower() in NOT_ENTITIES:
        reason.append("entity is not a faculty" if raw_entity else "no entity")
        return dict(placement="global", region="", entity=raw_entity,
                    target=f"global/{P.leaf}", reason="; ".join(reason))

    es = ent_short.get(name.lower())
    if not es:
        reason.append(f"no short code known for {name!r}")
        return dict(placement="global", region="", entity=name,
                    target=f"global/{P.leaf}", reason="; ".join(reason))

    regions = tree_entities.get(es, [])
    if not regions:
        reason.append(f"no entity folder {es!r} in the tree")
        return dict(placement="global", region="", entity=name,
                    target=f"global/{P.leaf}", reason="; ".join(reason))

    rs = region_short.get((region_name or "").lower()) if region_name else None
    if rs and rs in regions:
        chosen = rs
        reason.append(f"region {rs} read from the entity name")
    elif len(regions) == 1:
        chosen = regions[0]
        reason.append(f"entity exists only under {chosen}")
    else:
        reason.append(f"entity spans {sorted(regions)} and the name does not say which")
        return dict(placement="unresolved", region="", entity=name,
                    target="", reason="; ".join(reason))

    target = f"regions/{chosen}/entities/{es}/{P.leaf}"
    if target not in by_slug:
        reason.append("TARGET MISSING from the tree")
    return dict(placement="entity", region=chosen, entity=name,
                target=target, reason="; ".join(reason))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=None, help="output folder (default: data/taxonomy)")
    a = ap.parse_args()

    out = a.out or os.path.join(P.DATA, "taxonomy")
    os.makedirs(out, exist_ok=True)

    with open(P.SOURCE_JSON, encoding="utf-8") as f:
        items = json.load(f)
    by_slug, tree_entities = load_tree()
    ent_short, region_short = load_shortcodes()

    # ---- the lookups, straight from the export -----------------------------
    lookups = {}
    for name in ("entities", "categories"):
        path = os.path.join(P.DATA, "source", f"{name}.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                lookups[name] = json.load(f).get("value", [])

    ent_count, cat_count, tag_count, region_count = (Counter() for _ in range(4))
    rows, unresolved, missing_target = [], [], []

    for item in items:
        sid = F.get(item, "id")
        entity = (F.get(item, "entity") or "").strip()
        category = (F.get(item, "category") or "").strip()
        # SharePoint writes a taxonomy cell as "Label|GUID". Strip the GUID, or
        # the counts split one tag into as many rows as it has term ids -- which
        # is exactly what made news's tag counts untrustworthy.
        tags = [t.strip().partition("|")[0].strip()
                for t in re.split(r"[;,]", F.get(item, "tags") or "") if t.strip()]
        r = resolve(item, by_slug, tree_entities, ent_short, region_short)

        ent_count[entity or "(none)"] += 1
        cat_count[category or "(none)"] += 1
        for t in tags:
            tag_count[t] += 1
        region_count[r["region"] or "(global)"] += 1

        if r["placement"] == "unresolved":
            unresolved.append((sid, entity, r["reason"]))
        if "TARGET MISSING" in r["reason"]:
            missing_target.append((sid, r["target"]))

        rows.append({
            "id": sid,
            "title": (F.get(item, "title") or "")[:120],
            "entity": entity,
            "category": category,
            "tags": "; ".join(tags),
            "region": r["region"],
            "placement": r["placement"],
            "target_full_slug": r["target"],
            "target_exists": "yes" if r["target"] in by_slug else "no",
            "reason": r["reason"],
        })

    def write_csv(name, header, data):
        p = os.path.join(out, name)
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(data)
        return p

    write_csv("routing.csv", list(rows[0].keys()),
              [list(r.values()) for r in rows])
    write_csv("entities.csv", ["entity", "blogs", "resolves_to"],
              [[e, n, next((r["target_full_slug"] for r in rows if r["entity"] == e), "")]
               for e, n in ent_count.most_common()])
    cat_entity = {c.get("Title"): c.get("EntityId") for c in lookups.get("categories", [])}
    write_csv("categories.csv", ["category", "blogs", "entity_id_in_lookup"],
              [[c, n, cat_entity.get(c, "")] for c, n in cat_count.most_common()])
    write_csv("tags.csv", ["tag", "blogs"], tag_count.most_common())
    write_csv("regions.csv", ["region", "blogs"], region_count.most_common())

    placements = Counter(r["placement"] for r in rows)
    summary = {
        "type": "blogs",
        "items": len(rows),
        "placements": dict(placements),
        "regions": dict(region_count),
        "distinct": {"entities": len(ent_count), "categories": len(cat_count),
                     "tags": len(tag_count)},
        "lookup_sizes": {k: len(v) for k, v in lookups.items()},
        "unresolved": [{"id": i, "entity": e, "reason": r} for i, e, r in unresolved],
        "targets_missing_from_tree": [{"id": i, "target": t} for i, t in missing_target],
    }
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")

    rel = os.path.relpath(out, ROOT)
    print(f"  {len(rows)} blogs -> {rel}")
    print("\n  placement")
    for k, n in placements.most_common():
        print(f"    {k:<14}{n}")
    print(f"\n  distinct: {len(ent_count)} entities, {len(cat_count)} categories, "
          f"{len(tag_count)} tags")
    if unresolved:
        print(f"\n  UNRESOLVED ({len(unresolved)}):")
        for i, e, why in unresolved[:8]:
            print(f"    {i:<6}{e[:38]:<40}{why[:60]}")
    if missing_target:
        print(f"\n  TARGET FOLDER MISSING FROM THE TREE ({len(missing_target)}):")
        for i, t in missing_target[:8]:
            print(f"    {i:<6}{t}")
    needed = sorted({r["target_full_slug"] for r in rows
                     if r["target_full_slug"] and r["target_exists"] == "no"})
    if needed:
        print(f"\n  {len(needed)} destination folder(s) do not exist. The migration "
              f"will not create them:")
        for t in needed:
            print(f"    {t}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
