#!/usr/bin/env python3
"""
build_entity_abbrev.py — short form <-> long form for every entity.

No abbreviation field exists in the export, but LocalApproverGroup is 1:1 with
Entity (2048/2048 for Global, and one group per entity elsewhere) and the group
names are written in AKU's own shorthand: "MC_PK_NEWS_Approver",
"Sonam EA News Approver", "CA IGHD News". Stripping the boilerplate off those
group names recovers the abbreviation AKU actually uses.

Anything the group names don't yield is left blank for a human to fill rather
than invented here.

Usage:
    python build_entity_abbrev.py <input_dir_with_json> <output_dir>

Outputs:
    entity_abbrev.csv   entity_long, entity_short, slug, approver_groups, items
"""

import csv
import glob
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict

# Boilerplate that surrounds the abbreviation inside an approver-group name.
# Separators are split BEFORE this runs: "_" is a word character in regex, so
# \b never fires inside "MC_PK_NEWS" and the noise words would survive.
SEPARATORS = re.compile(r"[_\-]+")
NOISE = re.compile(
    r"\b(?:approvers?|news|group|content|ca|pk|ea|the|office|training)\b", re.I)

# Abbreviations recovered from group names are uppercase tokens; these are the
# ones that are real words rather than initialisms and should stay title-case.
WORDY = {"Sonam": "SONAM"}

ENTITY_REGION_SUFFIXES = (", East Africa", ", Pakistan")


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


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def abbrev_from_group(group):
    """'CA IGHD News' -> 'IGHD';  'MC_PK_NEWS_Approver' -> 'MC'."""
    cleaned = NOISE.sub(" ", SEPARATORS.sub(" ", group or ""))
    tokens = [t for t in re.split(r"\s+", cleaned) if t]
    # keep tokens that look like an initialism, or the known wordy ones
    picks = []
    for t in tokens:
        if t in WORDY:
            picks.append(WORDY[t])
        elif len(t) >= 2 and t.isupper():
            picks.append(t)
    return " ".join(picks)


def initials(name):
    """Fallback: initials of the significant words. 'Data Office' -> 'DO'."""
    skip = {"of", "for", "the", "and", "in", "de", "a"}
    words = [w for w in re.findall(r"[A-Za-z]+", name) if w.lower() not in skip]
    return "".join(w[0].upper() for w in words) if len(words) > 1 else ""


def main(indir, outdir):
    os.makedirs(outdir, exist_ok=True)
    files = sorted(glob.glob(os.path.join(indir, "*.json")))
    if not files:
        sys.exit(f"no .json in {indir}")

    groups = defaultdict(Counter)          # entity -> approver group -> n
    items = Counter()
    for path in files:
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            print(f"!! {os.path.basename(path)}: {e}", file=sys.stderr)
            continue
        base, _ = split_entity(lk(d.get("Entity")))
        if not base:
            continue
        items[base] += 1
        g = d.get("LocalApproverGroup")
        if g:
            groups[base][g] += 1

    rows = []
    for ent, n in items.most_common():
        cands = Counter()
        for g in groups[ent]:
            a = abbrev_from_group(g)
            if a:
                cands[a] += groups[ent][g]
        # Only abbreviations AKU actually uses, recovered from its own approver
        # group names. No initials are invented: a guessed short form is worse
        # than none, because the full entity name is always a valid label.
        short = cands.most_common(1)[0][0] if cands else ""
        source = "approver-group" if short else "none — use full name"
        rows.append({
            "entity_long": ent,
            "entity_short": short,
            "short_source": source,
            "slug_short": slugify(short),
            "slug_long": slugify(ent),
            "items": n,
            "approver_groups": " | ".join(
                f"{k}({v})" for k, v in groups[ent].most_common()),
        })

    p = os.path.join(outdir, "entity_abbrev.csv")
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        cw = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        cw.writeheader()
        cw.writerows(rows)
    print(f"  {len(rows):>5}  {os.path.basename(p)}\n")

    print(f"{'items':>6}  {'short':<10} {'source':<18} entity")
    print("-" * 78)
    for r in rows:
        print(f"{r['items']:>6}  {r['entity_short']:<10} "
              f"{r['short_source']:<18} {r['entity_long']}")

    by_src = Counter(r["short_source"] for r in rows)
    print("\n" + "  ".join(f"{k}: {v}" for k, v in by_src.most_common()))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
