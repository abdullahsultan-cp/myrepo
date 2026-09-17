# CLAUDE.md — Pages-Pipeline

Working context for the **pages** stage. Read the root
[../CLAUDE.md](../CLAUDE.md) first for the repo's conventions and the traps that
apply everywhere; this file is only what is true about pages.

---

## 0 · WHOSE WORK THIS IS — read before touching anything

**This branch is Muhammad Rabee Amir's work** (`rabee.amir@cloudprimero.com`).
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
