# CLAUDE.md

Guidance for Claude Code working in this repository. Most of what follows is here
because something went wrong once; where that is true, the breakage is named,
because that is what makes a rule stick.

**Read [ARCHITECTURE.md](ARCHITECTURE.md) for the design and
[CODING_STANDARDS.md](CODING_STANDARDS.md) for the rules.** This file is the
working context: what the project is, what is true that will surprise you, and
what has already gone wrong.

---

## 1 · What this is

AKU's website content is moving out of SharePoint into **Storyblok** — the
articles, the folder tree they live in, and every image, video and document they
reference.

**The SharePoint site is being switched off.** Anything not captured is lost when
it goes. That is why raw exports are committed, why backups are taken at both
ends, and why a step that cannot do its job must stop rather than guess.

| Type | State |
|---|---|
| **news** | **3,606 stories live**, 0 failed. 2,417 assets uploaded, 990 reused, 214 unrecoverable. Four in-place updates since: Twitter embeds, PDF links, 4 broken hrefs, the 11 Aug restore |
| **blogs** | **all 83 live and published**, 0 failed. Media filed beside each blog. `category`, `isFeatured`, `entities` and tags wait on the dev — see `Blogs-Pipeline/PENDING_DEV.md` |
| **events** | **2,710 live and published**, 0 failed. 2,862 assets; 29 banners absent from the export. `contact` and `event_types` wait on the dev |
| **pages** | site structure and permissions; its own stage, shares no code |

Space `289824742951963`. Default branch **`master`** (there is no `main`).

---

## 2 · The design in three sentences

News, blogs and events are the same job over different SharePoint lists, so there
is **one copy of the code** in `pipeline/` and each type declares what is
different about it. Pages is a different job — folder tree and permissions, no
list of items — so it keeps its own scripts and inherits nothing. Two rules
follow, and everything obeys them:

> **Code lives under `pipeline/`. Data lives under `<Type>-Pipeline/`.**
>
> **Anything that differs between types is a value, not a branch.**

`if P.type == "blogs"` appears nowhere. There are exactly three places a
difference can live, and if you are adding one somewhere else, stop:

| Seam | Where | For |
|---|---|---|
| **Paths** | `pipeline/core/paths_root.py` | `P.STORIES` resolves per type; a blogs run cannot name a news file |
| **Values** | `config/types/<type>.json` | column names, payload shape, routing, component, skipped steps |
| **Behaviour** | `<Type>-Pipeline/pipeline/pipeline.py` | a hook, or a same-named file that overrides a step |

**News overrides nothing.** That is the measure of whether this is working.

---

## 3 · Layout

```
pipeline/                THE SHARED CODE. Knows no content type.
  base.py                  class ContentPipeline
  run_pipeline.py          stage 1 orchestrator      entry point
  new_type.py              scaffold / --check a type entry point
  check_before_push.py     did I touch someone else's file?
  install_hooks.py         turn the pre-push guard on
  _bootstrap.py            puts every folder below on sys.path
  core/                    the seam and shared helpers. IMPORTED, NEVER RUN.
                             paths_root.py  every path, per type
                             fields.py      F.get(item, "body") — no column names
                             steps.py       the step list, from config/steps.json
                             text_clean.py  entities, markers, invisibles
                             link_routing.py where a SharePoint link should point
  content/                 source export -> story payload
  media/                   images, video, documents
  analyze/                 inventories and validation. READS, NEVER WRITES.
  taxonomy/                Region / Entity / Department
  migrate/                 disk <-> Storyblok. THE ONLY NETWORK CODE.
    download/                aku.edu -> disk   (read-only, interruptible)
    upload/                  disk -> Storyblok (writes)
    update/                  change stories ALREADY LIVE, in place
    review/                  verification, reports, backups

News-Pipeline/     pipeline/ data/ assets/ backup/    3,606 live
Blogs-Pipeline/    pipeline/ data/ assets/ backup/    83 live
Events-Pipeline/   pipeline/ data/ assets/ backup/    2,710 live
Pages-Pipeline/    pipeline/ data/ out/ portal/       inherits nothing

config/types/*.json      what differs per type  (_TEMPLATE.json is boilerplate)
config/steps.json        the 22 shared steps, as data
storyblok_space/         snapshots of the space — read-only, nobody's to merge
docs/  tests/            the specs; 126 tests
```

