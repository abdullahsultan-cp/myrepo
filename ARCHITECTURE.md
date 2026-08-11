# Architecture

How this repository is put together, and why. If you read one document before
changing code, read this one.

---

## The problem it solves

AKU's SharePoint site is being switched off. Four bodies of content have to move
to Storyblok: **news** (3,606 stories, done), **blogs** (83, converted),
**events** (awaiting its export) and **pages** (the site structure itself).

The first three are the same job over different SharePoint lists. The fourth is
not a list at all.

That distinction is the whole design.

---

## The two rules everything follows

> **1 · Code lives under `pipeline/`. Data lives under `<Type>-Pipeline/`.**
>
> **2 · Anything that differs between content types is a value, not a branch.**

Rule 1 means News-Pipeline holds no code and is not missing anything. Rule 2
means `if P.type == "blogs"` never appears; a difference goes in
`config/types/blogs.json`, in that type's subclass, or in a file in that type's
own folder.

---

## The shape

```
pipeline/                     THE PARENT. Shared by news, blogs and events.
  base.py                       class ContentPipeline — subclass per type
  run_pipeline.py               stage 1 orchestrator          entry point
  new_type.py                   scaffold / --check a type     entry point
  check_before_push.py          did you change someone else's file?
  install_hooks.py              opt in to the strict pre-push gate
  _bootstrap.py                 puts every folder below on sys.path
  core/       the seam and shared helpers    IMPORTED, NEVER RUN
  content/    source export -> story payload
  media/      assets: catalogue, download, verify, attach, inject
  analyze/    inventories and validation     READS, NEVER WRITES
  taxonomy/   Region / Entity / Department
  migrate/    disk <-> Storyblok             THE ONLY NETWORK CODE

News-Pipeline/    pipeline/  data/  assets/  backup/     3,606 live
Blogs-Pipeline/   pipeline/  data/  assets/  backup/     83 converted
Events-Pipeline/  pipeline/  data/  assets/  backup/     awaiting export
Pages-Pipeline/   pipeline/  data/  out/     portal/     a different job

config/types/*.json     what differs per type
config/steps.json       the shared step list, as data
storyblok_space/        snapshots of the space — read-only, nobody's to merge
docs/                   the specs
tests/                  pytest
```

Each folder states its job in its own README. A file in the wrong folder is a
bug in the structure, not a detail.

---

## The three seams

Everything type-specific passes through one of three places. If you are adding a
difference and it is not going through one of these, stop.

### 1 · Paths — `pipeline/core/paths_root.py`

`P` resolves every path under the selected content type. `P.STORIES` is
`News-Pipeline/data/stories` or `Blogs-Pipeline/data/stories` depending on
`--type`. A blogs run cannot read or overwrite a news artefact, because it
cannot name one.

### 2 · Values — `config/types/<type>.json`

| Section | Carries |
|---|---|
| `fields` | source column names — `body` is `NewsContent` or `Blog Detail` |
| `content_fields` | the payload shape, declared rather than coded |
| `hierarchy` | where items land in Storyblok |
| `source_urls` | where they came **from** on aku.edu — not the same thing |
| `storyblok` | the component and its body whitelist |
| `layout` | which blok each kind of content becomes, and its spacing |
| `skip_steps` / `extra_steps` | steps this type does not need, or only it has |

### 3 · Behaviour — `<Type>-Pipeline/pipeline/pipeline.py`

```python
class BlogsPipeline(ContentPipeline):
    type = "blogs"
```

Hooks: `import_source`, `clean_item`, `normalize_html`, `extract_pull_quote`,
`story_name`, `after_payload`. To replace a step outright, drop a file of the
same name in the type's folder — `resolve_script()` prefers it over the base.

**News overrides nothing**, and that is the measure of whether this works: every
news-shaped decision is a value in `news.json`.

---

## The flow

```
      the export            SharePoint OData JSON, or a CSV
          |
   import_source            -> <Type>-Pipeline/data/<type>.json
          |
STAGE 1   content/          extract -> clean -> normalize-html ->
          media/            convert-richtext -> enhance -> build-stories
          |                 then media: catalogue, download, attach, inject
          v
   data/stories/            THE PAYLOADS
          |
STAGE 2   taxonomy/         where each item belongs: region, entity, department
          |                 -> data/taxonomy/routing.csv
          v
STAGE 3   migrate/download/ aku.edu -> disk       reads only, interruptible
          migrate/upload/   disk -> Storyblok     WRITES
          migrate/review/   verification, reports, backups
          |
STAGE 4   migrate/update/   change LIVE stories   WRITES, in place
```

