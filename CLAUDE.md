# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

Migration of **3606 AKU news items** from SharePoint to **Storyblok**.

Two independent stages:

| Stage | Converts | Entry point |
|---|---|---|
| **Content pipeline** | SharePoint HTML → Storyblok rich text + story payloads | `scripts/run_pipeline.py` |
| **Taxonomy stage** | Region / Entity / Department → the Storyblok folder tree | `scripts/taxonomy/run_taxonomy.py` |

The content pipeline puts every story flat at `/news/{slug}`. The taxonomy stage
works out the real destination:

```
global/news/{item}                                                 250
Regions/{region}/News/{item}                                      1284
Regions/{region}/Entities/{entity}/News/{item}                    1499
Regions/{region}/Entities/{entity}/Departments/{dept}/News/{item}   573
```

**346 folders · 6 regions · 19 entities · 89 department folders.**

## Read first

| Doc | When |
|---|---|
| `docs/MIGRATION_DECISIONS.md` | any question about structure, regions, entities, departments, or why something is placed where it is |
| `docs/STORYBLOK_COMPONENTS.md` | components, media roles, rich-text schema, special characters |
| `scripts/taxonomy/README.md` | running or changing the taxonomy stage |
| `data/taxonomy/README.md` | what each output file contains |

Do not re-derive facts these already record. If a number here disagrees with the
data, trust the data and update the doc.

## Environment

- **Python 3.10+**, stdlib only for the taxonomy stage. The content pipeline needs
  `beautifulsoup4`, `html5lib`, `requests` (`requirements.txt`).
- Local venv lives **outside** the repo at `../.venv` (Windows:
  `..\.venv\Scripts\python.exe`).
- **Node 20+** and pnpm/npm only for `storyblok-viewer/`.

## Commands

```bash
# taxonomy
python scripts/taxonomy/run_taxonomy.py status     # what exists so far
python scripts/taxonomy/run_taxonomy.py            # all steps in order
python scripts/taxonomy/run_taxonomy.py tree       # one step

# content pipeline
python scripts/run_pipeline.py status
python scripts/run_pipeline.py extract-news
python scripts/run_pipeline.py clean-news

# audit what will be uploaded
python scripts/inventory_storyblok_components.py data/storyblok_component_inventory.json

# tests
python -m pytest tests/
```

## Layout

```
config/         Storyblok API config + region_overrides.csv (hand corrections)
data/
  news.json                 INPUT, tracked
  taxonomy/seed/            folders.json + storyblok_seed.json  <- for the backend
  taxonomy/routing/         per-item destination
  taxonomy/intermediate/    one file per stage, for auditing
  taxonomy/lookups/         city / entity / tag inventories
  news/ cleaned_news/ …     GITIGNORED, regenerate from news.json
docs/           the specs
scripts/        content pipeline (33 scripts)
scripts/taxonomy/   this project's taxonomy stage
```

`scripts/taxonomy/paths.py` is the **only** place directories are defined. Moving
a directory means editing that file and nothing else — never hardcode a path in a
taxonomy script.

## Conventions

- **Slugs**: lowercase-hyphenated, and entities use the **full name**, never the
  abbreviation — `regions/pakistan/entities/medical-college/news/`.
- **Provenance is mandatory.** Any derived field records the rule that produced
  it (`region_source`, `entity_source`, `department_source`). If you add a
  derivation, add its provenance column too.
- **Fail loudly.** The seed builders exit non-zero rather than write a broken
  file. Keep that: validate parents resolve, folders exist, slugs are unique.
- **One script per step.** Each stage is independently re-runnable and auditable.
  Do not merge steps for convenience.
- Match the surrounding style: stdlib only, module docstring explaining *why*,
  comments only where the reasoning is non-obvious.

## Things that will bite you

**No department field exists.** 41 fields in the export, none is a department;
none of the 33 pipeline scripts mentions one. Departments are derived from `Tags`,
so a tag can mean "from this department" or merely "about this subject" and
nothing distinguishes the two. **~40 of the 89 department folders may not
correspond to a real unit.** Never present a department as authoritative.

**Some entities and regions are inferred.** 678 entities were recovered for items
whose `Entity` was `"Global"`; 20 regions could not be read from `City`. Check
`provenance` before treating a placement as fact.

**`Entity = "Global"` means "no faculty owns this"** — it is exactly the set
`LocalApproverGroup = "Global Approvers"` (2048/2048), i.e. central comms
authored. It is not a region and never becomes an entity folder.

**Nine values in the Entity column are not entities** and route to `global/news`:
`Global`, `News training`, `Student Affairs and Services`, `Office of the
Provost`, `Office of the President`, `Office of the Registrar`, `Data Office`,
`Research`, `Library`.

**A story lives in exactly one Storyblok folder.** "Show on global" and "share to
another entity" are reference fields resolved at query time, never a second
folder. 161 stories carry share targets.

**Tag term-store drift**: 228 tag labels, most with 2–4 different `TermGuid`s for
the same label. **Dedupe tags by label, never by GUID.**

**`assets/` is gitignored and absent from a fresh clone.** No media can be
uploaded without it. 70 of 257 rich-text media references were never downloaded,
so 51 stories have broken inline references.

**Known and accepted as-is** (do not "fix" without asking): 67 pairs of true
duplicate stories migrate twice; 108 story slugs carry an appended SharePoint id
to resolve collisions; 3 items keep an odd region because `City` is real source
data and is never overridden by body-text guessing.

## Encoding

Send **UTF-8**. Do not transliterate to ASCII — 711 occurrences across 98
characters are legitimate content (accented names, Arabic/Urdu, `£`, `°`,
transliteration marks). Strip only the invisibles: U+200B (in 3004 of 3606
files), U+FEFF, U+00AD. The 12 U+FFFD replacement characters are unrecoverable
and need a human look.

On Windows, PowerShell 5.1 reads UTF-8 files as ANSI by default — use Python for
any file containing non-ASCII, or box-drawing characters end up mojibake. There
is no heredoc in PowerShell; write long strings to a file instead.

## Git

`.gitignore` excludes the six per-stage story folders (21,636 files, 167 MB) that
the README documents as generated; they rebuild from `data/news.json`. Tracked
size is ~45 MB. Do not commit `assets/`, `config/storyblok.json`, or `.venv`.
