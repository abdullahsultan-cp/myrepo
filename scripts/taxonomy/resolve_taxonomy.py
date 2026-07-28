#!/usr/bin/env python3
"""
resolve_taxonomy.py — derive the seeder path for every news item.

    Region  >  Entity  >  Department  >  Type

Region comes from City. Entity comes from Entity/AdditionalEntity. Department and
Type are NOT in the export, so they are inferred from tags + body text and every
row records WHICH rule fired, so you can audit instead of trust.

City is kept as a separate column purely to backtrack: if the entity says
"Medical College, Pakistan" but the city says Nairobi, region_conflict = True and
the row lands in _needs_review.csv.

Usage:
    python resolve_taxonomy.py <input_dir_with_json> <output_dir>

Outputs:
    taxonomy.csv        one row per item: full path + source + confidence per field
    _needs_review.csv   rows with a conflict or an UNKNOWN in the path
    _unresolved_departments.csv  raw "department of X" strings that matched no vocab
    _paths.csv          distinct Region>Entity>Department>Type paths + item counts
    _coverage.txt       how much of each dimension resolved
"""

import csv
import glob
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict

# ------------------------------------------------------------------ vocab
# Edit these. Everything downstream is derived, nothing is hardcoded elsewhere.

CITY_TO_REGION = {
    "Karachi": "Pakistan", "Islamabad": "Pakistan", "Hyderabad": "Pakistan",
    "Gilgit": "Pakistan", "Chitral": "Pakistan", "Lahore": "Pakistan",
    "Nairobi": "Kenya", "Mombasa": "Kenya", "Kisumu": "Kenya",
    "Dar es Salaam": "Tanzania", "Mwanza": "Tanzania", "Arusha": "Tanzania",
    "Kampala": "Uganda",
    "Kabul": "Afghanistan", "Bamyan": "Afghanistan",
    "London": "United Kingdom", "Dubai": "UAE", "Lisbon": "Portugal",
    "Global": "Global",
}

# Region groups used in entity names, for the city-vs-entity cross-check.
REGION_GROUPS = {
    "East Africa": {"Kenya", "Uganda", "Tanzania"},
    "Pakistan": {"Pakistan"},
}

# canonical department -> alias patterns (matched case-insensitively)
DEPARTMENTS = {
    "Neurosurgery": ["neurosurgery", "neurological surgery"],
    "Obstetrics & Gynaecology": ["obstetric", "gynaecolog", "gynecolog", "ob/gyn", "obs gyn"],
    "Paediatrics & Child Health": ["paediatric", "pediatric", "child health"],
    "Anaesthesiology": ["anaesthesiolog", "anesthesiolog", "critical care"],
    "Emergency Medicine": ["emergency medicine"],
    "Internal Medicine": ["internal medicine"],
    "Surgery": ["department of surgery", "general surgery"],
    "Radiology": ["radiolog"],
    "Pathology & Laboratory Medicine": ["patholog", "laboratory medicine"],
    "Psychiatry & Mental Health": ["psychiatry", "mental health"],
    "Cardiology": ["cardiolog", "cardiac", "heart"],
    "Oncology": ["oncolog", "cancer"],
    "Community Health Sciences": ["community health"],
    "Family Medicine": ["family medicine"],
    "Geriatrics & Gerontology": ["geriatric", "gerontolog"],
    "Nursing": ["nursing"],
    "Midwifery": ["midwifer"],
    "Regenerative Medicine": ["regenerative medicine", "stem cell"],
    "Medical Education": ["medical education", "postgraduate medical education", "pgme"],
    "Public Health": ["public health", "epidemiolog"],
    "Nutrition": ["nutrition", "malnutrition"],
    "Research Office": ["research office", "grant management"],
    "Quality, Teaching & Learning": ["qtl", "quality, teaching and learning",
                                     "teaching and learning"],
    "Office of the President": ["office of the president", "president's office"],
    "Governance": ["governance", "board of trustees", "trustee"],
    "Media & Communications": ["media innovation", "journalism", "communications"],
    "Educational Development": ["educational development"],
    "Muslim Civilisations": ["muslim civilisation", "muslim civilization"],
}

