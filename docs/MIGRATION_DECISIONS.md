# AKU News — SharePoint → Storyblok Migration

Where each of the 3606 news items goes, and how its region, entity and
department were determined.

**Status: complete.** Every item has a destination, every folder is defined, the
folder-only seed and the full seed are generated and validated. Nothing is
outstanding.

Last updated: 2026-07-28

---

## 1. Structure

**parent (region) → child (entity) → child (department)**

`Regions`, `Entities` and `Departments` are folders. Each level below region is
optional and is skipped when unknown; a department only ever sits under an entity.

```
global/news/{item}                                                 250

Regions/{region}/News/{item}                                      1284
Regions/{region}/Entities/{entity}/News/{item}                    1499
Regions/{region}/Entities/{entity}/Departments/{dept}/News/{item}   573
                                                             TOTAL 3606
```

- `News` is a **literal folder name** at every level. Siblings (`blogs`,
  `articles`) come later.
- **No sub-department level.**
- **No department directly under a region** — region news is flat.
- `global/` is flat: no entities, no departments.

`Regions/{region}/News/` exists because 1284 items have a region but no entity
establishable from any field (§3.3). They are region news with no owning
faculty — global for that region only. They can still be shared (§6).

### Totals

**346 folders · 6 regions · 19 entities · 60 region×entity nodes · 89 department folders**

| Level | Folders |
|---|---|
| root (`global`, `Regions`) | 2 |
| region | 6 |
| entities-root | 6 |
| entity | 60 |
| departments-root | 32 |
| department | 89 |
| news | 151 |

| Region | Items | Entities | region `/News/` | entity | entity+dept |
|---|---|---|---|---|---|
| Pakistan | 2188 | 17 | 1132 | 732 | 318 |
| Kenya | 651 | 13 | 88 | 360 | 200 |
| Tanzania | 234 | 14 | 29 | 179 | 23 |
| United Kingdom | 205 | 3 | 4 | 197 | 4 |
| Uganda | 76 | 8 | 20 | 29 | 26 |
| Afghanistan | 15 | 4 | 11 | 2 | 2 |
| `global/news/` | 250 | — | — | — | — |

---

## 1a. The vocabularies

### Regions — 6 countries + Global

| Region | Items | Entities |
|---|---|---|
| Pakistan | 2188 | 17 |
| Kenya | 651 | 13 |
| Tanzania | 234 | 14 |
| United Kingdom | 205 | 3 |
| Uganda | 76 | 8 |
| Afghanistan | 15 | 4 |
| *Global* (→ `global/news`, not a `Regions/` folder) | 237 | — |

### Entities — 19

Long form is used in URLs; short form is for identification only.

| Short | Long | Items | Regions |
|---|---|---|---|
| MC | Medical College | 473 | Afghanistan, Kenya, Pakistan, Tanzania, Uganda |
| IED | Institute for Educational Development | 343 | Afghanistan, Kenya, Pakistan, Tanzania, Uganda |
| SONAM | School of Nursing and Midwifery | 308 | Kenya, Pakistan, Tanzania, Uganda, United Kingdom |
| ISMC | Institute for the Study of Muslim Civilisations | 204 | Kenya, Pakistan, Tanzania, United Kingdom |
| CIME | Centre for Innovation in Medical Education | 197 | Kenya, Pakistan, Tanzania |
| GSMC | Graduate School of Media and Communications | 151 | Kenya, Pakistan, Tanzania, Uganda |
| QTL | Networks of Quality, Teaching and Learning | 66 | Kenya, Pakistan, Tanzania, Uganda, United Kingdom |
| EAI | East Africa Institute | 62 | Afghanistan, Kenya, Tanzania, Uganda |
| BMI | Brain and Mind Institute | 56 | Kenya, Pakistan, Tanzania |
| COE WCH | Centre of Excellence in Women and Child Health | 37 | Kenya, Pakistan, Uganda |
| IHD | Institute for Human Development | 36 | Afghanistan, Kenya, Pakistan, Tanzania, Uganda |
| IGHD | Institute for Global Health and Development | 34 | Pakistan |
| AERR | Arusha Climate and Environmental Research Centre | 30 | Pakistan, Tanzania |
| ELE | Network of English Language Enhancement | 19 | Kenya, Pakistan, Tanzania |
| CRM | Centre for Regenerative Medicine and Stem Cell Research | 16 | Pakistan |
| *(none)* | Environmental Responsibility | 14 | Kenya, Pakistan, Tanzania |
| FAS | Faculty of Arts and Sciences | 10 | Pakistan |
| SIG | Surgery Interest Group | 9 | Pakistan, Tanzania |
| CETE | Centre of Excellence for Trauma and Emergencies | 7 | Pakistan |

