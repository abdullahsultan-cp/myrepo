# CLAUDE.md — Events-Pipeline

Working context for the **events** migration. Read the root
[../CLAUDE.md](../CLAUDE.md) first for the repo's conventions and the traps that
apply everywhere; this file is only what is true about events.

Everything here was measured against the real export on 2026-08-11, not assumed.
Where a number appears, it came from counting.

---

## 1 · Where this stands

**Migrated. All 2,710 events are live in Storyblok and published.**

| | |
|---|---|
| Export | `data/source/Metadata.csv` — 2,710 rows, 36 columns |
| Media | `assets/Events/media/` — 2,754 files, 459 MB, **delivered with the export** |
| Target | `event_article`, id `205403637499544`, **21 fields** |
| Stage 1 | **all 22 steps, 2,710 payloads, 0 empty bodies** |
| Routing | 2,319 entity · 314 region · 77 global · **0 unrouted**, 43 folders |
| Stories | **2,710 uploaded, 0 failed**, 2,710 distinct ids, 2,710 in their expected place |
| Assets | **2,862 live** (2,371 uploaded + 491 reused) · 29 missing · 2 held back |
| Folders created | **0** content · **41** asset, every one an `…/events` leaf |
| Tracking DB | `aku_events_migration` — story 2,710 · asset 2,893 · link 1,661 |

**Keep the tracking database.** `event_article` has no `sharepoint_id` field, so
the `story` table is the only link between a live event and its export row — see
§5a. Without it neither remaining update plan can do anything.

What is left is in §7. None of it blocks anything; two items wait on other people
and one has an external deadline.

---

## 2 · The export, honestly

**Only 25 of the 36 columns carry anything.** Dead on all 2,710:
`AdditionalEntity`, `EventsURL`, `WF-Mapping-APR`, `WF-Mapping-INI`.

The real column names — **none of the news ones apply**:

```
ID              not Id                EventDetail    not NewsContent
EventTitle      not Title             EventSummary   not NewsSummary
StartDate       not ScheduleStartDate EndDate        Venue    Country
City            Entity                Tags           imageurl attachment_files
```

There is **no** author, pull quote, approver group, sequence number or alternate
language column. Do not scaffold fields for them.

`EventURL` is `event-detail.aspx?EventID=<n>` — a bare integer, **not**
`?nid=NEWS-1234`. 218 rows point at `authoring.aku.edu` and 5 at `vs13devw:90`, a
dev server.

---

## 3 · Facts that will surprise you

**Every single event is in the past.** `StartDate` runs 2007-10-30 to 2026-04-18
and the latest ended months ago. This is an archive. `event_article` still carries
`register_link`, `register_label` and `show_calendar`, and the space has an
`upcoming_events` component — publishing "Register Now" on a 2015 workshop is
wrong, and nobody has decided what to do about it.

**The body is far simpler than news.** All 2,710 bodies contain only nine HTML tag
types — `div br strong li p ul em a ol`. **Zero `<img>`, zero `<iframe>`, zero
`<table>`, zero headings.** Every hard path in the converter is unused; the only
ones that matter are the `<br><br>` splitter (21,144 `<br>`) and div→p (38,696
`<div>`). So `rich_text` alone carries every body, and **no new component is
needed for any of the 2,710**.

**There are no shared entities.** `AdditionalEntity` is present and empty on all
2,710, and `event_article` has no `entities` field anyway — `entity` is plain
`text`. News's `build_crossrefs` / `share_target` machinery does not apply here.

**There is no department signal.** News derived 89 department folders from tags.
Events' `Tags` is a single-valued event *type* (Course, Workshop, Talk …), not a
subject. Events routes at three levels only: global, region, entity.

**`Tags` is the cleanest data in the project.** 16 values, exactly one per event,
reconciling with `Tags.csv` with no orphans in either direction. One event has
none.

**`event_article` is moving.** It went from 7 fields to 20 between 4 and 10
August. `storyblok_space/components.json` was stale about exactly that component
and nothing else. Re-read it before the first upload.

**Word paste hides in `Venue`, not the body.** `<w>`, `<m>`, `<o>`, `<xml>` in 7
events and `<style>` in 6 — all inside `Venue`. `normalize_html` strips them.

---

## 4 · Decisions already made

They live in [`../config/types/events.json`](../config/types/events.json) under
`decisions`, with the evidence. **Read that before reopening any of them.** In
brief:

| | |
|---|---|
| `banner_image` | `imageurl`, else `attachment_files`. 2,667 of 2,710 get a hero |
| second image | only 32 events have both. The attachment becomes an image node at the **bottom** of the rich text |
| `location` | ← **`Venue`**, not `Country`. Costs 639 links across 504 events, because `location` is plain text |
| `Country` | chooses the region folder; no visible field |
| routing | entity → region → global, with news's 60% entity-majority fallback |
| entity alias | `Network of Quality…` → `Networks of Quality…`, one unit, two spellings |

**The second image's position is a house convention, not source data.** SharePoint
records no position: all 2,710 bodies contain zero `<img>` and none names the
file. "After the first paragraph" was tried and measured — it landed between two
paragraphs only 51% of the time and stranded 16% at the end anyway, because 194
of those bodies have a single paragraph. Do not present the position as authored.

---

## 5 · Never do these

**Never create a folder under `regions/` or `global/`.** The tree is the
front-end developer's. All 43 destinations these events need already exist;
`route()` checks every candidate against the live snapshot and falls through
rather than inventing one.

