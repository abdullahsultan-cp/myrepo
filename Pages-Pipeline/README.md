# Pages-Pipeline

The **site structure** migration: aku.edu's 4,591 pages, the 612 SharePoint webs
that hold them, and the permission model that says who may edit what.

This is a different job from news, blogs and events, and it keeps its own stage.
Those three are *content* — a list of items, each becoming a Storyblok story
through one shared pipeline. This one is *structure*: there is no item list to
transform, only exports that have to be reconciled into a folder tree and a role
model AKU can sign off before anything is built.

That is why it does not use `pipeline/` or `config/types/`, and why its output is
a set of CSVs and a browsable portal rather than Storyblok payloads.

---

> **Looking for the page CONTENT build?** This file is about the *structure* —
> the folder tree, the placements, the role model. Turning archived aku.edu HTML
> into Storyblok stories for Medical College, Pakistan is a later stage and has
> its own three files: [MC-PK-STATUS.md](MC-PK-STATUS.md) (where it stands),
> [MC-PK-RULES.md](MC-PK-RULES.md) (every conversion rule and why) and
> [MC-PK-RUNBOOK.md](MC-PK-RUNBOOK.md) (setup and command order).
> [CLAUDE.md](CLAUDE.md) indexes all of it.

---

# START HERE

If you have just picked this up, read this section and nothing else first.

## Where it stands

| | state |
|---|---|
| **The plan** | **done.** 628 folders, 4,548 of 4,591 pages have a destination. 19 of 20 structural checks pass; the 20th is AKU's own open questions |
| **The folder tree — backend's half** | **applied 9 Sep and verified against the API.** 8 regions, 75 entities, 110 departments — 0 missing, every `news`/`blogs`/`events` leaf present, 0 duplicates, 0 renames, 0 stories moved |
| **The folder tree — our half** | **ready to run, not run.** 438 section folders. `create_section_folders.py`, dry-run clean |
| **The pages themselves** | **not started, and the content is not even downloaded.** See the warning below |
| **Who does what** | 1,459 pages assigned to 9 people; 3,132 unassigned |

## ⚠️ Nobody has downloaded a single page's content

This is the most important thing on this page, and it is time-critical.

**The SharePoint site is being switched off.** Every page's body is still only on
aku.edu. Check for yourself — there is no page HTML anywhere in this repo:

| what we have | what it holds |
|---|---|
| `data/aku-university-filtered.csv` | `PageUrl, Action, Type, Webpart, FinalStatus, References` — **no body** |
| `data/SPPagesAKU-Metadata.csv` | title, dates, owner groups — **no body** |
| `data/AKU-EN_1.HTM` | a list of URLs — **no body** |
| `out/aku-live-page-verification.csv` | http status, breadcrumb, page title — **no body** |

So this stage knows, for all 4,591 pages, **where each one goes** — and for none
of them **what is in it**. `verify_live.py` already fetches pages from aku.edu
and reads their breadcrumb and `<title>`, so the fetching machinery exists; it
throws the body away. Extending it to keep the HTML is the single highest-value
thing left, and it gets harder the day the site goes dark.

## What to do next, in order

```
1.  create the 438 section folders          -> Step 1, below.  Ready now.
2.  download every page's HTML from aku.edu -> Step 2.  Nothing written yet.
3.  turn that HTML into Storyblok stories   -> Step 3.  Nothing written yet.
```

Step 1 is a script that exists and has been dry-run. Steps 2 and 3 are real work
that has not been started; what is already decided about them is written down so
you are not deciding it again.

---

# The tree is owned in two halves

Agreed with AKU on 8 September 2026. Getting this wrong creates a folder with
two owners, so it is worth being exact.

| | who creates it | what it is |
|---|---|---|
| `regions/<region>` | **the backend** | `pk`, `ke`, `gl`, … |
| `regions/<region>/entities/<entity>` | **the backend** | `mc`, `sonam`, `ied`, … |
| `.../departments/<department>` | **the backend** | `anaes`, `pathology`, … |
| `news` `blogs` `events` inside each of those | **the backend**, automatically | the content hubs |
| `entities` and `departments` containers | **the backend**, when a row gets its first child | |
| **everything else** | **us** | `about`, `research`, `study`, `alumni`, `programmes` … |