Each folder has a README stating its job. A file in the wrong folder is a bug in
the structure, not a detail.

---

## 4 · Environment and commands

- **Python 3.10+**, `requirements.txt`. The venv lives **outside** the repo at
  `../.venv` (Windows: `..\.venv\Scripts\python.exe`).
- **PostgreSQL** for migration state; `pipeline/migrate/db.py init` creates it.
- **Node 20+** only for `storyblok-viewer/` and the pages portal.
- Stage 3 needs `config/storyblok.json` — gitignored, one per person.

```bash
# stage 1 · content
python pipeline/run_pipeline.py all [--type blogs]
python <Type>-Pipeline/pipeline/run.py            # equivalent, cannot pick wrong
python <Type>-Pipeline/pipeline/run.py --describe # what this type overrides

# stage 2 · taxonomy
python pipeline/taxonomy/run_taxonomy.py [status|tree]
python Blogs-Pipeline/pipeline/resolve_taxonomy.py    # blogs has its own

# stage 3a · media, ONE process behind a lock
python pipeline/migrate/download/run_media_all.py --workers 6

# stage 3b · upload, resumable
python pipeline/migrate/review/dump_sb_tree.py    # refresh the folder tree FIRST
python pipeline/migrate/upload/run_migration.py

# stage 3c · change stories that are already live
python pipeline/migrate/update/run_update.py --list --type blogs
python pipeline/migrate/update/run_update.py <job> --type blogs           # dry run
python pipeline/migrate/update/run_update.py <job> --type blogs --apply   # writes

# review — none of these write
python pipeline/migrate/review/audit_assets.py --csv
python pipeline/migrate/review/verify_folders.py --csv
python pipeline/migrate/review/export_warnings.py
python pipeline/migrate/review/backup.py --type news [--verify]

# adding a type
python pipeline/new_type.py --list
python pipeline/new_type.py articles
python pipeline/new_type.py articles --check      # profile vs the REAL export

python -m pytest tests/     # 126
ruff check .
```

**`--type` defaults to `news`, which is live.** Set `AKU_CONTENT_TYPE` once, or
use the type's own `run.py`.

---

## 5 · Two people, three content types

`master` is the only branch. Events and pages are **the same person**; blogs is
another; news is done.

**You own `<Your-Type>-Pipeline/` and `config/types/<your-type>.json`.**
`pipeline/` is shared and is the only thing that can break someone else's work.

Before editing `pipeline/` to make one type behave, there is almost always
somewhere better:

| You want to | Where it goes |
|---|---|
| skip a step | `"skip_steps"` in your profile |
| add a step only you have | `"extra_steps"` in your profile |
| a differently-named column | `"fields"` |
| a different payload shape | `"content_fields"` |
| different routing | `"hierarchy"` |
| different behaviour in a step | a hook in your subclass |
| replace a step outright | a same-named file in `<Type>-Pipeline/pipeline/` |

Blogs needed **one** shared change to run end to end — tags arriving as
`"Label|GUID"` rather than SharePoint objects — and that was a real gap in the
base, not a blogs quirk.

```bash
python pipeline/install_hooks.py --type blogs   # once per clone
python pipeline/check_before_push.py --type blogs
```

The hook refuses a push touching someone else's folder and runs the tests;
`AKU_ALLOW_SHARED=1 git push` when the shared change is deliberate. There is no
CODEOWNERS file — with three people and non-overlapping folders it would be
ceremony. Full rules: [CONTRIBUTING.md](CONTRIBUTING.md).

---

## 6 · Never do these

**Never create a content folder.** `regions/` and `global/` belong to the
front-end developer. `ensure_folder` has a hard stop; a missing folder is an
error with instructions, not something to invent. Asset folders are a different
namespace and *are* created.

