# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

Migration of **3,606 AKU news stories** from SharePoint to **Storyblok** — the
content, the folder tree they live in, and every referenced asset.

Three stages, each independently runnable and resumable:

| Stage | Turns | Into | Entry point |
|---|---|---|---|
| **1 · Content** | SharePoint HTML | Storyblok rich text + story payloads | `scripts/run_pipeline.py` |
| **2 · Taxonomy** | City / Entity / Tags | Region → Entity → Department folders | `scripts/taxonomy/run_taxonomy.py` |
| **3 · Migration** | payloads + assets | live stories and assets in Storyblok | `scripts/migrate/` |

Stage 3 is split into two flows, and the directories match:

```
scripts/migrate/paths.py  db.py  schema.sql     shared by both flows

scripts/migrate/download/   Flow A · aku.edu -> disk       safe to interrupt
    run_media_all.py orchestrates:
    resolve_media_urls -> download_media -> export_asset_map -> report_failures

scripts/migrate/upload/     Flow B · disk -> Storyblok     writes
    db (load) -> upload assets -> upload stories -> verify -> export_links

scripts/migrate/review/     QA
    layout_samples.py  build_viewer_index.py
```

`paths.py` finds the repo root by walking up, so no script encodes its own depth.
Import it before any sibling or cross-stage import — it is what puts
`scripts/migrate/` and `scripts/` on `sys.path`:

```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import BASE  # noqa: E402
```

Destination shape:

```
global/news/{item}                                                  250
Regions/{region}/News/{item}                                      1,284
Regions/{region}/Entities/{entity}/News/{item}                    1,499
Regions/{region}/Entities/{entity}/Departments/{dept}/News/{item}   573
```

346 folders · 6 regions · 19 entities · 89 department folders.

## Read before changing behaviour

| Doc | For |
|---|---|
| `docs/MIGRATION_DECISIONS.md` | structure, regions, entities, departments, and why |
| `docs/STORYBLOK_TARGET_SCHEMA.md` | live component schema vs the migration payload |
| `docs/STORYBLOK_COMPONENTS.md` | components, media roles, rich text, characters |
| `docs/STORYBLOK_FIELDS_NEEDED.md` | fields the front-end still owes us |
| `README.md` | how to run everything |

Do not re-derive facts these already record. If a number here disagrees with the
data, trust the data and update the doc.

## Environment

- **Python 3.10+**; `requirements.txt` covers all three stages. The venv lives
  **outside** the repo at `../.venv` (Windows: `..\.venv\Scripts\python.exe`).
- **PostgreSQL** for migration state. `config/database.json` or `PG*` vars.
  Default `postgres@localhost/aku_news_migration`.
- **Node 20+** only for `storyblok-viewer/`.
- Stage 3 needs `config/storyblok.json` (gitignored).

## Commands

```bash
# taxonomy
python scripts/taxonomy/run_taxonomy.py status | tree | <step>
python scripts/taxonomy/export_dev_tree.py          # tree in the front end's shape
python scripts/taxonomy/validate_dev_tree.py their.json --csv diff.csv

# media (Flow A) — one process, behind a lock
python scripts/migrate/download/run_media_all.py --workers 6
python scripts/migrate/download/media_progress.py
python scripts/migrate/download/report_failures.py --csv
python scripts/migrate/download/retry_failed_media.py

# Storyblok (Flow B)
python scripts/migrate/db.py init | load | sample | status
python scripts/migrate/upload/upload.py plan | assets | stories | verify
python scripts/migrate/upload/sync_from_sb.py --snapshot

# audits
python scripts/inventory_storyblok_components.py data/storyblok_component_inventory.json
python scripts/fetch_storyblok_space.py        # read-only snapshot of the space
python scripts/migrate/review/layout_samples.py       # fewest pages covering every layout

python -m pytest tests/
```

## Conventions

- **Slugs**: lowercase-hyphenated; entities use the **full name**, never the
  abbreviation — `regions/pakistan/entities/medical-college/news/`.
- **Short names are metadata, never paths.** All 155 named folders have one.
  Entity shorts are derived from AKU approver-group names; department shorts
  (`config/department_abbrev.csv`) and region shorts (`config/region_abbrev.csv`,
  ISO 3166-1 alpha-2) are hand-authored because nothing in the export derives
  them. Edit the CSV and re-run `tree` — never edit `folders.json` by hand.
- **Provenance is mandatory.** Any derived field records the rule that produced
  it (`region_source`, `entity_source`, `department_source`). Add a new
  derivation, add its provenance column.
- **Fail loudly.** The seed builders exit non-zero rather than write a broken
  file. Keep that.
- **One script per step**, independently re-runnable. Do not merge steps.
- `scripts/taxonomy/paths.py` is the only place taxonomy directories are defined.
- Match the surrounding style: stdlib where possible, a module docstring that
  explains *why*, comments only where the reasoning is non-obvious.

## Hard-won lessons — do not relearn these

**One writer on `media_urls.json`.** Two resolver passes both load the cache and
both save it; the slower one reverts the other's corrections, silently.
`run_media_all.py` holds a lock. Never run two resolver passes at once.

