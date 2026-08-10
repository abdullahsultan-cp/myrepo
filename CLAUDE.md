# CLAUDE.md

Guidance for Claude Code working in this repository. Most of what follows is here
because something went wrong once; where that is true, the breakage is named,
because that is what makes a rule stick.

**Read [ARCHITECTURE.md](ARCHITECTURE.md) for the design and
[CODING_STANDARDS.md](CODING_STANDARDS.md) for the rules.** This file is the
working context: what the project is, what is true that will surprise you, and
what has already gone wrong.

---

## 1 · What this is

AKU's website content is moving out of SharePoint into **Storyblok** — the
articles, the folder tree they live in, and every image, video and document they
reference.

**The SharePoint site is being switched off.** Anything not captured is lost when
it goes. That is why raw exports are committed, why backups are taken at both
ends, and why a step that cannot do its job must stop rather than guess.

| Type | State |
|---|---|
| **news** | **3,606 stories live**, 0 failed. 2,417 assets uploaded, 990 reused, 214 unrecoverable |
| **blogs** | 83 imported, converted to rich text, routed. Not uploaded |
| **events** | scaffolding only — no export yet |
| **pages** | site structure and permissions; its own stage, shares no code |

Space `289824742951963`. Default branch **`master`** (there is no `main`).

---

## 2 · The design in three sentences

News, blogs and events are the same job over different SharePoint lists, so there
is **one copy of the code** in `pipeline/` and each type declares what is
different about it. Pages is a different job — folder tree and permissions, no
list of items — so it keeps its own scripts and inherits nothing. Two rules
follow, and everything obeys them:

> **Code lives under `pipeline/`. Data lives under `<Type>-Pipeline/`.**
>
> **Anything that differs between types is a value, not a branch.**

`if P.type == "blogs"` appears nowhere. There are exactly three places a
difference can live, and if you are adding one somewhere else, stop:

| Seam | Where | For |
|---|---|---|
| **Paths** | `pipeline/core/paths_root.py` | `P.STORIES` resolves per type; a blogs run cannot name a news file |
| **Values** | `config/types/<type>.json` | column names, payload shape, routing, component, skipped steps |
| **Behaviour** | `<Type>-Pipeline/pipeline/pipeline.py` | a hook, or a same-named file that overrides a step |

**News overrides nothing.** That is the measure of whether this is working.

---

## 3 · Layout

```
pipeline/                THE SHARED CODE. Knows no content type.
  base.py                  class ContentPipeline
  run_pipeline.py          stage 1 orchestrator      entry point
  new_type.py              scaffold / --check a type entry point
  check_before_push.py     did I touch someone else's file?
  install_hooks.py         turn the pre-push guard on
  _bootstrap.py            puts every folder below on sys.path
  core/                    the seam and shared helpers. IMPORTED, NEVER RUN.
                             paths_root.py  every path, per type
                             fields.py      F.get(item, "body") — no column names
                             steps.py       the step list, from config/steps.json
  content/                 source export -> story payload
  media/                   images, video, documents
  analyze/                 inventories and validation. READS, NEVER WRITES.
  taxonomy/                Region / Entity / Department
  migrate/                 disk <-> Storyblok. THE ONLY NETWORK CODE.
    download/                aku.edu -> disk   (read-only, interruptible)
    upload/                  disk -> Storyblok (writes)
    review/                  verification, reports, backups

News-Pipeline/     pipeline/ data/ assets/ backup/    3,606 live
Blogs-Pipeline/    pipeline/ data/ assets/ backup/    83 converted
Events-Pipeline/   pipeline/ data/ assets/ backup/    awaiting export
Pages-Pipeline/    pipeline/ data/ out/ portal/       inherits nothing

config/types/*.json      what differs per type  (_TEMPLATE.json is boilerplate)
config/steps.json        the 22 shared steps, as data
storyblok_space/         snapshots of the space — read-only, nobody's to merge
docs/  tests/            the specs; 37 tests
```

Each folder has a README stating its job. A file in the wrong folder is a bug in
the structure, not a detail.

---

## 4 · Environment and commands

- **Python 3.10+**, `requirements.txt`. The venv lives **outside** the repo at
  `../.venv` (Windows: `..\.venv\Scripts\python.exe`).
- **PostgreSQL** for migration state; `pipeline/migrate/db.py init` creates it.
- **Node 20+** only for `storyblok-viewer/` and the pages portal.
- Stage 3 needs `config/storyblok.json` — gitignored, one per person.