# news type -> (regex patterns, weight). Highest total score wins.
TYPE_RULES = {
    "Obituary": [(r"\bin memoriam\b", 6), (r"\bmourns the passing\b", 6),
                 (r"\bpassing of\b", 3), (r"\bwill be deeply missed\b", 3)],
    "Convocation": [(r"\bconvocation\b", 6), (r"\bgraduat(?:ed|es|ion)\b", 2),
                    (r"\bvaledictor", 3), (r"\bdiplomas\b", 2)],
    "Award": [(r"\baward(?:ed|s)?\b", 3), (r"\bprize\b", 3), (r"\bhonour(?:ed|s)?\b", 2),
              (r"\brecogni[sz]ed for\b", 2), (r"\bwinner\b", 2)],
    "Grant": [(r"\bseed grant\b", 5), (r"\bgrant of\b", 4), (r"\breceiv\w+ (?:a |the )?grant",
              5), (r"\bfunding from\b", 3), (r"£[\d,]+|\$[\d,]+ (?:grant|research)", 3)],
    "Accreditation": [(r"\bcertification\b", 5), (r"\baccredit", 5), (r"\bgold tier\b", 4),
                      (r"\bcompliance\b", 2)],
    "Partnership": [(r"\bpartnership\b", 5), (r"\bmemorandum of understanding\b", 6),
                    (r"\bMoU\b", 5), (r"\bcollaborat\w+ with\b", 2)],
    "Research": [(r"\bpublished in\b", 5), (r"\bthe study (?:found|also)", 4),
                 (r"\bnew study\b", 5), (r"\btrial (?:found|was conducted)", 4),
                 (r"\bdoi\.org\b", 4), (r"\breview,? published\b", 5),
                 (r"\bresearch(?:ers)? (?:at|have)\b", 2)],
    "Research Project": [(r"\bresearch project\b", 6), (r"\bresearch programme\b", 6),
                         (r"\bprincipal investigator\b", 5), (r"\bco-investigator\b", 4)],
    "Publication": [(r"\bnew book\b", 6), (r"\bbook abstract\b", 6), (r"\be-?book\b", 5),
                    (r"\bbook review", 4), (r"\border your copy\b", 5)],
    "Event": [(r"\bworkshop\b", 5), (r"\bconference\b", 3), (r"\bseminar\b", 4),
              (r"\bwebinar\b", 4), (r"\bceremony\b", 3), (r"\bsymposium\b", 4)],
    "Training": [(r"\btraining (?:took place|needs assessment|session)", 5),
                 (r"\bshort course\b", 5), (r"\bcontinuous professional development\b", 5),
                 (r"\bparticipants (?:learned|acquire)", 3)],
    "Appointment": [(r"\bhas been (?:chosen|appointed|named)\b", 5),
                    (r"\bappointed as\b", 5), (r"\bto (?:chair|head) the\b", 4),
                    (r"\binauguration of\b", 3)],
    "Infrastructure": [(r"\bgroundbreaking\b", 6), (r"\bbreaks ground\b", 6),
                       (r"\bnew building\b", 4), (r"\bsquare-?foot\b", 4)],
    "Opinion": [(r"\bwe need to understand\b", 3), (r"\bthe irony is\b", 3),
                (r"\byou see,\b", 3), (r"\bin my (?:view|opinion)\b", 4)],
    "Launch": [(r"\bofficially launch", 5), (r"\blaunched (?:their|its) startup\b", 6),
               (r"\bopened its doors\b", 4)],
    "Student Story": [(r"\bsoon to be graduate\b", 5), (r"\bwhen \w+ entered\b", 3),
                      (r"\bas (?:she|he) graduates\b", 4), (r"\bmedical student\b", 2)],
}

# Entities that ARE the department (centres/institutes with no sub-department)
ENTITY_IS_DEPARTMENT = re.compile(
    r"^(Centre|Center|Institute|Office|Networks?) ", re.I)

DEPT_PHRASE_RE = re.compile(
    r"\b(?:department|dept\.?|division|section|clinical stream)\s+of\s+"
    r"([A-Za-z][A-Za-z&/,'\- ]{2,60}?)"
    r"(?=[,.;:)]|\s+(?:at|in|and the|AKU|AKUH|MC\b)|$)", re.I)

UNKNOWN = "UNKNOWN"

# ------------------------------------------------------------------ helpers

TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<script\b.*?</script>", re.S | re.I)


