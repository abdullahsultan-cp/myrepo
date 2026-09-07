# Pages-Pipeline · how the hierarchy is built

Run in order from this directory. Each step writes the input the next one reads,
so any step can be re-run alone once its predecessor has run.

```bash
python probe_csv.py        # permissions CSV -> sites.json      (aku.edu only)
python join.py             # AKU-EN_1.HTM    -> pages.json      + join_report.txt
python sections.py         # unique-scope owners -> webs.json   + sections.txt
python build_hierarchy.py  # -> the accounting check + ../out/AKU-Folder-Hierarchy.{tree.txt,json}
python probe_roles.py      # groups -> groups.json + web_owners.json
python build_migration_plan.py   # -> plan.json + the folder/page/role CSVs in ../out/
python probe_people.py           # -> people.json
python build_roles.py            # -> roles.json + the four role CSVs
python verify_live.py            # -> aku-live-page-verification.csv  (hits the network)
python build_master_sheet.py     # -> aku-master-{pages,folders}.csv   THE deliverable
python build_assignments.py      # -> aku-page-assignments.csv        the work sheet
python audit_hierarchy.py        # -> the audit  (reads only, fails on a regression)
mkdir -p ../portal/public/data   # gitignored, so absent on a fresh clone
cp ../out/work/{plan,people,roles}.json ../portal/public/data/
```

## Is the result a legal tree?

`audit_hierarchy.py` asks the question none of the build steps do: not "is each
page placed" but "is the tree that came out something Storyblok can hold". It
reads `plan.json`, writes `aku-hierarchy-audit.csv` (one row per check), and
changes nothing. **16 of the 20 checks pass; the remaining 4 are questions for
AKU, not faults.** Four of the passes were a defect and three open questions
until 7 Sep 2026, and they are worth reading as a set, because each one was
invisible to every other step.

### A folder and a page cannot share a slug

In Storyblok a folder IS a story, so `regions/.../medical-college/departments`
cannot be both the folder holding 544 department pages and a page called
"Departments". AKU's site has both, in **10 places**. Nothing caught it: the
collision check in `build_migration_plan.py` compares a page against another
PAGE and never against a folder.

Fixed by making the page the folder's landing page. Which of the two rival pages
wins is **measured** — live HTTP status, then SharePoint version (below 1.0 is a
draft that was never published), then last-modified date. The obvious rule, "the
page inside the sub-web is the canonical one", is **wrong 4 times in 10**:
`mcpk/bbs/Pages/Research.aspx` was edited in December 2025 while the sub-web's
own `home.aspx` has not been touched since June 2016.

### Nothing is dropped

AKU's rule. The loser of each front door keeps its content at
`<folder>/<leaf>-archive` with a remark naming the page that superseded it — 25
pages. The same rule covers the 17 folders that held both a `home` and a
`default` page.

### A trailing `home` is not part of the address

SharePoint serves `X/Pages/home.aspx` AT `X/`, so keeping the segment published
the university homepage at `aku.edu/home` and every faculty front door one level
below where a reader expects it. `public_url()` strips it, exactly as it already
strips `regions`, `entities` and `departments`. The page still LIVES at
`<folder>/home`, so no folder and page ever share a slug. **The front end has to
strip the same four** — that is the one thing here that is not ours to change.

### A scaffold segment is invisible only in the middle

Stripping `departments` unconditionally was wrong, and it took the fix above to
expose it: `mcpk/Pages/departments.aspx` landed on
`aku.edu/pakistan/medical-college` — the **faculty's own front door** — and
pushed the Medical College homepage to `medical-college/home-2`. A scaffold
segment as the LAST segment is the thing being addressed, not structure, so it
stays. The reader would have found the department list where the faculty
homepage belongs.

## Checking a placement rather than trusting it

Three witnesses place a page, and only one of them speaks per page.

| Witness | Covers | Read by |
|---|---|---|
| the permissions export — who owns its web | all 4,591 | `build_migration_plan.py` |
| `SPPagesAKU-Metadata.csv` — the CW/CA groups set on the page itself | 3,265 | `page_owners.py` |
| the live site — the breadcrumb AKU prints on the page | the other 1,326 | `verify_live.py` |

