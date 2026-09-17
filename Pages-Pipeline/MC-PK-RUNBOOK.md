# MC-PK — setting up on another machine, and the command order

Read [MC-PK-STATUS.md](MC-PK-STATUS.md) for where the work stands and
[MC-PK-RULES.md](MC-PK-RULES.md) for why the builder does what it does.

---

## 1 · First run on a new machine

```bash
git fetch origin
git checkout pages/mc-pk-migration
git pull
```

**Two things are not in the repo and never will be.**

**a. The Storyblok token.** `config/storyblok.json` is gitignored, one per
person. Create it by hand:

```json
{ "space_id": "289824742951963", "management_token": "<your PAT>" }
```

> **Rotate the PAT before using it again.** The one used on the first machine was
> pasted into a chat window in plain text on 13 Sep 2026. Issue a new personal
> access token in Storyblok, and do not paste it anywhere but this file.

**b. `out/work/legacy_images/`** — 854 MB of downloaded source pictures, far too
large for git. You do **not** need them: every one is already uploaded and
recorded in `out/work/page_asset_map.json`. `upload_page_media.py` re-downloads
only what is missing from that map, and while aku.edu is still up it can.

Then:

```bash
python -m venv ../.venv                  # the venv lives OUTSIDE the repo
../.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Windows note: always `encoding="utf-8"` on `open()`, and set
`PYTHONIOENCODING=utf-8` before running anything that prints page titles — the
default cp1252 raises on the first accented name.

Check it works without writing anything:

```bash
python Pages-Pipeline/pipeline/build_pages.py        # rebuilds payloads only
python Pages-Pipeline/pipeline/create_pages.py       # DRY RUN, no --apply
```

`build_pages.py` ends with the retention check. If it exits non-zero, a page lost
content — read the named pages before going further.

---

## 2 · The order things run in

```bash
cd Pages-Pipeline/pipeline

# 1 · recover what JavaScript would have loaded  (merges, never replaces)
python recover_widgets.py                  # all pages
python recover_widgets.py --only 821       # one page

# 2 · build the payloads from the archived HTML
python build_pages.py                      # -> out/work/page_payloads.json
python build_pages.py --only 1085,802

# 3 · download and upload the pictures  (resumable; skips anything already mapped)
python upload_page_media.py                # dry run: download + report
python upload_page_media.py --apply

# 4 · create or update the stories  (never creates a folder; updates in place)
python create_pages.py                                    # dry run
python create_pages.py --apply --only 1085
python create_pages.py --apply --protect "<the 13 paths>" # see MC-PK-STATUS §3

# 5 · BACK UP, immediately after any write
#     (see §3 — there is no one-line script for MC pages yet)

# 6 · the review artefacts
python build_review_portal.py              # -> out/AKU-MC-Pages-Review.html
python build_compare_portal.py             # -> out/AKU-MC-Page-Compare.html
python build_sidebar_csv.py                # -> out/rabee-pages-with-sidebar.csv
```

**Never run two media resolvers at once.** They share state and the slower one
rewrites it from its own memory.

---

## 3 · Backing up

`pipeline/migrate/review/backup.py` selects by content type and does not cover
MC pages. Until it does, the snapshot is taken by reading every story under the
tree back from the API and gzipping it into `backup/storyblok/`. Name the file
for what just happened — the existing ones read
`mc-pages-AFTER-RICHTEXT-ACCORDIONS_…`, `mc-pages-AFTER-DEDUPE-AND-TABS_…`.

Take it **after** the write, not before. The point is a record of what the space
now holds.

---

## 4 · The two review tools

**`out/AKU-MC-Pages-Review.html`** — all 75 built pages with legacy, editor and
preview links.

**`out/AKU-MC-Page-Compare.html`** — the old page and the new one in one window.
Both open by double-clicking, no server.

The comparison embeds rather than frames, because **both live sites refuse to be
framed**:

```
aku.edu             X-FRAME-OPTIONS: SAMEORIGIN + CSP frame-ancestors
app.storyblok.com   X-Frame-Options: SAMEORIGIN
```

So the left pane is the archived HTML with aku.edu's own stylesheet, and its
JavaScript-loaded widgets are rebuilt from the recovered lists **using AKU's own
markup and CSS**, read out of their `Accordion.js`, `Tabs.js` and `gallerywp.js`.
The right pane is rendered from the story content read back from Storyblok. Both
end up in one document, which is the only way to scroll them in lockstep — a
cross-origin frame's scroll position cannot be read or set.

`aku-dev.vercel.app` sends no frame-blocking headers, so **Live** mode frames the
real front end. It renders **published stories only** (14 of 75; a draft comes
back as an empty shell) and scrolls independently.

Deep links work: `#70/split`, `#1/live`, `#58/wipe` — `<sr-no>/<mode>`.

An `<iframe>` is a replaced element: with `width:auto` it takes its intrinsic
300×150 and `left`+`right` will not stretch it. That is why the frame is given an
explicit desktop width and scaled down — sizing it to the half-pane instead makes
the site serve its **mobile** layout.

---

## 5 · Verifying a UI change

There is no headless browser installed, but **Chrome and Edge are on the machine**
and can render a local file to a PNG. Two UI bugs shipped before this was used:

```bash
"C:/Program Files/Google/Chrome/Application/chrome.exe" \
  --headless=new --disable-gpu --hide-scrollbars \
  --virtual-time-budget=30000 --window-size=1920,1000 \
  --screenshot=out.png --allow-file-access-from-files \
  "file:///…/AKU-MC-Page-Compare.html#70/split"
```

Then look at the PNG. Reading the code is not checking it.

---

## 6 · Git

Work on **`pages/mc-pk-migration`**, not `master`. The repo has a pre-push hook
that refuses a push touching another person's folder:

```bash
python pipeline/install_hooks.py --type pages   # once per clone
AKU_ALLOW_SHARED=1 git push                     # when a shared change is deliberate
```

Shared files this branch does touch, deliberately:
`pipeline/migrate/review/backup.py`, `storyblok_space/component_fields.csv`,
`storyblok_space/components.csv`, `storyblok_space/folder_tree.*`,
`storyblok_space/asset_folder_tree.json`, and a narrow set of `.gitignore`
exceptions so the irreplaceable inputs travel.

**Never commit** `config/storyblok.json`, `config/database.json`, `assets/`, or
`out/work/legacy_images/`.