`Environmental Responsibility` has no abbreviation in the source and uses its
full name (§3.2). Entity counts include items reaching the entity through a
department, so they exceed the direct `/News/` counts in §1.

### Departments — 16 names, 89 folders

Scoped per region + entity, so one name yields several folders.

| Department | Items | Folders | Under entities |
|---|---|---|---|
| Medical Education | 112 | 9 | BMI, CIME, IED, MC, SONAM |
| Paediatrics & Child Health | 106 | 13 | CIME, COE WCH, IED, IGHD, IHD, MC, SONAM |
| Nursing | 96 | 10 | CETE, CIME, IED, MC, SONAM |
| Psychiatry & Mental Health | 69 | 15 | BMI, EAI, FAS, IED, IHD, ISMC, MC, SONAM |
| Midwifery | 68 | 8 | CIME, IED, QTL, SONAM |
| Public Health | 33 | 8 | BMI, COE WCH, EAI, IED, MC, SONAM |
| Oncology | 26 | 5 | CRM, MC, SONAM |
| Regenerative Medicine | 16 | 2 | CRM, MC |
| Nutrition | 10 | 5 | EAI, IGHD, IHD, MC, SONAM |
| Cardiology | 8 | 1 | MC |
| Internal Medicine | 7 | 2 | CIME, MC |
| Family Medicine | 6 | 3 | CIME, MC |
| Neurosurgery | 6 | 2 | CIME, MC |
| Obstetrics & Gynaecology | 5 | 2 | CIME, MC |
| Governance | 3 | 3 | GSMC, ISMC, SONAM |
| Geriatrics & Gerontology | 2 | 1 | SONAM |

---

## 2. Region = country

14 city values → 6 countries plus `Global`:

| Region | Cities |
|---|---|
| Pakistan | Karachi, Islamabad, Lahore |
| Kenya | Nairobi, Mombasa, Limuru |
| Tanzania | Dar es Salaam, Arusha, Dodoma |
| Uganda | Kampala |
| Afghanistan | Kabul |
| United Kingdom | London |
| Global | city literally "Global" |

Resolution in priority order. Every row records which rule fired in
`region_source`, so any assignment can be audited or reversed.

| # | `region_source` | Items | Rule |
|---|---|---|---|
| 1 | `entity-suffix` | 408 | A region in the entity name beats the city — the tree records **ownership**, not event location. `Medical College, Pakistan` is Pakistan's even if the event was in Arusha. |
| 2 | `city` | 2949 | City → country. |
| 3 | `city-global` | 197 | City is literally "Global". |
| 4 | `entity-global` | 26 | No owning entity and no country → Global. |
| 5 | `entity-majority` | 6 | Entity's located news is ≥60% in one region. **Inferred.** |
| 6 | `fallback-global` | 14 | No country determinable (Portugal, Mozambique, West Africa, Asia). |
| 7 | `hand-corrected` | 6 | `region_overrides.csv` — 5 Kilifi County items → Kenya, 1 Uganda item → Uganda. All were `entity-majority` guesses the titles contradicted. |

**100% of items have a region.** A region taken from the `City` field is real
source data and is never overridden.

---

## 3. Entities

**19 entities**, after stripping the `, Pakistan` / `, East Africa` suffix from
the name and lifting it to the region level — that is what makes
`Medical College` one entity across regions instead of several. 4 exist in more
than one region: `Medical College`, `School of Nursing and Midwifery`,
`Institute for Educational Development`, `Faculty of Arts and Sciences`.