def unesc(s):
    return html.unescape(html.unescape(s or "")).strip()


def to_text(raw):
    s = SCRIPT_RE.sub(" ", raw or "")
    s = re.sub(r"<br\s*/?>|</(p|div|h[1-6]|li)>", "\n", s, flags=re.I)
    s = unesc(TAG_RE.sub("", s)).replace("\u00a0", " ")
    return re.sub(r"[ \t]+", " ", s)


def lk(v, f="Title"):
    if not isinstance(v, dict) or v.get("Id") in (-1, None):
        return ""
    return unesc(v.get(f))


def match_department(text):
    """Longest-alias-first so 'postgraduate medical education' beats 'medical education'."""
    low = text.lower()
    hits = []
    for canon, aliases in DEPARTMENTS.items():
        for a in aliases:
            if a in low:
                hits.append((len(a), canon))
                break
    return sorted(hits, reverse=True)[0][1] if hits else ""


def resolve_type(text, title, tags):
    blob = f"{title}\n{title}\n{' '.join(tags)}\n{text}"  # title weighted 2x
    scores = Counter()
    for t, rules in TYPE_RULES.items():
        for pat, wt in rules:
            n = len(re.findall(pat, blob, re.I))
            if n:
                scores[t] += wt * min(n, 3)
    if not scores:
        return UNKNOWN, "", ""
    top = scores.most_common(3)
    best, score = top[0]
    src = "strong" if score >= 6 else "weak"
    return best, src, "; ".join(f"{k}:{v}" for k, v in top)


