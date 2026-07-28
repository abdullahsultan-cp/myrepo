#!/usr/bin/env python3
"""
fetch_sp_lookups.py — pull the AUTHORITATIVE lookup lists straight from SharePoint.

Instead of guessing list names, it introspects the News list's fields to find which
list each lookup column actually points at (LookupList GUID), then dumps every row.
This is how you get the full City list, full Entities list, and the Category list
that your export never $expand'ed.

Usage:
    export SP_COOKIE='FedAuth=...; rtFa=...'          # or: export SP_TOKEN='eyJ0...'
    python fetch_sp_lookups.py https://www.aku.edu ./sp_lookups

Options:
    --list-guid   News list GUID (default: the one in your editLink)
    --insecure    skip TLS verify (on-prem self-signed)

Outputs:
    _fields.csv            every column on the News list: type, and target list for lookups
    lookup_<Field>.csv     Id,Title for each lookup target (City, Entity, Category, ...)
    _termset_<Field>.csv   term-store terms for taxonomy columns (Tags), if reachable
"""

import argparse
import csv
import os
import re
import sys
import xml.etree.ElementTree as ET

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

NEWS_LIST_GUID = "c8995003-4c86-4b76-8e89-00e8688c03d1"


def session(insecure):
    s = requests.Session()
    s.verify = not insecure
    s.headers["Accept"] = "application/json;odata=nometadata"
    cookie, token = os.environ.get("SP_COOKIE"), os.environ.get("SP_TOKEN")
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    elif cookie:
        s.headers["Cookie"] = cookie
    else:
        print("!! no SP_COOKIE or SP_TOKEN set — anonymous, will likely 403",
              file=sys.stderr)
    return s


def get_all(s, url):
    """Follow SharePoint paging until exhausted."""
    out = []
    while url:
        r = s.get(url, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"{r.status_code} {url}\n{r.text[:400]}")
        j = r.json()
        out.extend(j.get("value", j.get("d", {}).get("results", [])))
        url = j.get("odata.nextLink") or j.get("@odata.nextLink") \
            or j.get("d", {}).get("__next")
    return out


def w(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        cw = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        cw.writeheader()
        cw.writerows(rows)
    print(f"  {len(rows):>5}  {os.path.basename(path)}")


def termset_id(schema_xml):
    """Pull TermSetId out of a taxonomy field's SchemaXml."""
    if not schema_xml:
        return None
    m = re.search(r"TermSetId.{0,40}?([0-9a-fA-F-]{36})", schema_xml, re.S)
    if m:
        return m.group(1)
    try:  # properly, it's a Customization/ArrayOfProperty structure
        root = ET.fromstring(schema_xml)
        for p in root.iter():
            if (p.findtext("Name") or "") == "TermSetId":
                return (p.findtext("Value") or "").strip()
    except ET.ParseError:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("site", help="e.g. https://www.aku.edu  (or /sites/xyz subsite)")
    ap.add_argument("outdir")
    ap.add_argument("--list-guid", default=NEWS_LIST_GUID)
    ap.add_argument("--insecure", action="store_true")
    a = ap.parse_args()

    site = a.site.rstrip("/")
    api = f"{site}/_api/web"
    os.makedirs(a.outdir, exist_ok=True)
    s = session(a.insecure)

    # 1. every column on the News list, with each lookup's target list GUID
    fields = get_all(s, f"{api}/lists(guid'{a.list_guid}')/fields"
                          "?$select=Title,InternalName,TypeAsString,LookupList,"
                          "LookupField,AllowMultipleValues,Hidden,SchemaXml"
                          "&$filter=Hidden eq false&$top=500")
    w(os.path.join(a.outdir, "_fields.csv"),
      ["InternalName", "Title", "TypeAsString", "AllowMultipleValues",
       "LookupList", "LookupField"],
      sorted(fields, key=lambda f: f.get("InternalName", "")))

    # 2. dump each distinct lookup target list
    done = {}
    for f in fields:
        tgt = (f.get("LookupList") or "").strip("{}")
        if not tgt or not f.get("TypeAsString", "").startswith("Lookup"):
            continue
        name = f["InternalName"]
        if tgt in done:
            print(f"  (skip {name}: same list as {done[tgt]})")
            continue
        done[tgt] = name
        disp = f.get("LookupField") or "Title"
        try:
            meta = s.get(f"{api}/lists(guid'{tgt}')?$select=Title,ItemCount",
                         timeout=60).json()
            items = get_all(s, f"{api}/lists(guid'{tgt}')/items"
                                f"?$select=Id,{disp}&$top=5000")
            print(f"  {name} -> list '{meta.get('Title')}' "
                  f"({meta.get('ItemCount')} rows), display field '{disp}'")
            w(os.path.join(a.outdir, f"lookup_{name}.csv"),
              ["Id", "Title", "source_list", "source_list_guid"],
              [{"Id": i.get("Id"), "Title": i.get(disp),
                "source_list": meta.get("Title"), "source_list_guid": tgt}
               for i in items])
        except Exception as e:
            print(f"!! {name} ({tgt}): {e}", file=sys.stderr)

    # 3. taxonomy columns (Tags) — needs the term store, not a list
    for f in fields:
        if "Taxonomy" not in f.get("TypeAsString", ""):
            continue
        ts = termset_id(f.get("SchemaXml"))
        print(f"  taxonomy field {f['InternalName']} -> term set {ts}")
        if not ts:
            continue
        for ep in (f"{site}/_api/v2.1/termStore/sets/{ts}/terms?$top=1000",
                   f"{site}/_api/v2.1/termStore/sets/{ts}/children?$top=1000"):
            try:
                terms = get_all(s, ep)
                w(os.path.join(a.outdir, f"_termset_{f['InternalName']}.csv"),
                  ["id", "labels"],
                  [{"id": t.get("id"),
                    "labels": " | ".join(l.get("name", "")
                                         for l in t.get("labels", []))}
                   for t in terms])
                break
            except Exception as e:
                print(f"   .. {ep.rsplit('/', 1)[-1]}: {e}", file=sys.stderr)
        else:
            print("   !! term store REST unavailable — fall back to reading "
                  "TermGuid+Label straight from the item JSON (harvest_lookups.py)",
                  file=sys.stderr)

    print(f"\ndone -> {a.outdir}")


if __name__ == "__main__":
    main()
