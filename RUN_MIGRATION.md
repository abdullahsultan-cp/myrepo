# Running the migration

One command does everything:

```bash
cd "d:\AKU News\aku-data-transformation-pipeline-news-master"
..\.venv\Scripts\python.exe scripts\migrate\upload\run_migration.py
```

It checks its prerequisites, uploads every asset, creates every story in its own
folder, reads the result back, writes the reports and takes a backup. Expect
**2–4 hours**.

**Safe to stop at any time.** Close the laptop, lose power, press Ctrl-C — then
run the same command again. It continues from where it stopped and never creates
anything twice.

---

## Before the first run

Once only. Skip if you have run the migration before.

```bash
# 1. environment
..\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Storyblok credentials
copy config\storyblok.example.json config\storyblok.json
#    then set space_id and management_token

# 3. tracking database
..\.venv\Scripts\python.exe scripts\migrate\db.py init
..\.venv\Scripts\python.exe scripts\migrate\db.py load

# 4. snapshot the folder tree the front-end developer created
..\.venv\Scripts\python.exe scripts\migrate\review\dump_sb_tree.py
```

Step 4 matters: the migration reads that snapshot to find each story's
destination and to fill the `entities` field. **Re-run it whenever the developer
changes the folder tree.**

---

## The run

```bash
..\.venv\Scripts\python.exe scripts\migrate\upload\run_migration.py
```

```
1/4  assets      ~3,850 files -> Storyblok, into folders mirroring the story tree
2/4  stories     3,606 stories -> each into its own folder
3/4  read back   re-reads the space so the reports reflect reality
4/4  reports     CSVs, summary and a full backup
```

Useful variations:

| Command | Does |
|---|---|
| `run_migration.py --sample` | just the 20 review stories |
| `run_migration.py --skip-assets` | stories only, when assets are already up |
| `run_migration.py --reports-only` | regenerate reports, upload nothing |
| `run_migration.py --draft` | upload without publishing |

---

## Stopping and resuming

Press **Ctrl-C once**. It finishes the story it is on, writes its state and
exits. Press twice to abandon immediately — still safe, just less tidy.

To resume, run the same command. Nothing is duplicated, because three
independent things have to fail before that could happen:

1. **Postgres** records `sb_story_id` and `sb_asset_id` the moment each write
   returns, so a finished item is never revisited.
2. **A payload hash** means an unchanged story is skipped, not re-sent.
3. **A slug check** runs before anything is created, so even a *lost database*
   produces an update rather than a duplicate.

Verified: clearing `sb_story_id` for a story and re-running printed
`already in the space, updating` and left exactly one copy.

A lock file stops two runs racing. If a run was killed and the lock is stale,
delete `data/migrate/.migration.lock`.

---

## What you get

Everything lands in `data/migrate/`:

| File | Contents |
|---|---|
| `migration.log` | every action, appended, timestamped. Safe to `tail -f` |
| `reports/stories.csv` | **one row per story** — destination, ids, status, SharePoint and Storyblok links, error |
| `reports/folders.csv` | **one row per folder** — expected, uploaded, remaining, failed |
| `reports/taxonomy.csv` | **one row per region / entity / department** |
| `reports/assets.csv` | **one row per asset** — story, role, folder, status, URL |
| `reports/summary.json` | the run at a glance |
| `backup/stories_<stamp>.json` | full payload of every uploaded story |

`stories.csv` has an **`in_expected_place`** column: `false` means the story is
in Storyblok but not where the taxonomy says it belongs, usually because someone
moved it by hand.

Progress at any time, without touching the space:

```bash
..\.venv\Scripts\python.exe scripts\migrate\upload\run_migration.py --reports-only
```

---

## If it stops with an error

**"destination folders do not exist"** — the pre-flight refuses to start rather
than fail 2,000 stories in. This script cannot create folders under `regions/`
or `global/`; that tree belongs to the front-end developer. Ask for the missing
folders, then:

```bash
..\.venv\Scripts\python.exe scripts\migrate\review\dump_sb_tree.py
..\.venv\Scripts\python.exe scripts\migrate\review\verify_folders.py
```

**"another migration started N min ago"** — a run is already going, or one was
killed. If you are sure nothing is running, delete
`data/migrate/.migration.lock`.

**"no target_full_slug"** — the taxonomy has not been built:
`python scripts\taxonomy\run_taxonomy.py`

**Individual stories failed** — they are recorded with their error in
`reports/stories.csv` and left `status='failed'`. Re-running retries only those.

---

## After it finishes

```bash
# side-by-side review sheet: SharePoint vs Storyblok, one row per story
..\.venv\Scripts\python.exe scripts\migrate\upload\export_links.py
```

Still outstanding, deliberately:

- **Internal links** still point at aku.edu. 566 of them, kept as-is so they can
  be found and replaced once every story has a Storyblok id.
- **Two tables** are skipped and rebuilt by hand — stories 1335 and 3288.
- **~208 media** are not obtainable; the page renders fewer images than the
  export declares. `reports/assets.csv` lists them.