The seed shape differs per level, and it was read off the folder the dev built to
show us (`regions/test`), not assumed:

| level | seeded inside it |
|---|---|
| region | `blogs` `entities` `events` `news` |
| entity | `blogs` `departments` `events` `news` |
| department | `blogs` `events` `news` — no `departments` below it |

**The space uses SHORT CODES.** `regions/pk/entities/mc`, not
`regions/pakistan/entities/medical-college`. The pages plan uses the long form
and is translated on the way out. Four folders are one folder under two names —
see `out/aku-folder-aliases.json` and the warning in Step 1.

**Naming.** The backend names its own three levels from the UPPERCASE slug
(`FAS`, `ANAES`, `FAM-MED`). Everything else in the space is Title Case
(`Blogs`, `Events`, `Programmes`). Sections follow the second rule, which is also
what `pipeline/migrate/upload/upload.py:215` produces.

---

# Step 1 — create the 438 section folders

**Ready to run.** Every one of the 438 holds at least one page; empty sections
were already excluded.

## Before you run it

```bash
# 1. Refresh the snapshot. The script compares against it, and it is how it
#    knows what already exists. A stale one is how you create a duplicate.
python pipeline/migrate/review/dump_sb_tree.py

# 2. Look at the plan. It is written on every run, --apply or not.
cd Pages-Pipeline/pipeline
python create_section_folders.py
```

Expected output:

```
snapshot: 875 folders, space 289824742951963

aku-section-folders.csv   438 folder(s) to create
   by depth: {2: 32, 3: 185, 4: 192, 5: 20, 6: 9}
   204 have a parent this run creates first

DRY RUN. Nothing was written to the space.
```

Read `out/aku-section-folders.csv` before going further — one row per folder, in
creation order: `order, path, slug, name, plan_title, depth, parent_path,
parent_id, pages_in_subtree, managed_by`.

## Run it

```bash
python create_section_folders.py --apply --limit 5   # prove it on five
python pipeline/migrate/review/dump_sb_tree.py       # look at those five
python create_section_folders.py --apply             # the remaining 433
```

**`--limit 5` first, every time.** Five folders you can eyeball in Storyblok
costs a minute; 438 in the wrong place costs a day.

## The moment it finishes

```bash
python pipeline/migrate/review/dump_sb_tree.py       # refresh
python create_section_folders.py                    # must now say 0 to create
python pipeline/migrate/review/backup.py --type news
```

**Storyblok keeps no version history.** The snapshot and the read-back backup are
the only record of what the space held, and the only thing a later "was it always
like that?" can be settled against. Take them *after* the write, not before.

## What the script refuses to do, and why

Each guard is here because of something in [CLAUDE.md](../CLAUDE.md) §6–7 that
has already gone wrong in this repo once.

| it stops if | because |
|---|---|
| a region / entity / department / `news` / `blogs` / `events` folder is missing | that is the backend's. A gap means the backend has not finished, and creating it would give one folder two owners |
| a path is not in the pages plan | it never invents a folder |
| a parent has no id | Storyblok silently puts a parentless story at the **root** — that is how you get `about` sitting beside `regions/` |
| a folder already exists | `ensure_asset_folder` used to POST first and search only on failure. The space reached **769 asset folders, 444 redundant** |

It also treats `200`, `201` **and `204`** as success — accepting only (200, 201)
is how a run that moved 786 assets perfectly reported `0 moved, 786 failed` —
retries dropped connections as well as HTTP errors, and writes each new id to
`out/work/created_folders.json` **after every single creation**, so a crash at
folder 200 of 438 resumes instead of starting over.

## If it stops

| message | do this |
|---|---|
| `STOPPING: N folder(s) the BACKEND owns are missing` | the backend has not finished. Send them `out/AKU-Backend-Tree.json`, wait, refresh the snapshot, re-run |
| `STOPPING: N folder(s) name a parent that neither exists nor gets created` | the plan is inconsistent — rebuild it (`build_hierarchy_map.py`, then `build_backend_tree.py`) and re-run. Do **not** hand-edit the CSV |
| `STOPPING at <path>: its parent has no id` | refresh the snapshot and re-run; it resumes |
| `FAILED on <path>: 401` | `config/storyblok.json` has no valid `management_token` |
| `refusing to create folders in a space this plan was not built against` | the snapshot and `config/storyblok.json` name different spaces. Check which one you meant |