```bash
# stage 1 · content
python pipeline/run_pipeline.py all [--type blogs]
python <Type>-Pipeline/pipeline/run.py            # equivalent, cannot pick wrong
python <Type>-Pipeline/pipeline/run.py --describe # what this type overrides

# stage 2 · taxonomy
python pipeline/taxonomy/run_taxonomy.py [status|tree]
python Blogs-Pipeline/pipeline/resolve_taxonomy.py    # blogs has its own

# stage 3a · media, ONE process behind a lock
python pipeline/migrate/download/run_media_all.py --workers 6

# stage 3b · upload, resumable
python pipeline/migrate/review/dump_sb_tree.py    # refresh the folder tree FIRST
python pipeline/migrate/upload/run_migration.py

# review — none of these write
python pipeline/migrate/review/audit_assets.py --csv
python pipeline/migrate/review/verify_folders.py --csv
python pipeline/migrate/review/export_warnings.py
python pipeline/migrate/review/backup.py --type news [--verify]

# adding a type
python pipeline/new_type.py --list
python pipeline/new_type.py articles
python pipeline/new_type.py articles --check      # profile vs the REAL export

python -m pytest tests/     # 37
ruff check .
```

**`--type` defaults to `news`, which is live.** Set `AKU_CONTENT_TYPE` once, or
use the type's own `run.py`.

---

## 5 · Two people, three content types

`master` is the only branch. Events and pages are **the same person**; blogs is
another; news is done.

**You own `<Your-Type>-Pipeline/` and `config/types/<your-type>.json`.**
`pipeline/` is shared and is the only thing that can break someone else's work.

Before editing `pipeline/` to make one type behave, there is almost always
somewhere better:

| You want to | Where it goes |
|---|---|
| skip a step | `"skip_steps"` in your profile |
| add a step only you have | `"extra_steps"` in your profile |
| a differently-named column | `"fields"` |
| a different payload shape | `"content_fields"` |
| different routing | `"hierarchy"` |
| different behaviour in a step | a hook in your subclass |
| replace a step outright | a same-named file in `<Type>-Pipeline/pipeline/` |

Blogs needed **one** shared change to run end to end — tags arriving as
`"Label|GUID"` rather than SharePoint objects — and that was a real gap in the
base, not a blogs quirk.

```bash
python pipeline/install_hooks.py --type blogs   # once per clone
python pipeline/check_before_push.py --type blogs
```

The hook refuses a push touching someone else's folder and runs the tests;
`AKU_ALLOW_SHARED=1 git push` when the shared change is deliberate. There is no
CODEOWNERS file — with three people and non-overlapping folders it would be
ceremony. Full rules: [CONTRIBUTING.md](CONTRIBUTING.md).

---

## 6 · Never do these

**Never create a content folder.** `regions/` and `global/` belong to the
front-end developer. `ensure_folder` has a hard stop; a missing folder is an
error with instructions, not something to invent. Asset folders are a different
namespace and *are* created.

**Never delete and re-upload a story.** Update in place. A new id breaks every
review link already shared and loses manual edits.

**Never run two media resolvers at once.** They share `media_urls.json` and the
slower one rewrites it from its own memory, silently reverting corrections.
`run_media_all.py` holds a lock.

**Never let a scoping flag discard state.** `--refresh` once skipped loading the
cache, so a run scoped to 20 stories saved only those 20 and wiped 731 entries.

**Never modify a component or page schema.** Only the dev does that. If a payload
does not fit, the payload is wrong.

---

## 7 · Hard-won lessons

**Never name a content type in shared code.** Forty-five places said
`item["NewsContent"]`. For a blog that returns `None`, so two steps ran, exited
0, and wrote empty rich text for all 83 — no error anywhere. Ask the profile:
`F.get(item, "body")`.

**Find a path, do not count `dirname()` calls.** This has broken four times:
`paths_root.py` resolved the repo root to `pipeline/` after moving into `core/`;
`storyblok_config.py` did the same and returned `space_id: None`, so every API
call came back **401**; `join.py` reached for `../data/taxonomy/` and silently
stopped enriching; `story_media_classification.py` wrote the viewer constants
into `pipeline/storyblok-viewer/`. Anchor on something only the target has.

**A filter written for one thing will catch another.** The declarative payload
builder skipped every key beginning with `_`, meant for `_comment` entries.
`_uid` is a real Storyblok field, and all 3,606 payloads silently lost it.

**Never let a `set` decide the order of a committed file.** `build_url_lookup`
built its variants in a set literal; Python randomises string hashing per
process, so every regeneration wrote the same 7,057 entries in a different order
— a 5,774-line diff meaning nothing.

