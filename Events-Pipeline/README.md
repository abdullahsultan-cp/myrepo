# Events-Pipeline

The events migration. **All 2,710 events are live in Storyblok and published.**

```
2,710 stories   0 failed   2,710 distinct story ids   2,710 in their expected place
2,862 assets    29 banners missing from the export    2 held back (see §7)
   43 destination folders   0 content folders created   0 duplicate asset folders
```

Every number in this file was measured, not estimated. Where one looks odd it is
explained rather than rounded.

```
Events-Pipeline/
  CLAUDE.md      what is true about events, and what has been decided
  README.md      this file
  pipeline/      class EventsPipeline(ContentPipeline) + this type's own tools
  data/source/   THE EXPORT AS DELIVERED — tracked, never edited
  data/taxonomy/ routing.csv · folders.csv                    TRACKED
  data/*.json    per-step reports                             TRACKED
  data/raw|cleaned|normalized|richtext|richtext_enhanced|stories/
                 16,260 generated files                       gitignored
  assets/Events/media/   2,754 files, 459 MB                  gitignored
  out/           events-portal.html, ~23 MB                   gitignored
```

The machinery lives in the parent `pipeline/`. `pipeline/pipeline.py` here is the
subclass and **overrides nothing** — every difference is a value in
[`../config/types/events.json`](../config/types/events.json).

```bash
python Events-Pipeline/pipeline/run.py --describe     # what this type overrides
```

---

## 0 · What arrived

Delivered as `Events-20260811T115114Z-1-001/Events/` — the fourth cut, after
deliveries on 7, 9 and 10 August.

| In `data/source/` | Is | Size |
|---|---|---|
| `Metadata.csv` | **the 2,710 events** — 36 columns | 9.2 MB |
| `Metadata.xlsx` | the same data, as delivered | 2.4 MB |
| `Cities.csv` · `Countries.csv` · `Entities.csv` · `Tags.csv` | lookups: 14 · 9 · 34 · 16 rows | |
| `Create Event Form Snapshot.png` | the SharePoint authoring form | |
| `assets/Events/media/` | **2,754 files** | 459 MB |

**The media came with the export.** Unlike news, where the bundle was lost and
3,400 files had to be rebuilt from the live site, only **29** are named and
absent — see §7, and fetch them before aku.edu is switched off.

Only 25 of the 36 columns carry anything. Dead on all 2,710: `AdditionalEntity`,
`EventsURL`, `WF-Mapping-APR`, `WF-Mapping-INI`.

---

## 1 · Running it

```bash
export AKU_CONTENT_TYPE=events        # or use Events-Pipeline/pipeline/run.py

python pipeline/run_pipeline.py all           # stage 1 · content, 22 steps
python Events-Pipeline/pipeline/export_routing.py   # stage 2 · routing CSVs
python pipeline/migrate/db.py init            # stage 3 · tracking database
python pipeline/migrate/db.py load            #           2,710 + 2,893 rows
python pipeline/migrate/upload/upload.py assets
python pipeline/migrate/upload/upload.py stories --all-stories --publish
```

`db.py load` is safe to re-run at any point: `story` upserts on `sharepoint_id`
and **does not touch upload state** — `sb_story_id`, `status` and `payload_hash`
survive, so a reload mid-upload loses nothing. `link` is truncated and rebuilt;
`run` and `event` are append-only history.

### The two review tools

```bash
python Events-Pipeline/pipeline/build_portal.py     # ~2 min -> out/events-portal.html
```

Five views: **Archive** (2,710 cards), **Event** (blok plan beside a live
preview), **SharePoint source** (every column and what it becomes), **Storyblok
components**, **Entities, tags & places**. Every gap is a labelled box saying what
is absent and why — nothing is invented.

The preview runs each body through the **real** shared converter, including
`clean_document`, so it is what Storyblok actually holds rather than a mock-up.

```bash
python Events-Pipeline/pipeline/export_routing.py
#  -> data/taxonomy/routing.csv    2,710 rows: which entity/region/global, and WHY
#  -> data/taxonomy/folders.csv       43 rows: one per destination
```

It imports its routing from `build_portal.py`, so the CSV and the portal cannot
disagree. That mapping drifted three times when it lived in two files.

---

## 2 · Where the events went

