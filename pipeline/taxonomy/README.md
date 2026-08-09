# Taxonomy stage

Derives **Region → Entity → Department** for all 3606 news items and emits the
Storyblok folder structure.

The main pipeline (`pipeline/`) converts *content*. This stage decides *where each
story goes*. It reads `News-Pipeline/data/cleaned/` and writes `data/taxonomy/`.

Full spec and every decision: [`docs/MIGRATION_DECISIONS.md`](../../docs/MIGRATION_DECISIONS.md).

---

## Run it

```bash
python pipeline/taxonomy/run_taxonomy.py            # all steps, in order
python pipeline/taxonomy/run_taxonomy.py status     # what exists so far
python pipeline/taxonomy/run_taxonomy.py tree       # one step by name
```

Input is `News-Pipeline/data/cleaned/`, which is gitignored. After a fresh clone:

```bash
python pipeline/run_pipeline.py extract-news
python pipeline/run_pipeline.py clean-news
python pipeline/taxonomy/run_taxonomy.py
```

Stdlib only — nothing here needs `requirements.txt`.

---

## Steps

| Step | Script | Produces |
|---|---|---|
| `lookups` | `harvest_lookups.py` | city / entity / tag inventory + drift report |
| `regions` | `build_structure.py` | region per item, with the rule that fired |
| `abbrev` | `build_entity_abbrev.py` | short form per entity, from approver-group names |
| `recover` | `recover_entity.py` | entity for the 2048 items whose `Entity` is `"Global"` |
| `departments` | `build_departments.py` | department per item, derived from `Tags` |
| `crossrefs` | `build_crossrefs.py` | cross-entity share links from `AdditionalEntity` |
| `tree` | `build_folder_tree.py` | folder structure + per-item destination |
| `seed` | `build_seed_json.py` | folders + stories, one JSON for the backend |
| `folders` | `build_folders_only.py` | folders only, for creating the tree |

`tree` needs `regions`, `abbrev`, `recover`, `departments` and `crossrefs`.
`seed` and `folders` need `tree`.

Not part of the pipeline, run on demand:

| Script | Does |
|---|---|
| `export_dev_tree.py` | projects the tree into the front end's nested `region → entities → departments` shape |
| `validate_dev_tree.py` | compares a dev-supplied tree against ours, level by level |

## Short names

**All 155 named folders have one** — 6 regions, 60 entity folders, 89 department
folders. Nothing is null.

| Level | Source | File |
|---|---|---|
| Entity | **derived** from AKU approver-group names | `intermediate/entity_abbrev.csv` (generated) |
| Entity override | for the one with no usable group name | `config/entity_abbrev_overrides.csv` |
| Department | hand-authored — `Tags` carry no abbreviation | `config/department_abbrev.csv` |
| Region | ISO 3166-1 alpha-2 — `City` carries no code | `config/region_abbrev.csv` |

To change one, edit the relevant CSV and re-run `tree`. **Never edit
`folders.json` directly** — it is generated.

**`AERR`** for the Arusha centre looks wrong and is not — it comes from the group
`CA AERR`, so do not "correct" it to ACERC.

Short names are emitted as codes: **whitespace is hyphenated on the way out**, so
AKU's `COE WCH` becomes `COE-WCH`. Edit the CSVs to match AKU's real wording; the
builder handles the normalising.

Each folder ends up with `region_short`, `entity_short`, `department_short`, and a
`short_name` resolving to the deepest level it names.

Each step is a separate script on purpose: any one can be re-run and audited
alone, and every derived field records which rule produced it
(`region_source`, `entity_source`, `department_source`).

---

## Other files

| File | Purpose |
|---|---|
| `paths.py` | every input and output location; move a directory, edit this only |
| `resolve_taxonomy.py` | the original exploratory script. **Not in the chain** — kept because `build_departments.py` imports its `DEPARTMENTS` vocabulary |
| `resolve_taxonomy_sample.py` | random-sample variant of the above, for spot checks |
| `fetch_sp_lookups.py` | pulls authoritative lookup lists from SharePoint. **Not in the chain** — needs `SP_COOKIE` / `SP_TOKEN` and network. Use it if AKU ever exposes a Departments list |

---

## Two things to know before changing anything

**Departments are inferred.** No department field exists anywhere in the export —
41 fields, none of them a department, and none of the 33 main-pipeline scripts
mentions one. Departments come from `Tags`, so a tag can mean "from this
department" or merely "about this subject" and nothing distinguishes the two.
Roughly 40 of the 89 department folders may not correspond to a real unit.

**Some entities and regions are inferred too.** 678 entities were recovered for
items that had none, and 20 regions could not be read from the `City` field. The
`provenance` block on every story in the seed says which — check it before
treating a placement as authoritative.
