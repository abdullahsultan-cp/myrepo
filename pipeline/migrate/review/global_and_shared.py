#!/usr/bin/env python3
"""
global_and_shared.py — which stories are global, and which are shared elsewhere.

Two questions that look similar and are not:

    isGlobal   the story surfaces on the global listing as well as in its own
               folder. One flag per story.
    shared     the story is referenced from another entity's folder, via
               AdditionalEntity. Any number of targets per story.

A story can be either, both or neither. This lists each set with its counts, and
writes a CSV per set so a placement can be argued about with the row in hand.

Reads the tracking database, so it reflects what will actually be uploaded.

Usage:
    python scripts/migrate/review/global_and_shared.py
    python scripts/migrate/review/global_and_shared.py --csv
    python scripts/migrate/review/global_and_shared.py --limit 40
"""

import argparse
import csv
import os
import sys
from collections import Counter, defaultdict

# Walk up to the pipeline/ root rather than counting dirname() calls: the
# scripts using this sit at two different depths (migrate/ and
# migrate/review/), and a fixed count is right for one and wrong for the
# other -- which is exactly how this broke.
# Two things have to be importable: this flow's own helpers (migrate/paths.py,
# migrate/db.py) and the shared pipeline modules. The scripts using this sit at
# two different depths -- migrate/ and migrate/review/ -- so the pipeline root is
# found by walking up for _bootstrap.py rather than by counting dirname() calls,
# which is right for one depth and silently wrong for the other.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_d = os.path.dirname(os.path.abspath(__file__))
while _d != os.path.dirname(_d):
    if os.path.exists(os.path.join(_d, "_bootstrap.py")):
        sys.path.insert(0, _d)
        break
    _d = os.path.dirname(_d)
import _bootstrap  # noqa: F401,E402
from paths import BASE  # noqa: E402

import db as tracking  # noqa: E402

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from paths_root import P  # noqa: E402

OUT_DIR = os.path.join(P.MIGRATE, "reports")
PAGE = "https://www.aku.edu/news/Pages/news_details.aspx?nid={nid}"


