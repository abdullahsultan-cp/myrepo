#!/usr/bin/env python3
"""
analyze_storyblok_space.py — read the fetched space and report its real schema.

Answers the questions that decide how stories get built:
  * which components exist, by group, and which are content types vs nestable
  * the full field list of the target news_article, with types and options
  * which field plugins the front-end uses (the Management API refuses
    /field_types to a personal token, so they are recovered from component
    schemas where type == "custom")
  * which components the existing sample stories actually use
  * where the migration's own payload disagrees with the live schema

Usage:
    python scripts/analyze_storyblok_space.py [space_dir] [--json out.json]
"""

import json
import os
import sys
from collections import Counter, defaultdict

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def load(d, name):
    p = os.path.join(d, f"{name}.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def walk_bloks(obj, hit):
    if isinstance(obj, list):
        for o in obj:
            walk_bloks(o, hit)
    elif isinstance(obj, dict):
        if obj.get("component"):
            hit[obj["component"]] += 1
        for v in obj.values():
            if isinstance(v, (dict, list)):
                walk_bloks(v, hit)


def main():
    # Pull --json and its value out first; otherwise the value would be taken
    # as the positional space directory.
    argv = sys.argv[1:]
    out_json = None
    if "--json" in argv:
        i = argv.index("--json")
        out_json = argv[i + 1] if len(argv) > i + 1 else None
        del argv[i:i + 2]
    args = [a for a in argv if not a.startswith("--")]
    d = args[0] if args else os.path.join(BASE, "storyblok_space")
    if not os.path.isdir(d):
        sys.exit(f"not a directory: {d}")

    comps = load(d, "components") or []
    groups = {g["uuid"]: g["name"] for g in (load(d, "component_groups") or [])}
    stories = load(d, "stories_full") or []
    assets = load(d, "assets") or []

    by_uuid = {c["name"]: c for c in comps}
    report = {}

    # ------------------------------------------------ components by group
    print(f"{'=' * 78}\n  {len(comps)} COMPONENTS in {len(groups)} groups\n{'=' * 78}")
    grouped = defaultdict(list)
    for c in comps:
        grouped[groups.get(c.get("component_group_uuid"), "(ungrouped)")].append(c)
    for g in sorted(grouped, key=lambda x: (x == "(ungrouped)", x)):
        items = sorted(grouped[g], key=lambda c: c["name"])
        print(f"\n  {g}  [{len(items)}]")
        for c in items:
            kind = []
            if c.get("is_root"):
                kind.append("content-type")
            if c.get("is_nestable"):
                kind.append("nestable")
            nfields = len(c.get("schema") or {})
            print(f"    {c['name']:<34} {nfields:>3} fields  "
                  f"{'/'.join(kind) or 'n/a'}")

    report["components"] = {
        c["name"]: {
            "group": groups.get(c.get("component_group_uuid")),
            "is_root": bool(c.get("is_root")),
            "is_nestable": bool(c.get("is_nestable")),
            "field_count": len(c.get("schema") or {}),
        } for c in comps
    }

    # ------------------------------------------------ field plugins
    print(f"\n{'=' * 78}\n  FIELD PLUGINS (type == custom)\n{'=' * 78}")
    plugins = defaultdict(list)
    field_types = Counter()
    for c in comps:
        for fname, f in (c.get("schema") or {}).items():
            t = f.get("type")
            field_types[t] += 1
            if t == "custom":
                plugins[f.get("field_type") or "(unnamed)"].append(
                    f"{c['name']}.{fname}")
    if plugins:
        for p, uses in sorted(plugins.items(), key=lambda x: -len(x[1])):
            print(f"\n  {p}   used {len(uses)}x")
            for u in sorted(uses)[:14]:
                print(f"      {u}")
            if len(uses) > 14:
                print(f"      ... and {len(uses) - 14} more")
    else:
        print("  none")
    report["field_plugins"] = {k: v for k, v in plugins.items()}

    print(f"\n{'=' * 78}\n  FIELD TYPES USED ACROSS ALL COMPONENTS\n{'=' * 78}")
    for t, n in field_types.most_common():
        print(f"  {n:>5}  {t}")
    report["field_types"] = dict(field_types)

    # ------------------------------------------------ the target content type
    for target in ("news_article", "news"):
        c = by_uuid.get(target)
        if not c:
            continue
        print(f"\n{'=' * 78}\n  TARGET CONTENT TYPE: {target}\n{'=' * 78}")
        print(f"  is_root={bool(c.get('is_root'))}  "
              f"is_nestable={bool(c.get('is_nestable'))}  "
              f"group={groups.get(c.get('component_group_uuid'))}")
        sch = c.get("schema") or {}
        print(f"\n  {len(sch)} fields:\n")
        print(f"  {'field':<26} {'type':<14} {'req':<4} detail")
        print(f"  {'-'*26} {'-'*14} {'-'*4} {'-'*30}")
        fields = {}
        for fname, f in sch.items():
            t = f.get("type", "")
            req = "yes" if f.get("required") else ""
            detail = []
            if t == "custom":
                detail.append(f"plugin={f.get('field_type')}")
            if f.get("component_whitelist"):
                wl = f["component_whitelist"]
                detail.append(f"allows {len(wl)}: "
                              + ", ".join(sorted(wl)[:6])
                              + (" ..." if len(wl) > 6 else ""))
            if f.get("options"):
                opts = [o.get("value") for o in f["options"]]
                detail.append("options: " + ", ".join(str(o) for o in opts[:8]))
            if f.get("source"):
                detail.append(f"source={f['source']}")
            if f.get("filetypes"):
                detail.append(f"filetypes={','.join(f['filetypes'])}")
            if t == "bloks" and f.get("maximum"):
                detail.append(f"max={f['maximum']}")
            print(f"  {fname:<26} {t:<14} {req:<4} {'; '.join(detail)}")
            fields[fname] = {"type": t, "required": bool(f.get("required")),
                             "field_type": f.get("field_type"),
                             "component_whitelist": f.get("component_whitelist"),
                             "options": [o.get("value")
                                         for o in (f.get("options") or [])]}
        report[f"schema_{target}"] = fields

    # ------------------------------------------------ what the samples use
    print(f"\n{'=' * 78}\n  COMPONENTS USED BY THE {len(stories)} EXISTING STORIES\n{'=' * 78}")
    used = Counter()
    per_story = {}
    for st in stories:
        hit = Counter()
        walk_bloks(st.get("content") or {}, hit)
        used.update(hit)
        per_story[st.get("full_slug") or st.get("slug")] = dict(hit)
    for k, v in used.most_common():
        mark = "" if k in by_uuid else "   <-- NOT IN COMPONENT LIBRARY"
        print(f"  {v:>5}  {k}{mark}")
    report["used_by_samples"] = dict(used)

    print(f"\n  defined but never used in a story: "
          f"{len([c for c in by_uuid if c not in used])} of {len(by_uuid)}")

    print(f"\n{'=' * 78}\n  STORIES IN THE SPACE\n{'=' * 78}")
    for st in sorted(stories, key=lambda s: s.get("full_slug") or ""):
        comp = ((st.get("content") or {}).get("component")) or "?"
        print(f"  {'FOLDER' if st.get('is_folder') else 'story ':<7} "
              f"{comp:<18} {st.get('full_slug')}")

    print(f"\n{'=' * 78}\n  ASSETS ({len(assets)})\n{'=' * 78}")
    ext = Counter()
    for a in assets:
        fn = (a.get("filename") or "").split("?")[0]
        ext[os.path.splitext(fn)[1].lower() or "(none)"] += 1
    for e, n in ext.most_common():
        print(f"  {n:>5}  {e}")

    if out_json:
        with open(out_json, "w", encoding="utf-8", newline="\n") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n  report -> {out_json}")


if __name__ == "__main__":
    main()
