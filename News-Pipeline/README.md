# News-Pipeline

**3,606 stories live in Storyblok, 0 failed.**

```
News-Pipeline/
  pipeline/     class NewsPipeline(ContentPipeline) — this type's own code
  data/         the export and every per-stage output
  assets/News/  the media
  backup/       both ends, gzipped and committed
```

The machinery lives in the parent `pipeline/`; `pipeline/pipeline.py` here is the
subclass. News overrides **nothing** — every difference is declared in
`config/types/news.json` — which is exactly why it is worth having the file: when
news does need to diverge, there is one obvious place for it.

```bash
python News-Pipeline/pipeline/run.py            # every step
python News-Pipeline/pipeline/run.py --describe # what news overrides
```

---

## What is here

```
data/
  news.json               THE INPUT — the SharePoint export. Tracked.
  raw/ cleaned/           one file per story, per stage        gitignored
  normalized/ richtext/   ditto                                gitignored
  richtext_enhanced/
  stories/                THE PAYLOADS — what gets uploaded    gitignored
  taxonomy/               folder tree + routing. Tracked — hand to the backend
  migrate/                tracking DB exports, reports, logs
  *.json                  per-stage reports: unicode, tags, link map, media
assets/News/
  Metadata.csv            the media manifest — which file is whose banner
  media/                  3,902 files, 1.8 GB                  gitignored
backup/
  raw/                    the export as it arrived             TRACKED
  storyblok/              every story read back from the API    TRACKED
```

The gitignored folders are 21,636 files and 1.8 GB, and both are regenerable —
the first from `news.json`, the second from the live site. `backup/` is the
exception that is deliberately committed: SharePoint is being retired, so those
snapshots are the only record of what the content was.

---

## Adding more news

News is not a one-off. When AKU sends a fresh export:

```bash
# 1. keep the old one — it is the only copy of what was there before
python pipeline/migrate/review/backup.py --type news

# 2. drop the new export at News-Pipeline/data/news.json, then
python pipeline/new_type.py news --check      # did any column get renamed?
python pipeline/run_pipeline.py all           # rebuild every payload
python pipeline/taxonomy/run_taxonomy.py      # re-route; new entities appear here

# 3. fetch media for the new stories only (already-downloaded files are skipped)
python pipeline/migrate/download/run_media_all.py --workers 6

# 4. upload. Existing stories are UPDATED in place; only new ones are created
python pipeline/migrate/review/dump_sb_tree.py
python pipeline/migrate/upload/run_migration.py
```

**Step 2's `--check` matters most.** A renamed column yields an empty field
rather than an error — that is how `summary` pointed at a column called `Summary`
for the entire first migration when the real one is `NewsSummary`.

**Nothing is duplicated on a re-run.** Three independent guards have to fail
first: the tracking DB holds each `sb_story_id`, a payload hash skips unchanged
stories, and a slug lookup runs before anything is created even if the database
is lost. Verified by clearing an id and re-running: it printed
`already in the space, updating` and left one copy.

**Never delete and re-create a story.** A new id breaks every review link already
shared and loses any manual edit.

---

## If a story looks wrong

```bash
python pipeline/run_pipeline.py status                 # which stages are current
python pipeline/migrate/review/export_warnings.py      # every warning, with links
python pipeline/migrate/review/audit_assets.py --csv   # declared vs on disk
python pipeline/migrate/review/backup.py --verify      # what changed since the snapshot
```

`data/migrate/reports/stories.csv` has one row per story — destination, ids,
status, SharePoint and Storyblok links, and the error if it failed.

---

## Known and accepted

- **214 media are unrecoverable.** The page renders fewer images than the export
  declares, plus a few hard 404s. Listed in `data/migrate/reports/assets.csv`.
- **566 internal links** still point at aku.edu, kept deliberately so they can be
  found and replaced now that every story has an id.
- **54 language PDFs** still link to aku.edu and need uploading before the site
  goes.
- **Two tables** are skipped and rebuilt by hand: stories 1335 and 3288.
- **1,575 stories have no entity.** That is a fact about the source, not a
  failure — `Entity = Global` means no faculty owns the story.

Full reasoning: [`../docs/PROJECT.md`](../docs/PROJECT.md) and
[`../docs/MIGRATION_DECISIONS.md`](../docs/MIGRATION_DECISIONS.md).