**A portal must open from a bare clone** — [docs/PORTALS.md](docs/PORTALS.md). Someone has to be able to `git clone`,
double-click the HTML, and see it work — no Python, no database, no 3.5-hour
media download. The people who most need a portal are exactly the ones who will
never run the pipeline. `blogs-portal.html` was committed and looked perfect on
the machine that built it while pointing at `../assets/Blogs/media/…`, which is
gitignored: **181 broken images for everyone else.** Images now resolve through
`data/asset_map.json` to their uploaded `a.storyblok.com` URL, so nothing on disk
is needed. Test it by stashing everything untracked and opening the file.

**Back up immediately after anything that writes to the space. Not before —
after.** An upload, an update run, an asset move: the moment it finishes, take
the snapshot. Storyblok keeps **no version history**, so the read-back archive is
the only record of what the space held, and the only thing a later "was it always
like that?" can be settled against.

```bash
python pipeline/migrate/review/backup.py --type blogs
python pipeline/migrate/review/backup.py --verify      # diff vs live, no write
```

It writes two files per type: `backup/raw/` is the SharePoint export as it
arrived — the only record once the site is switched off — and
`backup/storyblok/` is every story **read back from the API** rather than assumed
from the payload that was sent. Both are committed; `.gitignore` names them as
explicit exceptions.

**A backup that silently contains the wrong content is worse than none.**
`backup_storyblok` selected stories from the tracking database, which holds news
and nothing else — so `--type blogs` archived all 3,606 **news** stories into
`Blogs-Pipeline/backup/storyblok/`, under a filename saying blogs. It now selects
by the type's own component, the one thing true for every type.

**Never delete and re-upload a story.** Update in place. A new id breaks every
review link already shared and loses manual edits. **Migration is not one pass**
— the dev hands over a field after the stories are up, a plugin's value format
only becomes knowable once something has it filled, a component we worked around
gets replaced. All of that goes through `pipeline/migrate/update/`, which reads
the live story, replaces only the fields the plan declared, and writes the rest
back untouched. Write a plan; do not hand-edit and do not re-upload.

**Never create an asset folder without looking first.** `ensure_asset_folder`
used to POST and only search if the post failed, on the assumption that "the API
rejects a duplicate name under one parent". **It does not.** The cache lives in
memory, so every fresh process rebuilt the whole tree beside the last one — the
space reached **769 asset folders, 7 `regions` roots and 5 `global` roots**, 444
of them redundant. It now seeds from `storyblok_space/asset_folder_tree.json`
(`P.ASSET_TREE`, refreshed by `migrate/review/dump_asset_tree.py`) and looks up
before it creates.

**Deleting an asset folder is not a leaf operation.** Storyblok does not delete a
folder's children with it — it **moves them to the root**. Cleaning up the
duplicates without re-parenting first left 142 folders at the top level and
emptied `regions/` and `global/`. Re-parent, then delete.

**`204 No Content` is success.** A PUT on an asset and a DELETE on a folder both
return it. Accepting only `(200, 201)` is how a run that moved 786 assets
perfectly reported `0 moved, 786 failed`.

**Never run two media resolvers at once.** They share `media_urls.json` and the
slower one rewrites it from its own memory, silently reverting corrections.
`run_media_all.py` holds a lock.

**Never let a scoping flag discard state.** `--refresh` once skipped loading the
cache, so a run scoped to 20 stories saved only those 20 and wiped 731 entries.

**Never modify a component or page schema.** Only the dev does that. If a payload
does not fit, the payload is wrong.

---

## 7 · Hard-won lessons

**Never name a content type in shared code.** Forty-five places said
`item["NewsContent"]`. For a blog that returns `None`, so two steps ran, exited
0, and wrote empty rich text for all 83 — no error anywhere. Ask the profile:
`F.get(item, "body")`.

**Find a path, do not count `dirname()` calls.** This has broken four times:
`paths_root.py` resolved the repo root to `pipeline/` after moving into `core/`;
`storyblok_config.py` did the same and returned `space_id: None`, so every API
call came back **401**; `join.py` reached for `../data/taxonomy/` and silently
stopped enriching; `story_media_classification.py` wrote the viewer constants
into `pipeline/storyblok-viewer/`. Anchor on something only the target has.

