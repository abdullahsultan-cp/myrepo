#!/usr/bin/env python3
"""
recover_entity.py — can the 2048 no-owner items be given a real entity?

Entity == "Global" means no faculty was assigned. Before accepting that, try
every other field that might name one:

    1. AdditionalEntity  — an explicit lookup to a real entity. Not inference.
    2. Tags              — 281 tag labels include entity names and AKU's own
                           abbreviations (CIME, BMI, SONAM, ISMC...).
    3. Approver group    — LocalApproverGroup is 1:1 with entity, but for these
                           items it is always "Global Approvers", so it can only
                           confirm the absence. Checked, not used.
    4. Title / body      — entity names written in prose.

Precision matters more than coverage here: a wrong entity files news under the
wrong faculty and, since departments sit under entities, under the wrong
permission scope. So aliases are exact-match only, generic words are excluded,
and every recovered row records the rule and the evidence.

Usage:
    python recover_entity.py <input_dir_with_json> <output_dir>

Outputs:
    recovered_entities.csv    per item: recovered entity, rule, evidence
    _recovery_summary.csv     counts per rule and per entity
    _still_no_entity.csv      items that stay at region level
"""

import csv
import glob
import html
import json
import os
import re
import sys
from collections import Counter

# ---------------------------------------------------------------- aliases
# canonical entity -> exact alias strings (matched case-insensitively, whole
# string for tags, word-boundary for prose). Deliberately conservative:
# "Research" and "Library" get no short alias because the bare words appear
# 760 and 33 times as ordinary topic tags.
ENTITY_ALIASES = {
    "Medical College": ["medical college", "aku medical college", "akumc"],
    "School of Nursing and Midwifery": [
        "school of nursing and midwifery", "sonam"],
    "Centre for Innovation in Medical Education": [
        "centre for innovation in medical education", "cime"],
    "Institute for the Study of Muslim Civilisations": [
        "institute for the study of muslim civilisations", "ismc"],
    "Institute for Educational Development": [
        "institute for educational development", "ied"],
    "Graduate School of Media and Communications": [
        "graduate school of media and communications", "gsmc"],
    "Brain and Mind Institute": ["brain and mind institute", "bmi"],
    "Networks of Quality, Teaching and Learning": [
        "networks of quality, teaching and learning", "qai-net", "tl-net",
        "bdl-net"],
    "East Africa Institute": ["east africa institute"],
    "Centre of Excellence in Women and Child Health": [
        "centre of excellence in women and child health",
        "centre of excellence in women & child health"],
    "Network of English Language Enhancement": [
        "network of english language enhancement"],
    "Institute for Human Development": ["institute for human development"],
    "Institute for Global Health and Development": [
        "institute for global health and development"],
    "Centre for Regenerative Medicine and Stem Cell Research": [
        "centre for regenerative medicine and stem cell research"],
    "Surgery Interest Group": ["surgery interest group"],
    "Centre of Excellence for Trauma and Emergencies": [
        "centre of excellence for trauma and emergencies"],
    "Faculty of Arts and Sciences": ["faculty of arts and sciences"],
    "Arusha Climate and Environmental Research Centre": [
        "arusha climate and environmental research centre"],
    "Office of the President": ["office of the president", "president's office"],
    "Office of the Registrar": ["office of the registrar"],
    "Office of the Provost": ["office of the provost"],
    "Environmental Responsibility": ["environmental responsibility"],
    "Student Affairs and Services": ["student affairs and services"],
    "Data Office": ["data office"],
}

TAG_EXACT = {}          # normalised tag label -> entity
for canon, aliases in ENTITY_ALIASES.items():
    for a in aliases:
        TAG_EXACT[a] = canon

# Prose patterns: only the full names, never the abbreviations. "MC" and "BMI"
# appear inside unrelated words and acronyms in body text.
PROSE = {canon: [re.compile(r"\b" + re.escape(a) + r"\b", re.I)
                 for a in aliases if len(a) > 12]
         for canon, aliases in ENTITY_ALIASES.items()}

ENTITY_REGION_SUFFIXES = (", East Africa", ", Pakistan")
TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<script\b.*?</script>", re.S | re.I)


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


