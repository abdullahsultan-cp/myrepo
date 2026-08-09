# How to run everything

Every command, in order, from a fresh clone to a finished migration.

If you only want to *run the migration* and the repo is already set up, you want
[../RUN_MIGRATION.md](../RUN_MIGRATION.md) — one command. This page is the whole
thing, including the stages that only need running once.

Windows paths are shown, since that is where this runs. The venv lives outside
the repo, hence `..\.venv\Scripts\python.exe`. On macOS or Linux use `python`
with a venv activated; nothing else changes.

---

## The whole thing at a glance

```
SETUP        install, credentials, database            15 min   once
STAGE 1      SharePoint HTML -> story payloads          10 min   once
STAGE 2      taxonomy -> the folder tree                30 sec   once
STAGE 3a     download every asset                      3.5 h     once
STAGE 3b     upload to Storyblok                       2-4 h     resumable
```

Stages 1 and 2 never touch the network. 3a only reads aku.edu. Only 3b writes.

**Every command takes `--type`** — `news`, `blogs`, `events`, default `news`. Or
set `AKU_CONTENT_TYPE` once and leave the flag off. Each type keeps its own data,
assets, backups and reports, so a blogs run cannot read or overwrite a news
artefact. `pipeline/new_type.py --list` shows what exists.

---

## Setup

```bash
# 1  environment
python -m venv ..\.venv
..\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2  Storyblok credentials
copy config\storyblok.example.json config\storyblok.json
#    then set space_id and management_token

# 3  tracking database
..\.venv\Scripts\python.exe pipeline\migrate\db.py init
```

Details on every prerequisite and where it comes from:
[REQUIRED_FILES.md](REQUIRED_FILES.md).

---

## Stage 1 · Content

Turns `News-Pipeline/data/news.json` into 3,606 Storyblok payloads.

```bash
..\.venv\Scripts\python.exe pipeline\run_pipeline.py all
```

That runs the steps below in order. Run them individually only when debugging —
and if you do, **do not stop after `build-stories`**: the media steps that follow
are what put images into the payloads.

```
extract                 split the export into one file per item
analyze-unicode         inventory every odd character      <- read the report
clean                   normalise them
analyze-tags            HTML tag inventory
normalize-html          SharePoint HTML -> semantic HTML
convert-richtext        -> Storyblok rich text
build-link-map          SharePoint URL -> story lookup
catalog-assets          inline images found in content
enhance-richtext        resolve links and asset URLs
build-stories           -> data/stories/            THE PAYLOADS
validate-media          Metadata.csv vs what is on disk
map-storyblok-media     story <-> media file mapping
inject-story-media      banner/medium/thumbnail/video INTO the payloads
catalog-richtext-media  inline media inventory
download-richtext-media fetch anything still missing
verify-richtext-media   confirm each file is on disk
attach-richtext-media   inline media INTO the payloads
classify-story-media    tag each story by media type
validate-metadata       final check
```

Four of these were called `extract-news`, `clean-news`, `analyze-news-tags` and
`validate-news-media`. The pipeline runs blogs and events through exactly the
same code, so the names lied about what the step does. **The old names still
work** — they print a one-line note and run the same step.

**Why the order matters.** `build-stories` writes the payload; `inject-story-media`
and `attach-richtext-media` fill in `media[]` and `richtext_media[]`. Running
`build-stories` alone empties both on all 3,606 stories — the images silently
vanish and every story uploads without pictures. The payload still validates; it
just has no media.

Running it on its own now **prints a warning naming the two steps still owed**.
That guard exists because the trap caught someone twice, the second time while
verifying a refactor: the "before" snapshot was a media-less state left by an
earlier lone run, which made a clean rename look as though it had altered all
3,606 payloads. `run_pipeline.py all` never triggers the warning, because there
the follow-up steps are coming anyway.

Check it worked:

```bash
..\.venv\Scripts\python.exe pipeline\run_pipeline.py status
..\.venv\Scripts\python.exe -m pytest tests\
```

---

## Stage 2 · Taxonomy

Works out where each story belongs and emits the folder tree.

```bash
..\.venv\Scripts\python.exe pipeline\taxonomy\run_taxonomy.py
```

30 seconds, no network. Produces:

| File | For |
|---|---|
| `News-Pipeline/data/taxonomy/seed/folders.json` | **the backend** — 346 folders, parent before child |
| `News-Pipeline/data/taxonomy/seed/regions_entities_departments.json` | **the front end** — the same tree in its nested shape |
| `News-Pipeline/data/taxonomy/routing/news_routing.csv` | every story's destination, with provenance |

Inspect without re-running:

```bash
..\.venv\Scripts\python.exe pipeline\taxonomy\run_taxonomy.py status
..\.venv\Scripts\python.exe pipeline\taxonomy\run_taxonomy.py tree
```

If the front-end developer keeps their own copy of the tree, check it agrees
before anyone creates folders from it:

```bash
..\.venv\Scripts\python.exe pipeline\taxonomy\validate_dev_tree.py their.json --csv diff.csv
```

---

## Stage 3a · Download the assets

```bash
..\.venv\Scripts\python.exe pipeline\migrate\download\run_media_all.py --workers 6
```

**~3.5 hours.** Fully resumable — kill it and run it again. On Windows,
`pipeline\migrate\download\resume_media.cmd` is double-clickable.

Runs five stages behind a lock file: resolve URLs for stories with media,
resolve the rest, download every resolved file, export the asset map and failure
report, rebuild the viewer index.

**One process only.** Two resolver passes share `media_urls.json` and the slower
one rewrites it from its own memory — that silently reverted corrected URLs
once. The lock refuses a second run.

While it runs, or afterwards:

