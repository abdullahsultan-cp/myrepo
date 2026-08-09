#!/usr/bin/env python3
"""
run_taxonomy.py — run the taxonomy stage end to end.

Derives Region > Entity > Department for all 3606 news items and emits the
Storyblok folder structure. Mirrors scripts/run_pipeline.py in spirit: each step
is a separate script so any one can be re-run and audited on its own.

Usage:
    python scripts/taxonomy/run_taxonomy.py            # every step, in order
    python scripts/taxonomy/run_taxonomy.py status     # what exists so far
    python scripts/taxonomy/run_taxonomy.py folders    # one step by name

Steps, in dependency order:

    lookups      city / entity / tag inventory from the export
    regions      region per item (7 rules, recorded in region_source)
    abbrev       short form per entity, recovered from approver-group names
    recover      entity for the 2048 items whose Entity value is "Global"
    departments  department per item, derived from Tags
    crossrefs    cross-entity share links from AdditionalEntity
    tree         folder structure + per-item destination
    seed         folders + stories, one JSON for the backend
    folders      folders only, for creating the tree

`tree` depends on regions, abbrev, recover, departments and crossrefs having run.
`seed` and `folders` depend on `tree`.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths

HERE = paths.TAXONOMY_DIR
PY = sys.executable

# name -> (script, args, a file that proves it ran)
STEPS = [
    ("lookups", "harvest_lookups.py", [paths.NEWS_DIR, paths.LOOKUPS],
     os.path.join(paths.LOOKUPS, "lk_entities.csv")),
    ("regions", "build_structure.py",
     [paths.NEWS_DIR, paths.INTERMEDIATE, "all"], paths.NEWS_STRUCTURE),
    ("abbrev", "build_entity_abbrev.py", [paths.NEWS_DIR, paths.INTERMEDIATE],
     paths.ENTITY_ABBREV),
    ("recover", "recover_entity.py", [paths.NEWS_DIR, paths.INTERMEDIATE],
     paths.RECOVERED_ENTITIES),
    ("departments", "build_departments.py",
     [paths.NEWS_DIR, paths.INTERMEDIATE], paths.ITEMS_DEPARTMENTS),
    ("crossrefs", "build_crossrefs.py", [paths.NEWS_DIR, paths.INTERMEDIATE],
     paths.CONNECTIONS),
    ("tree", "build_folder_tree.py", [paths.ROUTING],
     os.path.join(paths.ROUTING, "folder_structure.csv")),
    ("seed", "build_seed_json.py",
     [paths.ROUTING, os.path.join(paths.SEED, "storyblok_seed.json")],
     os.path.join(paths.SEED, "storyblok_seed.json")),
    ("folders", "build_folders_only.py", [paths.ROUTING, paths.SEED],
     os.path.join(paths.SEED, "folders.json")),
]


def rel(p):
    return os.path.relpath(p, paths.REPO)


def status():
    if not os.path.isdir(paths.NEWS_DIR):
        print(f"  MISSING INPUT  {rel(paths.NEWS_DIR)}")
    else:
        n = len([f for f in os.listdir(paths.NEWS_DIR) if f.endswith(".json")])
        print(f"  input          {rel(paths.NEWS_DIR)}  ({n} json)")
    print()
    for name, _, _, proof in STEPS:
        mark = "done" if os.path.exists(proof) else "-   "
        print(f"  {mark}  {name:<12} {rel(proof)}")


def run(step):
    name, script, args, proof = step
    print(f"\n{'=' * 70}\n  {name}\n{'=' * 70}")
    r = subprocess.run([PY, os.path.join(HERE, script)] + [str(a) for a in args])
    if r.returncode != 0:
        sys.exit(f"\n!! step '{name}' failed with exit code {r.returncode}")
    if not os.path.exists(proof):
        sys.exit(f"\n!! step '{name}' produced no {rel(proof)}")


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    if arg in ("status", "-s", "--status"):
        return status()
    paths.ensure_dirs()
    if arg == "all":
        if not os.path.isdir(paths.NEWS_DIR):
            sys.exit(f"input missing: {paths.NEWS_DIR}\n"
                     "Run scripts/run_pipeline.py clean-news first.")
        for s in STEPS:
            run(s)
        print(f"\n{'=' * 70}\n  taxonomy complete")
        print(f"  backend seed : {rel(os.path.join(paths.SEED, 'folders.json'))}")
        print(f"  full seed    : "
              f"{rel(os.path.join(paths.SEED, 'storyblok_seed.json'))}")
        return
    for s in STEPS:
        if s[0] == arg:
            return run(s)
    sys.exit(f"unknown step '{arg}'. One of: "
             f"{', '.join(s[0] for s in STEPS)}, status")


if __name__ == "__main__":
    main()
