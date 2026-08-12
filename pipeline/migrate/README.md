# pipeline/migrate — stage 3, the only code that touches the network

Split by **flow**, not by topic, because the two halves fail differently and are
run at different times.

```
paths.py  db.py  schema.sql     shared by both flows
download/    aku.edu -> disk        reads only. Safe to interrupt.
upload/      disk -> Storyblok      WRITES.
update/      change LIVE stories    WRITES, in place.
review/      verification, reports, backups.  Never writes to the space.
```

| Folder | Job | Risk if it goes wrong |
|---|---|---|
| `download/` | resolve every asset URL from the live site and fetch it | none — re-run it |
| `upload/` | create and update stories and assets in Storyblok | this is the one that can damage the space |
| `update/` | change one field on stories that are already published | contained — a plan may only touch the fields it declares, and backs up first |
| `review/` | audits, reports, folder checks, backups | none — reads only |

**`update/` is stage 4, and it is not an afterthought.** Migration is not one
pass: the dev hands over a field after the stories are up, a plugin's value
format only becomes knowable once something has it filled, a component we worked
around gets replaced. Each of those is the same job — reach into published
stories and change one thing without disturbing anything else. One engine, a
small plan per job, living in the type's own folder. See
[update/README.md](update/README.md).

---

## The rules that matter

**One media resolver at a time.** `download/run_media_all.py` holds a lock. Two
passes share `media_urls.json` and the slower one rewrites it from its own
memory, silently reverting corrected URLs.

**Never create a content folder.** `regions/` and `global/` belong to the
front-end developer. `upload.py` has a hard stop (`NO_CREATE`); a missing folder
is an error with instructions, not something to invent. Asset folders are a
different namespace and *are* created.

**Never delete and re-upload a story.** Update in place. A new id breaks every
review link already shared and loses manual edits. Three guards make a re-run
safe: the tracking DB's `sb_story_id`, a payload hash, and a slug lookup before
anything is created.

**Refresh the tree snapshot after the dev changes folders.**
`review/dump_sb_tree.py` — the migration reads it to find each story's
destination and to fill `entities`.

---

## Usual order

```bash
python pipeline/migrate/db.py init            # once
python pipeline/migrate/db.py load
python pipeline/migrate/review/dump_sb_tree.py
python pipeline/migrate/download/run_media_all.py --workers 6
python pipeline/migrate/upload/run_migration.py
python pipeline/migrate/review/backup.py --type news
```

Everything is resumable: stop any of it and run the same command again.

Full runbook: [`../../RUN_MIGRATION.md`](../../RUN_MIGRATION.md).