```
2,319  entity     regions/{r}/entities/{e}/events
  314  region     regions/{r}/events
   77  global     global/events
────────
2,710             across 43 destinations · 0 unrouted · 0 folders created
```

The rule: **entity folder, else region folder, else global.** Nothing is ever
created — every candidate is checked against the live tree, and an entity with no
folder in Storyblok files at region level. `Office of the Registrar` (50 events)
is the big one that does.

Region comes from `Country`, else `City`. Where no column locates an event,
news's rule 5 applies: an entity whose located events are ≥60% in one region
takes its unlocated ones there, because the tree records who *owns* an item
rather than where it happened. That moved 27 events. An explicit `Global` is
never second-guessed.

The largest destinations:

```
825  regions/pk/entities/mc/events        488  regions/pk/entities/ied/events
313  regions/uk/entities/ismc/events      274  regions/pk/events
114  regions/pk/entities/sonam/events      88  regions/pk/entities/qtl/events
 77  global/events
```

`global/events` did not exist and was the **only** content folder the dev had to
create. On the real run, all 43 resolved as `folder exists`.

**Asset folders mirror the content tree.** 41 were created during the upload,
every one an `…/events` leaf; no entity or region folder was created in either
tree.

---

## 3 · Every slug ends in its SharePoint id

```
regions/pk/entities/qtl/events/edtech-lounge-online-1397
regions/pk/entities/qtl/events/edtech-lounge-online-1403
```

Not cosmetic. **Events recur, so titles are not unique** — 2,710 events share
2,373 titles; 26 are called *EdTech Lounge Online* and all route to the same
folder. A plain title slug gives **201 colliding paths across 542 events**, and
`upload.py` checks `with_slug` before creating, so the second event would find
the first and PUT over it: 542 collapsing into 201, **341 gone with no error**,
and the `sharepoint_id → sb_story_id` mapping the update plans need becoming
many-to-one.

The start date was measured too and is **not** enough — 98 events share a title
*and* a day. Only the id is guaranteed unique. Declared as
`storyblok.slug_suffix: "id"`; news and blogs do not set it and keep clean
title slugs.

---

## 4 · What each event became

```
event_article                          id 205403637499544 · 21 fields
  banner_image     imageurl, else attachment_files            1,735 live
  body
    rich_text      "About this <Type>" — the type in green #008F51
    rich_text      the whole EventDetail
      └─ image     the attachment, for the 32 with two          at the bottom
    media_section  type=video                                     36 events
```

**No new component was needed for any of the 2,710.** The bodies contain only
nine HTML tag types and no images, iframes, tables or headings, so `rich_text`
carries all of them.

`rich_text` spacing is desktop padding-x **80**, not news's 176 — read off the
live event page. Reusing news's value renders every paragraph too narrow.

### Column mapping

| Source | Becomes |
|---|---|
| `EventTitle` | `title` |
| `EventDetail` | `body` → `rich_text` |
| `EventSummary` | `description` |
| `StartDate` | `start_at`, `deadline`, and `event_date` — **the start date only, never a range** |
| `EndDate` | `end_at` |
| `StartDate`/`EndDate` clock times | `event_time` — the daily session, on a one-day event and a 16-week course alike |
| `Venue` | **`location`** — and `mode` (§5) |
| `City` | `city` |
| `Country` | the **region folder** only; no visible field |
| `Entity` | `entity` — plain text, not folder ids |
| `Tags` | the opening heading's wording; `event_types` still empty (§7) |
| `imageurl` | `banner_image` |
| `attachment_files` | `banner_image` when `imageurl` is empty (933), else a body image (32) |
| `Video` | `media_section type=video` |
| `Registration` | `register_link` + `register_label` when it holds a URL |

---

## 5 · The rules that are not one-to-one

**`location`, and `mode` with it.** A venue that says online, zoom, virtual,
teams or webex and names **no physical place** becomes the single word `Online`,
and `mode` becomes `Online` with it — 923 events. The two come from one reading
of `Venue`, so they cannot contradict each other on the same card. A venue naming
a real room keeps its text and stays `In-Person` (1,787), even when it also says
"Register online": 67 events do, and replacing *Lecture Hall 3, Medical College*
with *Online* would state something untrue. No `Hybrid` is ever emitted — the
export never says which mode is primary.

