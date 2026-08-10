# CLAUDE.md

Guidance for Claude Code working in this repository. Most of what follows is here
because something went wrong once.

---

## 1 · What this is

Migration of AKU's SharePoint content into **Storyblok** — the content itself,
the folder tree it lives in, and every referenced image, video and document.

| Type | State |
|---|---|
| **news** | **3,606 stories live**, 0 failed. 2,417 assets uploaded, 990 reused, 214 unrecoverable |
| **blogs** | 83 posts imported and converted to rich text; layout decisions taken |
| **events** | profile scaffolded, awaiting its export |
| **pages** | own stage — `Pages-Pipeline/`, a genuinely different shape |

Space `289824742951963`. **The SharePoint site is being retired**, so anything not
captured here is lost when it goes. That is why `backup/raw/` exists.

Three stages, each independently runnable and resumable:

| Stage | Turns | Into | Entry point |
|---|---|---|---|
| **1 · Content** | SharePoint HTML | Storyblok rich text + story payloads | `pipeline/run_pipeline.py` |
| **2 · Taxonomy** | City / Entity / Tags | Region → Entity → Department folders | `pipeline/taxonomy/run_taxonomy.py` |
| **3 · Migration** | payloads + assets | live stories and assets | `pipeline/migrate/` |

---

## 2 · Layout

```
pipeline/                ONE codebase for news, blogs and events. GENERIC.
  run_pipeline.py          stage 1 orchestrator      <- entry point
  new_type.py              scaffold / --check a type <- entry point
  _bootstrap.py            puts every folder below on sys.path
  core/                    the seam and shared helpers. IMPORTED, NEVER RUN.
                             paths_root.py  resolves every path per --type
                             fields.py      reads a column without knowing the list
                             storyblok_richtext.py, storyblok_utils.py, ...
  content/                 source export -> story payload   (stage 1)
  media/                   assets: catalogue, download, attach, inject
  analyze/                 inventories and validation. READS, NEVER WRITES.
  taxonomy/                stage 2 · Region / Entity / Department
  migrate/                 stage 3
    download/                aku.edu -> disk   (read-only, interruptible)
    upload/                  disk -> Storyblok (writes)
    review/                  verification and backups (never writes to the space)

News-Pipeline/           data/ assets/ backup/ README    3,606 stories, LIVE
Blogs-Pipeline/          data/ assets/ backup/ README    83 posts, converted
Events-Pipeline/         data/ assets/ backup/ README    awaiting export

Pages-Pipeline/          separate stage — structure, not content
  data/                    the 3 real inputs
  pipeline/                its own code; paths.py names every path
  out/                     deliverables handed to AKU        TRACKED
  out/work/                intermediates between steps        gitignored
  portal/                  the React app

config/types/*.json      what differs per type   <- _TEMPLATE.json is the boilerplate
config/                  credentials, region/department abbreviations, overrides
docs/                    the specs
tests/                   pytest
storyblok-viewer/        Next.js preview of a payload, before uploading it
```

**`pipeline/` is generic; everything is inherited from it.** No script there
names a content type, a SharePoint column, or a payload key. A step asks
`F.get(item, "body")` and the profile says which column that is; the story shape
itself is declared in `content_fields`. Each folder has one job and a README
saying so — `core/` is imported and never run, `analyze/` reads and never writes.

**No script in `pipeline/` is named for a content type.** Four steps and seven
scripts said "news" for code that runs blogs and events identically — the names
lied about what they do. The old step names still work and print a note. Anything
genuinely per-type lives in the profile, including where the type lives on
aku.edu (`source_urls`), which is **not** the same as where it lands in Storyblok
(`hierarchy.leaf`); they coincide for news, which is exactly how a hardcoded
`/news` survived in `build_link_map.py`.

**The code is shared; the data is not.** Duplicating 74 scripts per type would
mean fixing every bug three times and watching the copies drift. Sharing them
without separating the data would mean one `data/` folder that silently means
"whatever ran last".

---

## 3 · Content types

**Anything that differs between types belongs in `config/types/<type>.json`, not
in a branch through the pipeline.** Adding a type is a new JSON file.

