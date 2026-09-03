#!/usr/bin/env python3
"""push_to_storyblok.py — one real "Component Testing" story in the live
space, content type `page`, carrying every nestable component in the space
and every variant its `option` fields allow — so it can be opened in the
Storyblok visual editor and checked against the actual front end.

Why `page` and not `news_article`
    `news_article.body` is whitelisted to the ~14 bloks THIS PIPELINE builds
    (see pipeline/migrate/upload/build_payload.py) -- it will not accept a
    header, a carousel, a footer. `page.body` carries no whitelist at all
    (storyblok_space/components.json: page -> body -> component_whitelist =
    None), so it is the only root type that can legally hold every nestable
    component in one story.

Why some components are missing
    Seven components are root types (blog_article, entity_settings,
    event_article, global, news_article, page, programme) -- whole-page
    containers, not bloks a page can nest inside itself. They are listed by
    name in the story's own intro instead of embedded. Every other nestable
    component in the space (89 of them, plus `header`, which is unusually
    both root AND nestable) gets a real instance.

How a component's fields are filled
    Read straight from storyblok_space/components.json, generically, by
    field type -- text, textarea, number, boolean, asset, multiasset,
    multilink, richtext, option, and the four `custom` plugins actually used
    (spacing-field-plugin, storyblok-colorpicker, native-color-picker; the
    space's other three custom plugins -- featured/category/event-types/
    entities -- only ever appear on the root types this script excludes).
    Every asset field gets a real, already-uploaded space asset, cycled from
    a small pool -- nothing here depends on an upload step.

Variants
    The first `option`-type field on a component (its "variant axis" --
    usually named variant/type/layout/display_mode) gets one instance per
    value the schema allows. Everything else in that instance uses the
    schema's own default, or the first option, or a plain placeholder.

Nested bloks fields (footer.columns, header.nav_items, carousel.slides, ...)
    recurse into the first whitelisted child, capped at depth 3 -- deep
    enough to fully resolve every real chain in this space (the longest is
    header -> header_nav_item -> nav_dropdown_column -> nav_dropdown_link).

Idempotent: re-running finds the existing folder/story by slug and updates
it in place. Left as a DRAFT (--publish to publish instead).

Usage:
    python Testing/Component-Testing/push_to_storyblok.py           # dry run
    python Testing/Component-Testing/push_to_storyblok.py --apply   # writes
"""
import argparse
import hashlib
import itertools
import json
import os
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
sys.path.insert(0, os.path.join(ROOT, "pipeline", "core"))
import _bootstrap

_bootstrap.ensure()
from storyblok_config import load_config, management_api_base

COMPONENTS_JSON = os.path.join(ROOT, "storyblok_space", "components.json")
GROUPS_JSON = os.path.join(ROOT, "storyblok_space", "component_groups.json")

FOLDER_NAME, FOLDER_SLUG = "Testing", "testing"
STORY_NAME, STORY_SLUG = "Component Testing", "component-testing"

# Whole-page containers -- never nested inside another story's body.
ROOT_ONLY = {"blog_article", "entity_settings", "event_article", "global",
             "news_article", "page", "programme"}

MAX_DEPTH = 3
THROTTLE = 0.35


class SB:
    def __init__(self, cfg):
        self.api = f"{management_api_base(cfg)}/spaces/{cfg['space_id']}"
        self.s = requests.Session()
        self.s.headers.update({"Authorization": cfg["management_token"]})

    def _call(self, method, path, *, json_body=None, params=None, tries=5):
        url = f"{self.api}/{path}"
        last = None
        for attempt in range(tries):
            try:
                r = self.s.request(method, url, json=json_body,
                                   params=params, timeout=120)
            except requests.exceptions.RequestException as e:
                if attempt == tries - 1:
                    raise
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", 2 * (attempt + 1))))
                continue
            if r.status_code >= 500 and attempt < tries - 1:
                time.sleep(1.5 * (attempt + 1))
                last = r
                continue
            return r
        return last

    def get(self, path, **kw):
        return self._call("GET", path, **kw)

    def post(self, path, body):
        time.sleep(THROTTLE)
        return self._call("POST", path, json_body=body)

    def put(self, path, body):
        time.sleep(THROTTLE)
        return self._call("PUT", path, json_body=body)


# ---------------------------------------------------------------- assets

EMPTY_ASSET = {"id": None, "alt": "", "name": "", "focus": "", "title": "",
               "source": "", "filename": "", "copyright": "",
               "fieldtype": "asset", "meta_data": {}}


def asset(id_, filename):
    return dict(EMPTY_ASSET, id=id_, filename=filename)