### 3.1 Values in the Entity column that are NOT entities

No folder. Their news goes to `global/news`; a cross-reference to one is a share
to `global/news`:

`Global` · `News training` · `Student Affairs and Services` ·
`Office of the Provost` · `Office of the President` · `Office of the Registrar` ·
`Data Office` · `Research` · `Library`

### 3.2 Short form ↔ long form

No abbreviation field exists in the export, but `LocalApproverGroup` is 1:1 with
`Entity` and uses AKU's own shorthand (`MC_PK_NEWS_Approver`,
`Sonam EA News Approver`). Stripping the boilerplate recovers 18. **Nothing is
guessed** — `Environmental Responsibility` has no recovered abbreviation and uses
its full name. Sheet: `out_final/entity_abbrev.csv`.

MC · SONAM · CIME · ISMC · IED · GSMC · BMI · QTL · EAI · COE WCH · ELE · IHD ·
IGHD · CRM · SIG · CETE · FAS · AERR

Short forms are for identification only. **URLs use the full form** —
`regions/pakistan/entities/medical-college/news/`.

### 3.3 Entity recovery for the no-owner items

2048 items have `Entity = "Global"` — no faculty assigned. That value is exactly
the set `LocalApproverGroup = "Global Approvers"` (2048/2048), so it genuinely
means "no faculty owns this": these were authored by the central comms team.

Every other field was checked for a hidden entity:

| Rule | Items | Used |
|---|---|---|
| `additional-entity` — explicit lookup naming one real entity | 347 | ✅ |
| `tag-exact` — a tag whose whole label is an entity name or abbreviation | 284 | ✅ |
| `additional-entity-first-of-many` — several refs; **first is owner, rest stay shares** | 86 | ✅ |
| `tag-exact-ambiguous` — two entity tags; **first is owner** | 18 | ✅ |
| `prose-name` — entity name in title or body | 315 | ❌ |

**678 recovered.** 1370 left with no entity, 21 whose value was not an entity.

Prose was rejected because roughly half are wrong — 194 of 266 rest on a single
passing mention, e.g. *"Independence Day celebrations at AKU"* → Medical College,
*"First Aga Khan University graduation in Uganda"* → ISMC (London). Since
departments sit under entities, a wrong entity misfiles both.

Recovery **never changes the region**: `City = Karachi` stays Pakistan, and the
entity is stored in its base form.

---

## 4. Departments

**There is no department field in the source.** Verified two ways: a field
inventory of all 3606 items (41 fields, none named department / faculty / unit /
division / specialty) and a grep of all 33 existing pipeline scripts (zero
mentions). `LocalApproverGroup` maps to *entity*, not department.

**Decision: derive from `Tags`** (populated on 3606/3606) so AKU has a real number
to work from. Where nothing is found, skip the level.

### 16 departments, no duplication

Many tag labels collapse to one canonical name — `Cardiac disease`,
`heart diseases` and `Heart diseases` all become a single **Cardiology** folder.
Verified: no two department names slugify to the same value.

Cardiology · Family Medicine · Geriatrics & Gerontology · Governance ·
Internal Medicine · Medical Education · Midwifery · Neurosurgery · Nursing ·
Nutrition · Obstetrics & Gynaecology · Oncology · Paediatrics & Child Health ·
Psychiatry & Mental Health · Public Health · Regenerative Medicine

### Scoped per entity

Each region+entity has its own departments, each with its own permissions — so
16 department names yield **89 department folders**. All 89 are created, including
those with 1–2 items.

### Exclusions

- **`Office of the President`** removed from the vocabulary — it is an entity
  value, not a department. Left in, the `President's Office` tag (39 uses) created
  `Pakistan/Office of the President/Departments/Office of the President/News`.
- **9 tag labels blocked** because they are entity names, not departments:
  `School of Nursing and Midwifery` (317 uses), `Institute for Educational
  Development` (242), `Institute for the Study of Muslim Civilisations` (196),
  `Centre for Innovation in Medical Education` (168), `Graduate School of Media
  and Communications` (151), `Networks of Quality, Teaching and Learning` (15).
  Unblocked they re-derive the entity as its own child — `Kenya > SONAM >
  Midwifery`, where the tag added nothing.