| Section | Carries | Why it differs |
|---|---|---|
| `hierarchy` | folder patterns, `leaf` | each type lands in `news/`, `blogs/` or `events/`, and may use fewer levels |
| `source_urls` | aku.edu prefix, detail page, id prefix | where it came FROM, which is not where it goes |
| `storyblok` | component, body whitelist, shared asset ids | a blog need not be a `news_article` |
| `layout` | blok mapping and spacing | a type can render differently |
| `fields` | source column names | a different SharePoint list names things differently |

```
news    -> regions/{region}/entities/{entity}/departments/{dept}/news
blogs   -> .../blogs
events  -> .../events
```

```bash
python pipeline/new_type.py --list           # what exists
python pipeline/new_type.py articles         # scaffold profile + folders + README
python pipeline/new_type.py articles --check # profile vs the real export
```

`--check` earns its keep: it found that news had `summary: "Summary"` when the
real column is `NewsSummary`. That mismatch produces an **empty field, not an
error** — the worst way to find out is after several thousand uploads. Run it
before the first run of any new type.

Use `paths_root` rather than building paths by hand:

```python
sys.path.insert(0, <pipeline dir>)
from paths_root import P
open(P.SOURCE_JSON)                                    # per type
P.folder_for("entity", region="Kenya", entity="Medical College")
P.component, P.layout, P.fields, P.leaf                # per type
```

Type selection, in precedence order: `--type`, `AKU_CONTENT_TYPE`, then `news`.
`P.use()` also **writes the env var**, so child processes inherit the choice.

`run_pipeline.py` reads `--type` **straight from argv** before anything else,
because its path constants are module-level and evaluate at import — read it in
argparse and the flag parses cleanly and changes nothing.

Files under `config/types/` whose name starts with `_` are **not** types.
`_TEMPLATE.json` is the boilerplate; without that rule the loader offered a
content type called "TYPE".

---

## 4 · Environment

- **Python 3.10+**; `requirements.txt` covers all three stages. The venv lives
  **outside** the repo at `../.venv` (Windows: `..\.venv\Scripts\python.exe`).
- **PostgreSQL** for migration state. `config/database.json` or `PG*` vars;
  default `postgres@localhost/aku_news_migration`. `db.py init` creates it.
- **Node 20+** only for `storyblok-viewer/`.
- Stage 3 needs `config/storyblok.json` (gitignored — copy the `.example`).

---

## 5 · Commands

```bash
# stage 1 · content
python pipeline/run_pipeline.py all [--type blogs]
python pipeline/run_pipeline.py status
python pipeline/run_pipeline.py build-stories        # one step

# stage 2 · taxonomy
python pipeline/taxonomy/run_taxonomy.py [status|tree|<step>]
python pipeline/taxonomy/export_dev_tree.py          # the front end's shape
python pipeline/taxonomy/validate_dev_tree.py their.json --csv diff.csv

# stage 3a · media, ONE process behind a lock
python pipeline/migrate/download/run_media_all.py --workers 6
python pipeline/migrate/download/media_progress.py
python pipeline/migrate/download/report_failures.py --csv
python pipeline/migrate/download/retry_failed_media.py

# stage 3b · upload, resumable
python pipeline/migrate/db.py init | load | status
python pipeline/migrate/review/dump_sb_tree.py       # refresh the folder snapshot
python pipeline/migrate/upload/run_migration.py      # the whole thing
python pipeline/migrate/upload/run_migration.py --reports-only
python pipeline/migrate/upload/upload.py plan | assets | stories | verify

# backups — both ends, gzipped and committed
python pipeline/migrate/review/backup.py --type news
python pipeline/migrate/review/backup.py --verify

# review, none of which write to the space
python pipeline/migrate/review/audit_assets.py --csv
python pipeline/migrate/review/verify_folders.py --csv
python pipeline/migrate/review/export_warnings.py
python pipeline/migrate/review/global_and_shared.py --csv
python pipeline/migrate/review/layout_samples.py --csv
python pipeline/fetch_storyblok_space.py             # read-only snapshot
python pipeline/inventory_storyblok_components.py

python -m pytest tests/
```