# Real assets already in the live space -- the same ones the reference story
# News-Pipeline/data/migrate/demo/200437344487526.json uses.
ASSET_POOL = [
    asset(193045184543116, "https://a.storyblok.com/f/289824742951963/"
          "2000x1324/ae04c901e5/photo_29.jpg"),
    asset(203278829185041, "https://a.storyblok.com/f/289824742951963/"
          "366x427/10b4a15217/saman_barkat.png"),
    asset(202607823391189, "https://a.storyblok.com/f/289824742951963/"
          "1440x811/0305b10066/web-pattern.png"),
    asset(202908142091464, "https://a.storyblok.com/f/289824742951963/"
          "375x184/c65753b5c0/quote-backgroung.png"),
    asset(198002989109947, "https://a.storyblok.com/f/289824742951963/"
          "2560x1707/229e9b326a/instititue.png"),
    asset(197603671028814, "https://a.storyblok.com/f/289824742951963/"
          "91x113/000957a952/isqua.png"),
    asset(203258848010479, "https://a.storyblok.com/f/289824742951963/"
          "2463094/b298c53b1d/3405-richtext-25644d4383-wed_speakers.jpg"),
    asset(203258790072553, "https://a.storyblok.com/f/289824742951963/"
          "6926416/22a1c04449/3405-richtext-1a4c2d5e97-nakawa-1.JPG"),
]
_asset_cycle = itertools.cycle(ASSET_POOL)


def next_asset():
    return dict(next(_asset_cycle))


def empty_multilink(url=""):
    return {"id": "", "url": url, "linktype": "url" if url else "story",
            "fieldtype": "multilink", "cached_url": url}


_counter = itertools.count()


