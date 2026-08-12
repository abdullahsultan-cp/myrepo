#!/usr/bin/env python3
"""event_types.py — fill event_types from the SharePoint Tags column.

    python pipeline/migrate/update/run_update.py event_types --type events
    python pipeline/migrate/update/run_update.py event_types --type events --apply

**This plan cannot run until the vocabulary is known.** It reads a mapping file
and exits with instructions if that file is absent, rather than guessing --
a guess here is a guess repeated 2,710 times.

## What we have

`Tags` is the cleanest column in the export: **single-valued**, 16 distinct
values, one per event, reconciling exactly with the delivered `Tags.csv` -- no
value used that the lookup lacks, no lookup entry unused. Exactly one event of
the 2,710 has no tag.

    Course 575 · Workshop 383 · Talk 320 · Lecture 314 · Seminar 309
    Other 268 · Conference 197 · Webinar 111 · Open day 76 · Symposium 48
    Convocation 34 · Meeting 24 · Exhibition 18 · 40 years of AKU 13
    Book Launch 10 · Grand Rounds 9

## What we do not have, and why it cannot be derived

`event_types` is a `custom` field of type `event-types-plugin`, and its
`options` list in the component schema is **empty** -- the vocabulary lives in
the plugin, not in the space. `/field_types` returns **403** to a personal
access token, so it cannot be read that way either.

The one filled value seen anywhere in the space is `"conf-workshop"`, on
`events-detail/test`. That single slug reads as Conference AND Workshop merged,
which means the front-end vocabulary is probably **coarser** than SharePoint's
16 and the mapping is many-to-one. So it is not a rename, and cannot be
mechanically slugified.

There is now a second candidate: `event_article` gained a **`Tags`** field
(position 20) on 12 Aug -- a `generic-dropdown` backed by
`.../api/v1/event-tags/dropdown?isActive=true`, multiSelect, `labelKey: name`,
`valueKey: id`. If those names match the 16 above, that endpoint answers this
question without the dev, and this plan should target `Tags` instead of
`event_types`. Check the endpoint before assuming which field is the right one.

## The mapping file

    Events-Pipeline/data/event_types_map.json

    {
      "_comment": "SharePoint tag label -> the value event_types expects.",
      "Course":   "course",
      "Workshop": "conf-workshop",
      ...
    }

A label mapped to `null` is deliberately dropped and reported. A label missing
from the file is an error, not a silent skip -- an unmapped tag would otherwise
leave those events untyped with nothing to say so.
"""

import json
import os
import sys

FIELD = "event_types"           # or "Tags" — see the docstring
AS_LIST = True                  # the plugin is multi-value; the test page holds
                                # ["conf-workshop"], a one-element list

FIELDS = [FIELD]

DESCRIPTION = "Tags -> event_types; needs data/event_types_map.json first"

MAP_NAME = "event_types_map.json"


def setup(source):
    """Load the label -> value mapping once, and fail loudly if it is absent."""
    if not source:
        # Nothing to type, so nothing to fail about. The engine always passes a
        # populated source; tests/test_update_plans.py calls setup({}) on every
        # plan in the repo, and a plan that exits during discovery fails the
        # shared suite -- and the pre-push hook -- for everyone.
        return {"map": {}}
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(os.path.dirname(here), "..", "data", MAP_NAME)
    path = os.path.normpath(path)
    if not os.path.exists(path):
        sys.exit(
            f"\n  {MAP_NAME} does not exist yet.\n\n"
            f"  event_types is a custom plugin and its vocabulary is not in the\n"
            f"  space -- /field_types returns 403 to a personal token. Ask the dev\n"
            f"  for the list of values, or read the Tags dropdown endpoint, then\n"
            f"  write the mapping to:\n\n"
            f"      {path}\n\n"
            f"  One entry per SharePoint tag label. There are 16. Map a label to\n"
            f"  null to drop it deliberately.\n")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    mapping = {k: v for k, v in raw.items() if not k.startswith("_")}

    # Every label the export actually uses must be accounted for. Catching this
    # once in setup beats discovering it 2,710 patch() calls later.
    used = {(r.get("Tags") or "").strip()
            for r in (source or {}).values() if (r.get("Tags") or "").strip()}
    missing = sorted(used - set(mapping))
    if missing:
        sys.exit(f"\n  {MAP_NAME} has no entry for: {missing}\n"
                 f"  Add them, or map to null to drop them deliberately.\n")
    unused = sorted(set(mapping) - used)
    if unused:
        print(f"  note: mapped but never used by any event: {unused}")
    return {"map": mapping}


def patch(content, source, ctx):
    """Return {FIELD: value}, or {} to leave this story alone."""
    if source is None:
        # No export row -- for events that means the tracking database is not
        # reachable. event_article carries no sharepoint_id, so the story table
        # is the only link back. See Events-Pipeline/CLAUDE.md.
        return {}
    tag = (source.get("Tags") or "").strip()
    if not tag:
        return {}                       # 1 event of 2,710
    value = ctx["map"].get(tag)
    if value is None:
        return {}                       # mapped to null: dropped on purpose
    if content.get(FIELD):
        return {}                       # already set; never overwrite an edit
    return {FIELD: [value] if AS_LIST else value}
