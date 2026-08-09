# Blogs-Pipeline

The blogs migration. **Waiting on one thing: the SharePoint export.**

Blogs are handled exactly as news, so there is no separate code here — the same
`pipeline/` drives both, selected with `--type`. This folder holds only the blogs
*data*, which is what keeps the two migrations from treading on each other.

## What is needed

Drop the export here:

```
Blogs-Pipeline/data/blogs.json
```

Same shape as `News-Pipeline/data/news.json` — a SharePoint OData response, either
a bare list or `{"value": [...]}`. The fields the pipeline actually reads:

| Field | Used for |
|---|---|
| `Id` | the filename and the tracking key |
| `Title` | title and slug |
| `NewsContent` | the body — the article HTML |
| `SequenceNumber` | the live SharePoint URL, for review sheets |
| `City` | region |
| `Entity` | owning entity |
| `Tags` | department |
| `LocalApproverGroup` | confirms "no faculty owns this" |
| `ScheduleStartDate` | the date |
| `AdditionalEntity` | share targets |

If the blogs list names any of these differently, tell me rather than renaming
the export — a mapping in `pipeline/paths_root.py` is clearer than a doctored
input, and it leaves the original intact.

## Then

```bash
..\.venv\Scripts\python.exe pipeline\run_pipeline.py all --type blogs
..\.venv\Scripts\python.exe pipeline\taxonomy\run_taxonomy.py --type blogs
..\.venv\Scripts\python.exe pipeline\migrate\download\run_media_all.py --type blogs
..\.venv\Scripts\python.exe pipeline\migrate\upload\run_migration.py --type blogs
```

Every artefact lands under this folder; nothing writes into `News-Pipeline/`.

## Two things to settle before uploading

**The destination folders.** News went into `.../news/`. The tree already has a
`blogs/` folder at every level — 155 of them — so blogs route to `.../blogs/`
instead. That is a one-line change in the taxonomy once the data confirms the
shape.

**The media bundle.** Blogs presumably reference their own images. The resolver
reads each live page to find them, exactly as it did for news, and downloads into
`Blogs-Pipeline/assets/Blogs/media/`. If a bundle already exists somewhere, drop
it in and the download step will skip what is already present.

## Layout

```
Blogs-Pipeline/
  data/
    blogs.json          the export           <- the only thing missing
    raw/ cleaned/ normalized/                 generated
    richtext/ richtext_enhanced/ stories/     generated
    taxonomy/ migrate/                        generated
  assets/Blogs/
    Metadata.csv        media manifest, if the export has one
    media/              downloaded assets
```
