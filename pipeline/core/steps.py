"""steps.py — the pipeline's step list, as data.

The 22 steps used to be a Python literal inside `run_pipeline.py`. That made the
file the one place every content type had to edit to add or reorder a step,
which is precisely the file two people working on two types would both touch.
Now the shared default lives in `config/steps.json` and a type adds its own in
its own profile, so the two never meet in a diff.

    config/steps.json              the shared default, 22 steps
    config/types/<type>.json       "extra_steps": [...]  and "skip_steps": [...]
    <Type>-Pipeline/pipeline/      a file of the same name overrides a step

## Why paths are tokens

A step declares what it needs and what it writes, and both are per content type:
`dir:stories` is `News-Pipeline/data/stories` or `Blogs-Pipeline/data/stories`
depending on `--type`. Writing the resolved path in the JSON would tie the shared
file to one type, so the JSON holds a token and this module resolves it.

    dir:raw  dir:cleaned  dir:normalized  dir:richtext
    dir:richtext_enhanced  dir:stories  dir:media
    file:metadata_csv
    report:<name>.json          -> <Type>-Pipeline/data/<name>.json
    viewer:constants            -> storyblok-viewer/src/constants
    viewer:<sub>/index.ts       -> a file under it
    abs:<path>                  an escape hatch; avoid

An unknown token raises. A silent empty path would make a step's prerequisite
check pass when it should fail, which is the failure mode this whole file is
trying to avoid.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths_root import ROOT, P

STEPS_JSON = os.path.join(ROOT, "config", "steps.json")
VIEWER = os.path.join(ROOT, "storyblok-viewer", "src", "constants")

_DIRS = {
    "raw": "RAW", "cleaned": "CLEANED", "normalized": "NORMALIZED",
    "richtext": "RICHTEXT", "richtext_enhanced": "RICHTEXT_ENHANCED",
    "stories": "STORIES", "media": "MEDIA_DIR", "taxonomy": "TAXONOMY",
    "migrate": "MIGRATE", "backup": "BACKUP", "data": "DATA",
}


def resolve(token):
    """One token -> an absolute path, under the selected content type."""
    if not isinstance(token, str) or ":" not in token:
        raise ValueError(
            f"step path {token!r} is not a token. Use dir:/report:/file:/viewer: "
            f"— see pipeline/core/steps.py")
    kind, _, rest = token.partition(":")
    if kind == "dir":
        prop = _DIRS.get(rest)
        if not prop:
            raise ValueError(f"unknown dir token {token!r}; known: "
                             f"{', '.join(sorted(_DIRS))}")
        return getattr(P, prop)
    if kind == "report":
        return P.report(rest)
    if kind == "file":
        if rest == "metadata_csv":
            return P.METADATA_CSV
        if rest == "source":
            return P.SOURCE_JSON
        raise ValueError(f"unknown file token {token!r}")
    if kind == "viewer":
        return VIEWER if rest == "constants" else os.path.join(VIEWER, *rest.split("/"))
    if kind == "abs":
        return rest
    raise ValueError(f"unknown token kind {kind!r} in {token!r}")


def _shared():
    with open(STEPS_JSON, encoding="utf-8") as f:
        return json.load(f)["steps"]


def _materialise(step):
    """A declared step -> the shape run_pipeline has always used."""
    out = dict(step)
    out["requires"] = [resolve(t) for t in step.get("requires", [])]
    out["produces"] = [resolve(t) for t in step.get("produces", [])]
    return out


def for_type(content_type=None):
    """The ordered steps for one content type.

    Shared defaults, minus what the profile skips, plus what it adds. A type
    that declares nothing gets exactly the shared list, which is why news --
    3,606 stories already migrated -- is unaffected by any of this.
    """
    if content_type:
        P.use(content_type)
    spec = P.spec
    skip = set(spec.get("skip_steps") or [])
    steps = [s for s in _shared() if s["name"] not in skip]

    by_name = {s["name"]: i for i, s in enumerate(steps)}
    for extra in (spec.get("extra_steps") or []):
        if "after" in extra:
            anchor = extra.pop("after")
            at = by_name.get(anchor)
            if at is None:
                raise SystemExit(
                    f"{P.type}: extra step {extra.get('name')!r} says after "
                    f"{anchor!r}, which is not a step. Steps: "
                    + ", ".join(s["name"] for s in steps))
            steps.insert(at + 1, extra)
        else:
            steps.append(extra)
        by_name = {s["name"]: i for i, s in enumerate(steps)}

    return [_materialise(s) for s in steps]


def for_type_unfiltered(content_type=None):
    """Every shared step, before any profile skip or addition."""
    if content_type:
        P.use(content_type)
    return [_materialise(s) for s in _shared()]


def names(content_type=None):
    return [s["name"] for s in for_type(content_type)]


if __name__ == "__main__":
    from paths_root import TYPES
    for t in (sys.argv[1:] or sorted(TYPES)):
        ns = names(t)
        print(f"\n  {t}: {len(ns)} steps")
        for n in ns:
            print(f"    {n}")
