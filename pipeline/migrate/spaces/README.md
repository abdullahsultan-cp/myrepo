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

```
sb_common.py     config, HTTP with retries, scrubbing, git   imported, never run
sb_backup.py     space -> repo    READS ONLY
sb_restore.py    repo -> space    WRITES
test_spaces_e2e.py   61 checks against a fake API. No network, no tokens.
```

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
git lfs version                      # if this fails: https://git-lfs.com
copy config\sites.example.json config\sites.json
notepad config\sites.json            # space id, token, repo path per site
python pipeline\migrate\spaces\sb_backup.py --check
```

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
  stories.json            the index
  stories/101.json        one file per story, full content
  assets.json             metadata
  assets/800x600/aaaa1111/pic.png     every binary, via Git LFS
  _summary.json           counts, and anything the token could not read
  .gitattributes          LFS patterns — see "Why LFS breaks quietly"
tools/                    a copy of these scripts, so the repo restores alone
```

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
- **field-type plugins.** Account-level, not space-level, and there is no create
  API. If the source space used custom plugins — `spacing-field-plugin`, for
  instance — they must already exist on the target account or the components
  referencing them will not save correctly.

Recreate those by hand from the JSON. Webhooks especially should not be
recreated blind: they point at URLs wired to the old space.

A rebuild is **not byte-identical** — every asset gets a new URL, so the result
is equivalent, not the same.

---

## Git LFS quota — decide before the first push

GitHub gives a free account **1 GB of LFS storage and 1 GB of bandwidth per
month**. Asset binaries count against both, and *every version of every file
counts*. Three spaces with a couple of gigabytes of media between them will
exceed it on the first push.

Measure first:

```powershell
python pipeline\migrate\spaces\sb_backup.py --site all --no-commit
```

then pick one:

- **buy a data pack** — $5/month per 50 GB, per account
- **`--no-assets`** — metadata only. Small and fast, but a rebuild then comes up
  with no images, so it is not full disaster recovery
- **keep binaries off GitHub** — `--no-assets` plus a separate copy of
  `storyblok/assets/` on a file share. The metadata still records exactly which
  file belonged where

Deleting a large file later does **not** reclaim the quota — it stays in history.

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
