#!/usr/bin/env python3
"""entities.py — fill `entities` the day the dev adds the field.

    python pipeline/migrate/update/run_update.py entities --type blogs
    python pipeline/migrate/update/run_update.py entities --type blogs --apply

**This one is finished.** `entities` is a list of entity FOLDER IDS as strings,
which we already know from news, so nothing is waiting on an example — only on
the field existing on `blog_article`. Run it the day it does.

## 17 of 83, not 83

The field is not "the Entity column". It is the story's own entity folder plus
every entity it is shared into. 66 of the 83 name something that is not a
faculty — `Global`, `Training`, `Data Innovation Office`, `Student Affairs and
Services` — so their list is legitimately empty, exactly as it is for 1,575
news stories.

    12  filed under an entity   its own folder id      11 IED, 1 FAS, all pk
     5  global and shared       qtl x4, cime x1
    66  not a faculty           empty, correctly

## The five shared ones get several ids

`qtl` exists in ke, pk, tz, ug and uk; `cime` in ke, pk and tz. That ambiguity
is why those blogs went to global in the first place — blogs have no City
column, so there was no region to file them under. Every region's copy is
listed, so the post is reachable from all of them.

Ids come from the live folder tree, never from a recorded path: the dev renamed
every folder to a short code once already — `regions/pakistan/entities/
medical-college` became `regions/pk/entities/mc` — and anything remembered from
before that is now wrong.
"""

import csv
import json
import os
import sys

FIELDS = ["entities"]

DESCRIPTION = "entity folder ids for the 17 that have one — ready to run"


def setup(source):
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    sys.path.insert(0, os.path.join(root, "pipeline"))
    import _bootstrap

    _bootstrap.ensure()
    from paths_root import P

    P.use("blogs")
    with open(P.SPACE_TREE, encoding="utf-8") as f:
        tree = json.load(f)
    folders = tree["folders"] if isinstance(tree, dict) else tree
    by_entity = {}
    for folder in folders:
        parts = (folder.get("full_slug") or "").split("/")
        if len(parts) == 4 and parts[0] == "regions" and parts[2] == "entities":
            by_entity.setdefault(parts[3], []).append(folder["id"])
            by_entity[(parts[1], parts[3])] = folder["id"]

    routing = {}
    with open(os.path.join(P.DATA, "taxonomy", "routing.csv"),
              encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            routing[str(row["id"])] = row
    return {"folders": by_entity, "routing": routing}


def ids_for(route, folders):
    out = []
    if route.get("placement") == "entity":
        parts = (route.get("target_full_slug") or "").split("/")
        if len(parts) >= 4 and parts[0] == "regions" and parts[2] == "entities":
            fid = folders.get((parts[1], parts[3]))
            if fid is not None:
                out.append(fid)
    for short in (route.get("share_entity") or "").split(";"):
        short = short.strip()
        if short:
            out += sorted(folders.get(short, []))
    # Storyblok stores these as strings, not numbers.
    seen, unique = set(), []
    for fid in out:
        if fid not in seen:
            seen.add(fid)
            unique.append(str(fid))
    return unique


def patch(content, source, ctx):
    sid = str(content.get("sharepoint_id") or "")
    route = (ctx.get("routing") or {}).get(sid)
    if not route:
        return {}
    wanted = ids_for(route, ctx.get("folders") or {})
    if not wanted or content.get("entities") == wanted:
        return {}
    return {"entities": wanted}