### No sub-departments

Not derivable. Tags are one flat namespace of 281 labels mixing entity names
(`medical college` 221), countries (`Kenya` 136), diseases (`Dengue` 41) and
generic words (`Research` 760, `aku` 267), with case-variant duplicates.

---

## 5. Routing rules

0. Entity value is not an entity (§3.1) → `global/news/{item}`
1. No country → `global/news/{item}`, whether or not an entity is known
   — rules 0 + 1: **250**
2. Country + entity + department →
   `Regions/{r}/Entities/{e}/Departments/{d}/News/` — **573**
3. Country + entity, no department →
   `Regions/{r}/Entities/{e}/News/` — **1499**
4. Country, no entity → `Regions/{r}/News/` — **1284**

The **`global` flag is separate from the folder**: it controls whether an item
also surfaces on the global site. **1244 items** carry it.

---

## 6. Relations / sharing

A story can appear under other entities (or entity + department), view-only.
Region-level news can be shared too.

**Storyblok constraint:** a story lives in exactly one folder with one
`full_slug`, so it cannot physically exist in two places. Sharing is a
**reference field on the story**, resolved at query time; the folder tree carries
the **owning** entity only.

Source: `AdditionalEntity`. A reference that became the owner is dropped — a
story is not shared with itself. After that **161 stories carry share targets**,
up to 5 each. A target resolves to that entity's `News` folder; references to a
non-entity or with no resolvable country resolve to `global/news`. Every
share-target folder is created even when it owns no news of its own.

---

## 7. Slugs

Lowercase-hyphenated, **full entity name, never the abbreviation**:

```
regions/pakistan/entities/medical-college/departments/cardiology/news/{story}
```

**108 story-slug collisions resolved.** Storyblok requires a unique slug within a
folder, so where two stories share a title in one folder the SharePoint id is
appended to the later one — the same tie-break the existing pipeline uses. Logged
in `out_tree/_slug_collisions.csv`.

---

## 8. Migrating as-is — known approximations

Decided: do not correct. Recorded so they are known.

| What | Scale | Note |
|---|---|---|
| True duplicate stories | 67 groups | Same title **and** identical body (`1008/1538`, `106/1523`; some groups have three). Both copies migrate at different slugs. A further 67 groups share a title but differ in body and are legitimately distinct. |
| Department assignment | 573 items | Tag-derived. A tag can mean "from this department" or merely "about this subject" and nothing distinguishes them, so a public-awareness piece tagged `Cardiac disease` files under Cardiology. Concentrated in the 1–2 item folders; ~40 of 89 may be fictional. |
| City-driven oddities | 3 items | `365` Afghanistan/IED, `351` Afghanistan/IHD read as East Africa; `2385` Tanzania/SIG reads as Pakistan. Region comes from the real `City` field, so left alone. |
| Thin entity nodes | ~10 | `Kenya/ISMC` (1), `United Kingdom/QTL` (1), `Tanzania/CIME` (1). Each becomes a real permission scope. `Tanzania/CIME` is **genuine** — *"CIME Inaugurates New Campus in Dar es Salaam"*. |
| `entity-majority` region | 6 items | Still inferred after the 6 corrections in §2. |
| `fallback-global` region | 14 items | Genuinely not tied to one country. |
| Tag term-store drift | 228 labels | Most carry 2–4 `TermGuid`s for the same label. Dedupe by **label**, never by GUID. |

---

## 9. Outputs

### Folder creation — backend

`out_folders/`

| File | Contents |
|---|---|
| **`folders.json`** | 483 KB — `meta` + flat ordered `folders` + nested `tree`. No stories. |
| **`folders_tree.txt`** | ASCII tree |
| **`folders.csv`** | the flat list as a spreadsheet |

The flat list is ordered **parent before child** — walk it once and resolve
`parent_full_slug` against folders already created. Each folder carries
`region` / `entity` / `entity_short` / `department` for metadata and permissions.
`expected_news_count` is informational; 32 folders are legitimately 0
(`Departments/` wrappers and entities whose news all sits in departments).

