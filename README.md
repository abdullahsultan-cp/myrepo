# AKU News — SharePoint to Storyblok migration

Migrates **3,606 news stories** from AKU's SharePoint site into Storyblok: the
article content, the folder structure they live in, and every image, video and
document they reference.

The work splits into three stages that can be run and re-run independently:

| Stage | Turns | Into | Entry point |
|---|---|---|---|
| **1 · Content** | SharePoint HTML | Storyblok rich text + story payloads | `scripts/run_pipeline.py` |
| **2 · Taxonomy** | City / Entity / Tags | the Region → Entity → Department folder tree | `scripts/taxonomy/run_taxonomy.py` |
| **3 · Migration** | payloads + assets | live stories and assets in Storyblok | `scripts/migrate/` |

Everything is resumable and idempotent. Nothing in stages 1–2 touches the
network; stage 3 does, and says so before it writes.

### Start here

| If you want to | Read |
|---|---|
| **run the migration** — one command | [RUN_MIGRATION.md](RUN_MIGRATION.md) |
| **understand the project** — what, why, where it stands | [docs/PROJECT.md](docs/PROJECT.md) |
| **run any stage** — every command, in order | [docs/HOW_TO_RUN.md](docs/HOW_TO_RUN.md) |
| **set up a fresh clone** — what is needed, where each piece comes from | [docs/REQUIRED_FILES.md](docs/REQUIRED_FILES.md) |

---

## Quick start

```bash
# 1. Python 3.10+ environment
python -m venv .venv
.venv\Scripts\activate          # Windows;  source .venv/bin/activate elsewhere
pip install -r requirements.txt

# 2. Content: split the export and normalise it
python scripts/run_pipeline.py extract-news
python scripts/run_pipeline.py clean-news
python scripts/run_pipeline.py normalize-html
python scripts/run_pipeline.py convert-richtext
python scripts/run_pipeline.py build-link-map
python scripts/run_pipeline.py enhance-richtext
python scripts/run_pipeline.py build-stories

# 3. Taxonomy: work out where every story belongs
python scripts/taxonomy/run_taxonomy.py

# 4. Media: find every asset on the live site and download it
python scripts/migrate/download/run_media_all.py            # ~3.5 hours, resumable

# 5. Storyblok: create the folders and the stories
python scripts/migrate/db.py init
python scripts/migrate/db.py load
python scripts/migrate/upload/upload.py plan               # dry run first
python scripts/migrate/upload/upload.py assets
python scripts/migrate/upload/upload.py stories
```

Windows users: `scripts/migrate/download/resume_media.cmd` runs step 4 with live
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
| **`data/news.json`** | the SharePoint OData export. **In Git.** |
| **Storyblok token** | `config/storyblok.json`, from `storyblok.example.json`. **Gitignored.** |
| `assets/News/media/` | **not** required — stage 4 rebuilds it from the live site |

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
config/                Storyblok + database credentials, region_overrides.csv
data/
  news.json              INPUT — the SharePoint export (tracked)
  news/ … storyblok_stories/    per-stage story JSON (GITIGNORED, regenerable)
  taxonomy/              folder tree, per-story routing, lookups
  migrate/               asset map, media URLs, failure reports
assets/News/media/     every downloaded image, video and document (GITIGNORED)
docs/                  the specs — read these before changing behaviour

scripts/               STAGE 1 · the content pipeline (33 scripts)
scripts/taxonomy/      STAGE 2 · Region / Entity / Department
scripts/migrate/       STAGE 3 · shared: paths.py, db.py, schema.sql
scripts/migrate/download/   Flow A · find and fetch every asset
scripts/migrate/upload/     Flow B · build payloads and write to Storyblok
scripts/migrate/review/     QA · layout samples, viewer index

storyblok-viewer/      Next.js app for reviewing the result
tests/                 pytest
```

Stage 3 is split by flow because the two halves fail differently and are run at
different times: **download** talks to aku.edu and is safe to interrupt,
**upload** talks to Storyblok and writes. `paths.py` and `db.py` stay at the
`migrate/` root because both flows use them — `paths.py` locates the repo root by
walking up, so a script's directory depth never has to be encoded in its source.

**Gitignored on purpose:** the six per-stage story folders (21,636 files,
167 MB) and `assets/` (3,902 files, 1.8 GB). Both are regenerable — the first
from `data/news.json`, the second from the live site. Tracked size is ~45 MB.

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
python scripts/migrate/download/run_media_all.py --workers 6
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
python scripts/migrate/download/retry_failed_media.py      # transient errors only
python scripts/migrate/download/guess_media_variants.py    # derive medium from banner name
python scripts/migrate/download/media_progress.py          # progress bar
```

Downloading rather than linking is deliberate: uploading straight from aku.edu
would hit the site a second time story by story, and the rate limiting that
caused 69 timeouts during resolution would return mid-upload — with a
half-finished Storyblok space to clean up.

### Flow B · Upload to Storyblok

```bash
python scripts/migrate/db.py init      # create the database + schema
python scripts/migrate/db.py load      # load 3606 stories, assets, links
python scripts/migrate/db.py sample    # flag the 20-story scenario sample
python scripts/migrate/db.py status    # progress

python scripts/migrate/upload/upload.py plan                    # what would happen
python scripts/migrate/upload/upload.py assets                  # from local disk
python scripts/migrate/upload/upload.py stories --folder news/rabee
python scripts/migrate/upload/upload.py verify                  # read back from the API
```

Useful flags: `--all-stories` (the whole corpus, not the sample), `--ids 2198,1177`,
`--limit N`, `--draft`.

**Idempotent without any Storyblok schema change.** The tracking table holds
`sb_story_id`, so a second run PUTs instead of POSTing; if the database is lost,
the slug is looked up before creating. A payload hash skips unchanged stories.

After anyone edits stories in the Storyblok UI:

```bash
python scripts/migrate/upload/sync_from_sb.py --snapshot   # reconcile moves/renames
python scripts/migrate/upload/export_links.py --check      # SharePoint/SB review sheet
```

---

## Design review — the smallest set of pages that shows everything

```bash
python scripts/migrate/review/layout_samples.py --csv
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
python scripts/migrate/review/build_viewer_index.py
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
| `scripts/taxonomy/README.md` | running or changing the taxonomy stage |
| `data/taxonomy/README.md` | what each output file contains |
| `CLAUDE.md` | conventions and gotchas, for AI assistants and new joiners alike |

---

## Tests

```bash
python -m pytest tests/
```