---

# Step 2 — download the page content

**Not written. This is the next thing to build, and it is urgent.**

`verify_live.py` already walks all 4,591 URLs, handles 401/404, caches to
`out/work/live_checks.json` and is interruptible. It reads the breadcrumb and the
`<title>` out of each response and discards the rest. What is needed is the same
sweep keeping the body.

What is already known, so you do not re-derive it:

- **3,982 of the 4,591 pages can be fetched.** The other 609 cannot, and
  `build` / `build_reason` in `out/aku-master-pages.csv` say which and why:
  **538** are login-only, **43** are superseded duplicates, **28** are dead on
  the live site. Note those are not the raw status counts — 547 pages return
  HTTP 401 and 34 return 404 in total, and a page that is both 404 AND
  superseded is counted once, under superseded. Do not add the status counts
  together and expect 609.
- **The 401s are AKU's to unblock.** Their place in the tree is reserved; when
  AKU hands the content over it drops into the path already planned.
- **Model it on `pipeline/migrate/download/`**, which does this for news, blogs
  and events: read-only, resumable, one process behind a lock.
- **SharePoint HTML carries three faults in every type** — undecoded entities,
  position markers, invisible characters. [CLAUDE.md](../CLAUDE.md) §9 has each
  one counted. Pages has its own `page_titles.py` for titles; a body cleaner
  will need the same treatment.

---

# Step 3 — create the pages as Storyblok stories

**Not written.** What is decided:

- **Destinations are final.** `out/aku-master-pages.csv` gives every page its
  `destination_path` (where the story is created) and `destination_url` (the
  address a reader sees). 0 duplicate paths, 0 duplicate addresses, 0 pages
  sitting on a folder's path — `aku-hierarchy-audit.csv` proves it.
- **A folder's landing page is a story called `home` inside it**, because a
  folder cannot hold content of its own. 467 pages are one.
- **Honour `out/aku-folder-aliases.json`.** Four folders have two names. A page
  planned for `.../departments/fam-med` goes into `.../departments/fm` — the
  folder that exists and holds the stories. Creating the plan's spelling makes
  the duplicate this whole exercise avoided.
- **Never create a folder from the page uploader.** If a destination folder is
  missing, Step 1 has not been run or the backend has not finished. `NO_CREATE`
  in the shared `pipeline/migrate/upload/upload.py` enforces this for news, blogs
  and events and must keep doing so.
- **The front end owes one change first** —
  [out/FOR-THE-FRONTEND-DEV.md](out/FOR-THE-FRONTEND-DEV.md). Until it lands, 467
  front doors sit a level too deep and `aku.edu/` has no homepage.

---

# Tracking the work

```bash
python build_assignments.py     # after the team fills in the work sheet
```

`out/aku-page-assignments.csv` is the sheet people edit — `Migration Status`,
`Testing Status`, `Tester`, `Tester Remarks`. `out/aku-progress.csv` is the
standing report per person, regenerated from it.

**Re-running never overwrites what somebody typed.** The script reads the
previous sheet back and carries those four columns across, keyed on the source
URL — the one column no rebuild can change. Verified: 11 rows marked Done with
tester names survived a full rebuild.

---

## Layout

```
data/       the real inputs — the only things a human supplies
data/backend/  the backend's own three tables, dumped from its database
pipeline/   the code, plus assets/ for what the rendered pages inline
out/        deliverables: the CSVs and HTML handed to AKU        TRACKED
out/work/   intermediates the steps pass between themselves      gitignored
portal/     the React app that makes all of it browsable
```

Before this split, all 17 files sat in one flat folder — 3 inputs, 11 generated
deliverables and a handful of views, with nothing to say which was which. The
generated ones were committed too, so a re-run looked like hand edits. Now the
distinction is the directory it lives in.

**`pipeline/paths.py` names every path.** Add a file there rather than joining a
path inline; that module exists because a hand-built `../data/taxonomy/...` in
`join.py` broke silently the day the repo grew a folder per content type, and
nothing said so — the enrichment it fed simply went quiet.

---

## The inputs

In `data/`. Everything else is derived.

