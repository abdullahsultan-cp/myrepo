#!/usr/bin/env python3
"""
list_components.py — every component (block) defined in the Storyblok space,
as a CSV. READ ONLY.

Calls GET /v1/spaces/{space}/components once and writes one row per component:
name, display name, group, whether it can be a root/nestable block, how many
fields it has, and the field names themselves. Add --fields for a second CSV
with one row per (component, field) so a field's type and required-ness are
visible too.

Credentials come from config/storyblok.json (gitignored) or the environment:
    STORYBLOK_SPACE_ID, STORYBLOK_MANAGEMENT_TOKEN, STORYBLOK_REGION

Usage:
    python pipeline/migrate/review/list_components.py
    python pipeline/migrate/review/list_components.py --fields
    python pipeline/migrate/review/list_components.py --out somewhere/components.csv
"""

import argparse
import csv
import os
import sys

try:
    import requests
except ImportError:
    sys.exit("pip install -r requirements.txt")

# The pipeline root is found by walking up for _bootstrap.py rather than by
# counting dirname() calls -- see audit_assets.py in this same folder for why
# a fixed count breaks depending on where a script sits.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_d = os.path.dirname(os.path.abspath(__file__))
while _d != os.path.dirname(_d):
    if os.path.exists(os.path.join(_d, "_bootstrap.py")):
        sys.path.insert(0, _d)
        break
    _d = os.path.dirname(_d)
import _bootstrap

_bootstrap.ensure()

from paths_root import ROOT
from storyblok_config import load_config, management_api_base

DEFAULT_OUT = os.path.join(ROOT, "storyblok_space", "components.csv")
DEFAULT_FIELDS_OUT = os.path.join(ROOT, "storyblok_space", "component_fields.csv")


def fetch_components(cfg):
    token, space = cfg.get("management_token"), cfg.get("space_id")
    if not token or not space or "YOUR_" in str(token):
        sys.exit("no credentials — set config/storyblok.json or "
                 "STORYBLOK_MANAGEMENT_TOKEN / STORYBLOK_SPACE_ID")

    api = f"{management_api_base(cfg)}/spaces/{space}/components"
    s = requests.Session()
    s.headers.update({"Authorization": token, "Content-Type": "application/json"})

    r = s.get(api, timeout=60)
    if r.status_code != 200:
        sys.exit(f"cannot read components: {r.status_code} {r.text[:300]}")
    return r.json().get("components", [])


def group_names(components):
    """component_group_uuid -> readable name, from the groups endpoint."""
    cfg = load_config()
    token, space = cfg.get("management_token"), cfg.get("space_id")
    api = f"{management_api_base(cfg)}/spaces/{space}/component_groups"
    s = requests.Session()
    s.headers.update({"Authorization": token, "Content-Type": "application/json"})
    r = s.get(api, timeout=60)
    if r.status_code != 200:
        return {}
    return {g["uuid"]: g["name"] for g in r.json().get("component_groups", [])}


def write_components_csv(components, groups, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "display_name", "group", "is_root",
                    "is_nestable", "field_count", "fields",
                    "created_at", "updated_at"])
        for c in sorted(components, key=lambda x: x.get("name", "")):
            schema = c.get("schema") or {}
            w.writerow([
                c.get("id"),
                c.get("name"),
                c.get("display_name") or "",
                groups.get(c.get("component_group_uuid"), ""),
                c.get("is_root", False),
                c.get("is_nestable", False),
                len(schema),
                ", ".join(sorted(schema.keys())),
                c.get("created_at", ""),
                c.get("updated_at", ""),
            ])


def write_fields_csv(components, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["component", "field", "type", "required", "default_value"])
        for c in sorted(components, key=lambda x: x.get("name", "")):
            schema = c.get("schema") or {}
            for field_name, field_def in sorted(schema.items()):
                w.writerow([
                    c.get("name"),
                    field_name,
                    field_def.get("type", ""),
                    field_def.get("required", False),
                    field_def.get("default_value", ""),
                ])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help=f"where to write the components CSV (default {DEFAULT_OUT})")
    ap.add_argument("--fields", action="store_true",
                    help="also write a second CSV, one row per (component, field)")
    ap.add_argument("--fields-out", default=DEFAULT_FIELDS_OUT)
    args = ap.parse_args()

    cfg = load_config()
    components = fetch_components(cfg)
    groups = group_names(components)

    write_components_csv(components, groups, args.out)
    print(f"  {len(components)} components -> {args.out}")

    if args.fields:
        write_fields_csv(components, args.fields_out)
        total_fields = sum(len(c.get("schema") or {}) for c in components)
        print(f"  {total_fields} fields -> {args.fields_out}")


if __name__ == "__main__":
    main()
