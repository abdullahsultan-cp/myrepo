#!/usr/bin/env python3
"""
sb_indexdb.py — build index.sqlite from a snapshot. Imported, or run directly.

Storyblok exposes no database and no dump endpoint, so there is no DB backup to
take: the JSON and CSV in the snapshot ARE the content. This builds a queryable
view over them, because "which stories use this image" and "what is in this
folder" are SQL questions, and answering them by grepping 3,042 JSON files is
nobody's idea of a mapping.

Everything here is DERIVED. The snapshot stays the source of truth; delete this
file and rebuild it in seconds. That is why it is safe to regard as disposable:

    python tools/sb_indexdb.py storyblok/          # from inside a backup repo

Tables:
    space, components, component_fields, datasources, datasource_entries,
    asset_folders, stories, assets, story_assets

story_assets is the one that is genuinely hard to get any other way: a row per
(story, asset) reference, found by scanning every story's content for asset URLs
rather than by trusting a field name. That is what makes "delete this asset ->
which pages break?" a one-line query.
"""

import csv
import json
import os
import re
import sqlite3
import sys
from urllib.parse import unquote, urlsplit

_ASSET_URL = re.compile(r"""https?://[^\s"'<>)\]]*?/f/\d+/[^\s"'<>)\]]*""")
_AFTER_F = re.compile(r"/f/\d+/(.+)$")


def _key(url):
    """The part after /f/<space id>/ -- the only stable part of an asset URL.

    assets.json returns the S3 host, story content uses the CDN host, and a paid
    plan can add a custom domain. Joining on whole URLs matched 892 of ~5,800
    references and made the mapping look far sparser than it is.
    """
    if not url or "/f/" not in url:
        return None
    m = _AFTER_F.search(unquote(urlsplit(url).path))
    return m.group(1) if m else None

SCHEMA = """
CREATE TABLE space (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE components (
    id INTEGER PRIMARY KEY, name TEXT, display_name TEXT,
    is_root INTEGER, is_nestable INTEGER, field_count INTEGER);

CREATE TABLE component_fields (
    component TEXT, field TEXT, type TEXT, plugin TEXT,
    PRIMARY KEY (component, field));

CREATE TABLE datasources (id INTEGER PRIMARY KEY, name TEXT, slug TEXT);
CREATE TABLE datasource_entries (
    id INTEGER PRIMARY KEY, datasource_id INTEGER, name TEXT, value TEXT);

CREATE TABLE asset_folders (
    id INTEGER PRIMARY KEY, name TEXT, parent_id INTEGER, path TEXT);

CREATE TABLE stories (
    id INTEGER PRIMARY KEY, uuid TEXT, kind TEXT, full_slug TEXT,
    parent_id INTEGER, parent_folder TEXT, name TEXT, component TEXT,
    state TEXT, unpublished_changes INTEGER, has_published_copy INTEGER,
    assets_referenced INTEGER, backup_file TEXT, updated_at TEXT);

CREATE TABLE assets (
    id INTEGER PRIMARY KEY, filename TEXT, asset_folder_id INTEGER,
    asset_folder TEXT, backup_file TEXT, file_present INTEGER, sha256 TEXT,
    content_type TEXT, bytes INTEGER, alt TEXT, url TEXT);

CREATE TABLE story_assets (
    story_id INTEGER, asset_id INTEGER, url TEXT,
    PRIMARY KEY (story_id, asset_id));

CREATE INDEX ix_stories_slug   ON stories(full_slug);
CREATE INDEX ix_stories_comp   ON stories(component);
CREATE INDEX ix_stories_parent ON stories(parent_folder);
CREATE INDEX ix_assets_folder  ON assets(asset_folder);
CREATE INDEX ix_assets_present ON assets(file_present);
CREATE INDEX ix_sa_asset       ON story_assets(asset_id);
"""

# Shown by --help and printed after a build, because an index nobody knows how to
# query is the same as no index.
EXAMPLES = """
  -- which pages break if this asset is lost?
  SELECT s.full_slug FROM story_assets sa
    JOIN stories s ON s.id = sa.story_id
    WHERE sa.asset_id = 133625424888727;

  -- assets whose bytes are NOT in storage, and who references them
  SELECT a.filename, count(sa.story_id) AS used_by
    FROM assets a LEFT JOIN story_assets sa ON sa.asset_id = a.id
    WHERE a.file_present = 0 GROUP BY a.id;

  -- biggest folders
  SELECT asset_folder, count(*) n, sum(bytes)/1048576 mb
    FROM assets GROUP BY asset_folder ORDER BY mb DESC LIMIT 10;

  -- stories whose live page differs from the draft
  SELECT full_slug FROM stories WHERE unpublished_changes = 1;

  -- which components use a given field plugin
  SELECT DISTINCT component FROM component_fields WHERE plugin = 'seo-metatags';

  -- unreferenced assets (candidates for nothing -- keep them, but know)
  SELECT count(*) FROM assets a
    WHERE NOT EXISTS (SELECT 1 FROM story_assets s WHERE s.asset_id = a.id);
"""