| File | Is |
|---|---|
| `aku-university-filtered.csv` | **the inventory** — AKU's current list, 4,591 pages. Authoritative |
| `aku-university-visible-pages.csv` | AKU's first list, 3,340. Kept only so `page_intake.dropped()` can name what has since been taken off |
| `AKU - User - Permissions - … .csv` | the SharePoint permissions export: 612 webs, owner groups, AD domains |
| `AKU-EN_1.HTM` | the only page-level URL inventory that exists — 3,340 URLs |
| `SPPagesAKU-Metadata.csv` | per-page metadata: title, dates, version, the CW/CA groups set on the page itself |
| `backend/*.json` | the backend's `regions`, `region_entities`, `entity_departments` tables |

No export is a superset of another: the permissions CSV knows sections with no
page in the inventory, and the inventory has pages under sub-paths the CSV never
lists as their own web. `join.py` reports the overlap honestly rather than
picking one and pretending.

---

## Regenerating the plan from scratch

Only needed if an input changes. In order, from `pipeline/` — each step writes
what the next reads, so any one can be re-run once its predecessor has.

```bash
cd Pages-Pipeline/pipeline

python probe_csv.py              # permissions CSV  -> sites.json
python join.py                   # + AKU-EN_1.HTM   -> pages.json, join_report.txt
python sections.py               # unique-scope owners -> webs.json, sections.txt
python build_hierarchy.py        # the accounting check + two gitignored intermediates
python probe_roles.py            # groups -> groups.json, web_owners.json
python build_migration_plan.py   # -> plan.json + the folder / page / role CSVs
python probe_people.py           # -> people.json
python build_roles.py            # -> roles.json + the four role CSVs
python verify_live.py            # -> aku-live-page-verification.csv   (network)
python build_master_sheet.py     # -> aku-master-{pages,folders}.csv   THE deliverable
python build_assignments.py      # -> the work sheet, folder assignments, progress
python build_hierarchy_map.py    # -> the old tree joined to the new one
python build_backend_tree.py     # -> AKU-Backend-Tree.json + aku-folder-aliases.json
python create_section_folders.py # -> the 438 sections   (--apply writes)
python audit_hierarchy.py        # -> 20 checks. Reads only; fails on a regression
```

`audit_hierarchy.py` last, always. It is the only step whose job is to disagree
with the others, and it fails the build on a regression rather than reporting one.

Then the portal:

```bash
mkdir -p ../portal/public/data
cp ../out/work/plan.json ../out/work/people.json ../out/work/roles.json ../portal/public/data/
cd ../portal && npm install && npm run dev
```

`python site_visits.py` regenerates `out/aku-site-visits.csv` — the record of
every aku.edu page actually opened and what it showed. It is a sweep, not a build
step, and it is deliberately unfinished: `REMAINING` in that file is the honest
to-do list.

---

## The deliverables

Everything in `out/`, tracked, regenerated by the run above.

**Read these three first:**

| File | Contents |
|---|---|
| `aku-master-pages.csv` | **start here** — every page in one sheet, 5,233 rows: AKU's 4,591 plus 642 found by crawling, each with a `remark` saying what is wrong with it and a `build` column saying whether it can be made. Nothing is dropped |
| `aku-page-assignments.csv` | **the work sheet** — one row per page with the person migrating it, a unique page name, pre-filled migration and testing status, old slug beside new slug |
| `aku-hierarchy-audit.csv` | **is the result a legal tree** — one row per check, 19 pass / 1 for AKU |

**The tree, and handing it over:**

| File | Contents |
|---|---|
| `AKU-Backend-Tree.json` | **the backend seed** — a bare array of regions → entities → departments in the backend's own vocabulary (`shortName`, `storyblokFolderId`, `dbId`), with an `action` per node. This is the file the backend dev is sent |
| `aku-folder-aliases.json` | the four folders that have two names, and the notes that used to ride along in the seed file. **Not** the backend's problem — it is for whoever creates the pages |
| `aku-section-folders.csv` | **the 438 folders we create**, in creation order with each parent's Storyblok id |
| `aku-folder-map.csv` | every folder in the proposed tree, its parent and its owning unit |
| `aku-master-folders.csv` | the same, with the 116 that would be created empty said out loud |
| `aku-folder-assignments.csv` | the assignment as it was agreed — 151 complete folders, who has each |
| `aku-progress.csv` | how far each person has got, read back from the work sheet |