### Full seed — folders + stories

`out_tree/storyblok_seed.json` (3.1 MB) — the same 346 folders plus 3606 stories
with `full_slug`, `folder_full_slug`, region/entity/department,
`surface_global`, `shared_folder_full_slugs` and `provenance`
(`region_source`, `entity_source` — so a disputed placement can be traced to
either the data or a rule).

### Review

| File | Contents |
|---|---|
| `out_tree/folder_tree.txt` | tree with per-folder item counts |
| `out_tree/story_paths.csv` | `story_id, name, sb_path, shared_path_1–5` |
| `out_tree/news_routing.csv` | the above plus region / entity / department / provenance |
| `out_tree/_slug_collisions.csv` | the 108 suffixed slugs |
| `out_final/entity_abbrev.csv` | 19 entities: short form, long form, approver groups |
| `out_recover/recovered_entities.csv` | every recovery candidate with rule + evidence |
| `out_dept/_items_departments.csv` | per-item department + which tag fired |
| `region_overrides.csv` | the 6 hand corrections |

### Validation

Both seed files fail hard rather than emit a broken structure. Confirmed:
every folder parent resolves and precedes its child · no duplicate folder slugs ·
every story's folder exists · every share target exists · no duplicate story
slugs · no uppercase in any slug · placements sum to 3606 · the folder-only and
full seed contain identical folder sets.

### Run order

```
build_structure.py       region per item
harvest_lookups.py       city / entity / tag inventory
build_entity_abbrev.py   short form per entity
recover_entity.py        entity for the no-owner items
build_departments.py     department from tags
build_crossrefs.py       cross-entity share links
build_folder_tree.py     folder structure + story paths
build_seed_json.py       -> out_tree/storyblok_seed.json
build_folders_only.py    -> out_folders/folders.json  (folders only)
```

---

## 10. Folder tree

346 folders. Also at `out_folders/folders_tree.txt`; as data in
`out_folders/folders.json` and `out_folders/folders.csv`.

Display names are shown. Slugs are the lowercase-hyphenated form
(`Medical College` -> `medical-college`, `Psychiatry & Mental Health` -> `psychiatry-mental-health`).

