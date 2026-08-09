# The AKU content migration, end to end

What this project is, why it is built the way it is, and where it currently
stands. Read this first; the other docs go deeper on one area each.

| | |
|---|---|
| **Moving** | news, blogs, events and pages |
| **From** | AKU's SharePoint site, being retired |
| **To** | Storyblok, space `289824742951963` |
| **Into** | Region → Entity → Department, a different leaf folder per type |

| Type | Status |
|---|---|
| **news** | **3,606 stories live**, plus ~3,900 images, GIFs, PDFs and videos |
| **blogs** | awaiting its export |
| **events** | awaiting its export |
| **pages** | own stage — `Pages-Pipeline/` |

Everything below describes news, because news is the one that has been run end
to end. Blogs and events follow the same three stages with their own profile in
`config/types/`; what differs is listed in §2.

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

Four migrations, one codebase. News, blogs and events are the same job over
different SharePoint lists; pages is a different shape and keeps its own stage.

```
pipeline/              ONE codebase, selected with --type
News-Pipeline/         data/ assets/ backup/     3,606 stories, migrated
Blogs-Pipeline/        data/ assets/ backup/     awaiting its export
Events-Pipeline/       data/ assets/ backup/     awaiting its export
Pages-Pipeline/        data/ build/ out/ portal/ structure, not content
config/types/*.json    what differs per type
```

**No script in `pipeline/` is named for a content type.** Four steps and seven
scripts carried "news" in their names while running blogs and events through
identical code. Renamed; the old step names still work and print a note. See
[HOW_TO_RUN.md](HOW_TO_RUN.md).

**The data is separated; the code is not.** Duplicating 74 scripts per type
would mean fixing every bug three times and watching the copies drift. Sharing
them without separating the data would mean one `data/` folder that silently
means "whatever ran last". `pipeline/paths_root.py` is the seam.

### What differs per type, and where

Each type has a profile in `config/types/`. Nothing about a type is expressed as
a branch through the pipeline; it is a value in a file.

| | Lives in | Because |
|---|---|---|
| **Hierarchy** | `hierarchy.patterns` | each type lands in its own leaf folder — `news`, `blogs`, `events` — and may use fewer levels |
| **Source URLs** | `source_urls` | where the type lives *on aku.edu*, which is not where it lands in Storyblok |
| **Components** | `storyblok.component`, `body_whitelist` | a blog or an event need not be a `news_article`, and its body may allow different bloks |
| **Layout** | `layout` | which blok each kind of source content becomes, and the spacing for each |
| **Source columns** | `fields` | a different list names things differently; map them rather than doctoring the export |

`source_urls` and `hierarchy.leaf` are the pair most easily confused. One is the
path SharePoint serves the item under, the detail page its internal links point
at (`news_details.aspx?nid=NEWS-1234`) and the shape of that id; the other is the
Storyblok folder it lands in. **They are identical for news** — which is exactly
how a hardcoded `/news` survived in `build_link_map.py` long after everything
around it had been made generic. Get `source_urls` wrong for a new type and every
internal cross-link silently fails to resolve, staying pointed at a site that is
being switched off. `new_type.py --check` counts how many real links in the export
match, so the answer is a number rather than a hope.

Adding a type is a new JSON file, not a new pipeline.

```
news    -> regions/pakistan/entities/medical-college/departments/cardiology/news
blogs   -> regions/pakistan/entities/medical-college/departments/cardiology/blogs
events  -> regions/pakistan/entities/medical-college/departments/cardiology/events
```

### Adding one

```bash
python pipeline/new_type.py --list             # what exists now
python pipeline/new_type.py articles           # profile + folders + README
#   ... put the export at Articles-Pipeline/data/articles.json ...
python pipeline/new_type.py articles --check   # profile vs the real export
```

`new_type.py` copies `config/types/_TEMPLATE.json`, which is annotated with a
CONFIRM marker on every value that is a guess until someone checks it. Three
guesses fail silently rather than loudly, so `--check` exists to catch the worst
of them:

| Wrong value | Symptom |
|---|---|
| `fields.body` | every item migrates **blank** — no error at all |
| `fields.*` | that field is empty, quietly |
| `source_urls` | every internal cross-link stays pointed at aku.edu |
| `storyblok.component` | rejected, or worse, accepted into the wrong shape |
| `hierarchy.leaf` | the upload stops, asking for a folder nobody has |

`--check` reads the real export and reports which profile keys name a column that
does not exist, suggesting near matches. It found `summary: "Summary"` in the
news profile when the column is `NewsSummary` — after the migration had already
run. It also counts how many of the export's actual links match `source_urls`
(news: 119 match the detail page, 149 the prefix), so a wrong guess shows up as a
zero rather than as silence.

