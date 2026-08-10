# Events-Pipeline

**Awaiting its export.** Everything here is scaffolding; nothing has run.

Events share `pipeline/` with news and blogs, selected with `--type events`. This
folder holds only the events *data*.

---

## What is needed

One file, from AKU:

```
Events-Pipeline/data/source/<the export>
```

Then tell the profile what shape it is. `config/types/events.json` currently
assumes a JSON export named `events.json`; if it arrives as a CSV, like blogs
did, set:

```json
"source_format": "csv",
"source_file":   "data/source/<name>.csv"
```

and `pipeline/content/import_source.py` converts it, decoding SharePoint's own
encodings on the way (`"Category [ID: 4]"` → `Category` + `Category_id`,
`"string;#2025"` → `2025`).

---

## Then, in order

```bash
python pipeline/content/import_source.py --type events   # if the export is a CSV
python pipeline/new_type.py events --check               # profile vs the real export
python pipeline/run_pipeline.py all --type events
python pipeline/taxonomy/run_taxonomy.py --type events
python pipeline/migrate/upload/run_migration.py --type events
```

**Run `--check` before anything else.** `config/types/events.json` was scaffolded
from news, so every column name in it is a guess. A name that does not exist
yields an **empty field, not an error** — and if the wrong one is `body`, all of
them migrate blank. `--check` reads the real export and reports each mismatch
with near matches, and counts how many of the export's actual links match
`source_urls`.

Blogs proved the point: 13 of 15 field names were wrong.

---

## Confirm before the first upload

| | Currently | Why it matters |
|---|---|---|
| `fields` | copied from news | see above |
| `source_urls` | guessed `/events`, `Event_Details.aspx`, `EVENT-` | wrong values mean every internal cross-link silently fails to resolve and stays pointing at a site being switched off |
| `storyblok.component` | `news_article` — a placeholder | **the space already has an `event_article` component.** Almost certainly that one. Read it first: `python pipeline/analyze/fetch_storyblok_space.py` |
| `hierarchy.leaf` | `events` | the tree already carries `events/` at every level, so no new folders are needed |

`event_article` differs from `news_article`: it has `show_events` and
`show_events_header`, and lacks `author`, `date`, `read_time`, `languages`,
`entities` and `isGlobal`. Whatever the export contains will have to fit that,
or the dev adds fields.

---

## Layout

```
Events-Pipeline/
  data/
    source/             the export as delivered — tracked, never edited
    events.json         converted, if the source is a CSV
    raw/ cleaned/ normalized/                  generated, gitignored
    richtext/ richtext_enhanced/ stories/      generated, gitignored
    taxonomy/ migrate/                         generated
  assets/Events/
    media/              downloaded assets      gitignored
  backup/
    raw/                the export as it arrived           TRACKED
    storyblok/          every story read back from the API TRACKED
```

Same shape as News-Pipeline and Blogs-Pipeline, deliberately: one layout means
one set of habits, and `pipeline/core/paths_root.py` resolves all of it from the
profile.