**A filter written for one thing will catch another.** The declarative payload
builder skipped every key beginning with `_`, meant for `_comment` entries.
`_uid` is a real Storyblok field, and all 3,606 payloads silently lost it.

**Never let a `set` decide the order of a committed file.** `build_url_lookup`
built its variants in a set literal; Python randomises string hashing per
process, so every regeneration wrote the same 7,057 entries in a different order
— a 5,774-line diff meaning nothing.

**A snapshot is only a baseline if you know how it was made.** Verifying a rename
by diffing 3,606 payloads showed all 3,606 changed. The *before* state had been
left by a lone `build-stories` run, which empties `media[]`. The refactor was
clean.

**Read the exit code, not the last line.** `all` ends in a wall of output, and two
steps print `Validation: FAILED` **by design** — they report the 206 unrecoverable
media and return zero. That is what let a genuinely failing step hide for weeks.

**A test that cannot fail is worse than no test.** The first entry-point test
imported in-process, after the test module had already called
`_bootstrap.ensure()`, so it passed against a file with its bootstrap deleted. It
now uses a fresh interpreter.

**Beware the auto-fixer.** `ruff check --fix` sorted the imports in `new_type.py`
and put `from paths_root import ...` above the `ensure()` that puts paths_root on
sys.path. It would also have deleted `import _bootstrap` from 65 files as unused.
The import now calls `ensure()`, so it cannot be removed as dead.

**Silence is not success.** `subprocess.run(capture_output=True)` held an hour of
output until the child exited, so a stage looked hung. Stream, and show position.

**Retry connection errors, not just HTTP errors.** `SB._call` retried 429 and 5xx
but let a `ConnectionError` raise, ending two runs at 95 and 8 minutes.

**Pool the S3 session.** A bare `requests.post()` per file left thousands of
sockets in `TIME_WAIT` until Windows ran out of ephemeral ports — that is what
`WinError 10013` means.

**Rebuild nothing by regrouping tree nodes if a string split will do.** Splitting
paragraphs by moving BeautifulSoup children destroyed six stories — 2279 came out
as `<p><br/>×19</p>` with all 4,000 characters gone.

**Do not put `/Pages/` in the chrome filter.** Real banners live at
`/news/PublishingImages/pages/News_Admin/…`. It silently deleted content images
and made 165 stories look empty.

**A text node is a fragment, not a string. Never trim one.** Wiring the shared
cleaner into `convert_richtext` looked harmless and would have rewritten **2,449
of 3,606 news stories**: `clean_text` ended with `.strip()`, and inside rich text
the renderer *concatenates* adjacent text nodes, so the space at a node's edge is
the space between two sentences.

    ...Conference programme. This year's SCCA Conference...
    ...Conference programme.This year's SCCA Conference...

`collapse=True` trims, because a biography or a summary is a whole value.
`collapse=False` does not, because a node is half of something. Nothing was
published — it was caught by diffing all 3,606 before applying, which is the
only reason it is a paragraph here and not an incident. **Any change to shared
text handling must be measured against news before it runs.**

**Measure a guess before shipping it, and prefer a gap.** Twice now the obvious
match has been the wrong one: `stephen-lyon.jpg` sits in the same folder as post
15 "Stephen Lyon: I owe a debt of gratitude to Pakistan", whose real banner is
`Blogs_banner_SL.jpg`; and "Didar Ali" drew Salim Surani's photograph because
"ali" hides inside "sALIm". Both were caught by scoring the rule against pairs
already known to be correct — nearest-upload-time picked 43 of 69, rarest-word
title matching was wrong 11 times out of 28. A rule that cannot be measured
should not be run, and a rule that abstains is doing its job. **A wrong image on
a published article is worse than no image.**

**Check output, do not assume it.** Every bug above was found by looking at a
result: a banner that was a logo, a counter that went backwards, a read time
implying 16 wpm, a description that was the word "The".

---

## 8 · Facts that surprise people

**No department field exists.** 41 columns, none of them a department. The 89
department folders come from 16 tag labels, so a public-awareness piece tagged
`Cardiac disease` files under Cardiology. Never present one as authoritative.