def to_text(raw):
    s = SCRIPT_RE.sub(" ", raw or "")
    return re.sub(r"\s+", " ", unesc(TAG_RE.sub(" ", s)))


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


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

    rows, still = [], []
    by_rule = Counter()
    by_entity = Counter()
    addl_shape = Counter()
    approver_check = Counter()
    total_noowner = 0

    for path in files:
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            print(f"!! {os.path.basename(path)}: {e}", file=sys.stderr)
            continue

        if lk(d.get("Entity")) != "Global":
            continue
        total_noowner += 1
        approver_check[d.get("LocalApproverGroup") or "(blank)"] += 1

        title = unesc(d.get("Title"))
        tags = [unesc(t.get("Label")) for t in (d.get("Tags") or [])
                if t.get("Label")]

        # ---- rule 1: AdditionalEntity (explicit lookup, strongest)
        refs, ref_regions = [], []
        for a in d.get("AdditionalEntity") or []:
            t = lk(a)
            if not t or t == "Global":
                continue
            base, suf = split_entity(t)
            if base not in refs:
                refs.append(base)
                ref_regions.append(suf)
        addl_shape[len(refs)] += 1

        entity = rule = evidence = ""
        if len(refs) == 1:
            entity, rule, evidence = refs[0], "additional-entity", refs[0]
        elif len(refs) > 1:
            entity, rule = refs[0], "additional-entity-first-of-many"
            evidence = " | ".join(refs)

        # ---- rule 2: a tag that IS an entity name
        if not entity:
            hits = []
            for t in tags:
                c = TAG_EXACT.get(norm(t))
                if c and c not in hits:
                    hits.append(c)
            if len(hits) == 1:
                entity, rule, evidence = hits[0], "tag-exact", hits[0]
            elif len(hits) > 1:
                entity, rule = hits[0], "tag-exact-ambiguous"
                evidence = " | ".join(hits)

        # ---- rule 3: full entity name in title or body
        if not entity:
            blob = f"{title}\n{unesc(d.get('NewsSummary'))}\n" \
                   f"{to_text(d.get('NewsContent'))}"
            scores = Counter()
            for canon, pats in PROSE.items():
                n = sum(len(p.findall(blob)) for p in pats)
                if n:
                    scores[canon] = n
            if scores:
                top = scores.most_common()
                if len(top) == 1 or top[0][1] >= 2 * top[1][1]:
                    entity, rule = top[0][0], "prose-name"
                    evidence = " ".join(f"{k}:{v}" for k, v in top[:3])
                else:
                    entity, rule = top[0][0], "prose-name-ambiguous"
                    evidence = " ".join(f"{k}:{v}" for k, v in top[:3])

        row = {
            "news_id": d.get("Id"),
            "published_date": (d.get("ScheduleStartDate")
                               or d.get("Created") or "")[:10],
            "title": title,
            "city": lk(d.get("City")),
            "recovered_entity": entity,
            "recovery_rule": rule,
            "evidence": evidence,
            "additional_entities": " | ".join(refs),
            "tags": " | ".join(tags),
        }
        if entity:
            rows.append(row)
            by_rule[rule] += 1
            by_entity[entity] += 1
        else:
            still.append(row)

    hdr = ["news_id", "published_date", "title", "city", "recovered_entity",
           "recovery_rule", "evidence", "additional_entities", "tags"]
    w(os.path.join(outdir, "recovered_entities.csv"), hdr, rows)
    w(os.path.join(outdir, "_still_no_entity.csv"), hdr, still)
    w(os.path.join(outdir, "_recovery_summary.csv"),
      ["kind", "key", "items"],
      [{"kind": "rule", "key": k, "items": v} for k, v in by_rule.most_common()]
      + [{"kind": "entity", "key": k, "items": v}
         for k, v in by_entity.most_common()])

    print(f"\n{'='*62}")
    print(f"  no-owner items examined : {total_noowner}")
    print(f"  entity RECOVERED       : {len(rows)}  "
          f"({100*len(rows)//max(total_noowner,1)}%)")
    print(f"  still no entity        : {len(still)}")
    print("\n  by rule (in priority order):")
    for k in ("additional-entity", "additional-entity-first-of-many",
              "tag-exact", "tag-exact-ambiguous", "prose-name",
              "prose-name-ambiguous"):
        if by_rule.get(k):
            print(f"    {by_rule[k]:>5}  {k}")
    print("\n  AdditionalEntity shape:")
    for k, v in sorted(addl_shape.items()):
        print(f"    {v:>5}  {k} real reference(s)")
    print("\n  LocalApproverGroup on these items:")
    for k, v in approver_check.most_common(5):
        print(f"    {v:>5}  {k}")
    print("\n  recovered entities:")
    for k, v in by_entity.most_common():
        print(f"    {v:>5}  {k}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