def w_csv(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, lineterminator="\n", fieldnames=cols,
                            extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)
    print(f"    {len(rows):>5}  {os.path.relpath(path, BASE)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="store_true")
    ap.add_argument("--limit", type=int, default=25,
                    help="how many examples to print per set")
    a = ap.parse_args()

    with tracking.connect() as c:
        c.execute("SET search_path TO migration, public")
        stories = c.execute("""
            SELECT sharepoint_id, sequence_number, title, region, entity,
                   department, placement, surface_global, target_full_slug
            FROM story ORDER BY sharepoint_id""").fetchall()
        shares = c.execute("""
            SELECT sharepoint_id, ref_region, ref_entity, ref_full_slug
            FROM share_target ORDER BY sharepoint_id""").fetchall()

    by_id = {s[0]: s for s in stories}
    share_map = defaultdict(list)
    for sid, reg, ent, full in shares:
        share_map[sid].append((reg or "", ent or "", full or ""))

    glob = [s for s in stories if s[7]]
    shared = [s for s in stories if share_map.get(s[0])]
    both = [s for s in glob if share_map.get(s[0])]
    neither = [s for s in stories
               if not s[7] and not share_map.get(s[0])]

    print("=" * 74)
    print("  COUNTS")
    print("=" * 74)
    print(f"  total stories                     {len(stories):>6}")
    print(f"  isGlobal = true                   {len(glob):>6}"
          f"   ({100 * len(glob) / len(stories):.1f}%)")
    print(f"  shared to another entity          {len(shared):>6}"
          f"   ({100 * len(shared) / len(stories):.1f}%)")
    print(f"    - share references in total     {len(shares):>6}")
    print(f"  both global AND shared            {len(both):>6}")
    print(f"  neither                           {len(neither):>6}")

    # ---------------------------------------------------------------- global
    print(f"\n{'=' * 74}")
    print("  isGLOBAL = TRUE — by where the story itself lives")
    print("=" * 74)
    for k, n in Counter(s[6] or "(none)" for s in glob).most_common():
        print(f"    {n:>5}  {k}")

    print("\n  by region")
    for k, n in Counter(s[3] or "(none)" for s in glob).most_common():
        print(f"    {n:>5}  {k}")

    print("\n  top entities")
    for k, n in Counter(s[4] or "(no entity)" for s in glob).most_common(12):
        print(f"    {n:>5}  {k}")

    # --------------------------------------------------------------- shared
    print(f"\n{'=' * 74}")
    print("  SHARED TO ANOTHER ENTITY")
    print("=" * 74)
    print("  how many targets each story has")
    for n, k in sorted(Counter(len(v) for v in share_map.values()).items()):
        print(f"    {k:>5} stories share to {n} entit{'y' if n == 1 else 'ies'}")

    print("\n  most-shared-INTO entities (the destination)")
    # A reference to one of the nine non-entity values (Office of the President
    # and friends) has no entity to name, and resolves to global/news. Showing
    # "region/None" for those would read as a data fault rather than the rule.
    dest = Counter(full if not ent else f"{reg}/{ent}"
                   for sid, reg, ent, full in shares)
    for k, n in dest.most_common(15):
        note = "   <- a non-entity reference; resolves to global" \
            if k == "global/news" else ""
        print(f"    {n:>5}  {k}{note}")

    print("\n  most-shared-FROM entities (the owner)")
    src = Counter(f"{by_id[sid][3]}/{by_id[sid][4] or '(no entity)'}"
                  for sid in share_map if sid in by_id)
    for k, n in src.most_common(12):
        print(f"    {n:>5}  {k}")

    # -------------------------------------------------------------- examples
    def show(label, rows):
        print(f"\n{'=' * 74}")
        print(f"  {label}  (first {min(a.limit, len(rows))} of {len(rows)})")
        print("=" * 74)
        for s in rows[:a.limit]:
            sid, seq, title, region, entity, dept, placement, sg, target = s
            where = "/".join(x for x in (region, entity, dept) if x) or "global"
            print(f"  {sid:<6} {title[:58]}")
            print(f"         {where}   [{placement}]")
            tg = share_map.get(sid) or []
            if tg:
                print(f"         shared to: "
                      f"{', '.join(f'{r}/{e}' for r, e, _ in tg)}")

    show("isGlobal = true", glob)
    show("shared to another entity", shared)

    # ------------------------------------------------------------------ csv
    if a.csv:
        print(f"\n{'=' * 74}\n  CSV\n{'=' * 74}")

        def row(s):
            sid, seq, title, region, entity, dept, placement, sg, target = s
            tg = share_map.get(sid) or []
            return {
                "sharepoint_id": sid, "sequence_number": seq or "",
                "title": title, "region": region or "",
                "entity": entity or "", "department": dept or "",
                "placement": placement or "", "is_global": bool(sg),
                "target_full_slug": target or "",
                "share_count": len(tg),
                "shared_to_entities": "; ".join(
                    f if not e else f"{r}/{e}" for r, e, f in tg),
                "shared_to_folders": "; ".join(f for _, _, f in tg),
                "sharepoint_url": PAGE.format(nid=(seq or "").upper())
                                  if seq else "",
            }

        cols = list(row(stories[0]))
        w_csv(os.path.join(OUT_DIR, "is_global.csv"), cols,
              [row(s) for s in glob])
        w_csv(os.path.join(OUT_DIR, "shared_entities.csv"), cols,
              [row(s) for s in shared])
        # one row per share reference, for counting by destination
        w_csv(os.path.join(OUT_DIR, "share_references.csv"),
              ["sharepoint_id", "title", "owner_region", "owner_entity",
               "shared_to_region", "shared_to_entity", "shared_to_folder"],
              [{"sharepoint_id": sid, "title": by_id[sid][2] if sid in by_id
                else "", "owner_region": by_id[sid][3] if sid in by_id else "",
                "owner_entity": by_id[sid][4] if sid in by_id else "",
                "shared_to_region": reg, "shared_to_entity": ent,
                "shared_to_folder": full}
               for sid, reg, ent, full in shares])


if __name__ == "__main__":
    main()