`storyblok.component` is the one thing it cannot check; read the live space with
`pipeline/fetch_storyblok_space.py` before the first upload.

### The three stages

```
STAGE 1  content     SharePoint HTML  ->  Storyblok rich text + payloads
STAGE 2  taxonomy    City/Entity/Tags ->  Region / Entity / Department tree
STAGE 3  migration   payloads+assets  ->  live in Storyblok
```

Stage 3 splits again, because the halves fail differently and run at different
times:

```
pipeline/migrate/download/   aku.edu -> disk         safe to interrupt, read-only
pipeline/migrate/upload/     disk -> Storyblok       writes
pipeline/migrate/review/     verification, no writes
```

**Two conventions hold everywhere.** Every derived field records the rule that
produced it — `region_source`, `entity_source`, `department_source` — so a
disputed placement can be traced to either the data or a decision. And every
builder exits non-zero rather than write a file it knows is broken.

### Backups

Both ends of the migration are snapshotted, because the question that keeps
arising is "did the migration do this, or was it always like that?" and a diff
answers it where argument does not.

```bash
python pipeline/migrate/review/backup.py --type news
```

* `backup/raw/` — the SharePoint export as it arrived. The site is being
  retired, so once it is gone this is the only record of the original content.
* `backup/storyblok/` — every story read back from the API, not assumed from
  what was sent.

`--verify` compares the newest snapshot against the live space and reports what
has changed, moved or been deleted since.

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

The original export bundle — `News-Pipeline/assets/News/media/` plus its `Metadata.csv`
manifest — was lost before this repo existed. `news_media_report.json` proves all
3,421 files were present when the pipeline first ran.

They were rebuilt from the live site. Two resolution paths, because the export's
renaming destroyed the link back to the source:

- rich-text assets kept a `source_key`, so `https://www.aku.edu{source_key}`
  resolves directly
- banner and medium have no `source_key` and unguessable names, so each story
  page is read once and cached

**Result: 3,902 files, 1.8 GB. 3,400 of 3,610 declared files recovered (94.2%).**

The remaining 206 are not recoverable: most never resolved because the page
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
                 a LONE image stays inside it, in place: text / image / text
  iframe         a tweet or embed, in place
  quote_banner   every pull quote
  split_section  a quote that arrives with an image
  media_section  type=video for YouTube and hosted video
                 type=gallery for a run of 2+ images, at that point in the body
                 one closing gallery for images the body never positioned
```

A lone image stays *inside* the rich text rather than becoming a standalone
`image` blok, which renders it far too large for what is really a mid-article
illustration.

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

**News is complete.** Every figure below was read back from the API after the
run, not inferred from what was sent.

| | |
|---|---|
| Content pipeline | ✅ 3,606 payloads built |
| Taxonomy | ✅ 346 folders, every story routed |
| Folder tree in Storyblok | ✅ created by the front-end developer, 149 destinations verified present |
| Assets on disk | ✅ 3,902 files / 1.8 GB |
| Assets in Storyblok | ✅ 2,417 uploaded, 990 reused, 214 unrecoverable |
| Stories in Storyblok | ✅ **3,606 of 3,606**, 0 failed, 3,606 distinct ids |
| Placement | ✅ 0 misplaced |
| Folders created by the migration | ✅ **none** — the log says `created folder` zero times |

```
1,499  entity                regions/{r}/entities/{e}/news
1,284  region                regions/{r}/news
  573  entity-department     regions/{r}/entities/{e}/departments/{d}/news
  250  global                global/news
                             across 149 destination folders
```

2,092 warnings were raised. 1,846 are by design — 1,575 `no entity` (the story
genuinely has none) and 233 `asset not uploaded` (unrecoverable media). The
remaining 246 were actioned: 186 empty bodies fixed and re-uploaded, 54 language
PDFs still open, 6 connection errors that retried clean.

Blogs and events await their exports. Their profiles exist and route correctly,
but `storyblok.component` and `fields` are still copied from news — confirm both
before their first upload.

### Known and accepted

- **Internal links still point at aku.edu.** 566 of them, kept as-is so they can
  be found and replaced now that every story has a Storyblok id. A second pass,
  by design — a link cannot resolve to a story that does not exist yet.
- **54 language PDFs** still link to aku.edu, which dies with the site. They need
  uploading and the links re-pointing.
- **Two tables are skipped** and rebuilt by hand: stories 1335 and 3288.
- **214 media are unobtainable**, listed in `reports/assets.csv`.
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
| [../Pages-Pipeline/README.md](../Pages-Pipeline/README.md) | the pages stage — a different job, and why it keeps its own |
| [../CLAUDE.md](../CLAUDE.md) | conventions and the bugs already paid for |