**678 entities and 20 regions are inferred**, not read. Check `provenance`.

**`Entity = "Global"` means "no faculty owns this"** — exactly the set with
`LocalApproverGroup = "Global Approvers"` (2,048/2,048). Not a region.

**Nine values in the Entity column are not entities** and route to `global/news`:
`Global`, `News training`, `Student Affairs and Services`, `Office of the
Provost`, `Office of the President`, `Office of the Registrar`, `Data Office`,
`Research`, `Library`.

**The folder tree was renamed under us.** The dev changed every folder to a short
code: `regions/pakistan/entities/medical-college` became `regions/pk/entities/mc`.
Storyblok moved the stories with them — all 3,606 verified present, 0 missing —
but every review link shared beforehand died, and `target_full_slug` in the
reports is stale. **Refresh `storyblok_space/folder_tree.json` before trusting a
routing result.**

**`spacing` is not optional** — `spacing-field-plugin`, on every blok:

| Components | mobile x | desktop x |
|---|---|---|
| `rich_text` | 20 | **176** |
| `quote_banner`, `media_section` (video), `brand_banner` | — | — |
| gallery, `split_section`, `iframe`, `image`, `button` | 20 | **80** |

All carry margin-bottom 24 / 56, unit `px`. `button` is the one blok whose field
is `Spacing`, capital S.

**`entities` is a list of entity FOLDER IDS** — numeric, as strings. Not UUIDs,
not slugs. 1,575 stories legitimately have none.

**Images keep their source position.** A lone image stays *inside* the rich text;
the standalone `image` blok renders it far too large. Two or more consecutive
images become a gallery **at that point**, not at the end.

**`AERR` is not a typo** — it comes from the approver group `CA AERR`. Do not
"correct" it. Short names never contain whitespace; `COE WCH` is emitted as
`COE-WCH`.

**Two odd placements were reviewed and kept**: `Pakistan / Arusha Climate and
Environmental Research Centre` (0 stories) and `Afghanistan / East Africa
Institute` (1). The first is in `config/tree_accepted_exceptions.csv`.

**Read time**: 238 wpm plus 12s per image. The reference story's hand-typed
"28 min read" for 447 words implies 16 wpm — a placeholder, not a spec.

**SharePoint has no buttons.** No `<button>`, no `role="button"`, no `btn` class
in 3,606 stories — only 19 with CTA-worded or CTA-styled links.

**179 news articles are one giant paragraph** with `<br><br>` between what are
plainly paragraphs. The splitter runs **last**, on the serialised HTML.

**Blogs differ from news in ways that matter.** No `City` column, so region comes
from inside the entity name (`Institute for Educational Development, Pakistan`).
`Metadata.csv` is the *content*, not a media manifest. Tags arrive as
`"Label|GUID"`. Bodies carry inline `{pullquote}` markers.

**Do not restyle inline formatting.** Link colour, bold, italic and underline come
across as authored.

---

## 9 · Text out of SharePoint — use `text_clean`, always

Three faults arrive in **every** type's HTML. `pipeline/core/text_clean.py`
handles all three; a type that derives text from HTML and does not call it will
ship at least one of them. Events will hit these on day one.

```python
from text_clean import clean_richtext, clean_text, strip_html

strip_html(bio)                 # a field holding HTML
clean_text(summary)             # a plain string
clean_richtext(doc)             # a Storyblok rich-text document
```

**Entities must be decoded.** Strip the tags, leave the entities, and the reader
sees the literal characters mid-sentence — *"Dr&#160;Asad I Mian"*. That reached
**published blog biographies: 88 `&#160;`, 12 `&amp;`, 2 `&quot;`, 1 `&#58;`
across 34 blogs.** The portal decoded them and the payload builder did not,
which is exactly why there is now one shared function instead of two code paths.

Every form counted across both exports, so nothing here is guessed:

| | blogs | news | |
|---|---|---|---|
| `&#58;` | 2,044 | 10,998 | a colon — usually inside a URL, so a live link |
| `&#160;` | 672 | 14,026 | non-breaking space |
| `&quot;` | 149 | 8,041 | |
| `&amp;` | 59 | 805 | |
| `&#123;` `&#125;` | 38 each | 99 each | **braces — decode to `{` and `}`** |
| `&mdash;` `&gt;` `&lt;` `&#39;` | — | 90 | |