Between them every page is checked by something other than its own URL. The
metadata agrees with the folder owner on 2,580 of the 2,656 pages where both
speak, and the 76 exceptions are shared apps carrying their author's group — one
faculty-profile app copied into seven faculties — not ownership disputes.
`verify_live.py` opened the other 1,326: **1,048 breadcrumbs confirm the
placement and none contradict it.** 257 did not answer (252 HTTP 401, 5 HTTP 404),
16 are the site root and have no section above them, and 4 sit in a SharePoint
library whose breadcrumb is local to the library.

`verify_live.py` caches every fetch in `out/work/live_checks.json`, so a re-run
only fetches what it has not seen. It never re-files a page: it writes what the
site said beside what the plan decided, and a disagreement is a question for a
human.

## The roles

`build_migration_plan.py` emits a **flat** role list — one `<unit>-editor` /
`<unit>-publisher` pair per team, 280 roles — and the folder columns that name
them. `build_roles.py` replaces that with the **hierarchy**, and is the one to
read for anything about permissions:

| Output | One row per |
|---|---|
| `aku-role-hierarchy.csv` | custom role: tier, rung, scope, parent, who it replaces |
| `aku-role-capabilities.csv` | action × rung — the matrix AKU signs off |
| `aku-old-role-inventory.csv` | SharePoint group → custom role (all 336) |
| `aku-old-role-strings.csv` | distinct `Assigned Roles` value → capability (all 34) |
| `aku-user-roles.csv` | person: groups held today → roles to assign |

A role is **one rung of a five-step ladder at one scope**, and scope inherits
downward, so 8,676 folder-level grants become 769 role assignments and 463 of the
584 people need exactly one role.

Three decisions in there are worth knowing before changing it:

**`Limited Access` becomes nothing.** SharePoint adds it so a user can traverse to
an item granted directly. 2,503 rows of it grant no access to anything.

**`Design` is not carried over.** It is on 26,000 rows because a publishing site
ships it with `Contribute`. Deriving `component-developer` from it would tell AKU
that 400 content people may rewrite component schemas. Only the `Designers` group
becomes that role.

**A role is one rung at ONE scope, never a list of scopes.** `MC EA` owns an event
microsite *and* the East Africa medical college; folding the college in as a
secondary scope of the events role handed it to all 155 people who publish events.
A team spanning two places holds two roles.

## The two sources, and what each one alone cannot tell you

| Source | Gives | Blind to |
|---|---|---|
| `AKU - User - ... - SharePoint_2016_User_Roles_Mapping.csv` | 611 aku.edu webs, their titles, owner groups, AD domains | pages — it lists webs only |
| `AKU-EN_1.HTM` | 3,340 page URLs with move/update disposition | 42 of the 82 sections, which hold no page |

Joining them is the point: 42 sections exist only in the CSV, and 2 webs
(`library/pk/fhs/SitePages`, `mrtc-pk/research/Pages/Projects`) hold 14 pages that
appear in no permission row. `build_hierarchy.py` fails loudly if any web or page
does not land somewhere in the tree.

## How region and entity are decided

Only rows with `Permission Scope = Unique` carry ownership. Inherited rows repeat
the AKU-wide groups (`AKU Owners`, `Designers`, `Hierarchy Managers`) into every
web and say nothing. Three witnesses, in order of strength:

1. a dedicated `CW <X>` / `CA <X>` pair (content writer / content approver), or a
   `FacultyOwners-<x>` / `<X> News Writer` group;
2. the AD domain in the login account — `aku\` Karachi, `nbi\` Nairobi,
   `dar\` Dar es Salaam, `ismc\` London — as a majority over the web's unique rows;
3. the section's own CSV title, when it names the country outright
   (`Medical College, Kenya`).

Every placement in `SEC` records which of these produced it. `confidence` is
`witnessed` only when the export proves it, `inferred` when only a name or slug
convention supports it, and `decide` when AKU has to answer. The 4 `decide` and 16
`inferred` rows are listed in the HTML under **Open questions** — do not treat them
as settled.

## Editing

The classification table `SEC` in `build_hierarchy.py` is the single place a
placement changes. It asserts against the CSV on every run: add a section to
aku.edu and the build refuses to proceed until `SEC` covers it. Do not hand-edit
the generated `AKU-Folder-Hierarchy.*` intermediates. Its HTML page is retired
— see the note beside `OUT_HTML` in that file, and read the tree in
`AKU-Tree.html` instead.
