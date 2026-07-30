# The AKU news migration, end to end

What this project is, why it is built the way it is, and where it currently
stands. Read this first; the other docs go deeper on one area each.

| | |
|---|---|
| **Moving** | 3,606 news stories |
| **From** | AKU's SharePoint site (`aku.edu/news`), being retired |
| **To** | Storyblok, space `289824742951963` |
| **Plus** | ~3,900 images, GIFs, PDFs and videos |
| **Into** | 346 folders — Region → Entity → Department |

---

## 1 · The shape of the problem

SharePoint gave us one flat list of 3,606 items with 41 columns of metadata and
a blob of editor-generated HTML per story. Storyblok wants structured content —
typed components, a rich-text document tree, assets referenced by id — filed
into a folder hierarchy that expresses who owns each story.

Nothing in the export says where a story belongs. That had to be derived, and
deriving it is most of the work.

Three problems, in order of difficulty:

**Where does each story live?** No department field exists anywhere in the
export. Regions come from a free-text `City` column. Entity is blank ("Global")
for 2,048 of the 3,606. See §3.

**What are its images?** The export renamed every file on the way out, so
`2198-BannerImage.jpg` gives no clue that the original is
`/news/PublishingImages/CapBanner.jpg`. And the asset bundle itself was lost —
only the renamed manifest survived. See §4.

**What does the content become?** SharePoint HTML carries 26 distinct tags, much
of it Word paste and editor chrome. Storyblok's `news_article` has 16 fields and
a body restricted to a whitelist of components. See §5.

---

## 2 · Architecture

Three stages. Each is independently runnable, resumable, and leaves an audit
trail; none needs the next one to have worked.

```
STAGE 1  content     SharePoint HTML  ->  Storyblok rich text + payloads
STAGE 2  taxonomy    City/Entity/Tags ->  Region / Entity / Department tree
STAGE 3  migration   payloads+assets  ->  live in Storyblok
```

Stage 3 splits again, because the halves fail differently and run at different
times:

```
scripts/migrate/download/   aku.edu -> disk         safe to interrupt, read-only
scripts/migrate/upload/     disk -> Storyblok       writes
scripts/migrate/review/     verification, no writes
```

**Two conventions hold everywhere.** Every derived field records the rule that
produced it — `region_source`, `entity_source`, `department_source` — so a
disputed placement can be traced to either the data or a decision. And every
builder exits non-zero rather than write a file it knows is broken.

---

## 3 · Where each story goes

```
global/news/{story}                                                    250
Regions/{region}/News/{story}                                        1,284
Regions/{region}/Entities/{entity}/News/{story}                      1,499
Regions/{region}/Entities/{entity}/Departments/{dept}/News/{story}     573
```

**346 folders · 6 regions · 60 entity folders (19 distinct) · 89 department
folders.** The tree is owned by the front-end developer and is final; the
migration treats it as read-only and refuses to create anything under `regions/`
or `global/`.

Three things are worth knowing before trusting a placement:

**Departments are inferred from tags.** No department field exists — 41 columns,
none of them a department; none of the 33 stage-1 scripts mentions one. The 89
folders come from 16 tag labels. A tag can mean "from this department" or merely
"about this subject", and nothing distinguishes them, so a public-awareness piece
tagged `Cardiac disease` files under Cardiology.

**678 entities were recovered, not read.** `Entity = "Global"` on 2,048 stories
means no faculty owns it — it is exactly the set with
`LocalApproverGroup = "Global Approvers"`. Two trustworthy rules recovered an
owner for 678: an explicit `AdditionalEntity`, or a tag whose whole label is an
entity name. Prose-matching rules were tried and rejected — roughly half were
wrong.

**A story lives in exactly one folder.** "Show on global" and "share to another
entity" are reference fields resolved at query time, never a second copy.

Full reasoning and every rule: [MIGRATION_DECISIONS.md](MIGRATION_DECISIONS.md).

---

## 4 · The assets, and how they were recovered

The original export bundle — `assets/News/media/` plus its `Metadata.csv`
manifest — was lost before this repo existed. `news_media_report.json` proves all
3,421 files were present when the pipeline first ran.

They were rebuilt from the live site. Two resolution paths, because the export's
renaming destroyed the link back to the source:

- rich-text assets kept a `source_key`, so `https://www.aku.edu{source_key}`
  resolves directly
- banner and medium have no `source_key` and unguessable names, so each story
  page is read once and cached

**Result: 3,902 files, 1.8 GB. 3,400 of 3,610 declared files recovered (94.2%).**

The remaining 210 are not recoverable: 204 never resolved because the page
genuinely renders fewer images than the export declares, and 6 have a URL that
now 404s. Each was re-tested individually. Only the original bundle has them.

`Metadata.csv` was later reconstructed from `asset_map.csv`
(`rebuild_metadata_csv.py`) — 3,421 references, matching the original count
exactly. That restored the pipeline's ability to run end to end from a clone.