**`--refresh` must not discard the cache.** It once skipped loading entirely, so
a run scoped to 20 stories saved only those 20 and wiped 731 resolved entries.
Scoping flags restrict *what is re-fetched*, never *what is kept*.

**Do not put `/Pages/` in the chrome filter.** Real banner images live at
`/news/PublishingImages/pages/News_Admin/…`. That pattern silently deleted
content images and made 165 stories look like they had none. Filter anchors by
file extension instead.

**URL-encoding breaks naive filters.** `Style Library` arrives as
`Style%20Library`, so `Style[%\s]*Library` misses it and `AKU_logo.gif` gets
assigned as a story's banner.

**Sanitise filenames before opening them.** `UNCRC-vrs-ACC.pdf?sequence=1&isallowed=y`
is a legal URL and an illegal Windows path; `open()` raises `OSError` errno 22,
which names nothing. Use `safe_name()`.

**`[A-Za-z]:[/\\]` matches the `s:/` in `https://`.** It classified every
download failure as an unfixable local path. Match `/[A-Za-z]:[/\\]`.

**`media[]` and `richtext_media[]` overlap.** Dedupe by filename or every inline
asset is counted twice.

**Check output, do not assume it.** Every bug above was found by inspecting a
result — a banner that was a logo, a counter that went backwards, a read time
implying 16 wpm.

## Things that are true and surprising

**No department field exists** — 41 fields in the export, none of them a
department; none of the 33 stage-1 scripts mentions one. Departments come from
`Tags`, so ~40 of the 89 department folders may not correspond to a real unit.
Never present a department as authoritative.

**678 entities and 20 regions are inferred.** Check `provenance` before treating
a placement as fact.

**`AERR` is not a typo** — it comes straight from the approver group `CA AERR`, so
it is AKU's own abbreviation. Do not "correct" it to ACERC.

**Short names never contain whitespace.** `build_folder_tree.py` hyphenates it, so
AKU's `COE WCH` is emitted as `COE-WCH`. Keep the source CSVs faithful to AKU's
wording and let the builder normalise — that way a new group name with a space
cannot leak into the JSON.

**Two odd placements were reviewed and deliberately kept**, so do not "fix" them:
`Pakistan / Arusha Climate and Environmental Research Centre` (0 stories, Arusha
is Tanzanian) and `Afghanistan / East Africa Institute` (1 story, inferred
entity). The first is recorded in `config/tree_accepted_exceptions.csv` so
`validate_dev_tree.py` reports it as accepted rather than as a failure.

**`Entity = "Global"` means "no faculty owns this"** — it is exactly the set
`LocalApproverGroup = "Global Approvers"` (2048/2048), i.e. central comms
authored. It is not a region and never becomes an entity folder.

**Nine values in the Entity column are not entities**, and route to
`global/news`: `Global`, `News training`, `Student Affairs and Services`,
`Office of the Provost`, `Office of the President`, `Office of the Registrar`,
`Data Office`, `Research`, `Library`.

**`spacing` is not optional.** Every blok in the pixel-perfect demo sets the
`spacing-field-plugin` value; without it a blok renders with no vertical rhythm.
Values live in `build_payload.py`.

**`entities` is an array of UUIDs** that resolve to nothing in the space — not a
story, folder or datasource entry. Internal to `entities-plugins`, which
`/field_types` will not expose to a personal token. **Left empty pending the
front-end developer.** Do not invent values.

**Read time**: 238 wpm plus 12s per image. The demo's hand-typed "28 min read"
for 447 words implies 16 wpm — a placeholder, not a spec. `build_payload.py` and
`storyblok-viewer/src/app/lib.ts` must agree.

**Assets: 3,902 files / 1.8 GB reconstructed from the live site**, 3,413 URLs
resolved from 3,606 pages. 208 declared files are not obtainable: the page
renders one image where the export declares two or three, plus 19 hard 404s.
`news_media_report.json` proves all 3,421 existed when the original pipeline ran,
so the original `assets/` bundle is the only complete source for the residual gap.

**SharePoint has no buttons.** No `<button>`, no `role="button"`, no `btn` class
anywhere in 3,606 stories — only 14 stories with call-to-action link text and 5
with a styled box link. Buttons are a new-design decision, not migrated content.

## Encoding

Send **UTF-8**. Do not transliterate — 711 occurrences across 98 characters are
legitimate content (accented names, Arabic/Urdu for 44 stories, `£`, `°`,
transliteration marks). Strip only invisibles: U+200B (was in 3,004 of 3,606
files), U+FEFF, U+00AD. The 12 U+FFFD are unrecoverable and need a human.

**Always pass `encoding="utf-8"` to `open()`.** Python's default on Windows is
cp1252 and it raises on the first accented name in the corpus. 72 call sites
across stage 1 were missing it; one of them was failing a test.

On Windows, PowerShell 5.1 reads UTF-8 as ANSI — use Python for files containing
non-ASCII, or box-drawing characters become mojibake. There is no heredoc in
PowerShell; write long strings to a file. `Set-Content -Encoding utf8` adds a BOM.

## Git

`.gitignore` excludes the six per-stage story folders (21,636 files, 167 MB) and
`assets/` (1.7 GB) — both regenerable. Tracked size ~45 MB. Never commit
`assets/`, `config/storyblok.json`, `config/database.json`, or `.venv`.
