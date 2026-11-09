# CLAUDE.md — Pages-Pipeline

Working context for the **pages** stage. Read the root
[../CLAUDE.md](../CLAUDE.md) first for the repo's conventions and the traps that
apply everywhere; this file is only what is true about pages.

---

## 0 · WHOSE WORK THIS IS — read before touching anything

**Branch `abdullah/pages-sheet-builder` is Abdullah Sultan's**
(`abdullah.sultan@cloudprimero.com`), built on top of Rabee's
`pages/mc-pk-migration`. Abdullah's page-fix workflow is §0a below. Everything
in the rest of this section still holds for Rabee's 75 Medical College pages:
do not touch them from here.

**`pages/mc-pk-migration` is Muhammad Rabee Amir's work** (`rabee.amir@cloudprimero.com`).
He migrates Medical College, Pakistan. If you are working here on his behalf,
these are the boundaries, and they are not advisory.

### `regions/pk/entities/mc/` is SHARED. It is not his folder.

1,300 stories live under it. Counted from the newest backup on 16 Sep 2026:

| stories | whose | may you touch them? |
|---|---|---|
| **75** | **Rabee's** | yes — this is the work |
| 840 | Abdullah Sultan | **no** |
| 325 | Jahanzaib Akhter | **no** |
| 58 | last saved by `System Administrator`, none of them his | **no** |
| 2 | `news_article` stories he edited on 8 Sep, not part of this migration | **no** |

Being under `mc/` means nothing. **94% of that folder belongs to other people.**

### The only reliable list of his pages is the CSV

`out/rabee-pages-links-v2.csv` — 75 rows, each with `storyblok_path` and
`story_id`. Read it, match on those, act on nothing else.

**Do not use `last_author` to decide ownership. It is wrong both ways:**

- 5 of his 75 read `System Administrator`, because he re-saved them in the
  Storyblok editor. An ownership test on his name silently skips them.
- 58 other stories also read `System Administrator` and are not his.
- 2 stories do carry his name and are still not his to rebuild — they are
  `news_article` stories from the news migration, not pages.

### Before you write

- **Ask him before anything destructive.** Deleting a story, deleting an asset,
  deleting a folder, unpublishing, or overwriting a page he corrected by hand.
  His instruction, 15 Sep 2026: *"ASK ME BEFORE DOING ANYTHING"*.
- **Pages 1–13 are hand-corrected.** Rebuilding overwrites his editing. Pass
  `--protect` with their paths — listed in [MC-PK-STATUS.md](MC-PK-STATUS.md) §3
  — or change the one field you need in place.
- **Back up after every write**, never before. Storyblok keeps no version
  history, so the read-back archive in `backup/storyblok/` is the only record of
  what the space held.
- **Never delete and re-upload a story.** Update in place. A new id breaks every
  review link already shared and loses his manual edits.
- **Never create a content folder.** `regions/` belongs to the front-end
  developer; `create_pages.py` hard-stops on a missing one.

### The token is not in the repo

`config/storyblok.json` is gitignored, one per machine. If it is absent, stop and
ask — do not look for a token anywhere else, and never write one into a file that
git tracks. [MC-PK-RUNBOOK.md](MC-PK-RUNBOOK.md) §1 has the shape of the file.

---

## 0a · Fixing one page at a time (Abdullah's workflow)

Abdullah sends pairs: an old aku.edu URL and the Storyblok editor URL of the
story that should match it. The job is to make the story hold everything the old
page held, laid out in the house style below. Space `289824742951963`.

### The loop

```
cd Pages-Pipeline/pipeline
python fix_page.py <editor-url-or-id> <old-url>            # dry run: saves out/work/fix/<sid>.before.json + html/<sid>.html
python fix_page.py <editor-url-or-id> <old-url> --apply    # write, UNPUBLISHED
#   or, when the generic build is not right: a small per-page script that reads
#   <sid>.before.json, edits the body and writes <sid>.after.json, then
python apply_fix.py <sid> [--publish]                      # PUT in place + backups
python documents.py <sid> [--apply]                        # aku.edu PDFs -> Storyblok assets
python club_page.py <sid>                                  # Uganda/Kenya club pages (one fixed layout)
```

- **Write unpublished.** Publish only when he says so, for that page.
- **He edits in the editor while you work.** Re-read the story right before
  building; `apply_fix.py` refuses if `updated_at` moved since `before.json`.
- **Backups after every write** go to `backup/storyblok/fixes/fix_<sid>_{BEFORE,AFTER}_<ts>.json.gz`.
- **Mostly-right story → targeted edit,** not a full rebuild.
- **Verify before writing:** every word and every link of the old page is in
  the new body (word/link diff), and `build_from_sheet.Schema.problems()` is
  empty. Shared country cards (`teaching_impact` with generic `card` bloks) are
  a team design: keep them and exclude `teaching_impact.cards` from the check.
- **Per-page scripts and work files live in `out/work/fix/`** (gitignored).
  Only reusable code goes in `pipeline/`.

### House style (learnt from his corrections, in `house_style.py`)

