# MC-PK — where the page build stands

Medical College, Pakistan — `regions/pk/entities/mc/`. This is the **content
build**: turning archived aku.edu HTML into Storyblok `page` stories. It is a
later stage than [README.md](README.md), which is about the folder tree.

Every number here came from counting, on **16 Sep 2026**. Where a count is a
guess it says so.

---

## 1 · The numbers

Owner `Rabee Amir` in `out/aku-page-assignments.csv` — all 416 rows are
`medical-college` / `pakistan`.

| | |
|---|---|
| Rows assigned | **416** |
| Blocked, AKU to unblock | 41 |
| Not migrating (gone) | 1 |
| **Buildable** | **374** |
| **Built and live** | **75** |
| **Remaining** | **299** |
| Published | 14 |
| Draft | 61 |
| Assets uploaded | **1,160** |

All 75 built pages match a row in the assignment sheet by `Old URL`; none is
stray.

**The sheet's `Migration Status` is stale.** It reads `Not started` for all 374,
including the 75 that are live. Nobody has written progress back to it. Do not
read that column as truth — `out/rabee-pages-links-v2.csv` is what is actually
built.

**A caveat on "299".** Earlier in the work a narrower CSV of 242 MC pages was
being used, and against that list the remainder was 167. 299 is the figure
against the full assignment sheet, which is the authoritative one. If AKU is
working from the 242 list, reconcile the two before quoting a number to them.

---

## 2 · The three CSVs that matter

| file | rows | what it is |
|---|---|---|
| `out/rabee-pages-links-v2.csv` | 75 | **the built pages** — legacy link, Storyblok editor link, preview link, path, published, story id |
| `out/rabee-pages-with-sidebar.csv` | 28 | built pages whose legacy page has a side nav, with both links |
| `out/aku-page-assignments.csv` | 4,591 | the whole team's work sheet; 416 rows are ours |

---

## 3 · Pages 1–13 are hand-finished — do not rebuild them

Rabee corrected these in the Storyblok editor. Rebuilding overwrites his work.
`create_pages.py` takes `--protect` for exactly this:

```
regions/pk/entities/mc/about/partnerships
regions/pk/entities/mc/about/recognition
regions/pk/entities/mc/about/support-us
regions/pk/entities/mc/allied-health/academic-traineeship-programmes
regions/pk/entities/mc/allied-health/certificate
regions/pk/entities/mc/allied-health/home
regions/pk/entities/mc/allied-health/research-grants
regions/pk/entities/mc/animal-facility
regions/pk/entities/mc/cbcb/careers
regions/pk/entities/mc/cbcb/goals
regions/pk/entities/mc/ccbp/collaborations
regions/pk/entities/mc/ccbp/home
regions/pk/entities/mc/ccbp/message-director
```

**To bring one of them up to a new rule, update it IN PLACE** — read the live
story, replace only the fields the rule touches, write the rest back. That is
how page 8 (`animal-facility`) got rich-text accordions on 16 Sep without losing
anything. See §5 of [MC-PK-RULES.md](MC-PK-RULES.md).

---

## 4 · Data that cannot be regenerated

aku.edu is being switched off. These are committed deliberately, against the
repo's usual rule about `out/work/`:

| path | size | why it cannot be rebuilt |
|---|---|---|
| `out/work/legacy_html/` | 120 files, 12 MB | the archived pages. Once the site is dark there is no source |
| `out/work/page_widgets.json` | 603 KB | **97 widget sets across 56 pages** — 38 accordions, 29 galleries, 22 tile sets, 8 tab strips, pulled from SharePoint's REST API. None of it exists in the HTML |
| `out/work/page_asset_map.json` | 361 KB | source URL → uploaded Storyblok asset, 1,160 entries. Losing it means re-uploading everything as duplicates |
| `out/work/build_list_v2.json` | 18 KB | the 63-page working set `build_pages.py` rebuilds |

`out/work/legacy_images/` (854 MB) is **not** committed — every one of those
files is already in Storyblok and recorded in the asset map.

Six read-back backups are in `backup/storyblok/`, newest
`mc-pages-AFTER-PAGE8-RICHTEXT_20260916-133356.json.gz` (1,440 stories under
`regions/pk/entities/mc/`). Storyblok keeps no version history, so these are the
only record of what the space held.

---

## 5 · Known problems, none of them blocking

**For AKU / Rabee to decide**

- **Three titles look wrong** — `publications` and `amnat` are slugs, and the
  page slugged `imran-memon` is titled `DMU`. They come from the sheet, so the
  sheet is where to fix them. `CITRIC` and `CPS-TWG` are real acronyms, leave them.
- **192 links still point at aku.edu**, and they die with the site: 34 document
  links (20 on `mc/home`, 5 on `jrl`) and 158 page links. `citric-report-2025` is
  *only* two PDF links, so it becomes an empty page. One is malformed at source:
  `http://ccit@aku.edu/` on `ccit/home`.
- **`faculty/profile` cannot be built.** It is a JavaScript template; the HTML
  holds contact-form labels and nothing else. It should be marked not-buildable
  rather than left as an empty page.
- **`allied-health/home`'s `cta_link` points at the Storyblok editor URL** of its
  own blok, not at a page. A reader clicking "learn more" lands in the CMS. Its
  real target, `chairs-message`, is planned but not yet built.

**Still to do in the builder**

`featured_news`, `quote_banner`, cbcb/home's slider → `hero.slides` plus the
partners strip, and the one-off `data-science/news` restructure. All were asked
for and none is done.

**Loose ends**

- Two uploaded images are referenced by no page (`aamnat-1.png` on 995,
  `bio-repository-banner-rev2.jpg` on 1077). Cause never found.
- `ccbp/publications` was empty for a long time because of a silent API failure
  (§4 of [MC-PK-RULES.md](MC-PK-RULES.md)); it is fixed, but it is worth assuming
  other pages have been hollow for reasons nobody has looked for yet.
