# pipeline/migrate/spaces — whole-space backup and restore

Three sites, three Storyblok spaces, three GitHub repos:

| Site | Space | Backup repo |
|---|---|---|
| **AKUH** | its own | `akuh-storyblok-backup` |
| **AKU** | its own | `aku-storyblok-backup` |
| **AKUEB** | its own | `akueb-storyblok-backup` |

Each space is dumped complete into its own repo, with git history, and can be put
back. Nothing is shared between the three — different component libraries,
different page designs — and no code here assumes otherwise.

Each backup repo is **self-sustaining**: `tools/` holds the whole pipeline, so a
backup or a restore needs nothing but that checkout and Python. This folder is
just where the code is edited; every run copies the current version into the repo
it writes to, and any set-up repo can stand up the next one:

```powershell
# inside a backup repo — no reference to this pipeline anywhere
python tools/sb.py doctor                   # is everything in place?
python tools/sb.py backup --push            # THE ONE CLICK
python tools/sb.py audit                    # prove it covers the space
python tools/sb.py orphans                  # bucket files the space dropped
python tools/sb.py restore-story 12345 --apply
python tools/sb.py restore-assets --apply   # deleted image: bucket -> space
python tools/sb.py rebuild 999888 --apply

# stand up a sibling repo from this one
python tools/sb.py init ../akueb-backups --name AKUEB --space 289824724335130
```

`backup.cmd` / `backup.sh` at the repo root are double-clickable wrappers.
Credentials come from `tools/sites.json` (gitignored) or from the environment —
`SB_TOKEN_<SITE>` and `AZURE_STORAGE_CONNECTION_STRING` — which is what a
scheduled job should use so no secret is written to disk. The site, space id and
region are read from the snapshot, so no command needs `--site`.

```
sb.py            the one command, shipped into every backup repo
sb_common.py     config, HTTP with retries, scrubbing, git   imported, never run
sb_storage.py    where binaries go: a folder, or Azure Blob  imported, never run
sb_portal.py     builds assets-portal.html                   imported, never run
sb_backup.py     space -> repo + container    READS ONLY against Storyblok
sb_restore.py    repo + container -> space    WRITES
test_spaces_e2e.py   121 checks against a fake API. No network, no tokens.
```

**The backup is in two halves.** The text — schema, settings, every story, the
mapping, the scripts and the docs — goes to the site's GitHub repo. The media goes
to **Azure Blob**, because the three spaces hold ~42 GB against GitHub's 1 GB.
`storyblok/manifest_assets.csv` is the join: a relative path and a **sha256** for
every file, so the halves can be proved to match rather than assumed to.

```
"assets": {"backend": "azure", "container": "storyblok-backup",
           "prefix": "AKUH", "tier": "Cool",
           "connection_string": "..."}   or AZURE_STORAGE_CONNECTION_STRING
```

One container, one prefix per site. Blobs are written **Cool** — roughly half the
price of Hot for data written once and read almost never. Not Archive: that is
cheaper again but needs hours of rehydration, and a backup you cannot read for
hours is not one you can restore from during an incident.

---

## This is not `migrate/review/backup.py`

Two different jobs, and confusing them would be expensive:

| | `review/backup.py` | `spaces/sb_backup.py` |
|---|---|---|
| scope | one **content type**'s stories | a whole **space** |
| space | this migration's space, only | AKUH, AKU, AKUEB |
| holds | stories, gzipped, one file | schema, settings, stories, **asset binaries** |
| for | proving what the migration did | disaster recovery for three live sites |
| restores? | no — it is evidence | yes, both directions |

`review/backup.py` stays exactly as it is. That is why every file here carries an
`sb_` prefix: two files named `backup.py` doing different things is how the wrong
one gets run.

## Why this sits under `migrate/`

`migrate/` is the only code in this repo that touches the network, and that is
worth keeping true — it is the one-line answer to "where can something reach
Storyblok from?". Split by flow, like its siblings:

| Folder | Direction | Writes to a space? |
|---|---|---|
| `download/` | aku.edu -> disk | no |
| `upload/` | disk -> Storyblok | yes |
| `update/` | live stories, in place | yes |
| `review/` | audits and reports | **no** |
| `spaces/` | space <-> repo, both ways | `sb_restore.py` only, and only with `--apply` |

`sb_restore.py` is the only script under `pipeline/` that writes to a space this
repo did not migrate. Everything about it defaults to refusing.

---

## Setup

Git LFS must be installed — asset binaries go through it.

```powershell
copy config\sites.example.json config\sites.json
notepad config\sites.json     # space id, token, repo path, assets_dir per site
python pipeline\migrate\spaces\sb_backup.py --check
```

Git LFS is only needed if you commit binaries into the repo — i.e. if you leave
`assets_dir` unset. With the media on a bucket the repo is text-only and needs no
LFS at all.