**Downloading rather than linking was deliberate.** Uploading straight from
aku.edu would hit the site a second time, story by story, and the rate limiting
that caused 69 timeouts during resolution would return mid-upload — with a
half-finished space to clean up.

---

## 5 · What a story becomes

`news_article`, 16 fields. The body is a `bloks` field restricted to a
whitelist. The layout was signed off against a hand-built reference story and is
documented in [STORYBLOK_TARGET_SCHEMA.md](STORYBLOK_TARGET_SCHEMA.md).

```
description    paragraph 1, MOVED out of the body — it appears once, as the intro
banner_image   uploaded asset
entities       entity FOLDER IDS: own entity + AdditionalEntity share targets
isGlobal       surfaces on global as well as its own entity
languages      article_language_link per real alternate language (Urdu, Sindhi)

body, in document order from paragraph 2:
  rich_text      prose, lists, headings, links, bold/italic/underline/superscript
  image          a single body image, in place: text / image / text
  iframe         a tweet or embed, in place
  quote_banner   every pull quote
  split_section  a quote that arrives with an image
  media_section  type=video for YouTube and hosted video
                 type=gallery for 2+ images, LAST, before featured news
```

**Spacing is mandatory on every blok** and there are exactly three values, read
off the reference story. A blok without one renders with no vertical rhythm.

| | mobile | desktop | Used by |
|---|---|---|---|
| reading column | pad 20 | pad **176** | `rich_text` |
| full bleed | — | — | `quote_banner`, video, `brand_banner` |
| mid width | pad 20 | pad **80** | `image`, `iframe`, `split_section`, gallery |

All with margin-bottom 24 mobile / 56 desktop, `px`.

**Position wins for images.** An image the source ties to a paragraph stays under
that paragraph. Only a *run* of adjacent images becomes a gallery, at that point.
The end gallery collects only images the export never positioned.

Encoding: send UTF-8, never transliterate. 711 occurrences across 98 characters
are legitimate content — accented names, Arabic and Urdu, `£`, `°`. Only
invisibles are stripped: U+200B was in 3,004 of 3,606 files.

---

## 6 · Where it stands

| | |
|---|---|
| Content pipeline | ✅ 3,606 payloads built |
| Taxonomy | ✅ 346 folders, every story routed |
| Folder tree in Storyblok | ✅ created by the front-end developer, 149 destinations verified present |
| Assets on disk | ✅ 3,902 files / 1.8 GB |
| Assets in Storyblok | 50 of ~3,850 |
| Stories in Storyblok | **20 of 3,606** — the review sample |
| Migration runner | ✅ resumable, tested |

The 20 exist so the layout could be judged before 3,606 were committed. Once
signed off, one command does the rest: [../RUN_MIGRATION.md](../RUN_MIGRATION.md).

### Known and accepted

- **Internal links still point at aku.edu.** 566 of them, kept as-is so they can
  be found and replaced once every story has a Storyblok id. A second pass, by
  design — a link cannot resolve to a story that does not exist yet.
- **Two tables are skipped** and rebuilt by hand: stories 1335 and 3288.
- **~208 media are unobtainable**, listed in `reports/assets.csv`.
- **`Pakistan / Arusha Climate and Environmental Research Centre`** gets zero
  stories — Arusha is in Tanzania. Reviewed and kept deliberately; recorded in
  `config/tree_accepted_exceptions.csv`.
- **`Afghanistan / East Africa Institute`** holds one story whose entity was
  inferred. Probably a bad inference. Kept.
- **SharePoint has no buttons.** No `<button>`, no `role="button"`, no `btn`
  class in 3,606 stories — only 19 stories with CTA-worded or CTA-styled links.
  A `button` blok is a new-design decision, not migrated content.

---

## 7 · The other docs

| Doc | For |
|---|---|
| [../RUN_MIGRATION.md](../RUN_MIGRATION.md) | running the migration — one command, resume, reports |
| [HOW_TO_RUN.md](HOW_TO_RUN.md) | every stage and command, in order, from a clone |
| [REQUIRED_FILES.md](REQUIRED_FILES.md) | which files are needed, where each comes from |
| [MIGRATION_DECISIONS.md](MIGRATION_DECISIONS.md) | the taxonomy: every rule and why |
| [STORYBLOK_TARGET_SCHEMA.md](STORYBLOK_TARGET_SCHEMA.md) | the live schema vs what we produce |
| [STORYBLOK_COMPONENTS.md](STORYBLOK_COMPONENTS.md) | components, media roles, characters |
| [STORYBLOK_FIELDS_NEEDED.md](STORYBLOK_FIELDS_NEEDED.md) | what the front end still owes |
| [../CLAUDE.md](../CLAUDE.md) | conventions and the bugs already paid for |