Full runbook: [RUN_MIGRATION.md](RUN_MIGRATION.md). Per-step reference:
[docs/HOW_TO_RUN.md](docs/HOW_TO_RUN.md).

---

## 6 · Read before changing behaviour

| Doc | For |
|---|---|
| `docs/PROJECT.md` | the whole system — stages, profiles, layout spec, results |
| `docs/MIGRATION_DECISIONS.md` | structure, regions, entities, departments, and why |
| `docs/STORYBLOK_TARGET_SCHEMA.md` | live component schema vs the migration payload |
| `docs/STORYBLOK_COMPONENTS.md` | components, media roles, rich text, characters |
| `docs/STORYBLOK_FIELDS_NEEDED.md` | fields the front-end still owes us |
| `docs/REQUIRED_FILES.md` | what must exist before each stage runs |

Do not re-derive facts these already record. If a number here disagrees with the
data, trust the data and update the doc.

---

## 7 · Conventions

- **Slugs**: lowercase-hyphenated; entities use the **full name**, never the
  abbreviation — `regions/pakistan/entities/medical-college/news/`.
- **Short names are metadata, never paths.** All 155 named folders have one.
  Entity shorts derive from AKU approver-group names; department
  (`config/department_abbrev.csv`) and region shorts (`config/region_abbrev.csv`,
  ISO 3166-1 alpha-2) are hand-authored because nothing in the export derives
  them. Edit the CSV and re-run `tree` — never edit `folders.json` by hand.
- **Provenance is mandatory.** Any derived field records the rule that produced
  it: `region_source`, `entity_source`, `department_source`. New derivation, new
  provenance column.
- **Fail loudly.** Builders exit non-zero rather than write a file they know is
  broken.
- **One script per step**, independently re-runnable. Do not merge steps.
- **Always `encoding="utf-8"` on `open()`.** Windows defaults to cp1252 and
  raises on the first accented name in the corpus.
- **Never edit generated files.** Change the source and re-run.
- Match the surrounding style: stdlib where possible, a module docstring that
  explains *why*, comments only where the reasoning is non-obvious.

---

## 8 · Never do these

**Never create a content folder.** `regions/` and `global/` belong to the
front-end developer. `ensure_folder` has a hard stop (`NO_CREATE`); a missing
folder is an error with instructions, not something to fix by inventing one.
Asset folders (`/asset_folders`) *are* created — different namespace, explicitly
allowed.

**Never delete and re-upload a story.** Update in place. A new id breaks every
review link already shared and loses any manual edit. `upload.py` PUTs when the
DB holds an `sb_story_id`, and falls back to a slug lookup when it does not.

**Never run two media resolvers at once.** They share `media_urls.json` and the
slower one rewrites it from its own memory, silently reverting corrected URLs.
`run_media_all.py` holds a lock.

**Never let a scoping flag discard state.** `--refresh` once skipped loading the
cache, so a run scoped to 20 stories saved only those 20 and wiped 731 entries.
Scoping restricts *what is re-fetched*, never *what is kept*.

**Never modify a component or a page schema.** Only the dev does that. If a
payload does not fit, the payload is wrong.

---

## 9 · Hard-won lessons

**Silence is not success.** `subprocess.run(capture_output=True)` held an hour of
output until the child exited, so the assets stage printed nothing and looked
hung. It wasn't. Stream, and show position, rate and ETA.

**Retry connection errors, not just HTTP errors.** `SB._call` retried 429 and 5xx
but let a `ConnectionError` raise straight out, ending two runs at 95 and 8
minutes. A transient fault is the likeliest thing to happen in a three-hour job.

**Pool the S3 session.** A bare `requests.post()` per file left thousands of
sockets in `TIME_WAIT` until Windows ran out of ephemeral ports — that is what
`WinError 10013` actually means. `sb.s3` is a pooled `requests.Session`.

**Do not put `/Pages/` in the chrome filter.** Real banners live at
`/news/PublishingImages/pages/News_Admin/…`. That pattern silently deleted content
images and made 165 stories look empty. Anchor on file extension.