Clone the three (empty, private) GitHub repos to the paths you put in
`config/sites.json` first — then `origin` is already set and `--push` works. If a
path does not exist the script `git init`s it instead, and you must add the remote
yourself.

Use a **Personal Access Token** (Storyblok -> My Account -> Personal access
tokens). A space-level token 403s on `internal_tags`, `field_types` and several
settings endpoints; the backup still runs and records the gaps in
`_summary.json`. Tokens can come from `SB_TOKEN_AKUH` / `SB_TOKEN_AKU` /
`SB_TOKEN_AKUEB` instead of the file, which is what CI should do.

`config/sites.json` is gitignored, alongside `config/storyblok.json`.

---

## Backing up

```powershell
python pipeline\migrate\spaces\sb_backup.py --site all --push
python pipeline\migrate\spaces\sb_backup.py --site AKU
python pipeline\migrate\spaces\sb_backup.py --site AKUEB --only schema,stories
python pipeline\migrate\spaces\sb_backup.py --site AKUH --no-assets
```

Read-only against Storyblok: every request is a GET.

**A run that finds nothing changed makes no commit.** No timestamp is written
into any tracked file, so an unchanged space leaves `git status` empty. The commit
*date* is when the snapshot was taken — that is what git is for. Assets already
on disk at the right size are not re-fetched, so only the first run is slow.

What lands in each repo:

```
storyblok/
  space.json  components.json  component_groups.json  presets.json
  datasources.json  datasource_entries.json  internal_tags.json
  asset_folders.json  space_roles.json  webhook_endpoints.json
  workflows.json  workflow_stages.json  releases.json  tasks.json
  branches.json  field_types_*.json
  apps.json  app_provisions.json  extensions.json    installed apps
  stories.json            the index
  stories/101.json        one file per story, full content
  assets.json             metadata
  manifest_stories.csv    which story sits in which folder
  manifest_assets.csv     every asset: folder, file path, sha256
  assets_location.json    whether the binaries are here or on a bucket
  _summary.json           counts, and anything the token could not read
  assets/…                only when binaries are committed (Git LFS)
tools/                    a copy of these scripts, so the repo restores alone
README.md  CLAUDE.md  RESTORE.md    written into the repo by each run
```

Each run also writes three documents into the backup repo, so it explains itself
to whoever opens it under pressure — which will not be whoever set it up:

- **README.md** — what every file is, and how to read the manifests
- **CLAUDE.md** — the rules for an agent working in that repo: never hand-edit the
  snapshot, never rewrite history, every restore is a dry run until `--apply`
- **RESTORE.md** — the runbook: verify the backup, repair in place, rebuild a lost
  space, and the manual steps a rebuild cannot do

All three are free of counts and timestamps, so they do not rewrite themselves on
every run and bury the real changes.

### The manifests — the mapping a person can read

The JSON already holds every `parent_id`, but nobody audits a 4,000-story tree by
following id chains. Both CSVs are sorted by path, so a story that moved is one
moved line in `git diff` rather than a changed integer buried in a story file.

`manifest_stories.csv` — id, uuid, kind (story/folder), full_slug,
**parent_folder**, name, component, state (published/draft),
unpublished_changes, **assets_referenced**, backup_file, updated_at:

```
id     uuid      kind    full_slug          parent_folder  component     state      assets  backup_file
10     uuid-10   folder  news               (root)                       draft              
101    uuid-101  story   news/a             news           news_article  published  2       stories/101.json
102    uuid-102  story   news/b             news           news_article  draft      0       stories/102.json
```

`manifest_assets.csv` — id, filename, **asset_folder**, **backup_file**,
**file_present**, content_type, bytes, alt, url:

```
id    filename  asset_folder  backup_file                        file_present
9001  pic.png   photos        assets/800x600/aaaa1111/pic.png    yes
9002  doc.pdf   (root)        assets/x/bbbb2222/doc.pdf          yes
```

**`file_present` is the column that matters.** An asset with metadata but no
binary would be recreated as an empty asset by a rebuild, and every story
pointing at it would render a broken image. The backup prints a warning and the
column says `NO`, so that is knowable before a restore rather than after.

`assets_referenced` counts distinct asset URLs found anywhere in a story's
content — asset fields, rich-text image nodes and URLs written into prose alike.
It is matched on the `/f/<space id>/` path segment rather than on the host,
because paid plans can serve assets from a custom domain and matching on the word
"storyblok" reported zero for those spaces, silently.

**One file per story, not one `stories_full.json`.** This repo already learned
that one: committing the 44 MB single-file dump produced a 1.3-million-line diff
that swamped everything real in the same commit. Per-story files mean one changed
story is one small diff. Named by id, not slug — the slug is what changes when
the dev renames the folder tree, and a slug-named file turns a rename into a
delete plus an add, losing that story's history.

