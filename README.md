# AKU — SharePoint to Storyblok migration

Moves AKU's website content out of SharePoint and into Storyblok: the articles
themselves, the folder tree they live in, and every image, video and document
they reference.

**The SharePoint site is being switched off.** Anything not captured here is lost
when it goes. That single fact explains most of the design — why raw exports are
committed, why backups are taken at both ends, and why a step that cannot do its
job stops rather than guessing.

---

## Where things stand

| Content type | State | Folder |
|---|---|---|
| **news** | **3,606 stories live in Storyblok**, 0 failed. 2,417 assets uploaded | `News-Pipeline/` |
| **blogs** | 83 mapped to `blog_article`; **8 uploaded and reviewed**, 75 waiting on the owner's go-ahead | `Blogs-Pipeline/` |
| **events** | scaffolding only — awaiting the export from AKU | `Events-Pipeline/` |
| **pages** | site structure and permissions; deliverables built, under review | `Pages-Pipeline/` |

Storyblok space `289824742951963`. Default branch is `master`.

---

## Read this first, depending on why you are here

| If you want to | Read |
|---|---|
| **understand how it fits together** | [ARCHITECTURE.md](ARCHITECTURE.md) |
| **run the whole migration** — one command | [RUN_MIGRATION.md](RUN_MIGRATION.md) |
| **run one stage** | [docs/HOW_TO_RUN.md](docs/HOW_TO_RUN.md) |
| **set up a fresh clone** | [docs/REQUIRED_FILES.md](docs/REQUIRED_FILES.md) |
| **work alongside someone else** | [CONTRIBUTING.md](CONTRIBUTING.md) |
| **write code here** | [CODING_STANDARDS.md](CODING_STANDARDS.md) |
| **know why the content looks like it does** | [docs/MIGRATION_DECISIONS.md](docs/MIGRATION_DECISIONS.md) |
| **work on one content type** | that type's own `README.md` |

---

## The idea, in one page

**Three of the four content types are the same job.** News, blogs and events are
each a list of SharePoint items that has to become a Storyblok story: pull the
item out, clean its Unicode, turn editor HTML into semantic HTML, convert that to
Storyblok rich text, attach its images, work out which folder it belongs in, and
upload it.

So there is **one copy of that code**, in `pipeline/`, and each type says what is
different about it in a small file of its own. Three copies would mean fixing
every bug three times and watching them drift apart.

**Pages is not that job.** It has no list of items — it reconciles two exports
into a folder tree and a permission model. It keeps its own scripts and inherits
nothing.

Two rules follow, and everything obeys them:

> **Code lives under `pipeline/`. Data lives under `<Type>-Pipeline/`.**
>
> **Anything that differs between types is a value, not a branch.**

`if P.type == "blogs"` appears nowhere in the codebase. A difference goes in
`config/types/blogs.json`, in that type's subclass, or in a file in that type's
own folder.

---

## Layout

```
pipeline/                    THE SHARED CODE. Knows no content type.
  base.py                      class ContentPipeline — each type subclasses it
  run_pipeline.py              stage 1 orchestrator             entry point
  new_type.py                  scaffold / check a content type  entry point
  check_before_push.py         did I change someone else's file?
  install_hooks.py             turn the pre-push guard on
  core/       the seam and shared helpers      IMPORTED, NEVER RUN
                paths_root  fields  steps  text_clean  link_routing
  content/    source export -> story payload
  media/      images, video, documents
  analyze/    inventories and validation       READS, NEVER WRITES
  taxonomy/   Region / Entity / Department
  migrate/    disk <-> Storyblok               THE ONLY NETWORK CODE
                download/ upload/ update/ review/

News-Pipeline/               3,606 stories, live
  pipeline/                    class NewsPipeline — overrides nothing
  data/                        the export, and one file per story per stage
  assets/News/media/           3,902 files (gitignored, re-downloadable)
  backup/                      the export as it arrived + Storyblok read back
Blogs-Pipeline/              83 mapped, 8 live
  pipeline/                    class BlogsPipeline + its own taxonomy resolver
Events-Pipeline/             awaiting its export
  pipeline/                    class EventsPipeline — boilerplate
Pages-Pipeline/              site structure — a different job
  pipeline/                    its own 18 scripts, inherits nothing
  data/  out/  portal/

config/types/*.json          what differs per type
config/steps.json            the shared step list, as data
storyblok_space/             snapshots of the space (read-only, nobody's to merge)
docs/                        the specs
tests/                       pytest — 88 tests
```

