#!/usr/bin/env python3
"""run_update.py — change stories that are already live, in place.

    python pipeline/migrate/update/run_update.py --list
    python pipeline/migrate/update/run_update.py category --type blogs
    python pipeline/migrate/update/run_update.py category --type blogs --apply

Migration is not one pass. The dev hands us a field after the stories are up;
a plugin's value format only becomes knowable once something in the space has
it filled; a component we worked around gets replaced by a real one. Every one
of those is the same job — **reach into stories that are already published and
change one thing, without disturbing anything else.**

News has been through this twice already: it went live using `iframe` for
Twitter embeds because nothing better existed, and the space now has a
`social_embed` component with a `twitter` variant that is meant to replace it.

Doing that by hand does not scale and doing it by re-upload is forbidden — a
new story id breaks every review link already shared and loses manual edits.
Hence this: one engine, and a small **plan** per job.

## The rules it enforces

**A plan may only touch the fields it declares.** `FIELDS` is a whitelist, and
a plan that returns anything else is a hard error, not a warning. This is the
whole safety model: the live content is read, only declared keys are replaced,
and everything else is written back exactly as it was found. An editor's manual
fix to a field you did not declare survives your update.

**Nothing is written without `--apply`.** The default run reads, computes and
prints a diff. Read it before you write.

**A backup is taken first.** Every story it is about to change is saved to
`<Type>-Pipeline/backup/updates/<job>-<n>.json.gz` before the first PUT.
Storyblok keeps no version history, so this file is the only way back.

**Stories are never created or deleted.** It PUTs existing ids. A story it
cannot match is reported and skipped.

## Writing a plan

A plan is one file in your own type's folder, so two people updating two types
never touch the same file:

    <Type>-Pipeline/pipeline/updates/<name>.py

    FIELDS = ["category"]          # the only keys patch() may return
    DESCRIPTION = "fill category once the plugin format is known"

    def patch(content, source, ctx):
        '''Return {field: new value}, or {} to leave this story alone.'''
        if content.get("category"):
            return {}                       # already set; do not churn it
        return {"category": ctx["categories"][source["Category_id"]]}

`content` is the story as it is live right now. `source` is the matching row
from your export, matched on `sharepoint_id`, or None. `ctx` is whatever
`setup()` returned, if the plan defines one — use it to load a lookup once
rather than per story.

Start from `pipeline/migrate/update/_template.py`.

## Body bloks

Patching a blok inside `body` is the same mechanism: declare `body`, walk it,
return the new list. `_template.py` shows the shape, and `helpers.walk_bloks`
saves writing the recursion again.
"""

import argparse
import glob
import gzip
import importlib.util
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
_up = HERE
while _up != os.path.dirname(_up) and not os.path.exists(
        os.path.join(_up, "_bootstrap.py")):
    _up = os.path.dirname(_up)
sys.path.insert(0, _up)
import _bootstrap

_bootstrap.ensure()

from paths_root import ROOT, P
from storyblok_config import load_config

# `migrate` is not on the bootstrap path — its folders are entry points that
# handle their own imports. The Storyblok client lives with the uploader and is
# not duplicated here: one retry policy, one throttle, one place to fix them.
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "upload"))
from upload import SB


def plans_dir(type_name):
    return os.path.join(ROOT, f"{type_name.capitalize()}-Pipeline",
                        "pipeline", "updates")


def find_plans(type_name):
    d = plans_dir(type_name)
    if not os.path.isdir(d):
        return {}
    return {os.path.basename(p)[:-3]: p
            for p in sorted(glob.glob(os.path.join(d, "*.py")))
            if not os.path.basename(p).startswith("_")}


def load_plan(path):
    spec = importlib.util.spec_from_file_location("update_plan", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "patch"):
        sys.exit(f"  {path} defines no patch(content, source, ctx)")
    fields = list(getattr(mod, "FIELDS", []))
    if not fields:
        sys.exit(f"  {path} declares no FIELDS. A plan that may change "
                 f"anything is a plan that will.")
    return mod, fields


def live_stories(sb, component):
    """Every story in the space using this component, paginated."""
    out, page = [], 1
    while True:
        r = sb.get("stories", params={"contain_component": component,
                                      "per_page": 100, "page": page})
        if r is None or r.status_code != 200:
            sys.exit(f"  listing stories failed: "
                     f"{getattr(r, 'status_code', 'no response')}")
        chunk = r.json().get("stories", [])
        out += chunk
        if len(chunk) < 100:
            return out
        page += 1