---

## Restoring

**Both modes are a dry run until you add `--apply`.**

### `--mode in-place` — the space is still there

```powershell
$SB = "pipeline\migrate\spaces\sb_restore.py"
python $SB --site AKU --mode in-place --all                     # what drifted?
python $SB --site AKU --mode in-place --story 12345 --apply
python $SB --site AKU --mode in-place --all --apply
python $SB --site AKU --mode in-place --story 12345 --from-rev HEAD~5 --apply
```

Finds each story by its own id and PUTs the saved content back. **It never
deletes and never re-creates** — the rule this repo already holds: a new id
breaks every review link already shared and loses manual edits. The price of that
promise is that a *hard-deleted* story cannot come back this way, because its id
is gone. Those are listed and skipped.

The dry run is useful on its own — it is a diff against the live space:

```
  identical 4318   differ 3   hard-deleted 1   unreadable 0
    12345      news/pk/mc/some-story           content
    12401      news/global/another             content, name
```

Restored by default: `content`, `name`, `tag_list`, `is_startpage`, `meta_data`.
Deliberately **not** `slug`, `parent_id` or `position` — those move a story, and
moving 4,000 stories to repair one broken body is a bigger accident than the one
being fixed. `--with-structure` adds them when you mean it.

Publish state is mirrored from the snapshot, so a story that was a draft when the
backup was taken is not pushed live because it happened to be restored.

`--from-rev` is why the backup is a git repo and not a folder that gets
overwritten: "put it back the way it was on Tuesday" is the actual request, and
only history can answer it.

### `--mode rebuild` — the space is gone, or you are cloning it

```powershell
python $SB --site AKUEB --mode rebuild --into 999888            # dry run
python $SB --site AKUEB --mode rebuild --into 999888 --apply
```

Creates, in dependency order: component groups -> components -> datasources and
entries -> internal tags -> asset folders -> assets -> story folders -> stories
-> a relink pass.

Every id in the new space differs, so references inside content are rewritten as
it goes. Storyblok stores the same asset reference three ways — an asset object
with `id` and `filename`, a rich-text `image` node with `attrs.src`, and bare
URLs sitting in prose — and all three are handled. Fixing only the tidy object
case is how a rebuilt space comes up with half its images missing.

Story uuids are sent on create and kept where Storyblok allows it, which is what
lets internal links survive. Where a uuid comes back different, a second pass
rewrites the links that pointed at it — comparing against what was *sent*, not
against the backup, so a story that merely contains an image is not re-written
for nothing.

Old -> new id maps land in `restore_maps/rebuild-<space>-<stamp>.json`.

**Guards, each overridable with `--force` after reading what it said:**

- refuses to rebuild into the site's own space (that duplicates everything)
- refuses a target that already holds stories (same reason)
- in-place refuses to write one space's backup into a different space id

### What rebuild does not recreate

Captured in the snapshot for reference, but not created:

- space settings, roles, webhooks, workflows and stages, releases, tasks,
  deployment branches, presets
- **installed apps and extensions.** Captured to `apps.json`,
  `app_provisions.json` and `extensions.json`, but installing a marketplace app
  needs an OAuth flow a script cannot drive. Reinstall each one by hand.
- **field-type plugins.** Account-level, not space-level, and there is no create
  API. If the source space used custom plugins — `spacing-field-plugin`, for
  instance — they must already exist on the target account or the components
  referencing them will not save correctly.

Recreate those by hand from the JSON; the generated `RESTORE.md` lists each with
what to do. Webhooks especially should not be recreated blind: they point at URLs
wired to the old space.

A rebuild is **not byte-identical** — every asset gets a new URL, so the result
is equivalent, not the same.

---

## Proving it is actually backed up

```powershell
$SB = "pipeline\migrate\spaces\sb_backup.py"
python $SB --site AKUH --audit           # cheap: no egress. Exits non-zero on a gap
python $SB --site AKUH --audit --deep    # reads every byte back. Bills egress
python $SB --site AKUH --only assets --repair --no-commit   # re-fetch what is broken
```

`--audit` does not re-read the numbers the backup just printed — a backup that
reports its own success is worth very little. It re-queries the live space and
compares: every story id present and holding content, every published version,
every asset's metadata and bytes, the manifests, the portal, and the docs. Any gap
exits non-zero, so it can gate a nightly job.

Two cost decisions are baked in. The default audit reads the sha256 recorded on
each stored blob rather than downloading it, so a nightly check costs nothing; it
catches a missing or replaced file but not corruption in place, which is what
`--deep` is for. And skipping unchanged files by size cannot see corruption that
kept the size — eight bytes overwritten by eight others — so **`--repair`**
deep-verifies first and forces a re-fetch of whatever fails. A test covers exactly
that blind spot.