| old page has | build |
|---|---|
| a headed section of prose | **one `rich_text` per section**: heading level 1, not bold, centred; multi-word heading has its **last word in `#008F51`** (textStyle mark); an **empty paragraph after the heading**; paragraphs centred |
| short top text with no heading | give it a main heading in the same style |
| plain bullets | `sub_inner_group` `variant: outcomes`, one item per bullet, titled after the section |
| bullets that are links | `sub_inner_group` `variant: links` |
| bullets with a link *inside* the sentence | `faculty_publications` grouped (sub_inner_group items are plain labels and would lose the link) |
| linked name + description | `faculty_publications` default items (title, link, description) |
| several headings each with short text (Vision / Mission…) | `faculty_publications` `variant: grouped`, one group per heading, one item holding the text; intro in the block description |
| accordion | `info_accordion` **with a heading**; card with a picture → `variant: split_section` (wrap above 1,000 chars); without → `variant: rich_text`; sub-headings inside cards are **H5, never bold** (`card_text`) |
| legacy left sidebar (`[id$=V4QuickLaunchMenu]`) | **`library_navigator`** rebuilt from the page's own sidebar (`rebuild_navigator`; third-level links are flattened after their parent, never dropped). Never `quick_actions`, unless there is no sidebar |
| PDF on aku.edu | upload to the asset folder matching the story path, link as `linktype: asset` (`documents.py`) |
| email | plain url multilink `mailto:x` (not linktype email) |
| dacast video | keep an `iframe` blok — `media_section` video does not play dacast. YouTube/Vimeo → `media_section` |
| photo of a person | only a confirmed AKU-source photo; otherwise the placeholder avatar (asset 208069654188076) |

**Never drop a hyperlink.** If an old link is wrong, find the right target (the
admissions hubs `/admissions/Pages/{kenya,tanzania,pakistan,graduate}.aspx` list
every programme) rather than leaving it unlinked. When the old page itself looks
wrong (duplicate names, dead links), flag it to him; do not guess.

### aku.edu is flaky

Connections drop intermittently; `fix_page.py` retries. If every fetch fails,
the network is the problem, not the page — say so and stop.

---

## 1 · The two halves of this stage

| half | what it is | read |
|---|---|---|
| **structure** | the folder tree, the 4,591 placements, the role model | [README.md](README.md) — its START HERE is the runbook |
| **content** | archived aku.edu HTML → Storyblok `page` stories, Medical College Pakistan | the three files below |

1. **[MC-PK-STATUS.md](MC-PK-STATUS.md)** — where it stands. 75 of 374 built,
   299 remaining, which pages must not be rebuilt, what is known-broken, and
   which files cannot be regenerated once aku.edu goes dark.
2. **[MC-PK-RULES.md](MC-PK-RULES.md)** — every conversion rule and the reason it
   exists. Most were written after something broke, or after Rabee corrected a
   page by hand. **Do not change one without reading why it is there.**
3. **[MC-PK-RUNBOOK.md](MC-PK-RUNBOOK.md)** — setting up on a new machine, the
   order the scripts run in, and how to verify a UI change.

Claude's local memory holds the same rules but is **per machine and does not
travel with a clone**. On any machine other than the one this was built on,
`MC-PK-RULES.md` is the only copy.

---

## 2 · The four things that will bite you first

**`spacing_preset` is always `"subsection"`; the legacy `spacing` plugin is never
written.** One exception, and it is his: a row that owns its spacing carries
`"section"`, and the blok inside it carries `"zero"`.

**Use a component's rich-text slot, never its plain text field.** Using
`info_accordion_item.content` instead of `.body` flattened 275 accordion panels
across 23 pages and lost every list, link, table and picture in them.

**Most of the content is not in the HTML.** SharePoint webparts are filled by
JavaScript from lists. `out/work/page_widgets.json` holds 97 recovered sets that
exist nowhere else now. Never overwrite it — `recover_widgets.py` merges.

**The archived HTML is the last copy.** aku.edu is being switched off.
`out/work/legacy_html/` is 120 pages that cannot be fetched again once it goes.

---

## 3 · The scripts, in the order they run

| script | does |
|---|---|
| `pipeline/recover_widgets.py` | pulls accordion / gallery / tiles / tabs data from AKU's open REST API. **Merges** |
| `pipeline/build_pages.py` | archived HTML → `out/work/page_payloads.json`. Refuses to write a page that keeps under 70% of its source text |
| `pipeline/upload_page_media.py` | downloads from aku.edu, uploads to Storyblok, files each asset at its own story's path. Resumable |
| `pipeline/create_pages.py` | creates or **updates in place**. Never creates a folder. `--protect`, `--only`, `--apply` |
| `pipeline/build_review_portal.py` | the 75-page index |
| `pipeline/build_compare_portal.py` | old page beside new, one window, draggable divider |
| `pipeline/build_sidebar_csv.py` | which built pages have a side navigation |

Abdullah's sheet builder and page fixer (§0a):

| script | does |
|---|---|
| `pipeline/sheet.py` | the team CSV: destination folder/slug, story name, absolute URLs |
| `pipeline/build_from_sheet.py` | wraps `build_pages`: accordion cards, video, iframes, the `Schema` check, `--style house\|team` |
| `pipeline/house_style.py` | the house-style rules in §0a — section text, lists, publications, navigator, card text |
| `pipeline/fix_page.py` | rebuild ONE existing story from its old page. Dry run unless `--apply`; refuses on content loss, schema problems or a stale story |
| `pipeline/apply_fix.py` | write `out/work/fix/<sid>.after.json` in place, stale check, backups |
| `pipeline/club_page.py` | student club pages: about, executive committee, signature events, cards, navigator |
| `pipeline/documents.py` | aku.edu PDFs → Storyblok assets, relinked |
| `pipeline/score_against_reference.py` | score built pages against the hand-built ones |
| `COMPONENT-MAP.md` | old-page pattern → component, with the reasons |