def _rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def build(outdir, dest=None):
    dest = dest or os.path.join(outdir, "index.sqlite")
    if os.path.exists(dest):
        os.remove(dest)          # rebuilt wholesale; never migrated in place
    db = sqlite3.connect(dest)
    db.executescript(SCHEMA)

    space = _json(os.path.join(outdir, "space.json"), {})
    db.executemany("INSERT INTO space VALUES (?,?)",
                   [(k, json.dumps(v, ensure_ascii=False)
                     if isinstance(v, (dict, list)) else str(v))
                    for k, v in sorted(space.items())])

    comps = _json(os.path.join(outdir, "components.json"), [])
    db.executemany("INSERT INTO components VALUES (?,?,?,?,?,?)", [
        (c.get("id"), c.get("name"), c.get("display_name"),
         1 if c.get("is_root") else 0, 1 if c.get("is_nestable") else 0,
         len(c.get("schema") or {})) for c in comps])
    fields = []
    for c in comps:
        for fname, f in (c.get("schema") or {}).items():
            f = f or {}
            fields.append((c.get("name"), fname, f.get("type"),
                           f.get("field_type") if f.get("type") == "custom"
                           else None))
    db.executemany("INSERT OR REPLACE INTO component_fields VALUES (?,?,?,?)",
                   fields)

    db.executemany("INSERT INTO datasources VALUES (?,?,?)", [
        (d.get("id"), d.get("name"), d.get("slug"))
        for d in _json(os.path.join(outdir, "datasources.json"), [])])
    db.executemany("INSERT OR REPLACE INTO datasource_entries VALUES (?,?,?,?)", [
        (e.get("id"), e.get("datasource_id"), e.get("name"),
         json.dumps(e.get("value"), ensure_ascii=False)
         if isinstance(e.get("value"), (dict, list)) else e.get("value"))
        for e in _json(os.path.join(outdir, "datasource_entries.json"), [])])

    folders = _json(os.path.join(outdir, "asset_folders.json"), [])
    by_id = {f["id"]: f for f in folders if f.get("id") is not None}

    def fpath(fid):
        parts, seen = [], set()
        cur = by_id.get(fid)
        while cur is not None and cur["id"] not in seen:
            seen.add(cur["id"])
            parts.append(str(cur.get("name") or cur["id"]))
            cur = by_id.get(cur.get("parent_id")) if cur.get("parent_id") else None
        return "/".join(reversed(parts))

    db.executemany("INSERT INTO asset_folders VALUES (?,?,?,?)", [
        (f.get("id"), f.get("name"), f.get("parent_id"), fpath(f.get("id")))
        for f in folders])

    # ---- stories and assets, from the manifests (already the joined view)
    pub_dir = os.path.join(outdir, "stories_published")
    published = {f[:-5] for f in os.listdir(pub_dir)
                 if f.endswith(".json")} if os.path.isdir(pub_dir) else set()
    smap = {}
    srows = []
    for r in _rows(os.path.join(outdir, "manifest_stories.csv")):
        sid = _int(r.get("id"))
        smap[sid] = r
        srows.append((
            sid, r.get("uuid"), r.get("kind"), r.get("full_slug"), None,
            r.get("parent_folder"), r.get("name"), r.get("component") or None,
            r.get("state"), 1 if r.get("unpublished_changes") == "yes" else 0,
            1 if str(sid) in published else 0,
            _int(r.get("assets_referenced")) or 0,
            r.get("backup_file") or None, r.get("updated_at")))
    db.executemany("INSERT OR REPLACE INTO stories VALUES "
                   "(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", srows)

    url_to_id = {}
    arows = []
    for r in _rows(os.path.join(outdir, "manifest_assets.csv")):
        aid = _int(r.get("id"))
        k = _key(r.get("url"))
        if k:
            url_to_id[k] = aid
        arows.append((
            aid, r.get("filename"), None, r.get("asset_folder"),
            r.get("backup_file"), 1 if r.get("file_present") == "yes" else 0,
            r.get("sha256") or None, r.get("content_type") or None,
            _int(r.get("bytes")), r.get("alt") or None, r.get("url")))
    db.executemany("INSERT OR REPLACE INTO assets VALUES "
                   "(?,?,?,?,?,?,?,?,?,?,?)", arows)
    # asset_folder_id is filled from assets.json, which has it; the manifest
    # carries the readable path instead.
    for a in _json(os.path.join(outdir, "assets.json"), []):
        db.execute("UPDATE assets SET asset_folder_id=? WHERE id=?",
                   (a.get("asset_folder_id"), a.get("id")))

    # ---- the join: every (story, asset) reference, by scanning content
    story_dir = os.path.join(outdir, "stories")
    pairs, unmatched = [], 0
    if os.path.isdir(story_dir):
        for fn in os.listdir(story_dir):
            if not fn.endswith(".json"):
                continue
            sid = _int(fn[:-5])
            blob = open(os.path.join(story_dir, fn), encoding="utf-8").read()
            if "/f/" not in blob:
                continue
            for url in set(_ASSET_URL.findall(blob)):
                aid = url_to_id.get(_key(url))
                if aid is None:
                    # A reference to something not in assets.json: an asset
                    # deleted from the library while a story still points at it.
                    # Counted, because it is a broken image on a live page.
                    unmatched += 1
                    continue
                pairs.append((sid, aid, url))
    db.executemany("INSERT OR REPLACE INTO story_assets VALUES (?,?,?)", pairs)

    db.commit()
    counts = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("components", "component_fields", "datasources",
                        "datasource_entries", "asset_folders", "stories",
                        "assets", "story_assets")}
    db.close()
    counts["dangling_asset_refs"] = unmatched
    return dest, counts


if __name__ == "__main__":
    where = sys.argv[1] if len(sys.argv) > 1 else "storyblok"
    if not os.path.isdir(where):
        sys.exit(f"no snapshot directory at {where}")
    path, counts = build(where)
    print(f"built {path}\n")
    for k, v in counts.items():
        print(f"  {k:<22} {v}")
    print(EXAMPLES)