## Draft and published are two different backups

The Management API returns **drafts**. On AKUH, 231 stories have unpublished
changes and 365 are not published at all — so for those, what visitors see is not
what `stories/<id>.json` holds. Restoring drafts over a live site would publish
work in progress, which is data loss wearing the costume of a restore.

So `stories_published/<id>.json` holds the published version too, fetched from the
Content Delivery API using the space's own delivery token. That token is read from
the space record and **never written anywhere** — `save()` scrubs `first_token`,
and nothing persists it. If the space has no delivery token the run says so loudly
rather than quietly producing a draft-only backup.

## The portal

`assets-portal.html`, at the repo root, one self-contained file per site. The left
pane is the Storyblok asset folder tree with a file count and cumulative size per
node; the right lists each file with its folder, its **path in the container**,
size, type, sha256, and a stored yes/no. There is a filter box, an "only missing
from storage" toggle, and optional thumbnails.

Thumbnails point at Storyblok's public URLs, so they work while the space is alive
and stop resolving once it is gone. That is deliberate: this is a map of the
backup, and the structure, paths and checksums do not depend on them.

## Where the media lives — the decided arrangement

Measured from the three spaces:

| Site | Space | Pages | Media files | Media size |
|---|---|---|---|---|
| AKUEB | 289824724335130 | 177 | 16,334 | 31.65 GB |
| AKUH | 286308248262721 | 3,042 | 5,767 | ~8.25 GB |
| AKU | 289824742951963 | 7,126 | 5,022 | 1.90 GB |
| | | **10,345** | **27,123** | **~42 GB** |

GitHub includes **1 GB** of large-file storage, so committing 42 GB was never an
option: files pushed to GitHub stay in history and keep counting even once
deleted. The media goes to **Azure Blob** — one container, one prefix per site —
and the repo keeps the index.

Checksums are computed as the bytes stream past on the way to the container, so
hashing costs nothing on top of the upload. A file already stored at the right size
keeps the checksum the previous run recorded rather than being read back;
re-hashing 42 GB nightly would make the job unaffordable, and a checksum nobody
can afford to compute is a checksum nobody has.

Nothing is staged for the whole space. Each file streams from Storyblok through a
single temp file and straight into the container. That one temp file is
deliberate — the Azure SDK may retry a block, and a hash taken over a
non-seekable stream that gets re-read is silently wrong, which is the one failure
this whole design exists to detect.

**Alternatives, both still supported.** `assets_dir` points at a folder, a mount or
a share instead of Azure. Leaving both out commits binaries into the repo through
Git LFS, which is the right choice only for a space small enough to fit the quota.

---

## What is deliberately not captured

| Endpoint | Why |
|---|---|
| `/api_keys` | the space's own access tokens. Live credentials, and this output goes to a remote. |
| `/collaborators` | `real_email`, `alt_email` and every member's name. Personal data, not needed to restore content. `--collaborators` to include it. |
| `/activities` | an audit log that grows without bound and restores nothing. `--activities` to include it. |

`preview_token` (on every story) and `first_token` (on the space) are stripped
recursively from everything written; the space `owner` block is dropped because
it carries the account holder's email. A test asserts none of them reach disk.

---

## Why LFS breaks quietly

`.gitattributes` is written inside `storyblok/`, beside `assets/`, **not** at the
repo root. A gitattributes pattern containing a slash is anchored to the
directory holding the file, so a root-level `assets/** filter=lfs` never matches
`storyblok/assets/...`. Nothing errors: `git lfs ls-files` prints nothing and git
stores every binary raw, permanently. Two tests exist only to catch that.

The patterns are a **catch-all with text exceptions**, not a list of binary
extensions. A list has to predict what editors upload, and the one it misses —
`.heic`, `.dwg`, `.indd` — lands in normal git and stays in history. Attribute
matching is also case-sensitive, so a list needs every pattern twice; a photo
saved as `.JPG` is exactly the file you least want stored raw.

---

## Tests

```powershell
python pipeline\migrate\spaces\test_spaces_e2e.py    # 61 checks, ~20s
python -m pytest tests/test_storyblok_spaces.py      # the fast unit checks
```

The end-to-end file stands up a stateful fake Management API on localhost and
runs the real scripts against it: three sites into three separate repos, LFS
conversion, credential scrubbing, in-place restore including the wrong-space and
hard-deleted guards, and a full rebuild with asset and link remapping verified.
It is not in `tests/` because it does git and socket work and takes ~20s, and the
pre-push hook should stay quick; `tests/test_storyblok_spaces.py` holds the pure
logic that is worth pinning on every push.

Every assertion is there because the thing it checks was wrong at some point, or
would fail silently if it broke.