`&#123;` is the one that catches people: it decodes to `{`, so entities must be
decoded **before** markers are matched or `&#123;pullquote&#125;` reaches the
page intact. `clean_text` does them in that order and a test pins it.

**Decoding runs once, deliberately.** `&amp;#160;` would need a second pass, but
looping until stable destroys text that legitimately shows markup — a sentence
containing `&amp;amp;` means to render `&amp;`. Neither export has a single
double-encoded entity (counted, not assumed), so `looks_encoded()` reports any
survivor instead, and `tests/test_text_clean.py` fails the build on it.

**Position markers are not content.** SharePoint marks where a component belongs
with a token left in the prose: `{pullquote}` (14 across 13 blogs),
`{EmbeddedCode}` (1). Once the quote is a `quote_banner` and the embed a
`social_embed`, the marker has done its job — leave it in and the reader sees
`{pullquote}` in the middle of a paragraph.

**Paragraphs of pure whitespace.** The editor leaves paragraphs holding only
`<br>` and no words — **79 across 30 blogs**, one of them a single paragraph
with seventeen line breaks. They render as a gap. Strip a paragraph only when it
has no text **and no image**: images live inside the rich text, so testing "no
text" alone silently deletes a picture.

**Hidden characters.** Every one present in the two exports, counted — not a
guess at what might be there:

| | count | what happens |
|---|---|---|
| `U+200B` zero width space | **8,187** | deleted |
| `U+202F` narrow no-break space | 79 | becomes a normal space |
| `U+00A0` no-break space | 47 | becomes a normal space |
| `U+2028` line separator | 6 | becomes a newline |
| `U+00AD` soft hyphen | 5 | deleted |
| `U+2009` thin space | 1 | becomes a normal space |
| `U+FEFF` byte-order mark | 1 | deleted |

The rest of each Unicode block is handled too, so the next export cannot
introduce a variant nobody thought of, along with the bidirectional controls —
invisible characters that silently reorder the text around them.

**`U+200C` and `U+200D` are never stripped.** Zero-width non-joiner and joiner
change how Urdu, Arabic and Indic scripts render, and 44 news stories carry
Arabic and Urdu. **Filtering by Unicode category `Cf` — the obvious way to catch
zero-width spaces — sweeps both away with them.** That is why the table is an
explicit list of code points and not a category test.

**In an href, an invisible is not cosmetic — it breaks the link.** Four live
news stories carry one at the end of a URL, so the browser asks for a host that
does not exist. `clean_href` deletes rather than substitutes there: a no-break
space becomes a space in prose, but inside a URL it is a fault either way and
turning it into a space would hide it from whoever goes looking next.

**Write the table as code points.** The first version used the characters
themselves and was unreviewable — nobody can see that a string of invisibles has
picked up a plain space and lost `U+00A0`, which is exactly what happened, and
only `clean_href` caught it because it skips the whitespace collapse that was
masking the bug.

All three were found by a person looking at published pages, not by any check.
`tests/test_blogs_payload.py` pins them down now.

## 9a · Encoding

Send **UTF-8**. Do not transliterate — 711 occurrences across 98 characters are
legitimate content: accented names, Arabic and Urdu for 44 stories, `£`, `°`.
Strip only invisibles: U+200B (in 3,004 of 3,606 files), U+FEFF, U+00AD. The 12
U+FFFD are unrecoverable and need a human.

**Always `encoding="utf-8"` on `open()`**, and `newline="\n"` when writing.
Python's Windows default is cp1252 and raises on the first accented name.

On Windows, PowerShell 5.1 reads UTF-8 as ANSI — use Python for files containing
non-ASCII. There is no heredoc in PowerShell; write long strings to a file.
`run_pipeline.py` gives every child `PYTHONIOENCODING=utf-8`, because two stages
died on *printing* a Turkish `ğ`, not on the work.

---

## 10 · Verifying a change

**Run it. Reading is not checking.**

