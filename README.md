# AKU — SharePoint to Storyblok migration

Migrates AKU's SharePoint content into Storyblok — the article content, the
folder structure it lives in, and every image, video and document it references.

**News is done: 3,606 stories live.** Blogs are imported and converted — 83
posts, awaiting layout sign-off. Events await their export; pages has its own
stage.

One codebase drives all of them, selected with `--type`. What differs between
types — hierarchy, components, layout, source column names — lives in
`config/types/*.json`, not in branches through the pipeline.

The work splits into three stages that can be run and re-run independently:

| Stage | Turns | Into | Entry point |
|---|---|---|---|
| **1 · Content** | SharePoint HTML | Storyblok rich text + story payloads | `pipeline/run_pipeline.py` |
| **2 · Taxonomy** | City / Entity / Tags | the Region → Entity → Department folder tree | `pipeline/taxonomy/run_taxonomy.py` |
| **3 · Migration** | payloads + assets | live stories and assets in Storyblok | `pipeline/migrate/` |

Everything is resumable and idempotent. Nothing in stages 1–2 touches the
network; stage 3 does, and says so before it writes.

### Start here

| If you want to | Read |
|---|---|
| **run the migration** — one command | [RUN_MIGRATION.md](RUN_MIGRATION.md) |
| **understand the project** — what, why, where it stands | [docs/PROJECT.md](docs/PROJECT.md) |
| **run any stage** — every command, in order | [docs/HOW_TO_RUN.md](docs/HOW_TO_RUN.md) |
| **set up a fresh clone** — what is needed, where each piece comes from | [docs/REQUIRED_FILES.md](docs/REQUIRED_FILES.md) |
| **add a content type** — blogs, events, anything else | [Adding a content type](#adding-a-content-type) |

---

## Quick start

```bash
# 1. Python 3.10+ environment
python -m venv .venv
.venv\Scripts\activate          # Windows;  source .venv/bin/activate elsewhere
pip install -r requirements.txt

# 2. Content: split the export and normalise it — 7 steps, or `all`
python pipeline/run_pipeline.py all
#   extract  clean  normalize-html  convert-richtext
#   build-link-map  enhance-richtext  build-stories

# 3. Taxonomy: work out where every story belongs
python pipeline/taxonomy/run_taxonomy.py

# 4. Media: find every asset on the live site and download it
python pipeline/migrate/download/run_media_all.py            # ~3.5 hours, resumable

# 5. Storyblok: create the stories and their assets
python pipeline/migrate/db.py init
python pipeline/migrate/db.py load
python pipeline/migrate/upload/upload.py plan               # dry run first
python pipeline/migrate/upload/run_migration.py            # assets, stories, reports
```

Every command takes `--type` (`news`, `blogs`, `events`; default `news`), or reads
`AKU_CONTENT_TYPE`. Each type keeps its own data, assets and backups.

Windows users: `pipeline/migrate/download/resume_media.cmd` runs step 4 with live
progress behind a lock, and can be double-clicked to resume after a reboot.

| Stage | Runtime | Network |
|---|---|---|
| 2 · content, all 7 steps | ~6 min | none |
| 3 · taxonomy | ~30 s | none |
| 4 · media resolve + download | **~3.5 h** | reads aku.edu |
| 5 · Storyblok upload | ~40 min | **writes** to Storyblok |

---

## What you need before starting

| Requirement | Notes |
|---|---|
| **Python 3.10+** | `requirements.txt` — bs4, html5lib, requests, psycopg |
| **PostgreSQL** | any local instance; used only to track migration state |
| **Node 20+** and pnpm/npm | only for the review viewer |
| **`News-Pipeline/data/news.json`** | the SharePoint OData export. **In Git.** |
| **Storyblok token** | `config/storyblok.json`, from `storyblok.example.json`. **Gitignored.** |
| `News-Pipeline/assets/News/media/` | **not** required — stage 4 rebuilds it from the live site |

### Configuration

```bash
cp config/storyblok.example.json config/storyblok.json
# then set space_id and management_token
```

Database connection comes from `config/database.json` (gitignored) or the
standard `PGHOST` / `PGUSER` / `PGPASSWORD` / `PGDATABASE` variables. The default
is `postgres@localhost/aku_news_migration`.

---

## Repository layout

```
pipeline/                 THE PARENT — the machinery every type inherits
  base.py                   class ContentPipeline
  core/                     the seam + shared helpers (imported, never run)
  content/                  source export -> story payload
  media/                    assets: catalogue, download, attach, inject
  analyze/                  inventories and validation (reads, never writes)
  taxonomy/                 stage 2 · Region / Entity / Department
  migrate/download/         stage 3a · aku.edu -> disk
  migrate/upload/           stage 3b · disk -> Storyblok
  migrate/review/           verification and backups, no writes

News-Pipeline/            3,606 stories, migrated
  pipeline/                 class NewsPipeline(ContentPipeline)
  data/                     source export + per-stage output
  assets/News/media/        3,902 files (GITIGNORED, re-downloadable)
  backup/                   raw export + live Storyblok snapshots
Blogs-Pipeline/           83 posts, imported and converted
  pipeline/                 class BlogsPipeline — skips 2 media steps
Events-Pipeline/          awaiting its export
  pipeline/                 class EventsPipeline — boilerplate

Pages-Pipeline/           structure, not content — its own stage
  data/                     the 3 real inputs
  pipeline/                 its own code; paths.py names every path
  out/                      deliverables handed to AKU (TRACKED)
  out/work/                 intermediates (gitignored)
  portal/                   the React app

config/types/*.json       what differs per type
config/                   credentials, region overrides, abbreviations
docs/                     the specs — read before changing behaviour
tests/                    pytest
```

Stage 3 is split by flow because the two halves fail differently and are run at
different times: **download** talks to aku.edu and is safe to interrupt,
**upload** talks to Storyblok and writes. `paths.py` and `db.py` stay at the
`migrate/` root because both flows use them, and `pipeline/core/paths_root.py`
resolves everything per `--type`.

**Gitignored on purpose:** the six per-stage story folders (21,636 files,
167 MB) and `assets/` (3,902 files, 1.8 GB), per type. Both are regenerable — the
first from the source export, the second from the live site.

**Backed up on purpose:** `backup/raw/` keeps the SharePoint export as it
arrived, and `backup/storyblok/` keeps every story read back from the API. Both
are gzipped and committed, because the site is being retired and "was it always
like that?" needs an answer that is a diff rather than an argument.

```bash
python pipeline/migrate/review/backup.py --type news      # snapshot both ends
python pipeline/migrate/review/backup.py --verify         # what changed since?
```

---

## Stage 3 in detail — the two flows

### Flow A · Download media

The export renamed media on the way out (`2198-BannerImage.jpg`), so the local
filename says nothing about where the file lives on aku.edu. Two resolution
paths:

* rich-text assets carry a `source_key`, and `https://www.aku.edu{source_key}`
  resolves directly
* banner / medium have no `source_key` and the real name is unguessable
  (`2198-BannerImage.jpg` is really `/news/PublishingImages/CapBanner.jpg`), so
  the story page is read once and cached

```bash
python pipeline/migrate/download/run_media_all.py --workers 6
```

That runs, behind a lock file:

| # | Script | Does |
|---|---|---|
| 1–2 | `download/resolve_media_urls.py` | reads all 3,606 pages, caches every asset URL |
| 3 | `download/download_media.py` | fetches each distinct file **once** into `assets/News/media/` |
| 4 | `download/export_asset_map.py` | writes `asset_map.csv` — file → story → target field |
| 4 | `download/report_failures.py` | writes `failures.csv` |
| 5 | `review/build_viewer_index.py` | refreshes the review viewer |

Current state: **3,606/3,606 pages read, 3,413 asset URLs resolved, 3,902 files
(1.8 GB) on disk.** 208 declared media have no URL — the page renders one image
where the export declares two or three, plus 19 hard 404s. `report_failures.py`
lists them.

**Run it as one process.** Two resolver passes share `media_urls.json`, and the
slower one rewrites the file from its own memory — that silently reverted
corrected URLs once. The lock refuses a second run rather than letting them fight.

Recovery helpers, for when something did not resolve:

```bash
python pipeline/migrate/download/retry_failed_media.py      # transient errors only
python pipeline/migrate/download/guess_media_variants.py    # derive medium from banner name
python pipeline/migrate/download/media_progress.py          # progress bar
```

Downloading rather than linking is deliberate: uploading straight from aku.edu
would hit the site a second time story by story, and the rate limiting that
caused 69 timeouts during resolution would return mid-upload — with a
half-finished Storyblok space to clean up.

### Flow B · Upload to Storyblok

```bash
python pipeline/migrate/db.py init      # create the database + schema
python pipeline/migrate/db.py load      # load 3606 stories, assets, links
python pipeline/migrate/db.py sample    # flag the 20-story scenario sample
python pipeline/migrate/db.py status    # progress

python pipeline/migrate/upload/upload.py plan                    # what would happen
python pipeline/migrate/upload/upload.py assets                  # from local disk
python pipeline/migrate/upload/upload.py stories                 # each to its own folder
python pipeline/migrate/upload/upload.py verify                  # read back from the API
```

Useful flags: `--all-stories` (the whole corpus, not the sample), `--ids 2198,1177`,
`--limit N`, `--draft`.

Every story routes itself from its `target_full_slug`; `--folder` exists only to
divert a review batch into one place. **The uploader never creates a folder under
`regions/` or `global/`** — that tree belongs to the front-end developer, and a
missing folder is an error with instructions rather than an invented directory.

**Idempotent without any Storyblok schema change.** The tracking table holds
`sb_story_id`, so a second run PUTs instead of POSTing; if the database is lost,
the slug is looked up before creating. A payload hash skips unchanged stories.

After anyone edits stories in the Storyblok UI:

```bash
python pipeline/migrate/upload/sync_from_sb.py --snapshot   # reconcile moves/renames
python pipeline/migrate/upload/export_links.py --check      # SharePoint/SB review sheet
```

---

## Adding a content type

Adding a type is filling in a form, not copying a pipeline.

```bash
python pipeline/new_type.py --list             # what exists now
python pipeline/new_type.py articles           # profile + folders + README
#   ... put the export at Articles-Pipeline/data/articles.json ...
python pipeline/new_type.py articles --check   # profile vs the real export
```

The scaffold copies `config/types/_TEMPLATE.json`, which carries a CONFIRM marker
on every value that is a guess. Three of those guesses fail **silently**, which
is why `--check` exists:

| Wrong | What happens |
|---|---|
| `fields.body` | every item migrates blank — nothing errors |
| any other `fields.*` | that field is quietly empty |
| `storyblok.component` | rejected, or accepted into the wrong shape |
| `hierarchy.leaf` | the upload stops, asking for a folder nobody has |

`--check` reads the export and reports every profile key naming a column that
does not exist, with near matches. It found `summary: "Summary"` in the news
profile when the real column is `NewsSummary`. The component cannot be checked
automatically — read the live space first:

```bash
python pipeline/fetch_storyblok_space.py
python pipeline/inventory_storyblok_components.py
```

Then the ordinary stages, with `--type`:

```bash
python pipeline/run_pipeline.py all --type articles
python pipeline/taxonomy/run_taxonomy.py --type articles
python pipeline/migrate/download/run_media_all.py --type articles
python pipeline/migrate/upload/run_migration.py --type articles
```

---

## Design review — the smallest set of pages that shows everything

```bash
python pipeline/migrate/review/layout_samples.py --csv
```

Greedy set-cover over 21 layout-bearing features (hero, second image, gallery,
inline image, YouTube, hosted video, tweet, iframe, pull quote, table, lists,
headings, blockquote, PDF, GIF, RTL, superscript, long, short, no-media). **Eight
live pages cover all 21** — written to `data/migrate/layout_samples.csv` with the
SharePoint URL and the list of layouts each one demonstrates. Use those eight for
the design sign-off instead of browsing the archive.

**There are no buttons in SharePoint.** All 3,606 stories were scanned: zero
`<button>` tags, zero `role="button"`, zero `btn`/`cta` classes, zero
`<input type=submit>`. What exists is 14 stories whose link *text* reads like a
call to action ("click here", "read more", "learn more") and 5 with a link
carrying an inline background or border style. So a `button` blok is a new-design
decision, not migrated content — the migration emits those 19 as ordinary links
unless the design says otherwise.

---

## Review viewer

```bash
python pipeline/migrate/review/build_viewer_index.py
cd storyblok-viewer && npm install && npm run dev     # localhost:4000
```

Four pages: **Overview** (counts and the element inventory), **Archive**
(faceted listing), **Structure** (the folder tree as an org chart), **Inspector**
(per-story data). Images come from the live SharePoint site, so a story renders
as it does today. See `storyblok-viewer/README.md`.

---

## Things that will bite you

**No department field exists.** 41 fields in the export, none of them a
department. Departments are inferred from `Tags`, so roughly 40 of the 89
department folders may not correspond to a real unit. Never present a department
as authoritative.

**Some entities and regions are inferred too.** 678 entities were recovered for
stories whose `Entity` was `"Global"`; 20 regions could not be read from `City`.
Every story carries `region_source` / `entity_source` — check them before
treating a placement as fact.

**A story lives in exactly one Storyblok folder.** "Show on global" and "share to
another entity" are reference fields resolved at query time, never a second
folder.

**Dedupe tags by label, never by GUID.** 228 tag labels, most carrying 2–4
different `TermGuid`s for the same label.

**Send UTF-8; do not transliterate.** The pipeline already normalises every
SharePoint artefact (17,000+ curly quotes, 7,997 zero-width spaces) while
preserving 711 legitimate occurrences — accented names, Arabic/Urdu, `£`, `°`.

**On Windows**, PowerShell 5.1 reads UTF-8 files as ANSI; use Python for anything
containing non-ASCII, or box-drawing characters become mojibake. PowerShell has
no heredoc — write long strings to a file. Every `open()` in the pipeline passes
`encoding="utf-8"` explicitly, because Python's Windows default is cp1252 and it
raises on the first accented name in the corpus — keep it that way in new code.

**Buttons do not exist in the source.** See the design-review section: 3,606
stories contain no button markup at all, only 19 CTA-styled or CTA-worded links.

---

## Documentation

| Doc | Read it when |
|---|---|
| [`RUN_MIGRATION.md`](RUN_MIGRATION.md) | running the migration: one command, resume, reports |
| [`docs/PROJECT.md`](docs/PROJECT.md) | you want the whole picture — problem, architecture, state |
| [`docs/HOW_TO_RUN.md`](docs/HOW_TO_RUN.md) | every stage and command, in order, from a clone |
| [`docs/REQUIRED_FILES.md`](docs/REQUIRED_FILES.md) | setting up: what is needed, and how to get or rebuild it |
| `docs/MIGRATION_DECISIONS.md` | anything about structure, regions, entities, departments |
| `docs/STORYBLOK_TARGET_SCHEMA.md` | the live component schema vs what the migration produces |
| `docs/STORYBLOK_COMPONENTS.md` | components, media roles, rich-text schema, characters |
| `docs/STORYBLOK_FIELDS_NEEDED.md` | fields the front-end still has to add |
| `pipeline/taxonomy/README.md` | running or changing the taxonomy stage |
| `News-Pipeline/data/taxonomy/README.md` | what each taxonomy output file contains |
| `config/types/_TEMPLATE.json` | every per-type setting, annotated |
| [`CLAUDE.md`](CLAUDE.md) | conventions and the bugs already paid for — for AI assistants and new joiners alike |

---

## Tests

```bash
python -m pytest tests/
```
