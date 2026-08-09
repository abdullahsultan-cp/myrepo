# What you need to run this, and where each piece comes from

A fresh clone is ~45 MB and cannot run anything. Four things are missing, and
they come from four different places. This page says which, why, and exactly how
to obtain or rebuild each.

## The short version

| Need | Get it by | Time |
|---|---|---|
| Python + Postgres + Node | installing them | 10 min |
| `config/storyblok.json` | copying the example, pasting a token | 2 min |
| `News-Pipeline/data/news.json` | **already in Git** — nothing to do | — |
| `News-Pipeline/assets/News/media/` | running the media downloader | ~3.5 h |
| everything under `data/` | running the pipeline | ~10 min |

Only one thing has to come from a person: the Storyblok token.

Paths below name the news pipeline. **Every other content type has the same shape
under its own folder** — `Blogs-Pipeline/data/blogs.json`,
`Events-Pipeline/assets/Events/media/` — and the filenames come from
`config/types/<type>.json`. Pass `--type` to any command, or set
`AKU_CONTENT_TYPE`.

---

## 1 · Software

| | Why | Check |
|---|---|---|
| **Python 3.10+** | all three stages | `python --version` |
| **PostgreSQL** | tracks what has been migrated | `psql --version` |
| **Node 20+** | only for the review viewer | `node --version` |

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows;  source .venv/bin/activate elsewhere
pip install -r requirements.txt
```

The venv can live outside the repo — on this machine it is at `../.venv`, which
is why commands read `..\.venv\Scripts\python.exe`.

---

## 2 · Credentials

### `config/storyblok.json` — **required, and from a person**

```bash
cp config/storyblok.example.json config/storyblok.json
```

```json
{
  "space_id": "289824742951963",
  "management_token": "<personal access token>",
  "region": "eu"
}
```

Get the token from Storyblok → **My Account → Personal access tokens**. It has
full write access to the space, so treat it as a password.

**Gitignored, and must stay that way.** A token in a commit is a token that has
to be rotated.

### `config/database.json` — optional

Defaults to `postgres@localhost/aku_news_migration`. Override here or with the
standard `PGHOST` / `PGUSER` / `PGPASSWORD` / `PGDATABASE` variables. Also
gitignored.

---

## 3 · The one real input: `News-Pipeline/data/news.json`

**Already in Git. You do not need to obtain it.**

The raw SharePoint OData export — 3,606 items, 41 columns each. Everything else
under `data/` is derived from this file, which is why it is the only large thing
tracked.

<details>
<summary>If you ever need to re-export it from SharePoint</summary>

```
https://www.aku.edu/news/_api/web/lists/getbytitle('News')/items?$top=5000
Accept: application/json;odata=nometadata
```

Save the response as `News-Pipeline/data/news.json`. The pipeline accepts either a bare list
or `{"value": [...]}`. The fields it actually needs: `Id`, `Title`,
`NewsContent`, `SequenceNumber`, `City`, `Entity`, `Tags`,
`LocalApproverGroup`, `ScheduleStartDate`, `NewsInUrdu`.

The site is being retired, so this is a one-way door. The copy in Git is the
record.
</details>

---

## 4 · The media: `News-Pipeline/assets/News/media/`

**Gitignored — 3,902 files, 1.8 GB. Rebuilt, not downloaded from Git.**

```bash
python pipeline/migrate/download/run_media_all.py --workers 6
```

~3.5 hours, resumable — fetched pages are skipped and files already on disk are
not fetched twice. On Windows, `pipeline/migrate/download/resume_media.cmd` is
double-clickable and does the same thing.

### Why this is a rebuild rather than a copy

The original export bundle was **`News-Pipeline/assets/News/media/` plus a `Metadata.csv`
manifest**. Both were lost before this repo existed;
`data/news_media_report.json` proves all 3,421 files were present when the
pipeline first ran.

The bundle was reconstructed from the live site. That is harder than it sounds,
because the export renamed every file: `2198-BannerImage.jpg` gives no clue that
the original is `/news/PublishingImages/CapBanner.jpg`. Two paths:

- rich-text assets kept a `source_key` → `https://www.aku.edu{source_key}`
- banner and medium have no `source_key`, so each story page is read once and
  its images matched by position

**Recovered: 3,400 of 3,610 declared files (94.2%).** The remaining 210 are gone
for good — 204 where the page renders fewer images than the export claims, 6
whose URL now 404s. Only the original bundle has them, so if anyone ever finds
it, drop it in and re-run; nothing else changes.

**Run it as one process.** Two resolver passes share `media_urls.json`, and the
slower one rewrites the file from its own memory — that silently reverted
corrected URLs once. `run_media_all.py` holds a lock.

### `News-Pipeline/assets/News/Metadata.csv`

Part of the lost bundle. It maps each story to its banner / medium / thumbnail /
video filenames, and `inject_story_media.py` cannot run without it — no
manifest, no `media[]` array, no images on any story.

Reconstructed from `asset_map.csv`, which carries the same facts:

```bash
python pipeline/migrate/rebuild_metadata_csv.py --write
```

3,421 references across 3,077 stories, matching the original count exactly. It
refuses to overwrite an existing file, so a real export always wins.

---

## 5 · Everything else under `data/`

**Gitignored, regenerable, ~10 minutes.** Six folders holding one JSON per story
per stage — 21,636 files, 167 MB. Tracking them would put 21k churning files in
the diff of every pipeline run.

```bash
python pipeline/run_pipeline.py all
```