```bash
..\.venv\Scripts\python.exe pipeline\migrate\download\media_progress.py
..\.venv\Scripts\python.exe pipeline\migrate\download\report_failures.py
..\.venv\Scripts\python.exe pipeline\migrate\review\audit_assets.py --csv
```

Recovery, if something did not resolve:

```bash
..\.venv\Scripts\python.exe pipeline\migrate\download\retry_failed_media.py
..\.venv\Scripts\python.exe pipeline\migrate\download\guess_media_variants.py
```

If `News-Pipeline/assets/News/Metadata.csv` is absent, rebuild it before stage 1's media steps:

```bash
..\.venv\Scripts\python.exe pipeline\migrate\rebuild_metadata_csv.py --write
```

---

## Stage 3b · Upload to Storyblok

```bash
# load the tracker, and snapshot the folder tree the front end created
..\.venv\Scripts\python.exe pipeline\migrate\db.py load
..\.venv\Scripts\python.exe pipeline\migrate\review\dump_sb_tree.py

# then the whole migration, in one resumable command
..\.venv\Scripts\python.exe pipeline\migrate\upload\run_migration.py
```

**Re-run `dump_sb_tree.py` whenever the developer changes the folder tree.** The
migration reads that snapshot to find each story's destination and to fill the
`entities` field.

Safe to stop at any point — Ctrl-C, close the laptop, lose power. Run the same
command again and it continues without duplicating anything. Full detail, the
report list and every error it can stop on:
[../RUN_MIGRATION.md](../RUN_MIGRATION.md).

Before committing to all 3,606:

```bash
..\.venv\Scripts\python.exe pipeline\migrate\upload\run_migration.py --sample
```

---

## Backups

Snapshot both ends before anything significant, and again after. The question
that keeps arising is "did the migration do this, or was it always like that?",
and a diff answers it where argument does not.

```bash
..\.venv\Scripts\python.exe pipeline\migrate\review\backup.py --type news
..\.venv\Scripts\python.exe pipeline\migrate\review\backup.py --verify
```

| Written to | Is |
|---|---|
| `{Type}-Pipeline/backup/raw/{type}_{stamp}.json.gz` | the SharePoint export as it arrived — the only record once the site is retired |
| `{Type}-Pipeline/backup/storyblok/{type}_{stamp}.json.gz` | every story **read back from the API**, not assumed from what was sent |

Both are gzipped and **committed** — `.gitignore` names them as explicitly not
ignored. `--verify` diffs the newest snapshot against the live space and reports
what has changed, moved or been deleted since.

---

## A new content type

```bash
..\.venv\Scripts\python.exe pipeline\new_type.py --list
..\.venv\Scripts\python.exe pipeline\new_type.py articles
#   ... put the export at Articles-Pipeline\data\articles.json ...
..\.venv\Scripts\python.exe pipeline\new_type.py articles --check
```

`--check` compares the profile against the real export. Run it before anything
else: a `fields` entry naming a column that does not exist yields an **empty
value, not an error**, and `fields.body` being wrong migrates every item blank.
Confirm `storyblok.component` by reading the live space
(`pipeline\fetch_storyblok_space.py`) — that one cannot be checked automatically.

Then the ordinary stages with `--type articles`.

---

## Reviewing

```bash
..\.venv\Scripts\python.exe pipeline\migrate\review\build_viewer_index.py
cd storyblok-viewer && npm install && npm run dev     # localhost:4000
```

Four pages: overview and element counts, a faceted archive, the folder tree as
an org chart, and a per-story inspector. Images load from the live SharePoint
site, so a story renders as it does today.

Other review tools, none of which write anything:

```bash
# the fewest pages that between them show every layout — 8 cover all 21
..\.venv\Scripts\python.exe pipeline\migrate\review\layout_samples.py --csv

# does every folder the migration needs exist in the space?
..\.venv\Scripts\python.exe pipeline\migrate\review\verify_folders.py --csv

# which pages are missing media, and is it our fault or the source's?
..\.venv\Scripts\python.exe pipeline\migrate\review\unresolved_media.py --csv

# SharePoint vs Storyblok, side by side, one row per story
..\.venv\Scripts\python.exe pipeline\migrate\upload\export_links.py
```

---

## Quick reference

| I want to | Command |
|---|---|
| run the migration | `pipeline\migrate\upload\run_migration.py` |
| see progress, touching nothing | `run_migration.py --reports-only` |
| resume after a stop | the same command again |
| rebuild the payloads | `pipeline\run_pipeline.py all` |
| rebuild the folder tree | `pipeline\taxonomy\run_taxonomy.py` |
| re-download assets | `pipeline\migrate\download\run_media_all.py` |
| refresh the folder snapshot | `pipeline\migrate\review\dump_sb_tree.py` |
| check what is missing | `pipeline\migrate\review\audit_assets.py` |
| reconcile after manual edits | `pipeline\migrate\upload\sync_from_sb.py --snapshot` |
| back up both ends | `pipeline\migrate\review\backup.py --type news` |
| see what changed since a backup | `pipeline\migrate\review\backup.py --verify` |
| add a content type | `pipeline\new_type.py <name>` then `--check` |
| run the tests | `python -m pytest tests\` |

---

## Two things that will catch you out

**PowerShell 5.1 reads UTF-8 as ANSI.** Use Python for anything containing
non-ASCII, or box-drawing characters become mojibake. There is no heredoc in
PowerShell either — write long strings to a file. `Set-Content -Encoding utf8`
adds a BOM.

**Always pass `encoding="utf-8"` to `open()`.** Python's default on Windows is
cp1252 and it raises on the first accented name in the corpus. Every call site in
the repo does this; keep it that way in new code.