def candidates(sb, component, contains):
    """The stories worth reading in full.

    Every story has to be fetched individually to see its content, and news is
    3,610 of them — twenty minutes of reading to change 38. A plan that only
    cares about stories holding a particular component says so with
    `CONTAINS`, and the space does the narrowing: 43 reads instead of 3,610.

    Without CONTAINS every story of the type is read, which is correct and
    slow. Say so in the output rather than appearing to hang.
    """
    if not contains:
        return live_stories(sb, component)
    narrowed = live_stories(sb, contains)
    keep = {s["id"] for s in narrowed} & {s["id"] for s
                                          in live_stories(sb, component)}
    return [s for s in narrowed if s["id"] in keep]


def source_by_id():
    """{sharepoint id: export row}, whichever shape the export arrived in.

    Blogs is a bare list; news is the raw OData envelope with the rows under
    `value`. Both are the export as delivered and neither is going to be
    reshaped to suit this script.
    """
    if not os.path.exists(P.SOURCE_JSON):
        return {}
    with open(P.SOURCE_JSON, encoding="utf-8") as f:
        raw = json.load(f)
    rows = raw.get("value", []) if isinstance(raw, dict) else raw
    return {str(x.get("ID")): x for x in rows if isinstance(x, dict)}


def sb_id_to_sharepoint():
    """{storyblok story id: sharepoint id} from the tracking database.

    Needed because **a live news_article carries no sharepoint_id**. Blogs put
    one in the payload, news did not, so the only link back to the export is
    the `story` table. Returns {} if the database is unreachable — most jobs
    only rewrite what is already in the story and never look at `source`, and
    those must not be blocked by a database the blogs owner has no reason to
    have running.
    """
    try:
        sys.path.insert(0, os.path.dirname(HERE))
        import db
        with db.connect() as c:
            c.execute("SET search_path TO migration, public")
            return {str(sb): str(sp) for sp, sb in c.execute(
                "SELECT sharepoint_id, sb_story_id FROM story "
                "WHERE sb_story_id IS NOT NULL").fetchall()}
    except Exception as exc:
        print(f"  tracking database unavailable ({type(exc).__name__}); "
              f"`source` will be None unless the story carries a "
              f"sharepoint_id")
        return {}


def backup(rows, job):
    d = os.path.join(P.PIPELINE, "backup", "updates")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{job}-{len(rows)}.json.gz")
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    return path


def short(value, width=68):
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) \
        else value
    text = " ".join(text.split())
    return text[:width] + ("…" if len(text) > width else "")


def components_in(value):
    """Counted component names inside a blok list, at any depth."""
    seen = {}

    def visit(node):
        if isinstance(node, dict):
            name = node.get("component")
            if name:
                seen[name] = seen.get(name, 0) + 1
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return seen