**A snapshot is only a baseline if you know how it was made.** Verifying a rename
by diffing 3,606 payloads showed all 3,606 changed. The *before* state had been
left by a lone `build-stories` run, which empties `media[]`. The refactor was
clean.

**Read the exit code, not the last line.** `all` ends in a wall of output, and two
steps print `Validation: FAILED` **by design** — they report the 206 unrecoverable
media and return zero. That is what let a genuinely failing step hide for weeks.

**A test that cannot fail is worse than no test.** The first entry-point test
imported in-process, after the test module had already called
`_bootstrap.ensure()`, so it passed against a file with its bootstrap deleted. It
now uses a fresh interpreter.

**Beware the auto-fixer.** `ruff check --fix` sorted the imports in `new_type.py`
and put `from paths_root import ...` above the `ensure()` that puts paths_root on
sys.path. It would also have deleted `import _bootstrap` from 65 files as unused.
The import now calls `ensure()`, so it cannot be removed as dead.

**Silence is not success.** `subprocess.run(capture_output=True)` held an hour of
output until the child exited, so a stage looked hung. Stream, and show position.

**Retry connection errors, not just HTTP errors.** `SB._call` retried 429 and 5xx
but let a `ConnectionError` raise, ending two runs at 95 and 8 minutes.

**Pool the S3 session.** A bare `requests.post()` per file left thousands of
sockets in `TIME_WAIT` until Windows ran out of ephemeral ports — that is what
`WinError 10013` means.

**Rebuild nothing by regrouping tree nodes if a string split will do.** Splitting
paragraphs by moving BeautifulSoup children destroyed six stories — 2279 came out
as `<p><br/>×19</p>` with all 4,000 characters gone.

**Do not put `/Pages/` in the chrome filter.** Real banners live at
`/news/PublishingImages/pages/News_Admin/…`. It silently deleted content images
and made 165 stories look empty.

**Measure a guess before shipping it, and prefer a gap.** Twice now the obvious
match has been the wrong one: `stephen-lyon.jpg` sits in the same folder as post
15 "Stephen Lyon: I owe a debt of gratitude to Pakistan", whose real banner is
`Blogs_banner_SL.jpg`; and "Didar Ali" drew Salim Surani's photograph because
"ali" hides inside "sALIm". Both were caught by scoring the rule against pairs
already known to be correct — nearest-upload-time picked 43 of 69, rarest-word
title matching was wrong 11 times out of 28. A rule that cannot be measured
should not be run, and a rule that abstains is doing its job. **A wrong image on
a published article is worse than no image.**

**Check output, do not assume it.** Every bug above was found by looking at a
result: a banner that was a logo, a counter that went backwards, a read time
implying 16 wpm, a description that was the word "The".

---

## 8 · Facts that surprise people

**No department field exists.** 41 columns, none of them a department. The 89
department folders come from 16 tag labels, so a public-awareness piece tagged
`Cardiac disease` files under Cardiology. Never present one as authoritative.

**678 entities and 20 regions are inferred**, not read. Check `provenance`.

**`Entity = "Global"` means "no faculty owns this"** — exactly the set with
`LocalApproverGroup = "Global Approvers"` (2,048/2,048). Not a region.

**Nine values in the Entity column are not entities** and route to `global/news`:
`Global`, `News training`, `Student Affairs and Services`, `Office of the
Provost`, `Office of the President`, `Office of the Registrar`, `Data Office`,
`Research`, `Library`.

**The folder tree was renamed under us.** The dev changed every folder to a short
code: `regions/pakistan/entities/medical-college` became `regions/pk/entities/mc`.
Storyblok moved the stories with them — all 3,606 verified present, 0 missing —
but every review link shared beforehand died, and `target_full_slug` in the
reports is stale. **Refresh `storyblok_space/folder_tree.json` before trusting a
routing result.**

**`spacing` is not optional** — `spacing-field-plugin`, on every blok:

| Components | mobile x | desktop x |
|---|---|---|
| `rich_text` | 20 | **176** |
| `quote_banner`, `media_section` (video), `brand_banner` | — | — |
| gallery, `split_section`, `iframe`, `image`, `button` | 20 | **80** |

All carry margin-bottom 24 / 56, unit `px`. `button` is the one blok whose field
is `Spacing`, capital S.

**`entities` is a list of entity FOLDER IDS** — numeric, as strings. Not UUIDs,
not slugs. 1,575 stories legitimately have none.

**Images keep their source position.** A lone image stays *inside* the rich text;
the standalone `image` blok renders it far too large. Two or more consecutive
images become a gallery **at that point**, not at the end.