For any change to shared code, prove news is unchanged — its 3,606 payloads are
known-good:

```bash
find News-Pipeline/data/stories -name '*.json' | sort | xargs md5sum > /tmp/before
python pipeline/run_pipeline.py all
find News-Pipeline/data/stories -name '*.json' | sort | xargs md5sum > /tmp/after
diff /tmp/before /tmp/after && echo unchanged
```

That check has caught what reading the diff did not. Also run the other types far
enough to prove they still work, and `pytest`.

**Backups: after anything that writes, every time.** See §6 — the rule is
*after*, not before, because the point is a record of what the space now holds.

```bash
python pipeline/migrate/review/backup.py --type news   # both ends, gzipped
python pipeline/migrate/review/backup.py --verify      # diff vs the live space
```

`backup/raw/` is the export as it arrived — the only record once SharePoint goes.
`backup/storyblok/` is every story read back from the API rather than assumed.
Both are committed; `.gitignore` names them as explicit exceptions.

**Never commit** `config/storyblok.json`, `config/database.json`, `assets/`, or a
large regenerable snapshot. `storyblok_space/stories_full.json` is 44 MB and once
produced a single 1.3-million-line diff that swamped everything real in the same
commit.

---

## 11 · Still open

- **blogs: 75 of 83 are not uploaded.** The 8 demo stories are live and reviewed;
  the rest wait on the owner. `python Blogs-Pipeline/pipeline/upload.py --all
  --apply` when told. `global/blogs` now exists — that entry used to say it did
  not
- **`category` and `isFeatured` are empty on all 83 blogs.** Nothing in the space
  has either plugin filled, so there is no example of the value format. One saved
  example of each unblocks 80 and 43 posts respectively. `entities` needs only
  the field — the plan is written and the format is known from news
- **events** is migrated — 2,710 live and published. Left: **29 banners absent
  from the export** (the files are on aku.edu, which is being switched off), event
  2486's 2 assets waiting on one asset folder, and `contact` / `event_types`
  waiting on the dev, both plans written. `Events-Pipeline/README.md` §7
- **blogs data with no field**: `FeatureSequence` (45), `Close Comments` (14),
  `Post Year`, and 626 comments. `IsActive` is ignored on the owner's
  instruction — blog 37 is the only `False` and it publishes anyway. Every one
  of these decisions, with its reasoning, is in `config/types/blogs.json` under
  `decisions`
- **blogs `entities` is needed by 17, not 83.** The field is a list of entity
  FOLDER IDS — the story's own entity plus any it is shared into — not the
  Entity column. 66 of the 83 name something that is not a faculty (`Global`,
  `Training`, `Data Innovation Office`), so their list is legitimately empty,
  as it is for 1,575 news stories. 12 are filed under an entity; 5 are shared
- **13 blogs will publish with no hero.** Closed, not pending — SharePoint holds
  no banner-to-post mapping at all (`Banner_x0020_Image` is null on all 89 posts,
  no attachments, the detail page renders client-side). Evidence and the
  measured reason for not guessing are in `data/banners_absent.json` and
  `fetch_missing_media.py`
- **DONE, kept for the record:** the 38 Twitter iframes are now `social_embed`
  bloks, 47 stories' PDF links point at their uploaded assets, and 4 broken
  hrefs are fixed. The 5 iframes still in the space are 3 working YouTube
  embeds and 2 of the dev's own test stories, deliberately left alone
- **blogs decisions are recorded** in `config/types/blogs.json` under
  `decisions` and `shared_placement`, with the reasoning. Post Year is **kept** —
  7 of 83 are December posts filed under the following year, so it is an
  editorial issue-year and cannot be derived from `date`. Blog 37 is the one
  post with `IsActive = False`
- **54 language PDFs** still link to aku.edu, which dies with the site
- **566 internal links** still point at aku.edu, kept deliberately so they can be
  found and replaced now that every story has an id
- **214 media** unrecoverable; listed in `reports/assets.csv`
- **Two tables** skipped and rebuilt by hand: news stories 1335 and 3288
- **`ruff format`** is not enforced — it would rewrite 106 of 139 files, which
  belongs in its own deliberate commit
