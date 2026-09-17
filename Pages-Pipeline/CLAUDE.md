# CLAUDE.md — Pages-Pipeline

Working context for the **pages** stage. Read the root
[../CLAUDE.md](../CLAUDE.md) first for the repo's conventions and the traps that
apply everywhere; this file is only what is true about pages.

This stage has two halves, and they are different jobs:

| half | what it is | read |
|---|---|---|
| **structure** | the folder tree, the 4,591 placements, the role model | [README.md](README.md) — its START HERE is the runbook |
| **content** | archived aku.edu HTML → Storyblok `page` stories, Medical College Pakistan | the three files below |

---

## Read these before touching the content build

1. **[MC-PK-STATUS.md](MC-PK-STATUS.md)** — where it stands. 75 of 374 built,
   299 remaining, which pages are hand-finished and must not be rebuilt, what is
   known-broken, and which files cannot be regenerated once aku.edu goes dark.
2. **[MC-PK-RULES.md](MC-PK-RULES.md)** — every conversion rule and the reason it
   exists. Most were written after something broke or after Rabee corrected a
   page by hand. **Do not change one without reading why it is there.**
3. **[MC-PK-RUNBOOK.md](MC-PK-RUNBOOK.md)** — setting up on a new machine
   (including the token, which is not in the repo), the order the scripts run in,
   and how to verify a UI change.

Claude's local memory holds the same rules but is **per machine and does not
travel with the repo**. On any machine, `MC-PK-RULES.md` is the source of truth.

---

## The five things that will bite you first

**Pages 1–13 are hand-corrected.** Rebuilding overwrites Rabee's work. Pass
`--protect` with their paths (listed in MC-PK-STATUS §3), or update a single
field in place.

**`spacing_preset` is always `"subsection"`; the legacy `spacing` plugin is never
written.** The one exception is a row that owns its spacing: `"section"` on the
row, `"zero"` on what is inside it.

**Use a component's rich-text slot, never its plain text field.** Using
`info_accordion_item.content` instead of `.body` flattened 275 accordion panels
and lost every list, link, table and picture in them.

**Most of the content is not in the HTML.** SharePoint webparts are filled by
JavaScript from lists; `out/work/page_widgets.json` holds 97 recovered sets that
exist nowhere else. Never overwrite it — `recover_widgets.py` merges.

**Only touch stories whose `last_author` is Muhammad Rabee Amir.** Other people's
pages are off limits.

---

## The scripts, in the order they run

| script | does |
|---|---|
| `pipeline/recover_widgets.py` | pulls accordion / gallery / tiles / tabs data from AKU's REST API. **Merges** |
| `pipeline/build_pages.py` | archived HTML → `out/work/page_payloads.json`. Refuses to write a page that keeps <70% of its source text |
| `pipeline/upload_page_media.py` | downloads from aku.edu, uploads to Storyblok, files each asset at its story's own path. Resumable |
| `pipeline/create_pages.py` | creates or **updates in place**. Never creates a folder. `--protect`, `--only`, `--apply` |
| `pipeline/build_review_portal.py` | the 75-page index |
| `pipeline/build_compare_portal.py` | old page vs new, in one window, with a wipe divider |
| `pipeline/build_sidebar_csv.py` | which built pages have a side nav |

Back up **after** every write. Storyblok keeps no version history.