**URL-encoding breaks naive filters.** `Style Library` arrives as
`Style%20Library`; `Style[%\s]*Library` misses it and `AKU_logo.gif` becomes a
story's banner.

**Sanitise filenames before opening them.**
`UNCRC-vrs-ACC.pdf?sequence=1&isallowed=y` is a legal URL and an illegal Windows
path; `open()` raises `OSError` errno 22, which names nothing. Use `safe_name()`.

**`[A-Za-z]:[/\\]` matches the `s:/` in `https://`.** It classified every download
failure as an unfixable local path. Match `/[A-Za-z]:[/\\]`.

**Rebuild nothing by regrouping tree nodes if a string split will do.** Splitting
paragraphs by moving BeautifulSoup children destroyed six stories — 2279 came out
as `<p><br/>×19</p>` with all 4,000 characters gone. Cutting the serialised HTML
cannot lose a node. Proven by an A/B run over all 3,606: text of zero stories
changed.

**Converting a `for` to a `while` needs every path to advance.** A missing
`i += 1` on the fall-through spun forever and read exactly like a hung database.

**`media[]` and `richtext_media[]` overlap.** Dedupe by normalised filename or
every inline asset is counted twice. `media_key()` folds
`3405-richtext-<hash>-Dar-2.jpeg` and `Dar (2).jpeg` onto the same key.

**Regenerating one artefact can empty another.** `richtext_media` emptied on
regeneration and cost story 2198 its five images. Unplaced images are now derived
from the DB asset records, not from a file that may be stale.

**A snapshot is only a baseline if you know how it was made.** Verifying a
rename by diffing 3,606 payloads before and after showed all 3,606 changed —
alarming, and wrong. The *before* state had been left by a lone `build-stories`
run, which empties `media[]`; the full run was putting the media back. The
refactor was clean. `run_pipeline.py` now warns when a step is run alone that
leaves the payloads worse than it found them.

**A filter written for one thing will catch another.** The declarative payload
builder skipped every key beginning with `_`, meant for `_comment` entries. `_uid`
is a real Storyblok field, and all 3,606 payloads silently lost it — caught by the
byte-identity check, not by reading the code.

**Do not commit a snapshot you can regenerate, if it is big.**
`storyblok_space/stories_full.json` is 44 MB of every story's body, written as a
side effect of a schema check. Committing it produced a single 1.3-million-line
diff that swamped everything real in the same commit, and it duplicated
`backup/storyblok/*.json.gz`, which does the same job in 6 MB and is taken
deliberately. Track the structural files, ignore the bulk.

**Never let a set decide the order of a committed file.** `build_url_lookup`
built its variants in a `{...}` set literal, and Python randomises string hashing
per process — so every regeneration wrote the same 7,057 entries in a different
order. That is a 5,774-line diff that means nothing, on a file that is reviewed
by diff. Use a list wherever output order is observable.

**A path built by walking up from `__file__` breaks silently when the tree
moves.** Two of these survived the content-type restructure:
`Pages-Pipeline/pipeline/join.py` reached for `../data/taxonomy/...`, and
`extract_storyblok_filter_constants.py` for `data/storyblok_stories`. Neither
errored in a way anyone saw — the first quietly stopped enriching, the second
failed at the very end of every `all` run and left the viewer's filter constants
non-existent. Both pipelines now resolve paths through a module (`paths_root.py`,
`Pages-Pipeline/pipeline/paths.py`) so a move is one edit, not seventeen.

**Read the exit code of the whole run, not the last thing printed.** `all`
finishes with a wall of per-step output, and a step that fails in the middle of
it looks identical to one that succeeded. Two known steps print
`Validation: FAILED` **by design** — they report the 206 unrecoverable media —
and return zero, which is what made a genuinely failing step easy to miss.

**A name that says "news" in generic code is a bug waiting to happen.** Seven
scripts and four steps carried it while running blogs and events identically. The
one place it was real — a hardcoded `/news` URL prefix — hid in plain sight
precisely because everything around it was named the same way.

**Check output, do not assume it.** Every bug above was found by looking at a
result: a banner that was a logo, a counter that went backwards, a read time
implying 16 wpm, a description that was the word "The", a JSON file whose diff
was 5,774 lines of nothing.