**423 locations keep their CTA blocks**, by decision — `AKU Auditorium R E G I S
T R A T I O N Register for the course Fee…`. A cut-at-first-marker rule was
written and measured (231 of 423 shortened, none emptied) and **not adopted**:
the standing rule is to import what SharePoint has. The evidence is in
`data/venue_review.csv`.

**Text is cleaned by the shared cleaner.** The export holds 79,495 HTML entities
and 2,353 were reaching the built payloads — `&quot;` 1,420 times, `&nbsp;` 795 —
to publish as literal characters mid-sentence. Now 0, verified on all 2,710. See
[../CLAUDE.md §9](../CLAUDE.md).

**163 documents were relinked at upload time.** `attach-richtext-media` writes
`/events-media/<file>` at stage 1, when nothing is uploaded and no real URL
exists; `build_payload.relink_media()` rewrites them to
`https://a.storyblok.com/…` once the assets are up. Left alone they 404 — mostly
the programmes and registration forms those pages exist for.

---

## 6 · What has nowhere to go

Each carries real content and `event_article` has no field for it:

| Source | Events | |
|---|---|---|
| **`Contact`** | **2,710** | 2,046 links across 1,251 events. **The largest gap** |
| `EventSubTitle` | 1,713 | |
| `ImageCredit` | 1,538 | |
| `EventSite` | 147 | the event's own microsite |
| `OtherCity` | 107 | free text — `Online`, `Rabat`, `Times vary` |
| `EventSubsite` | 74 | |
| `OnGoingEvent` | 123 true | |
| `SocialMedia` | 1 | |

`Registration` is partly placed: 799 events have a URL in `register_link`; the
other 132 hold prose, and by decision those are left empty rather than invented.

---

## 7 · Still open

**29 events have no hero.** Their banners are named in `imageurl` but absent from
the delivered media; some are `http://…` URLs rather than filenames. **The files
are on aku.edu, which is being switched off** — this is the only item here with an
external deadline.

**Event 2486 published with an empty banner.** Its 2 assets are held back because
`regions/uk/entities/qtl` does not exist in the **asset** tree (it does in
content) and creating an entity folder is not permitted. One folder from the
front-end developer, then a two-file catch-up run.

**`contact` and `event_types` are empty on all 2,710**, waiting on the developer.
Both update plans are already written — `pipeline/updates/contact.py` and
`pipeline/updates/event_types.py` — and both refuse to guess. See
[CLAUDE.md §5a](CLAUDE.md): they depend on the Postgres `story` table, because
`event_article` has no `sharepoint_id` field and that table is the only link back
to the export row. **Keep that database.**

**A deleted story is reported as `unchanged` on a re-run.** `upload.py` trusts
`payload_hash` without checking the story still exists, so a story removed in the
Storyblok UI is silently skipped. It cost a step four times during this
migration. Fix: treat a 404 on PUT as "recreate", or verify existence before
trusting the hash. Shared code — it affects news and blogs too.

**The routing cascade lives only in `build_portal.py`**, not in
`pipeline/taxonomy/`. It works and is what produced the live tree, but it is not
where a reader would look for it.

**The archive question.** `StartDate` runs 2007-10-30 to 2026-04-18 and every
event is in the past, yet `event_article` carries `register_link` and
`show_calendar`, and all four display switches are `true` by decision. Nobody has
decided whether the registration UI is suppressed for past events.

---

## 8 · Three things that surprise people

**`Tags` is a single-valued event type**, not a subject taxonomy — 16 values, one
per event, reconciling exactly with `Tags.csv`, one event with none. So unlike
news there is **no department signal**, and events routes at three levels only.

**There are no shared entities.** `AdditionalEntity` is empty on all 2,710, and
`event_article` has no `entities` field to hold one. `entities_field` is declared
`null` in the profile, which is what stops the uploader emitting 2,710 warnings
about entity folder ids nothing reads.

**Word paste hides in `Venue`, not the body.** Seven events published as
`Conference Room, Emergency Medicine Normal 0 false false false EN-US X-NONE /*
Style Definitions */ table.MsoNormalTable {…}` until `strip_html` learned to drop
`<style>` **contents** rather than only its tags. 46 of the same blocks sit in the
news export, which is why that fix went into `pipeline/core/text_clean.py`.

**26 decisions are recorded** in
[`../config/types/events.json`](../config/types/events.json) under `decisions`,
each with its evidence and, where one was rejected, the measurement that rejected
it. Read those before reopening anything.
