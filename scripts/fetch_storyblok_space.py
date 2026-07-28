#!/usr/bin/env python3
"""
fetch_storyblok_space.py — snapshot the live Storyblok space. READ ONLY.

Pulls the component (block) library, component groups, presets, datasources,
internal tags, asset folders, the story tree, and any field-type plugins, so the
migration can be written against the real schema instead of a guess.

Issues GET requests only. Nothing is created, updated or deleted.

Credentials come from config/storyblok.json (gitignored) or the environment:
    STORYBLOK_SPACE_ID, STORYBLOK_MANAGEMENT_TOKEN, STORYBLOK_REGION

Usage:
    python scripts/fetch_storyblok_space.py [output_dir]

Default output: storyblok_space/ at the repo root. One JSON per resource plus
_summary.json. The token is never written to any output file.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import requests
except ImportError:
    sys.exit("pip install -r requirements.txt")

from storyblok_config import load_config, management_api_base

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# resource -> (path suffix, key holding the list, paginated?)
RESOURCES = [
    ("components", "components", "components", True),
    ("component_groups", "component_groups", "component_groups", False),
    ("presets", "presets", "presets", False),
    ("datasources", "datasources", "datasources", True),
    ("internal_tags", "internal_tags", "internal_tags", True),
    ("asset_folders", "asset_folders", "asset_folders", False),
    ("assets", "assets", "assets", True),
    ("stories", "stories", "stories", True),
    ("workflow_stages", "workflow_stages", "workflow_stages", False),
]
# Deliberately not fetched: /collaborators returns real_email, alt_email and
# names for every space member. It is personal data, it is useless to the
# migration, and this snapshot is committed.

# Keys stripped from every saved payload. Storyblok returns a per-story
# preview_token, which is a live credential.
SECRET_KEYS = {"first_token", "preview_token", "api_key", "management_token",
               "password", "real_email", "alt_email"}


def scrub(obj):
    """Recursively drop credential and personal-data keys before saving."""
    if isinstance(obj, list):
        return [scrub(o) for o in obj]
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items() if k not in SECRET_KEYS}
    return obj


def session(token):
    s = requests.Session()
    # Management API takes the token directly, with no Bearer prefix.
    s.headers.update({"Authorization": token,
                      "Content-Type": "application/json"})
    return s


def get(s, url, params=None, tries=4):
    for attempt in range(tries):
        r = s.get(url, params=params, timeout=60)
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 2 * (attempt + 1)))
            print(f"      rate limited, waiting {wait}s")
            time.sleep(wait)
            continue
        return r
    return r


def fetch_list(s, api, suffix, key, paginated):
    url = f"{api}/{suffix}"
    if not paginated:
        r = get(s, url)
        if r.status_code != 200:
            return None, f"{r.status_code} {r.text[:160]}"
        return r.json().get(key, r.json()), None

    out, page = [], 1
    while True:
        r = get(s, url, {"per_page": 100, "page": page})
        if r.status_code != 200:
            if page == 1:
                return None, f"{r.status_code} {r.text[:160]}"
            break
        chunk = r.json().get(key) or []
        out.extend(chunk)
        total = int(r.headers.get("Total", len(out)))
        if len(out) >= total or not chunk:
            break
        page += 1
    return out, None


def main(outdir=None):
    cfg = load_config()
    token, space = cfg.get("management_token"), cfg.get("space_id")
    if not token or not space or "YOUR_" in str(token):
        sys.exit("no credentials — set config/storyblok.json or "
                 "STORYBLOK_MANAGEMENT_TOKEN / STORYBLOK_SPACE_ID")

    outdir = outdir or os.path.join(BASE, "storyblok_space")
    os.makedirs(outdir, exist_ok=True)
    api = f"{management_api_base(cfg)}/spaces/{space}"
    s = session(token)

    def save(name, obj):
        obj = scrub(obj)
        p = os.path.join(outdir, f"{name}.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
        n = len(obj) if isinstance(obj, list) else 1
        print(f"    saved {name}.json  ({n})")
        return n

    summary = {"space_id": space, "region": cfg.get("region"), "counts": {},
               "errors": {}}

    print(f"space {space} ({cfg.get('region')})  {management_api_base(cfg)}\n")

    # ---- space itself
    r = get(s, api)
    if r.status_code != 200:
        sys.exit(f"cannot read space: {r.status_code} {r.text[:300]}")
    sp = r.json().get("space", {})
    sp.pop("owner", None)          # owner carries the account holder's email
    save("space", sp)              # save() scrubs credentials recursively
    summary["space_name"] = sp.get("name")
    summary["space_plan"] = sp.get("plan")
    print(f"    name: {sp.get('name')}   plan: {sp.get('plan')}")

    # ---- the resources
    for name, suffix, key, paginated in RESOURCES:
        print(f"\n  {name}")
        data, err = fetch_list(s, api, suffix, key, paginated)
        if err:
            print(f"    !! {err}")
            summary["errors"][name] = err
            continue
        summary["counts"][name] = save(name, data)

    # ---- field-type plugins: space-scoped first, then account-scoped
    print("\n  field_types (field plugins)")
    root = management_api_base(cfg)
    for label, url in (("space", f"{api}/field_types"),
                       ("account", f"{root}/field_types")):
        r = get(s, url)
        if r.status_code == 200:
            ft = r.json().get("field_types", r.json())
            for f in (ft if isinstance(ft, list) else []):
                f.pop("body", None)          # plugin source can be huge
            summary["counts"][f"field_types_{label}"] = save(
                f"field_types_{label}", ft)
        else:
            print(f"    ({label}) {r.status_code} — not available with this token")
            summary["errors"][f"field_types_{label}"] = r.status_code

    # ---- full content for every story (list endpoint omits content)
    stories_path = os.path.join(outdir, "stories.json")
    if os.path.exists(stories_path):
        with open(stories_path, encoding="utf-8") as f:
            stories = json.load(f)
        print(f"\n  story content ({len(stories)} stories)")
        full, failed = [], []
        for st in stories:
            r = get(s, f"{api}/stories/{st['id']}")
            if r.status_code == 200:
                full.append(r.json().get("story"))
            else:
                failed.append((st.get("id"), st.get("full_slug"),
                               r.status_code))
        summary["counts"]["stories_full"] = save("stories_full", full)
        if failed:
            print(f"    !! {len(failed)} could not be read")
            summary["errors"]["stories_full"] = failed

    with open(os.path.join(outdir, "_summary.json"), "w",
              encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 66}")
    for k, v in summary["counts"].items():
        print(f"  {v:>6}  {k}")
    if summary["errors"]:
        print("\n  not retrieved:")
        for k, v in summary["errors"].items():
            print(f"    {k}: {v}")
    print(f"\n  -> {outdir}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