---

## 10 · Facts that surprise people

**No department field exists.** 41 columns, none of them a department; none of
the 33 stage-1 scripts mentions one. The 89 department folders come from 16 tag
labels, so a public-awareness piece tagged `Cardiac disease` files under
Cardiology. Never present a department as authoritative.

**678 entities and 20 regions are inferred**, not read. Check `provenance` before
treating a placement as fact.

**`Entity = "Global"` means "no faculty owns this"** — exactly the set with
`LocalApproverGroup = "Global Approvers"` (2048/2048), i.e. central comms
authored. It is not a region and never becomes an entity folder.

**Nine values in the Entity column are not entities** and route to `global/news`:
`Global`, `News training`, `Student Affairs and Services`, `Office of the
Provost`, `Office of the President`, `Office of the Registrar`, `Data Office`,
`Research`, `Library`.

**`spacing` is not optional** — `spacing-field-plugin`, on every blok. Three
values, chosen by component:

| Components | mobile x | desktop x |
|---|---|---|
| `rich_text` | 20 | **176** |
| `quote_banner`, `media_section` (video), `brand_banner` | — | — |
| gallery, `split_section`, `iframe`, `image`, `button` | 20 | **80** |

All carry margin-bottom 24 mobile / 56 desktop, unit `px`. A blok without spacing
has no vertical rhythm at all — easiest thing to get wrong, hardest to spot in a
payload. `button` is the one blok whose field is `Spacing`, capital S.

**`entities` is a list of entity FOLDER IDS** — numeric, as strings. Not UUIDs,
not slugs. Resolved from the live-tree snapshot: the story's own entity plus its
`AdditionalEntity` share targets. All 60 resolved. 1,575 stories legitimately
have none, which is a fact about the source, not a failure.

**Images keep their source position.** A lone image stays *inside* the rich text —
the standalone `image` blok renders it far too large for a mid-article
illustration. Two or more consecutive images become a gallery **at that point**,
not at the end. Only images the body never referenced go to a closing gallery.

**`AERR` is not a typo** — it comes from the approver group `CA AERR`. Do not
"correct" it to ACERC. Short names never contain whitespace; the builder
hyphenates, so AKU's `COE WCH` is emitted as `COE-WCH`. Keep the source CSVs
faithful to AKU's wording and let the builder normalise.

**Two odd placements were reviewed and deliberately kept**: `Pakistan / Arusha
Climate and Environmental Research Centre` (0 stories, Arusha is Tanzanian) and
`Afghanistan / East Africa Institute` (1 story, inferred). The first is in
`config/tree_accepted_exceptions.csv` so `validate_dev_tree.py` reports it as
accepted rather than as a failure.

**Read time**: 238 wpm plus 12s per image. The reference story's hand-typed
"28 min read" for 447 words implies 16 wpm — a placeholder, not a spec.
`build_payload.py` and `storyblok-viewer/src/app/lib.ts` must agree.

**SharePoint has no buttons.** No `<button>`, no `role="button"`, no `btn` class
in 3,606 stories — only 19 with CTA-worded or CTA-styled links. Buttons are a
new-design decision, not migrated content.

**179 articles are one giant paragraph** with `<br><br>` between what are plainly
separate paragraphs. That is why the splitter exists, and it runs **last**, on the
serialised `normalized_html`, after divs have become `<p>`.

**Do not restyle inline formatting.** Link colour, bold, italic and underline come
across as authored. `text-decoration:underline` becomes an underline mark.

---

## 11 · Encoding

Send **UTF-8**. Do not transliterate — 711 occurrences across 98 characters are
legitimate content: accented names, Arabic and Urdu for 44 stories, `£`, `°`.
Strip only invisibles: U+200B (in 3,004 of 3,606 files), U+FEFF, U+00AD. The 12
U+FFFD are unrecoverable and need a human.

On Windows, PowerShell 5.1 reads UTF-8 as ANSI — use Python for files containing
non-ASCII, or box-drawing becomes mojibake. There is no heredoc in PowerShell;
write long strings to a file. `Set-Content -Encoding utf8` adds a BOM.
`run_pipeline.py` gives every child `PYTHONIOENCODING=utf-8`, because two stages
died on *printing* a Turkish `ğ`, not on the work.