Every folder has its own `README.md` saying what belongs in it.

---

## Quick start

```bash
# 1 · environment. The venv lives OUTSIDE the repo on this machine.
python -m venv ../.venv
../.venv/Scripts/python.exe -m pip install -r requirements.txt

# 2 · your own Storyblok token
cp config/storyblok.example.json config/storyblok.json
#    then paste your PAT into management_token

# 3 · say which content type is yours, so nothing runs against news by accident
export AKU_CONTENT_TYPE=blogs           # $env:AKU_CONTENT_TYPE = "blogs"
python pipeline/install_hooks.py --type blogs

# 4 · build the payloads
python Blogs-Pipeline/pipeline/run.py
```

**`--type` defaults to `news`, which is live.** A command without it runs against
the finished migration. Setting `AKU_CONTENT_TYPE` once, or using your own
`<Type>-Pipeline/pipeline/run.py`, removes the risk entirely.

| Stage | Runtime | Network |
|---|---|---|
| 1 · content, all 22 steps | ~9 min | none |
| 2 · taxonomy | ~30 s | none |
| 3a · media resolve + download | **~3.5 h** | reads aku.edu |
| 3b · Storyblok upload | 2–4 h | **writes** |

---

## What you need that is not in the repo

| Requirement | Notes |
|---|---|
| **Python 3.10+** | `requirements.txt`: bs4, html5lib, requests, psycopg, pytest, ruff |
| **PostgreSQL** | any local instance; tracks what has been migrated. `pipeline/migrate/db.py init` creates it |
| **Node 20+** | only for `storyblok-viewer/` and the pages portal |
| **A Storyblok token** | `config/storyblok.json`, gitignored. **Each person uses their own** |

The source exports **are** committed — `News-Pipeline/data/news.json` and
`Blogs-Pipeline/data/source/Metadata.csv` — because SharePoint is going away and
they are the only record. The media is not: 1.8 GB, re-downloadable, gitignored.

---

## The three stages

```
STAGE 1  content     SharePoint HTML  ->  Storyblok rich text + payloads
STAGE 2  taxonomy    City/Entity/Tags ->  Region / Entity / Department routing
STAGE 3  migration   payloads+assets  ->  live in Storyblok
```

Stages 1 and 2 never touch the network. Stage 3 splits in two because the halves
fail differently and are run at different times: **download** reads aku.edu and
is safe to interrupt; **upload** writes to Storyblok.

Everything is resumable. Stage 3b cannot duplicate a story — three independent
guards have to fail first: the tracking database's `sb_story_id`, a payload hash,
and a slug lookup before anything is created.

### Stage 1, step by step

```
extract                 split the export into one file per item
analyze-unicode         inventory every odd character      <- READ THIS REPORT
clean                   normalise them
analyze-tags            which HTML tags the bodies contain
normalize-html          SharePoint editor HTML -> semantic HTML
convert-richtext        -> Storyblok rich text
build-link-map          SharePoint URL -> story lookup
catalog-assets          images referenced in the bodies
enhance-richtext        resolve internal links and asset URLs
build-stories           -> data/stories/          THE PAYLOADS
validate-media          Metadata.csv vs what is on disk
map-storyblok-media     story <-> media file
inject-story-media      banner/medium/thumbnail INTO the payloads
catalog-richtext-media  inline media inventory
download-richtext-media fetch anything missing
verify-richtext-media   confirm each file is on disk
attach-richtext-media   inline media INTO the payloads
classify-story-media    tag each story by media type
validate-metadata       final check
extract-viewer-filters  the review viewer's filter lists
import-storyblok        superseded by stage 3b
```

**`build-stories` is not the last step.** It rewrites every payload and leaves
`media[]` empty; the media steps put the images back. Running it alone empties
the images on every story and the payload still looks valid. `run_pipeline.py`
warns when you do it.

**Two steps print `Validation: FAILED` by design** — they report the 206 media
that cannot be recovered, and both return zero. Watch the count, not the word.

---

## Working on one content type

Each type has its own folder, its own profile, and its own subclass. A subclass
says only what is different:

```python
class BlogsPipeline(ContentPipeline):
    type = "blogs"
```