**Stage 4 is not an afterthought.** Migration is not one pass: the dev hands
over a field after the stories are up, a plugin's value format only becomes
knowable once something in the space has it filled, a component we worked
around gets replaced by a real one. Each of those is the same job — reach into
published stories and change one thing without disturbing anything else — so
there is one engine and a small **plan** per job, living in the type's own
folder (`<Type>-Pipeline/pipeline/updates/`). A plan declares the fields it may
touch and the engine refuses anything else. See
[pipeline/migrate/update/README.md](pipeline/migrate/update/README.md).

Stages 1 and 2 never touch the network. Stage 3a only reads. **Only 3b writes**,
and it is split from 3a because the halves fail differently and are run at
different times.

Every stage is resumable and idempotent. Stage 3b in particular has three
independent guards against duplicating a story: the tracking database's
`sb_story_id`, a payload hash, and a slug lookup before anything is created.

---

## Why pages is separate

`Pages-Pipeline/pipeline/` holds its own 18 scripts and inherits nothing.

News, blogs and events are lists of items that become stories. Pages is not a
list: it reconciles two exports into a folder tree and a permission model, and
shares no step with the others. Bending it into `ContentPipeline` would mean
overriding every hook to do something unrelated, which teaches a reader nothing.

Its own README says so, next to the code.

---

## Working in parallel

Two people, two content types, no conflicts — by structure, not by care.

| Mechanism | Removes |
|---|---|
| Separate `<Type>-Pipeline/` folders | the everyday case: your files are yours |
| `config/steps.json` + profile `extra_steps` | the step list, once the one file every type had to edit |
| `.gitattributes` `merge=ours` on generated files | three-way merges of machine-written files |
| `.gitattributes` line-ending normalisation | Windows checkouts reading as whole-file rewrites |
| `storyblok_space/` shared and space-level | blogs reaching into News-Pipeline for the folder tree |
| `pipeline/check_before_push.py` | pushing a change to someone else's file unnoticed |
| `.githooks/pre-push` | ...and doing it anyway |
| `.github/CODEOWNERS` | a shared change merging without the other owner seeing it |

Full rules: [CONTRIBUTING.md](CONTRIBUTING.md). Style and the rules paid for in
blood: [CODING_STANDARDS.md](CODING_STANDARDS.md).

---

## Adding a content type

```bash
python pipeline/new_type.py articles           # profile + folders + README
#   put the export at Articles-Pipeline/data/source/
python pipeline/content/import_source.py --type articles
python pipeline/new_type.py articles --check   # profile vs the real export
python Articles-Pipeline/pipeline/run.py
```

Nothing shared is edited. `--check` is not optional: a field naming a column the
export does not have yields an **empty value, not an error**, and if that field
is `body`, every item migrates blank. It found `summary: "Summary"` in the news
profile — where the real column is `NewsSummary` — after the migration had
already run.

---

## What the design is defending against

Every structural decision here answers something that actually happened.

| Decision | The failure it prevents |
|---|---|
| `F.get(item, "body")` instead of `item["NewsContent"]` | 83 blogs converted to empty rich text, exit 0, no warning |
| Find the root, do not count `dirname()` | four separate silent breakages, including every API call returning 401 |
| Steps as data | the one file two people both had to edit |
| Payload shape as data | 27 News-list columns hardcoded in a "generic" builder |
| Space snapshots shared and read-only | blogs reading news's copy of the folder tree |
| Byte-identity check on news | `_uid` vanishing from all 3,606 payloads |
| Warn when a step is run alone | `build-stories` silently emptying every story's images |
| Report, never guess | one blog whose entity spans three regions |

---

## Where to look next

| | |
|---|---|
| [README.md](README.md) | how to run it |
| [CONTRIBUTING.md](CONTRIBUTING.md) | who owns what, and how to avoid conflicts |
| [CODING_STANDARDS.md](CODING_STANDARDS.md) | the rules, and what each one cost |
| [CLAUDE.md](CLAUDE.md) | conventions, and every trap found so far |
| [docs/PROJECT.md](docs/PROJECT.md) | the migration itself, end to end |
| `pipeline/README.md` | the base class, in detail |
| `<Type>-Pipeline/README.md` | that type's state and its open questions |