---

## 11a · Two people, two content types

[`ARCHITECTURE.md`](ARCHITECTURE.md) is the design, [`CONTRIBUTING.md`](CONTRIBUTING.md)
the ownership rules, [`CODING_STANDARDS.md`](CODING_STANDARDS.md) the coding
rules. The short version:

**You own `<Your-Type>-Pipeline/` and `config/types/<your-type>.json`.**
Everything in `pipeline/` is shared and can break the other person's work.

Before editing `pipeline/` to make one type behave, check whether it belongs in
that type instead: `skip_steps()`, `extra_steps()`, a hook, a file of the same
name in `<Type>-Pipeline/pipeline/`, or a value in the profile. Blogs needed
exactly **one** shared change to run end to end, and it was a real gap in the
base rather than a blogs quirk.

```bash
python pipeline/install_hooks.py --type blogs   # once per clone
python pipeline/check_before_push.py --type blogs
```

The first installs a pre-push gate that **refuses** a push touching someone
else's folder — `AKU_ALLOW_SHARED=1 git push` when the shared change is
deliberate. The second is the same check, advisory, any time.

**The step list is data** (`config/steps.json`), and a type adds its own via
`extra_steps` in its profile. That file used to be a Python literal inside
`run_pipeline.py` — the one file every type had to edit to add a step, and so
the one both people would touch.

**`--type` defaults to news, which is live.** A command without it runs against
the finished migration. `export AKU_CONTENT_TYPE=blogs`, or use
`Blogs-Pipeline/pipeline/run.py`, which cannot be wrong.

**The folder tree is space-level**, at `storyblok_space/folder_tree.json`, not
under any one type — every type reads the same one. It used to live under
`News-Pipeline/`, which meant blogs reached across for it and two people
refreshed it in two places.

---

## 12 · Backups and git

**Back up both ends before anything significant.**

```
{Type}-Pipeline/backup/raw/{type}_{stamp}.json.gz          the export as it arrived
{Type}-Pipeline/backup/storyblok/{type}_{stamp}.json.gz    every story read back
```

The first is the only record of the original once SharePoint is retired; the
second is what Storyblok actually holds, read from the API rather than assumed.
Both gzipped and **committed** — `.gitignore` names them as explicitly not
ignored. `--verify` diffs the newest snapshot against the live space.

`.gitignore` excludes the six per-stage story folders (21,636 files, 167 MB) and
`assets/` (1.7 GB) — both regenerable, the first from the export, the second from
the live site. Tracked size ~45 MB. Never commit `assets/`,
`config/storyblok.json`, `config/database.json`, or `.venv`.

**Default branch is `master`; local work is on `main`.** Push with
`git push origin main:master`. Two people work in this repo and there is a PR
history — for anything large, push a branch rather than straight to master.

---

## 13 · Results, and what is still open

Migration of news, verified by reading the space back:

```
3,606 / 3,606 stories live      0 failed      0 misplaced      3,606 distinct ids
1,499 entity · 1,284 region · 573 entity-department · 250 global   across 149 folders
2,417 assets uploaded · 990 reused · 214 unrecoverable
No content folder was ever created — the log says "created folder" zero times.
```

2,092 warnings: 1,846 are by design (1,575 `no entity`, 233 `asset not
uploaded`); the rest were actioned.

Still open:

- **54 language PDFs** still link to aku.edu, which dies with the site. They need
  uploading to Storyblok and the links re-pointing.
- **566 internal links** still point at aku.edu, kept deliberately so they can be
  found and replaced now that every story has an id.
- **2 tables** skipped and rebuilt by hand: stories 1335 and 3288.
- **214 media** unrecoverable — the page renders fewer images than the export
  declares, plus hard 404s. Listed in `reports/assets.csv`.
- **blogs and events**: `storyblok.component`, `fields` and `source_urls` are
  placeholders copied from or guessed off news. Confirm all three — the live
  schema, the real export, and one real internal link — before the first upload.
  `new_type.py --check` does the last two.