**`AERR` is not a typo** — it comes from the approver group `CA AERR`. Do not
"correct" it. Short names never contain whitespace; `COE WCH` is emitted as
`COE-WCH`.

**Two odd placements were reviewed and kept**: `Pakistan / Arusha Climate and
Environmental Research Centre` (0 stories) and `Afghanistan / East Africa
Institute` (1). The first is in `config/tree_accepted_exceptions.csv`.

**Read time**: 238 wpm plus 12s per image. The reference story's hand-typed
"28 min read" for 447 words implies 16 wpm — a placeholder, not a spec.

**SharePoint has no buttons.** No `<button>`, no `role="button"`, no `btn` class
in 3,606 stories — only 19 with CTA-worded or CTA-styled links.

**179 news articles are one giant paragraph** with `<br><br>` between what are
plainly paragraphs. The splitter runs **last**, on the serialised HTML.

**Blogs differ from news in ways that matter.** No `City` column, so region comes
from inside the entity name (`Institute for Educational Development, Pakistan`).
`Metadata.csv` is the *content*, not a media manifest. Tags arrive as
`"Label|GUID"`. Bodies carry inline `{pullquote}` markers.

**Do not restyle inline formatting.** Link colour, bold, italic and underline come
across as authored.

---

## 9 · Encoding

Send **UTF-8**. Do not transliterate — 711 occurrences across 98 characters are
legitimate content: accented names, Arabic and Urdu for 44 stories, `£`, `°`.
Strip only invisibles: U+200B (in 3,004 of 3,606 files), U+FEFF, U+00AD. The 12
U+FFFD are unrecoverable and need a human.

**Always `encoding="utf-8"` on `open()`**, and `newline="\n"` when writing.
Python's Windows default is cp1252 and raises on the first accented name.

On Windows, PowerShell 5.1 reads UTF-8 as ANSI — use Python for files containing
non-ASCII. There is no heredoc in PowerShell; write long strings to a file.
`run_pipeline.py` gives every child `PYTHONIOENCODING=utf-8`, because two stages
died on *printing* a Turkish `ğ`, not on the work.

---

## 10 · Verifying a change

**Run it. Reading is not checking.**

For any change to shared code, prove news is unchanged — its 3,606 payloads are
known-good:

```bash
find News-Pipeline/data/stories -name '*.json' | sort | xargs md5sum > /tmp/before
python pipeline/run_pipeline.py all
find News-Pipeline/data/stories -name '*.json' | sort | xargs md5sum > /tmp/after
diff /tmp/before /tmp/after && echo unchanged
```

That check has caught what reading the diff did not. Also run the other types far
enough to prove they still work, and `pytest`.

**Backups**, before anything significant:

```bash
python pipeline/migrate/review/backup.py --type news   # both ends, gzipped
python pipeline/migrate/review/backup.py --verify      # diff vs the live space
```

`backup/raw/` is the export as it arrived — the only record once SharePoint goes.
`backup/storyblok/` is every story read back from the API rather than assumed.
Both are committed; `.gitignore` names them as explicit exceptions.

**Never commit** `config/storyblok.json`, `config/database.json`, `assets/`, or a
large regenerable snapshot. `storyblok_space/stories_full.json` is 44 MB and once
produced a single 1.3-million-line diff that swamped everything real in the same
commit.

---

## 11 · Still open

- **`global/blogs` does not exist** in Storyblok, and 70 of 83 blogs route there
- **events** has no export; its profile and component are placeholders. The space
  already has an `event_article`, which is **not** `news_article`
- **blogs**: `Entity` (83/83), `IsFeatured` (43), `FeatureSequence`,
  `Close Comments` (14), `IsActive`, `Post Year` and 626 comments have no field
  in `blog_article`
- **13 blogs will publish with no hero.** Closed, not pending — SharePoint holds
  no banner-to-post mapping at all (`Banner_x0020_Image` is null on all 89 posts,
  no attachments, the detail page renders client-side). Evidence and the
  measured reason for not guessing are in `data/banners_absent.json` and
  `fetch_missing_media.py`
- **54 language PDFs** still link to aku.edu, which dies with the site
- **566 internal links** still point at aku.edu, kept deliberately so they can be
  found and replaced now that every story has an id
- **214 media** unrecoverable; listed in `reports/assets.csv`
- **Two tables** skipped and rebuilt by hand: news stories 1335 and 3288
- **`ruff format`** is not enforced — it would rewrite 106 of 139 files, which
  belongs in its own deliberate commit