| Folder | Stage that writes it |
|---|---|
| `News-Pipeline/data/raw/` | `extract-news` — splits `news.json` into one file per story |
| `News-Pipeline/data/cleaned/` | `clean-news` — Unicode normalised |
| `News-Pipeline/data/normalized/` | `normalize-html` — SharePoint HTML → semantic HTML |
| `News-Pipeline/data/richtext/` | `convert-richtext` → rich-text JSON |
| `News-Pipeline/data/richtext_enhanced/` | `enhance-richtext` — links and assets resolved |
| `News-Pipeline/data/stories/` | `build-stories` + the media steps — **the payloads** |

**The media steps after `build-stories` are not optional.** `build-stories`
writes the payload; `inject-story-media` and `attach-richtext-media` put the
images into it. Running the first without the others empties `media[]` and
`richtext_media[]` on all 3,606 stories. Use `run_pipeline.py all`, or follow the
order in [HOW_TO_RUN.md](HOW_TO_RUN.md).

### Tracked under `data/`, because it is a deliverable or an input

| Path | What |
|---|---|
| `News-Pipeline/data/news.json` | the input |
| `News-Pipeline/data/taxonomy/` | folder tree, routing, lookups — **hand these to the backend** |
| `News-Pipeline/data/migrate/asset_map.csv` | file → story → target field. Also rebuilds `Metadata.csv` |
| `News-Pipeline/data/migrate/media_urls.json` | the resolver cache — 3,606 pages, expensive to rebuild |
| `data/*.json` | reports: unicode, tags, link map, media validation |

---

## 6 · How to clean a raw SharePoint export

If you are pointing this at a *different* SharePoint list, this is the sequence
and what each step is actually for.

```bash
python pipeline/run_pipeline.py extract-news     # split into one file per story
python pipeline/run_pipeline.py analyze-unicode  # inventory every odd character
python pipeline/run_pipeline.py clean-news       # normalise them
python pipeline/run_pipeline.py analyze-news-tags
python pipeline/run_pipeline.py normalize-html   # the important one
```

**`analyze-unicode` before `clean-news`, always.** It writes
`data/unicode_report.json`, which is the list of what will be changed. Read it
before running the clean — that is the review step, and skipping it means
transliterating real content.

What the clean does, and does not do:

- **Strips** invisibles: U+200B (in 3,004 of 3,606 files), U+FEFF, U+00AD
- **Normalises** SharePoint artefacts: 10,844 curly apostrophes, 12 U+FFFD
- **Keeps** 711 legitimate occurrences across 98 characters — accented names,
  Arabic and Urdu, `£`, `°`. Transliterating these would be a content bug, not a
  cleanup

`normalize-html` turns editor HTML into semantic HTML: unwraps `ExternalClass`
wrappers, converts layout `div`s to paragraphs, drops spacing divs, replaces
`iframe`s with placeholders, and strips presentation attributes.

**One trap worth knowing.** It strips `style` — correctly, it is mostly Word
paste. But SharePoint never writes `<u>`; it underlines with
`style="text-decoration:underline"`. So the underline goes with the attribute.
`preserve_underline` promotes it to a real `<u>` first, and has to run **before**
`normalize_inline_tags` unwraps `<span>` — running it after recovers 6 stories,
before recovers 27.

---

## 7 · Verifying you have everything

```bash
python pipeline/migrate/review/audit_assets.py       # every declared file vs disk
python pipeline/migrate/review/verify_folders.py     # every folder vs the space
python pipeline/taxonomy/run_taxonomy.py status
python -m pytest tests/
```

A healthy clone:

```
News-Pipeline/assets/News/media/     3,902 files, 1.87 GB
declared vs on disk    3,400 / 3,610  (94.2%)
folders                346 expected, 149 destinations, 0 missing
tests                  33 passed
```

---

## 8 · What is never committed, and what always is

**Never:** `assets/` · `config/storyblok.json` · `config/database.json` ·
`.venv/` · the six per-stage story folders.

Tracked size stays ~45 MB. If `git status` ever shows thousands of files, a
`.gitignore` rule has been lost.

**Always, despite living beside ignored things:** `{Type}-Pipeline/backup/`.
`.gitignore` names it as an explicit exception.

| Path | Is |
|---|---|
| `backup/raw/{type}_{stamp}.json.gz` | the export as it arrived — the only record once SharePoint is retired |
| `backup/storyblok/{type}_{stamp}.json.gz` | every story read back from the API, not assumed from what was sent |

```bash
python pipeline/migrate/review/backup.py --type news     # snapshot both ends
python pipeline/migrate/review/backup.py --verify        # diff vs the live space
```

Take one before anything significant and another after. "Did the migration do
this, or was it always like that?" then has an answer that is a diff rather than
an argument.

---

## 9 · A different content type

```bash
python pipeline/new_type.py --list             # what exists now
python pipeline/new_type.py articles           # profile + folders + README
python pipeline/new_type.py articles --check   # profile vs the real export
```

The scaffold creates `config/types/articles.json` from `_TEMPLATE.json` and the
`Articles-Pipeline/` tree. The only thing it cannot create is the export — drop
that at the path the README it wrote names, then run `--check`.

**`--check` before the first run, every time.** A `fields` entry naming a column
the export does not have yields an empty value and no error; if that entry is
`body`, every item migrates blank. `--check` reports each mismatch with near
matches from the real columns. `storyblok.component` still has to be confirmed by
hand against the live space — `pipeline/fetch_storyblok_space.py`.