**Permissions:**

| File | Contents |
|---|---|
| `aku-role-hierarchy.csv` | **the role model** — read this one for anything about permissions |
| `aku-role-capabilities.csv` | what each role may do |
| `aku-user-roles.csv` | every person, and the roles they land in |
| `aku-permission-groups.csv` | the SharePoint groups behind each folder's rights |
| `aku-old-role-inventory.csv`, `aku-old-role-strings.csv` | what SharePoint had, verbatim, so the mapping can be audited |

`build_migration_plan.py` emits a **flat** role list — one `<unit>-editor` /
`<unit>-publisher` pair per team, 280 roles. `build_roles.py` replaces that with
the **hierarchy**, and is the one to read.

**Views and evidence:**

| File | Contents |
|---|---|
| `AKU-Tree.html` | the shareable tree — every page's source URL beside the address it moves to, **both clickable** |
| `AKU-Hierarchy-Map.html` | the old tree beside the new one, 1,384 rows, filterable. Opens from a bare clone |
| `aku-hierarchy-map.csv` | the same rows for a spreadsheet: `from_path`, `to_path`, `action`, `stories`, `pages`, `remark` |
| `AKU-Hierarchy-Map.json` | the same, nested |
| `AKU-Folder-Structure.json` | the folder tree as a seed: `title`, `type`, `parent_name`, `parent_sb_id`, `slug`, `shortname` |
| `aku-page-map.csv` | every page, where it lands, and why |
| `aku-live-page-verification.csv` | every page opened on aku.edu: status, breadcrumb, title |
| `aku-site-visits.csv` | the live-site sweep: what each page showed and what it settled |
| `aku-pages-not-in-the-list.csv` | 642 URLs found by crawling that no AKU export lists |
| `aku-hierarchy-landing-pages.csv` | contested front doors, both source pages side by side. Empty since the 10 clashes were resolved |
| `FOR-THE-FRONTEND-DEV.md` | the one change the front end needs: strip a trailing `home` from the address |

### Opening the pages, old and new

Both HTML views link every page twice. The **grey slug opens the page as it is
today** on aku.edu, so a reviewer can read the content they are deciding about.

The **destination slug has nowhere to point** until somebody says where the new
site lives — every planned address is a `www.aku.edu` one, which is the site
being replaced, so linking it there would send the reviewer back to the very page
they are comparing against. So it ships as plain text with its path in `data-p`,
and there is a **New site base URL** box in the toolbar: paste
`https://aku-staging.example.com` and all 4,548 destinations become live links.

The value is held in `localStorage` under `aku_base` and **never written into the
committed file** — it is one reviewer's staging host, not a fact about the
migration, and two people reviewing against different hosts must not fight over
it. Both the read and the write are wrapped in `try/catch`, because
`localStorage` throws outright rather than returning null in a browser set to
block site data, and the page has to work with no stored value at all.

### Not tracked

`AKU-Folder-Hierarchy.*`, `AKU-Migration-Portal.html`, `AKU-Structure.html` and
`AKU-Migration-Plan.html` are written to `out/` but gitignored: each is a
megabyte rebuilt from `plan.json`, and committing them would put that churn in
every diff. `AKU-Tree.html` is the exception, because it is the file that gets
sent.

`AKU-Folder-Hierarchy.html` is **retired** and no longer written at all. It was
built before the plan and from a different basis, so its 611 source webs
disagreed with the plan's 628 destination folders and its prose claimed 19 open
questions above a section listing 2. Read the tree in `AKU-Tree.html` and the
numbers in `aku-master-pages.csv`.

---

## Where it borrows from news

`join.py` reads the news taxonomy's region / entity / department tree
(`News-Pipeline/data/taxonomy/seed/regions_entities_departments.json`) so the two
migrations spell the same units the same way. That is the only coupling, and it
goes through `paths.taxonomy_seed()` rather than a hand-built path — see above
for why.

Pages otherwise **shares no code**. `page_titles.py` duplicates 40 lines of
`pipeline/core/text_clean.py` deliberately: reaching across would put this stage
behind the shared-code push guard for a string function, and the code point list
is the same list.