def w(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        cw = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        cw.writeheader()
        cw.writerows(rows)
    print(f"  {len(rows):>5}  {os.path.basename(path)}")


# ------------------------------------------------------------------ main

def main(indir, outdir):
    os.makedirs(outdir, exist_ok=True)
    files = sorted(glob.glob(os.path.join(indir, "*.json")))
    if not files:
        sys.exit(f"no .json in {indir}")

    rows, review, unresolved_dept = [], [], Counter()
    cov = Counter()

    for path in files:
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            print(f"!! {os.path.basename(path)}: {e}", file=sys.stderr)
            continue

        nid = d.get("Id") or d.get("ID")
        title = unesc(d.get("Title"))
        text = to_text(d.get("NewsContent"))
        summary = unesc(d.get("NewsSummary"))
        tags = [unesc(t.get("Label")) for t in (d.get("Tags") or []) if t.get("Label")]
        reasons = []

        # ---------- CITY (the anchor / backtrack signal)
        city = lk(d.get("City"))
        city_id = (d.get("City") or {}).get("Id", "")

        # ---------- ENTITY
        prim = lk(d.get("Entity"))
        addl = [lk(a) for a in (d.get("AdditionalEntity") or []) if lk(a)]
        addl = [a for a in addl if a != prim]
        if prim and prim not in ("Global", "Research"):
            entity, ent_src = prim, "Entity"
        elif addl:
            entity, ent_src = addl[0], "AdditionalEntity[0]"
            reasons.append(f"entity fell back from '{prim}' to additional")
        else:
            entity, ent_src = prim or UNKNOWN, "Entity(catch-all)" if prim else "none"
            if entity in (UNKNOWN, "Global"):
                reasons.append("no specific entity")

        # ---------- REGION  (city first, entity suffix as the check)
        region = CITY_TO_REGION.get(city, "")
        reg_src = "City" if region else ""
        if not region:
            reasons.append(f"city '{city}' not in CITY_TO_REGION")
            region = UNKNOWN

        ent_region = ""
        m = re.search(r",\s*(Pakistan|East Africa|Kenya|Uganda|Tanzania)\s*$", entity)
        if m:
            ent_region = m.group(1)
        conflict = False
        if ent_region and region not in (UNKNOWN, "Global"):
            ok = region in REGION_GROUPS.get(ent_region, {ent_region})
            if not ok:
                conflict = True
                reasons.append(f"CONFLICT city={city}({region}) vs entity={ent_region}")

        scope = "global" if d.get("GlobalNews") else "local"

        # ---------- DEPARTMENT
        dept, dept_src, dept_raw = "", "", ""
        for t in tags:                                    # 1. tag matches vocab
            c = match_department(t)
            if c:
                dept, dept_src = c, f"tag:{t}"
                break
        if not dept:                                      # 2. "department of X" in body
            for mm in DEPT_PHRASE_RE.finditer(f"{summary}\n{text}"):
                raw = re.sub(r"\s+", " ", mm.group(1)).strip(" ,.")
                dept_raw = raw
                c = match_department(raw)
                if c:
                    dept, dept_src = c, "content:department-of"
                    break
                unresolved_dept[raw.lower()] += 1
        if not dept and ENTITY_IS_DEPARTMENT.match(entity):  # 3. entity IS the dept
            dept, dept_src = entity, "entity-is-department"
        if not dept:                                      # 4. loose scan of tags+title
            c = match_department(" ".join(tags) + " " + title)
            if c:
                dept, dept_src = c, "loose:tags+title"
        if not dept:
            dept, dept_src = UNKNOWN, "none"
            reasons.append("department unresolved")

        # ---------- TYPE
        ntype, type_src, type_scores = resolve_type(text, title, tags)
        if ntype == UNKNOWN:
            reasons.append("type unresolved")
        elif type_src == "weak":
            reasons.append(f"type '{ntype}' weak signal")

        # ---------- assemble
        path_str = " > ".join([region, entity, dept, ntype])
        unknowns = sum(x == UNKNOWN for x in (region, entity, dept, ntype))
        conf = "low" if conflict or unknowns >= 2 else "medium" if unknowns == 1 \
            or type_src == "weak" else "high"

        row = {
            "news_id": nid,
            "sequence_number": d.get("SequenceNumber") or "",
            "published_date": (d.get("ScheduleStartDate") or d.get("Created") or "")[:10],
            "title": title,
            "region": region,
            "region_source": reg_src,
            "city": city,
            "city_id": city_id,
            "entity": entity,
            "entity_source": ent_src,
            "entity_region": ent_region,
            "entities_additional": " | ".join(addl),
            "department": dept,
            "department_source": dept_src,
            "department_raw": dept_raw,
            "news_type": ntype,
            "type_source": type_src,
            "type_scores": type_scores,
            "scope": scope,
            "status": d.get("IsPulished") or "",
            "tags": " | ".join(tags),
            "path": path_str,
            "confidence": conf,
            "region_conflict": str(conflict),
            "needs_review": str(bool(reasons)),
            "review_reasons": "; ".join(reasons),
        }
        rows.append(row)
        if reasons:
            review.append(row)
        for k in ("region", "entity", "department", "news_type"):
            if row[k] != UNKNOWN:
                cov[k] += 1

    rows.sort(key=lambda r: r["published_date"], reverse=True)
    hdr = list(rows[0].keys())
    w(os.path.join(outdir, "taxonomy.csv"), hdr, rows)
    w(os.path.join(outdir, "_needs_review.csv"), hdr, review)
    w(os.path.join(outdir, "_unresolved_departments.csv"),
      ["raw_phrase", "count"],
      [{"raw_phrase": k, "count": v} for k, v in unresolved_dept.most_common()])

    paths = Counter(r["path"] for r in rows)
    w(os.path.join(outdir, "_paths.csv"), ["path", "item_count"],
      [{"path": p, "item_count": c} for p, c in paths.most_common()])

    n = len(rows)
    with open(os.path.join(outdir, "_coverage.txt"), "w", encoding="utf-8") as f:
        f.write(f"items: {n}\n\nRESOLVED\n")
        for k in ("region", "entity", "department", "news_type"):
            f.write(f"  {cov[k]:>5}/{n}  {100*cov[k]//n:>3}%  {k}\n")
        f.write("\nCONFIDENCE\n")
        for k, c in Counter(r["confidence"] for r in rows).most_common():
            f.write(f"  {c:>5}  {k}\n")
        f.write(f"\nneeds review: {len(review)}/{n}\n")
        f.write(f"distinct paths: {len(paths)}\n")
        f.write("\nTYPE DISTRIBUTION\n")
        for k, c in Counter(r["news_type"] for r in rows).most_common():
            f.write(f"  {c:>5}  {k}\n")
        f.write("\nDEPARTMENT DISTRIBUTION\n")
        for k, c in Counter(r["department"] for r in rows).most_common():
            f.write(f"  {c:>5}  {k}\n")
    print(f"\ncoverage -> {os.path.join(outdir, '_coverage.txt')}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
