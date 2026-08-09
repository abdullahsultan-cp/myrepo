#!/usr/bin/env python3
"""
validate_dev_tree.py — check a dev-supplied region/entity/department tree.

The front end builds its own nested region -> entity -> department JSON. That has
to agree exactly with data/taxonomy/seed/folders.json, because every story's
upload path is computed from ours: a name or slug that differs by one character
means the upload creates a second folder instead of finding theirs.

So this compares set-for-set at all three levels and reports, separately:

  MISSING  in ours but not theirs   -> stories will have nowhere to go
  EXTRA    in theirs but not ours   -> empty folders, or a real correction
  RENAMED  same slug, different name (or vice versa)

It also checks their internal consistency: slugs that do not match their own
name, has_news flags that contradict the child data, and duplicates.

Usage:
    python scripts/taxonomy/validate_dev_tree.py <their.json> [--csv out.csv]
"""

import argparse
import csv
import json
import os
import re
import sys
import unicodedata

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _bootstrap  # noqa: F401,E402  -- paths_root now lives in pipeline/core/
from paths_root import P  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.abspath(os.path.join(HERE, "..", ".."))
OURS = os.path.join(P.TAXONOMY, "seed", "folders.json")
# Oddities that were reviewed and deliberately kept. Without this the validator
# reports the same accepted decision as a failure on every run, and a genuinely
# new problem stops standing out.
ACCEPTED = os.path.join(BASE, "config", "tree_accepted_exceptions.csv")


def load_accepted():
    if not os.path.exists(ACCEPTED):
        return {}
    with open(ACCEPTED, encoding="utf-8-sig") as f:
        return {(r["kind"], r["path"]): r.get("reason", "")
                for r in csv.DictReader(f)}


def slugify(text):
    """Same rule the folder tree used, so slug comparisons are meaningful."""
    t = unicodedata.normalize("NFKD", str(text or ""))
    t = t.encode("ascii", "ignore").decode("ascii").lower()
    t = re.sub(r"[^a-z0-9]+", "-", t)
    return t.strip("-")


def load_ours():
    """Ours is a flat folder list; fold it back into region/entity/dept sets."""
    with open(OURS, encoding="utf-8") as f:
        folders = json.load(f)["folders"]

    regions, entities, depts = {}, {}, {}
    for f in folders:
        lvl, r, e, d = (f.get("level"), f.get("region"), f.get("entity"),
                        f.get("department"))
        val = (f["name"], f.get("short_name"))
        if lvl == "region":
            regions[f["slug"]] = val
        elif lvl == "entity":
            entities[(slugify(r), f["slug"])] = val
        elif lvl == "department":
            depts[(slugify(r), slugify(e), f["slug"])] = val
    return regions, entities, depts