That is the whole file for blogs — everything that makes blogs different is
declared in `config/types/blogs.json`, including the two steps it skips (its
banner files are named directly in the export, so the steps that work out which
file belongs to which story have nothing to do).

**News overrides nothing at all.** That is the measure of whether the design
works.

Three equivalent ways to run:

```bash
python pipeline/run_pipeline.py all --type blogs
python Blogs-Pipeline/pipeline/run.py
python Blogs-Pipeline/pipeline/run.py --describe     # what this type overrides
```

### Adding a content type

```bash
python pipeline/new_type.py articles           # profile + folders + README
#   put the export at Articles-Pipeline/data/source/
python pipeline/content/import_source.py --type articles
python pipeline/new_type.py articles --check   # profile vs the REAL export
python Articles-Pipeline/pipeline/run.py
```

Nothing shared is edited. **`--check` is not optional:** a field naming a column
the export does not have yields an **empty value, not an error**, and if that
field is `body`, every item migrates blank. It found `summary: "Summary"` in the
news profile — the real column is `NewsSummary` — after the migration had already
run.

---

## Things that will bite you

**No department field exists.** 41 columns in the news export, none of them a
department. The 89 department folders are inferred from 16 tag labels, so a
public-awareness piece tagged `Cardiac disease` files under Cardiology. Never
present a department as authoritative.

**`Entity = "Global"` means "no faculty owns this"**, not a region. It is exactly
the set with `LocalApproverGroup = "Global Approvers"` — 2,048 of 3,606.

**The folder tree changes under you.** The front-end developer renamed every
folder to a short code mid-project: `regions/pakistan/entities/medical-college`
became `regions/pk/entities/mc`. Storyblok moved the stories with them and
nothing was lost, but every review link shared beforehand died. Refresh
`storyblok_space/folder_tree.json` before trusting a routing result.

**Send UTF-8; never transliterate.** 711 occurrences across 98 characters are
real content — accented names, Arabic and Urdu, `£`, `°`. Only invisibles are
stripped.

**On Windows**, PowerShell 5.1 reads UTF-8 as ANSI, so use Python for anything
with non-ASCII. Every `open()` passes `encoding="utf-8"` explicitly, because
Python's Windows default is cp1252 and raises on the first accented name.

**Never create a folder under `regions/` or `global/`.** That tree belongs to the
front-end developer. The uploader has a hard stop; a missing folder is an error
with instructions, not something to invent.

---

## Review tools

```bash
python pipeline/migrate/review/layout_samples.py --csv   # 8 pages cover all 21 layouts
python pipeline/migrate/review/verify_folders.py --csv   # every folder vs the space
python pipeline/migrate/review/audit_assets.py --csv     # declared vs on disk
python pipeline/migrate/review/export_warnings.py        # every warning, with links
python pipeline/migrate/review/backup.py --type news     # snapshot both ends
python pipeline/migrate/review/backup.py --verify        # what changed since?
```

None of them writes to Storyblok.

The **review viewer** renders a story as it looks today, using the live
SharePoint images:

```bash
python pipeline/migrate/review/build_viewer_index.py
cd storyblok-viewer && npm install && npm run dev    # localhost:4000
```

---

## Tests and style

```bash
python -m pytest tests/        # 88 tests, seconds
ruff check .                   # style, mechanical
```

For any change to shared code, prove news is unchanged — its 3,606 payloads are
known-good:

```bash
find News-Pipeline/data/stories -name '*.json' | sort | xargs md5sum > /tmp/before
python pipeline/run_pipeline.py all
find News-Pipeline/data/stories -name '*.json' | sort | xargs md5sum > /tmp/after
diff /tmp/before /tmp/after && echo unchanged
```

Every refactor here has been checked that way, and it has caught things reading
the diff did not — `_uid` vanishing from all 3,606 payloads, for one.

---

## Still open

- **`global/blogs` does not exist** in Storyblok, and 70 of 83 blogs route there
- **events** has no export yet
- **54 language PDFs** still link to aku.edu, which dies with the site
- **566 internal links** still point at aku.edu, kept deliberately so they can be
  found and replaced now that every story has an id
- **214 media** unrecoverable; listed in `reports/assets.csv`
- **Two tables** skipped and rebuilt by hand: news stories 1335 and 3288