def uid(*parts):
    h = hashlib.md5(("|".join(str(p) for p in parts)
                     + str(next(_counter))).encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _box(top=None, left=None, right=None, bottom=None):
    return {"top": top, "left": left, "right": right, "bottom": bottom}


def spacing(*, mobile_x=20, desktop_x=80, mobile_mb=24, desktop_mb=56):
    return {"unit": "px",
            "mobile": {"margin": _box(bottom=mobile_mb),
                       "padding": _box(left=mobile_x, right=mobile_x)},
            "desktop": {"margin": _box(bottom=desktop_mb),
                        "padding": _box(left=desktop_x, right=desktop_x)}}


def doc(text):
    return {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


# ---------------------------------------------------------------- schema

def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_schema():
    data = load_json(COMPONENTS_JSON)
    return {c["name"]: c for c in data["components"]}


VARIANT_FIELD_PRIORITY = ("variant", "type", "layout", "display_mode",
                          "image_variant", "gallery_layout", "icon", "align")


def variant_axis(schema):
    """The field whose `option` values this component's instances should
    vary over, plus the ordered list of values. None if it has none."""
    option_fields = [(fn, f) for fn, f in schema.items()
                     if f.get("type") == "option" and f.get("options")]
    if not option_fields:
        return None, []
    by_name = {fn: (fn, f) for fn, f in option_fields}
    for name in VARIANT_FIELD_PRIORITY:
        if name in by_name:
            fn, f = by_name[name]
            return fn, [o["value"] for o in f["options"]]
    fn, f = option_fields[0]
    return fn, [o["value"] for o in f["options"]]


def default_scalar(fname, f, comp_name):
    t = f.get("type")
    if t == "text":
        return f"{comp_name} — {fname}"
    if t == "textarea":
        return f"Sample {fname} text for {comp_name}, generated for " \
               f"component testing."
    if t == "number":
        return ""
    if t == "boolean":
        dv = f.get("default_value")
        return bool(dv) if dv is not None else True
    if t == "option":
        dv = f.get("default_value")
        if dv:
            return dv
        opts = f.get("options") or []
        return opts[0]["value"] if opts else ""
    if t == "asset":
        return next_asset()
    if t == "multiasset":
        return [next_asset(), next_asset()]
    if t == "multilink":
        return empty_multilink("https://www.aku.edu")
    if t == "richtext":
        return doc(f"Sample {fname} richtext for {comp_name}.")
    return None


def build_custom(fname, f):
    ft = f.get("field_type")
    if ft == "spacing-field-plugin":
        return spacing()
    if ft == "storyblok-colorpicker":
        return {"_uid": uid("bgcolor"), "color": "",
                "plugin": "official-colorpicker"}
    if ft == "native-color-picker":
        return ""
    return None  # featured/category/event-types/entities-plugins: root-only


def build_instance(comp_name, schemas, *, depth=0,
                   override=None):
    """One content dict for `comp_name`. `override` = (field, value) to pin
    a single field (used to enumerate variants) instead of its default."""
    c = schemas[comp_name]
    schema = c.get("schema") or {}
    content = {"component": comp_name, "_uid": uid(comp_name, depth)}
    ov_field, ov_value = override or (None, None)
    for fn, f in schema.items():
        if fn == ov_field:
            content[fn] = ov_value
            continue
        t = f.get("type")
        if t == "bloks":
            wl = f.get("component_whitelist")
            if not wl or depth >= MAX_DEPTH or wl[0] not in schemas:
                content[fn] = []
            else:
                content[fn] = [build_instance(wl[0], schemas, depth=depth + 1)]
        elif t == "custom":
            v = build_custom(fn, f)
            if v is not None:
                content[fn] = v
        else:
            v = default_scalar(fn, f, comp_name)
            if v is not None:
                content[fn] = v
    return content


def instances_for(comp_name, schemas):
    """Every variant instance for one top-level component."""
    schema = schemas[comp_name].get("schema") or {}
    axis_field, values = variant_axis(schema)
    if not axis_field or len(values) < 2:
        return [build_instance(comp_name, schemas)]
    return [build_instance(comp_name, schemas, override=(axis_field, v))
            for v in values]


# ---------------------------------------------------------------- body

def heading_blok(text):
    return {"_uid": uid("heading", text), "component": "rich_text",
            "content": {"type": "doc", "content": [
                {"type": "heading", "attrs": {"level": 2},
                 "content": [{"type": "text", "text": text}]}]},
            "bg_pattern": dict(EMPTY_ASSET), "pattern_height": "",
            "pattern_mobile_height": "", "spacing": spacing(desktop_x=176)}


def intro_blok():
    excluded = ", ".join(sorted(ROOT_ONLY))
    text = (f"Every nestable component in the space, one instance per "
            f"schema variant, generated by "
            f"Testing/Component-Testing/push_to_storyblok.py from "
            f"storyblok_space/components.json. Not shown: the {len(ROOT_ONLY)} "
            f"root types, which are whole-page containers rather than "
            f"bloks a page can nest — {excluded}.")
    return {"_uid": uid("intro"), "component": "rich_text",
            "content": doc(text), "bg_pattern": dict(EMPTY_ASSET),
            "pattern_height": "", "pattern_mobile_height": "",
            "spacing": spacing(desktop_x=176)}


def build_body(schemas):
    groups = load_json(GROUPS_JSON)
    group_name = {g["uuid"]: g["name"] for g in groups}

    embeddable = sorted(
        n for n, c in schemas.items()
        if n not in ROOT_ONLY and (c.get("is_nestable") or c.get("is_root")))

    by_group = {}
    for n in embeddable:
        gname = group_name.get(schemas[n].get("component_group_uuid"),
                               "ungrouped")
        by_group.setdefault(gname, []).append(n)

    body = [intro_blok()]
    for gname in sorted(by_group):
        body.append(heading_blok(f"{gname} ({len(by_group[gname])})"))
        for comp_name in by_group[gname]:
            body.extend(instances_for(comp_name, schemas))
    return body


# ---------------------------------------------------------------- main

def find_story(sb, full_slug):
    r = sb.get("stories", params={"with_slug": full_slug, "per_page": 1})
    if r is not None and r.status_code == 200:
        for s in r.json().get("stories") or []:
            if s.get("full_slug") == full_slug:
                return s
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write to the live space; default is a dry run")
    ap.add_argument("--publish", action="store_true",
                    help="publish the story instead of leaving it a draft")
    args = ap.parse_args()

    schemas = load_schema()
    body = build_body(schemas)
    embeddable = {n for n, c in schemas.items()
                  if n not in ROOT_ONLY and (c.get("is_nestable")
                                             or c.get("is_root"))}
    comps_shown = {b["component"] for b in body}
    print(f"{len(body)} bloks total, {len(comps_shown)}/{len(embeddable)} "
          f"embeddable components present")
    missing = embeddable - comps_shown
    if missing:
        print(f"MISSING (bug): {sorted(missing)}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to "
              "create/update the folder and story in the live space.")
        return

    cfg = load_config()
    if not cfg.get("space_id") or not cfg.get("management_token"):
        sys.exit("config/storyblok.json is missing space_id or "
                 "management_token")
    print(f"space {cfg['space_id']} ({cfg['region']})")
    sb = SB(cfg)

    folder = find_story(sb, FOLDER_SLUG)
    if folder and folder.get("is_folder"):
        folder_id = folder["id"]
        print(f"folder exists  {FOLDER_SLUG}  (id {folder_id})")
    else:
        r = sb.post("stories", {"story": {
            "name": FOLDER_NAME, "slug": FOLDER_SLUG, "is_folder": True,
            "parent_id": 0, "content": {"component": "page"}}})
        if r.status_code not in (200, 201):
            sys.exit(f"cannot create folder: {r.status_code} {r.text[:300]}")
        folder_id = r.json()["story"]["id"]
        print(f"created folder {FOLDER_SLUG}  (id {folder_id})")

    content = {"component": "page", "_uid": uid("root"), "body": body}
    full_slug = f"{FOLDER_SLUG}/{STORY_SLUG}"
    existing = find_story(sb, full_slug)
    payload = {"story": {"name": STORY_NAME, "slug": STORY_SLUG,
                         "parent_id": folder_id, "content": content},
               "publish": 1 if args.publish else 0}

    if existing and not existing.get("is_folder"):
        r = sb.put(f"stories/{existing['id']}", payload)
        verb = "updated"
    else:
        r = sb.post("stories", payload)
        verb = "created"

    if r.status_code not in (200, 201):
        sys.exit(f"cannot {verb[:-1]} story: {r.status_code} {r.text[:800]}")

    story = r.json()["story"]
    editor = (f"https://app.storyblok.com/#/me/spaces/{cfg['space_id']}/"
             f"stories/0/0/{story['id']}")
    print(f"\n{verb} story  id={story['id']}  full_slug={story['full_slug']}")
    print(f"published: {bool(args.publish)}")
    print(f"editor: {editor}")


if __name__ == "__main__":
    main()