def describe(field, old, new):
    """One readable line per changed field.

    A blok list dumped as JSON is thousands of characters of _uids and tells
    you nothing — the first dry run printed exactly that. What matters is
    which components appeared and which went away.
    """
    if isinstance(new, list) and (components_in(new) or components_in(old)):
        before, after = components_in(old), components_in(new)
        moved = []
        for name in sorted(set(before) | set(after)):
            delta = after.get(name, 0) - before.get(name, 0)
            if delta:
                moved.append(f"{name} {before.get(name, 0)}->{after.get(name, 0)}")
        return f"{field}: " + (", ".join(moved) if moved
                               else "same components, contents changed")
    return f"{field}: {short(old, 22)} -> {short(new, 26)}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("job", nargs="?", help="plan name, without .py")
    ap.add_argument("--type", default=os.environ.get("AKU_CONTENT_TYPE", "news"))
    ap.add_argument("--list", action="store_true", help="plans for this type")
    ap.add_argument("--apply", action="store_true", help="actually write")
    ap.add_argument("--limit", type=int, help="stop after N changed stories")
    ap.add_argument("--only", help="comma-separated sharepoint ids")
    a = ap.parse_args()

    P.use(a.type)
    plans = find_plans(a.type)
    if a.list or not a.job:
        print(f"  update plans for {a.type} "
              f"({os.path.relpath(plans_dir(a.type), ROOT)}):")
        if not plans:
            print("    none yet — copy pipeline/migrate/update/_template.py "
                  "into that folder")
        for name, path in plans.items():
            mod, _ = load_plan(path)
            print(f"    {name:<22}{getattr(mod, 'DESCRIPTION', '')[:60]}")
        return 0
    if a.job not in plans:
        sys.exit(f"  no plan '{a.job}' for {a.type}. "
                 f"Known: {', '.join(plans) or 'none'}")

    plan, fields = load_plan(plans[a.job])
    cfg = load_config()
    component = json.load(open(os.path.join(ROOT, "config", "types",
                                            f"{a.type}.json"),
                               encoding="utf-8"))["storyblok"]["component"]
    sb = SB(cfg)
    print(f"  job '{a.job}' on {a.type} — may set {fields}")
    print(f"  {'WRITING' if a.apply else 'dry run — nothing will be written'}")

    contains = getattr(plan, "CONTAINS", None)
    stories = candidates(sb, component, contains)
    print(f"  {len(stories)} candidate story/stories"
          + (f" — narrowed to those containing '{contains}'" if contains
             else f" using {component} (reading every one; this is slow)"))
    source = source_by_id()
    by_sb = sb_id_to_sharepoint() if source else {}
    ctx = plan.setup(source) if hasattr(plan, "setup") else {}
    only = {x.strip() for x in (a.only or "").split(",") if x.strip()}

    changes, skipped, unmatched = [], 0, 0
    for n, st in enumerate(stories, 1):
        if len(stories) > 200 and n % 100 == 0:
            print(f"    read {n}/{len(stories)}…")
        full = sb.get(f"stories/{st['id']}")
        if full is None or full.status_code != 200:
            print(f"    read failed for {st['id']}; skipping")
            continue
        story = full.json()["story"]
        content = story["content"]
        # blogs carry it in the payload; news does not, so fall back to the
        # tracking table keyed by the Storyblok id.
        sid = str(content.get("sharepoint_id")
                  or by_sb.get(str(story["id"])) or "")
        if only and sid not in only:
            continue
        src = source.get(sid)
        if src is None:
            unmatched += 1
        try:
            patch = plan.patch(content, src, ctx) or {}
        except Exception as exc:                       # a plan bug, not ours
            sys.exit(f"    plan raised on story {st['id']} "
                     f"(sharepoint {sid or '?'}): {type(exc).__name__}: {exc}")
        stray = [k for k in patch if k not in fields]
        if stray:
            sys.exit(f"    plan tried to set undeclared field(s) {stray} on "
                     f"story {st['id']}. Add them to FIELDS deliberately, or "
                     f"stop setting them.")
        patch = {k: v for k, v in patch.items() if content.get(k) != v}
        if not patch:
            skipped += 1
            continue
        changes.append((story, patch))
        print(f"    {sid or story['id']:<8}{story['full_slug'][:40]:<42}"
              + "; ".join(describe(k, content.get(k), v)
                          for k, v in patch.items()))
        if a.limit and len(changes) >= a.limit:
            print(f"    stopping at --limit {a.limit}")
            break

    print(f"\n  {len(changes)} would change, {skipped} already correct"
          + (f", {unmatched} live stories match no export row" if unmatched else ""))
    if not changes:
        return 0
    if not a.apply:
        print("  nothing written. Re-run with --apply when the diff looks right.")
        return 0

    path = backup([s for s, _ in changes], a.job)
    print(f"  backed up {len(changes)} story/stories -> "
          f"{os.path.relpath(path, ROOT)}")

    written = failed = 0
    log = []
    for story, patch in changes:
        body = {"story": {"content": {**story["content"], **patch}},
                "publish": 1}
        r = sb.put(f"stories/{story['id']}", body)
        ok = r is not None and r.status_code in (200, 201)
        written += ok
        failed += not ok
        log.append({"id": story["id"], "slug": story["full_slug"],
                    "patch": patch, "ok": ok,
                    "status": getattr(r, "status_code", None)})
        if not ok:
            print(f"    FAILED {story['full_slug'][:52]} "
                  f"-> {getattr(r, 'status_code', 'no response')}")
        time.sleep(0)
    rep = os.path.join(P.DATA, f"update_{a.job}_report.json")
    with open(rep, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"job": a.job, "type": a.type, "fields": fields,
                   "written": written, "failed": failed, "rows": log}, f,
                  ensure_ascii=False, indent=2)
    print(f"  written {written}, failed {failed}")
    print(f"  -> {os.path.relpath(rep, ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