```
├── global/
│   └── news/
└── Regions/
    ├── Afghanistan/
    │   ├── Entities/
    │   │   ├── East Africa Institute/
    │   │   │   └── Departments/
    │   │   │       └── Public Health/
    │   │   │           └── News/
    │   │   ├── Institute for Educational Development/
    │   │   │   └── News/
    │   │   ├── Institute for Human Development/
    │   │   │   └── News/
    │   │   └── Medical College/
    │   │       └── Departments/
    │   │           └── Medical Education/
    │   │               └── News/
    │   └── News/
    ├── Kenya/
    │   ├── Entities/
    │   │   ├── Brain and Mind Institute/
    │   │   │   ├── Departments/
    │   │   │   │   ├── Medical Education/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Psychiatry & Mental Health/
    │   │   │   │   │   └── News/
    │   │   │   │   └── Public Health/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Centre for Innovation in Medical Education/
    │   │   │   ├── Departments/
    │   │   │   │   ├── Medical Education/
    │   │   │   │   │   └── News/
    │   │   │   │   └── Nursing/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Centre of Excellence in Women and Child Health/
    │   │   │   ├── Departments/
    │   │   │   │   ├── Paediatrics & Child Health/
    │   │   │   │   │   └── News/
    │   │   │   │   └── Public Health/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── East Africa Institute/
    │   │   │   ├── Departments/
    │   │   │   │   ├── Nutrition/
    │   │   │   │   │   └── News/
    │   │   │   │   └── Psychiatry & Mental Health/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Environmental Responsibility/
    │   │   │   └── News/
    │   │   ├── Graduate School of Media and Communications/
    │   │   │   ├── Departments/
    │   │   │   │   └── Governance/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Institute for Educational Development/
    │   │   │   └── News/
    │   │   ├── Institute for Human Development/
    │   │   │   ├── Departments/
    │   │   │   │   ├── Nutrition/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Paediatrics & Child Health/
    │   │   │   │   │   └── News/
    │   │   │   │   └── Psychiatry & Mental Health/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Institute for the Study of Muslim Civilisations/
    │   │   │   └── News/
    │   │   ├── Medical College/
    │   │   │   ├── Departments/
    │   │   │   │   ├── Internal Medicine/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Medical Education/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Nursing/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Obstetrics & Gynaecology/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Oncology/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Paediatrics & Child Health/
    │   │   │   │   │   └── News/
    │   │   │   │   └── Psychiatry & Mental Health/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Network of English Language Enhancement/
    │   │   │   └── News/
    │   │   ├── Networks of Quality, Teaching and Learning/
    │   │   │   ├── Departments/
    │   │   │   │   └── Midwifery/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   └── School of Nursing and Midwifery/
    │   │       ├── Departments/
    │   │       │   ├── Governance/
    │   │       │   │   └── News/
    │   │       │   ├── Midwifery/
    │   │       │   │   └── News/
    │   │       │   ├── Nursing/
    │   │       │   │   └── News/
    │   │       │   ├── Oncology/
    │   │       │   │   └── News/
    │   │       │   └── Psychiatry & Mental Health/
    │   │       │       └── News/
    │   │       └── News/
    │   └── News/
    ├── Pakistan/
    │   ├── Entities/
    │   │   ├── Arusha Climate and Environmental Research Centre/
    │   │   │   └── News/
    │   │   ├── Brain and Mind Institute/
    │   │   │   ├── Departments/
    │   │   │   │   ├── Psychiatry & Mental Health/
    │   │   │   │   │   └── News/
    │   │   │   │   └── Public Health/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Centre for Innovation in Medical Education/
    │   │   │   ├── Departments/
    │   │   │   │   ├── Family Medicine/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Internal Medicine/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Medical Education/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Midwifery/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Neurosurgery/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Nursing/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Obstetrics & Gynaecology/
    │   │   │   │   │   └── News/
    │   │   │   │   └── Paediatrics & Child Health/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Centre for Regenerative Medicine and Stem Cell Research/
    │   │   │   ├── Departments/
    │   │   │   │   ├── Oncology/
    │   │   │   │   │   └── News/
    │   │   │   │   └── Regenerative Medicine/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Centre of Excellence for Trauma and Emergencies/
    │   │   │   ├── Departments/
    │   │   │   │   └── Nursing/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Centre of Excellence in Women and Child Health/
    │   │   │   ├── Departments/
    │   │   │   │   ├── Paediatrics & Child Health/
    │   │   │   │   │   └── News/
    │   │   │   │   └── Public Health/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Environmental Responsibility/
    │   │   │   └── News/
    │   │   ├── Faculty of Arts and Sciences/
    │   │   │   ├── Departments/
    │   │   │   │   └── Psychiatry & Mental Health/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Graduate School of Media and Communications/
    │   │   │   └── News/
    │   │   ├── Institute for Educational Development/
    │   │   │   ├── Departments/
    │   │   │   │   ├── Medical Education/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Midwifery/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Nursing/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Paediatrics & Child Health/
    │   │   │   │   │   └── News/
    │   │   │   │   └── Public Health/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Institute for Global Health and Development/
    │   │   │   ├── Departments/
    │   │   │   │   ├── Nutrition/
    │   │   │   │   │   └── News/
    │   │   │   │   └── Paediatrics & Child Health/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Institute for Human Development/
    │   │   │   └── Departments/
    │   │   │       └── Paediatrics & Child Health/
    │   │   │           └── News/
    │   │   ├── Institute for the Study of Muslim Civilisations/
    │   │   │   └── News/
    │   │   ├── Medical College/
    │   │   │   ├── Departments/
    │   │   │   │   ├── Cardiology/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Family Medicine/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Medical Education/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Neurosurgery/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Nursing/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Nutrition/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Oncology/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Paediatrics & Child Health/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Psychiatry & Mental Health/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Public Health/
    │   │   │   │   │   └── News/
    │   │   │   │   └── Regenerative Medicine/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Network of English Language Enhancement/
    │   │   │   └── News/
    │   │   ├── Networks of Quality, Teaching and Learning/
    │   │   │   └── News/
    │   │   ├── School of Nursing and Midwifery/
    │   │   │   ├── Departments/
    │   │   │   │   ├── Geriatrics & Gerontology/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Medical Education/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Midwifery/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Nursing/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Nutrition/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Oncology/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Paediatrics & Child Health/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Psychiatry & Mental Health/
    │   │   │   │   │   └── News/
    │   │   │   │   └── Public Health/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   └── Surgery Interest Group/
    │   │       └── News/
    │   └── News/
    ├── Tanzania/
    │   ├── Entities/
    │   │   ├── Arusha Climate and Environmental Research Centre/
    │   │   │   └── News/
    │   │   ├── Brain and Mind Institute/
    │   │   │   ├── Departments/
    │   │   │   │   └── Psychiatry & Mental Health/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Centre for Innovation in Medical Education/
    │   │   │   └── News/
    │   │   ├── East Africa Institute/
    │   │   │   └── News/
    │   │   ├── Environmental Responsibility/
    │   │   │   └── News/
    │   │   ├── Graduate School of Media and Communications/
    │   │   │   └── News/
    │   │   ├── Institute for Educational Development/
    │   │   │   ├── Departments/
    │   │   │   │   └── Psychiatry & Mental Health/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Institute for Human Development/
    │   │   │   ├── Departments/
    │   │   │   │   └── Psychiatry & Mental Health/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Institute for the Study of Muslim Civilisations/
    │   │   │   └── News/
    │   │   ├── Medical College/
    │   │   │   ├── Departments/
    │   │   │   │   ├── Family Medicine/
    │   │   │   │   │   └── News/
    │   │   │   │   └── Paediatrics & Child Health/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Network of English Language Enhancement/
    │   │   │   └── News/
    │   │   ├── Networks of Quality, Teaching and Learning/
    │   │   │   └── News/
    │   │   ├── School of Nursing and Midwifery/
    │   │   │   ├── Departments/
    │   │   │   │   ├── Midwifery/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Nursing/
    │   │   │   │   │   └── News/
    │   │   │   │   ├── Paediatrics & Child Health/
    │   │   │   │   │   └── News/
    │   │   │   │   └── Psychiatry & Mental Health/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   └── Surgery Interest Group/
    │   │       └── News/
    │   └── News/
    ├── Uganda/
    │   ├── Entities/
    │   │   ├── Centre of Excellence in Women and Child Health/
    │   │   │   └── News/
    │   │   ├── East Africa Institute/
    │   │   │   └── News/
    │   │   ├── Graduate School of Media and Communications/
    │   │   │   └── News/
    │   │   ├── Institute for Educational Development/
    │   │   │   └── News/
    │   │   ├── Institute for Human Development/
    │   │   │   └── Departments/
    │   │   │       └── Psychiatry & Mental Health/
    │   │   │           └── News/
    │   │   ├── Medical College/
    │   │   │   ├── Departments/
    │   │   │   │   └── Medical Education/
    │   │   │   │       └── News/
    │   │   │   └── News/
    │   │   ├── Networks of Quality, Teaching and Learning/
    │   │   │   └── News/
    │   │   └── School of Nursing and Midwifery/
    │   │       ├── Departments/
    │   │       │   ├── Midwifery/
    │   │       │   │   └── News/
    │   │       │   ├── Nursing/
    │   │       │   │   └── News/
    │   │       │   └── Paediatrics & Child Health/
    │   │       │       └── News/
    │   │       └── News/
    │   └── News/
    └── United Kingdom/
        ├── Entities/
        │   ├── Institute for the Study of Muslim Civilisations/
        │   │   ├── Departments/
        │   │   │   ├── Governance/
        │   │   │   │   └── News/
        │   │   │   └── Psychiatry & Mental Health/
        │   │   │       └── News/
        │   │   └── News/
        │   ├── Networks of Quality, Teaching and Learning/
        │   │   └── News/
        │   └── School of Nursing and Midwifery/
        │       └── Departments/
        │           └── Midwifery/
        │               └── News/
        └── News/
```