def load_theirs(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    regions, entities, depts = {}, {}, {}
    problems = []
    seen_r = set()
    for reg in data:
        rs = reg.get("slug") or ""
        if rs in seen_r:
            problems.append(("duplicate-region", rs, "", ""))
        seen_r.add(rs)
        regions[rs] = (reg.get("name"), reg.get("short_name"))
        if slugify(reg.get("name")) != rs:
            problems.append(("slug-mismatch-region", rs,
                             f"name={reg.get('name')!r}",
                             f"expected slug {slugify(reg.get('name'))!r}"))

        seen_e = set()
        for ent in reg.get("entities") or []:
            es = ent.get("slug") or ""
            if es in seen_e:
                problems.append(("duplicate-entity", rs, es, ""))
            seen_e.add(es)
            entities[(rs, es)] = (ent.get("name"), ent.get("short_name"))
            if slugify(ent.get("name")) != es:
                problems.append(("slug-mismatch-entity", rs, es,
                                 f"name={ent.get('name')!r} -> "
                                 f"{slugify(ent.get('name'))!r}"))

            kids = ent.get("departments") or []
            # has_news=false with no departments means the folder holds nothing
            if ent.get("has_news") is False and not kids:
                problems.append(("entity-holds-nothing", rs, es,
                                 "has_news=false and no departments"))
            seen_d = set()
            for dep in kids:
                ds = dep.get("slug") or ""
                if ds in seen_d:
                    problems.append(("duplicate-department", rs, es, ds))
                seen_d.add(ds)
                depts[(rs, es, ds)] = (dep.get("name"),
                                       dep.get("short_name"))
                if slugify(dep.get("name")) != ds:
                    problems.append(("slug-mismatch-department", rs, es,
                                     f"{dep.get('name')!r} -> "
                                     f"{slugify(dep.get('name'))!r}"))
    return regions, entities, depts, problems


def compare(level, ours, theirs, fmt):
    missing = sorted(set(ours) - set(theirs))
    extra = sorted(set(theirs) - set(ours))
    both = set(ours) & set(theirs)

    def norm(v):
        return (v or "").strip()

    renamed = sorted(k for k in both if norm(ours[k][0]) != norm(theirs[k][0]))
    reshort = sorted(k for k in both if norm(ours[k][1]) != norm(theirs[k][1]))
    rows = []
    for k in missing:
        rows.append({"level": level, "status": "MISSING",
                     "path": fmt(k), "ours": ours[k][0], "theirs": ""})
    for k in extra:
        rows.append({"level": level, "status": "EXTRA",
                     "path": fmt(k), "ours": "", "theirs": theirs[k][0]})
    for k in renamed:
        rows.append({"level": level, "status": "RENAMED",
                     "path": fmt(k), "ours": ours[k][0], "theirs": theirs[k][0]})
    for k in reshort:
        rows.append({"level": level, "status": "SHORT_NAME",
                     "path": fmt(k), "ours": ours[k][1] or "(none)",
                     "theirs": theirs[k][1] or "(none)"})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("their_json")
    ap.add_argument("--csv")
    a = ap.parse_args()

    o_reg, o_ent, o_dep = load_ours()
    t_reg, t_ent, t_dep, problems = load_theirs(a.their_json)

    print("=" * 74)
    print("  COUNTS")
    print("=" * 74)
    print(f"  {'':<14}{'ours':>8}{'theirs':>9}")
    for label, o, t in (("regions", o_reg, t_reg), ("entities", o_ent, t_ent),
                        ("departments", o_dep, t_dep)):
        flag = "" if len(o) == len(t) else "   <-- differs"
        print(f"  {label:<14}{len(o):>8}{len(t):>9}{flag}")

    rows = []
    rows += compare("region", o_reg, t_reg, lambda k: k)
    rows += compare("entity", o_ent, t_ent, lambda k: f"{k[0]}/{k[1]}")
    rows += compare("department", o_dep, t_dep,
                    lambda k: f"{k[0]}/{k[1]}/{k[2]}")

    for status in ("MISSING", "EXTRA", "RENAMED", "SHORT_NAME"):
        sel = [r for r in rows if r["status"] == status]
        print(f"\n{'=' * 74}")
        note = {"MISSING": "in OUR tree, absent from theirs -> stories have "
                           "nowhere to go",
                "EXTRA": "in THEIR tree, absent from ours -> empty folder, "
                         "or a correction",
                "RENAMED": "same slug, different display name",
                "SHORT_NAME": "same folder, different short_name -> "
                              "fix in config/department_abbrev.csv or theirs"
                }[status]
        print(f"  {status}  ({len(sel)})   {note}")
        print("=" * 74)
        for r in sel:
            if status in ("RENAMED", "SHORT_NAME"):
                print(f"  {r['level']:<11} {r['path']}")
                print(f"              ours   {r['ours']!r}")
                print(f"              theirs {r['theirs']!r}")
            else:
                print(f"  {r['level']:<11} {r['path']:<62} "
                      f"{r['ours'] or r['theirs']}")
        if not sel:
            print("  (none)")

    print(f"\n{'=' * 74}")
    accepted = load_accepted()
    new_problems, known = [], []
    for kind, r, e, extra in problems:
        key = (kind, f"{r}/{e}" if e else r)
        (known if key in accepted else new_problems).append(
            (kind, r, e, extra, accepted.get(key, "")))

    print(f"  INTERNAL CONSISTENCY OF THEIR FILE  "
          f"({len(new_problems)} new, {len(known)} accepted)")
    print("=" * 74)
    for kind, r, e, extra, _ in new_problems:
        print(f"  NEW       {kind:<28} {r}/{e}  {extra}")
    for kind, r, e, extra, why in known:
        print(f"  accepted  {kind:<28} {r}/{e}")
        print(f"            {why[:94]}")
    if not problems:
        print("  (clean)")

    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, lineterminator="\n",
                               fieldnames=["level", "status", "path",
                                              "ours", "theirs"])
            w.writeheader()
            w.writerows(rows)
        print(f"\n  -> {a.csv}  ({len(rows)} differences)")

    bad = [r for r in rows if r["status"] == "MISSING"]
    fail = bool(bad or new_problems)
    print(f"\n  VERDICT: {'MISMATCH' if fail else 'MATCHES'}"
          f"  ({len(bad)} missing, {len(new_problems)} new internal issues, "
          f"{len(known)} accepted)")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