**Never invent an entity.** Only the 19 short codes with a folder in the space are
used. An entity with no folder files at region level — that is the rule, and it is
why `Office of the Registrar` (50 events) sits at region level.

**Never route from `OtherCity`.** It is free text: `Online`, `Times vary - All
campuses`, `Across AKU Entities`. Evidence, not a rule.

**Never trust the committed folder snapshot.** Refresh it first —
`python ../pipeline/migrate/review/dump_sb_tree.py`. It was three folders stale
within a day, and it is what routing is checked against.

---

## 5a · The update plans, and the one thing they depend on

Two fields are waiting on the dev and will be filled **after** the upload, in
place, through `pipeline/migrate/update/`. Both plans are already written:

```
pipeline/updates/contact.py        Contact -> the contact field   2,710 events
pipeline/updates/event_types.py    Tags    -> event_types         2,709 events
```

Neither can run yet — `contact` has no field to write to, and `event_types` has
no known vocabulary — and both say so and exit rather than guessing.

**What they read.** `run_update.py` gives a plan `source`, the matching row from
`P.SOURCE_JSON` (`data/events.json`), keyed by SharePoint id. So a plan sees the
original 36-column row, not our payload. `data/events.json` and
`data/source/Metadata.csv` are both tracked, so that half is safe.

> ### ⚠ Events needs the tracking database for ANY update
>
> The engine finds a story's SharePoint id like this:
>
> ```python
> sid = content.get("sharepoint_id") or by_sb.get(story["id"])
> ```
>
> **`event_article` has 21 fields and none is `sharepoint_id`**, so the first
> half is always empty for events. Everything falls to `by_sb` — the Postgres
> `story` table, `SELECT sharepoint_id, sb_story_id`. Blogs put a
> `sharepoint_id` in their payload and can match without a database; events
> cannot.
>
> So: **run `db.py init` and `db.py load` before uploading, and keep that
> database.** Without it `source` is `None` on all 2,710 and neither plan can do
> anything. `run_update.py` prints a warning and carries on rather than failing,
> which means a run could look successful having changed nothing.
>
> `meta_data.sharepoint_id` is written on every story and survives upload. The
> engine does not read it today, but it is the only way home if the database is
> ever lost — worth keeping for that alone.

`event_types` also needs `data/event_types_map.json`, one entry per SharePoint
tag label. `setup()` exits with the full path and instructions if it is absent,
and errors on any label the export uses that the file does not cover.

---

## 6 · Commands

```bash
# the review portal — 5 views, self-contained, no server
python Events-Pipeline/pipeline/build_portal.py
#   -> out/events-portal.html   (~20 MB, gitignored, ~2 min)

# where every event lands, as a spreadsheet
python Events-Pipeline/pipeline/export_routing.py
#   -> data/taxonomy/routing.csv    2,710 rows, one per event
#   -> data/taxonomy/folders.csv       43 rows, one per destination

# what this type overrides
python Events-Pipeline/pipeline/run.py --describe

# once the profile is finished
python pipeline/content/import_source.py --type events
python pipeline/new_type.py events --check      # NOT optional
python pipeline/run_pipeline.py all --type events
```

`build_portal.py` puts every body through the **real** shared converter —
`normalize_html` then `storyblok_richtext` — so its preview is what Storyblok
will actually hold, not a mock-up. `export_routing.py` imports its routing from
`build_portal.py`; the mapping lived in two places three times and drifted every
time.

---

## 7 · Still open

**Ours**

- **29 banners named but not on disk.** Some are `http://…` aku.edu URLs rather
  than filenames. **The only item with an external deadline** — the files die
  with the site
- **event 2486** published with an empty banner. Its 2 assets are held back
  because `regions/uk/entities/qtl` exists in the CONTENT tree but not the ASSET
  tree, and creating an entity folder is not permitted. One folder from the dev,
  then a two-file catch-up
- **a deleted story is reported as `unchanged` on a re-run.** `upload.py` trusts
  `payload_hash` without checking the story still exists, so one removed in the
  UI is silently skipped. It cost a step four times during this migration. Fix:
  treat a 404 on PUT as "recreate", or verify existence before trusting the hash.
  Shared code — news and blogs have the same trap
- the routing cascade lives only in `build_portal.py`; `pipeline/taxonomy/` has
  none of it. It works and produced the live tree, but it is not where a reader
  would look
- `build_link_map.py` still builds `?nid=NEWS-1234`; events is `?EventID=<n>`.
  Only 37 links across 9 stories are affected, and they are naturally an
  after-upload job now that every event has an id — `pipeline/core/link_routing.py`
  is the machinery for it
- `run_taxonomy.py` has no `--type`. Events does not use stage 2, so this is
  convenience only

**Dev**

- `event_types` vocabulary — 16 tags to plugin slugs. `/field_types` returns 403
  to a personal token, and the only filled value seen is `conf-workshop`, which
  reads as Conference AND Workshop merged, so the map is probably many-to-one
- **`Contact` — all 2,710 events, 2,046 links, no field.** The largest gap
- `Registration` — 901 links across 774 events; `register_link` holds one
- no field for `EventSubTitle` (1,713), `ImageCredit` (1,538), `EventSite` (147),
  `OtherCity` (107), `EventSubsite` (74), `OnGoingEvent` (123), `SocialMedia` (1)
- `media_section.spacing` is written by every page and **is not in the schema**
- does the space's publishing workflow intercept API publishes?
- root-level `events` is a story, not a folder — cosmetic, but `news` and `blogs`
  both have one

**AKU**

- the archive question in §3 — registration UI on past events
- `AdditionalEntity` empty on all 2,710: never used, or not exported?
