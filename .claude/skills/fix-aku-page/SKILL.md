---
name: fix-aku-page
description: Fix an AKU Storyblok page from its old aku.edu page. Use whenever the user gives an old aku.edu URL (www.aku.edu/...aspx) together with a Storyblok editor URL (app.storyblok.com/#/me/spaces/289824742951963/stories/0/0/<id>), with or without extra instructions ("put this in cards", "make it beautiful"), or asks to fix/rebuild/redo an AKU page.
---

# Fix one AKU page

Abdullah Sultan (AKU migration team) sends pairs: **old aku.edu URL + Storyblok
editor URL**, one page at a time. Make the Storyblok story hold everything the
old page held, laid out in his house style, and write it **unpublished**.

Read `Pages-Pipeline/CLAUDE.md` §0a once per session: the full house-style table
and the rules behind it. Everything below runs from `Pages-Pipeline/pipeline/`.

## 0. Once per laptop / session

```
python setup_check.py            # first time: python setup_check.py --token sb_pat_...
python recent_edits.py --days 3  # what he corrected by hand since our last writes
```
If `setup_check.py` fails on the token, ask him for one (Storyblok → My account →
Personal access tokens). Never put a token in a tracked file or a commit.
Read `recent_edits.py` output: a correction he made (removed a blok, moved a
highlight, changed columns...) is a rule. Apply it from now on, add it to
`house_style.py` if it is mechanical, and to CLAUDE.md §0a.

## 1. Dry run, then decide

```
python fix_page.py "<editor-url>" "<old-url>"
```
It saves `out/work/fix/<sid>.before.json`, the old HTML in `html/<sid>.html`,
and a proposed body in `<sid>.after.json`, and prints what changes.

- **The generic build is right and he gave no extra instruction** →
  `python fix_page.py "<editor-url>" "<old-url>" --apply`
- **He asked for something specific, or the story is already mostly right** →
  a targeted edit (step 2). A mostly-correct story is edited, not rebuilt.
- **A student club page** (`students/clubs-societies/<cc>/...`) →
  `python club_page.py <sid>` then `python apply_fix.py <sid>`.

Look at the old page yourself too (the html file, the main `MSOZoneCell`):
widgets, images, videos, PDFs, the left sidebar, contact boxes.

## 2. Targeted edit

Write a short script in `out/work/fix/<name>.py` (gitignored) using `page_edit`:

```python
import sys; sys.path.insert(0, '.')
from page_edit import Page, P, H5, hs, story_link
pg = Page('<editor-url>', '<old-url>')         # re-reads the live story
body = pg.body
# ... edit body with hs.section_text / hs.publications / hs.pub_item /
#     hs.sub_group / pg.navigator() / pg.nodes(el) ...
pg.save(body)                                   # refuses if a word/link is lost or schema fails
```
then `python apply_fix.py <sid>`. Run scripts with `python ../out/work/fix/<name>.py`.

## 3. Rules that are never broken

- **Write unpublished.** `--publish` only when he says "publish" for that page.
- **Never drop a word or a hyperlink.** If an old link is wrong, find the right
  target; if the old page itself looks wrong, tell him rather than guess.
- **He edits while you work.** Re-read before writing (`Page()` and `fix_page`
  do); `apply_fix.py` refuses a story changed since it was read.
- **Back up after every write** (the scripts do it, into `backup/storyblok/fixes/`).
- Never delete and re-create a story, never create content folders, never touch
  Rabee's Medical College pages (`regions/pk/entities/mc/`, Pages-Pipeline/CLAUDE.md §0).
- aku.edu PDFs → Storyblok assets (`fix_page --apply` does it; else `python documents.py <sid> --apply`).
- dacast video stays an `iframe` blok; YouTube/Vimeo → `media_section`.
- Pictures of people: only confirmed AKU-source photos, else the placeholder avatar.

## 4. Report back

Short, in his terms. Say:
- what the page holds now, block by block, in plain words
- what moved, and what you added or renamed (any heading you made up)
- that every word and link is kept (or what is not, and why)
- unpublished, backups saved
- anything odd on the old page he should know (wrong links, duplicates, missing content)

Then wait for the next pair.
