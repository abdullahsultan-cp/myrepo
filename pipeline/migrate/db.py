#!/usr/bin/env python3
"""
db.py — Postgres tracking database: create, load, report.

Every migration step records what it did here, so "which stories are done" is a
query rather than a guess, and a failed run resumes instead of restarting.

Connection comes from config/database.json (gitignored) or the environment:
    PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE

Usage:
    python scripts/migrate/db.py init      # create database + schema
    python scripts/migrate/db.py load      # load 3606 stories, links, shares
    python scripts/migrate/db.py sample    # flag the scenario-coverage sample
    python scripts/migrate/db.py status    # progress report
    python scripts/migrate/db.py reset     # drop the migration schema (asks)
"""

import csv
import json
import os
import re
import sys

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
# Walk up to the pipeline/ root rather than counting dirname() calls: the
# scripts using this sit at two different depths (migrate/ and
# migrate/review/), and a fixed count is right for one and wrong for the
# other -- which is exactly how this broke.
# Two things have to be importable: this flow's own helpers (migrate/paths.py,
# migrate/db.py) and the shared pipeline modules. The scripts using this sit at
# two different depths -- migrate/ and migrate/review/ -- so the pipeline root is
# found by walking up for _bootstrap.py rather than by counting dirname() calls,
# which is right for one depth and silently wrong for the other.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_d = os.path.dirname(os.path.abspath(__file__))
while _d != os.path.dirname(_d):
    if os.path.exists(os.path.join(_d, "_bootstrap.py")):
        sys.path.insert(0, _d)
        break
    _d = os.path.dirname(_d)
import _bootstrap

_bootstrap.ensure()

# _bootstrap does not reach into migrate/upload/, and this needs one thing from
# it: `slugify`. The uploader owns how a slug is chosen, and target_full_slug
# here has to agree with it character for character -- a slug that merely looks
# right turns run_migration's in_expected_place check into false alarms. So the
# same function is imported rather than a second copy kept. This mapping has
# already drifted three times in this project when it lived in two places.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "upload"))

from build_payload import slugify  # noqa: I001
from paths_root import P

try:
    import psycopg
except ImportError:
    sys.exit('pip install "psycopg[binary]"')

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_SQL = os.path.join(HERE, "schema.sql")
CONFIG = os.path.join(BASE, "config", "database.json")

STORIES_DIR = P.STORIES

# What the load reads differs per type, and all of it is a value rather than a
# branch. News's taxonomy writes taxonomy/routing/news_routing.csv with columns
# news_id / level / sb_path; events writes taxonomy/routing.csv with event_id /
# placement / folder_path. The defaults below are news's exactly, so a profile
# with no "tracking" block behaves as this file always has.
TRACK = P.spec.get("tracking") or {}


def _under_taxonomy(value, default):
    """A path under data/taxonomy/, given as a string or a list of segments."""
    parts = value if isinstance(value, list) else [value] if value else default
    return os.path.join(P.TAXONOMY, *parts)


ROUTING_CSV = _under_taxonomy(TRACK.get("routing_csv"),
                              ["routing", "news_routing.csv"])
STORY_PATHS = _under_taxonomy(TRACK.get("story_paths_csv"),
                              ["routing", "story_paths.csv"])
SCENARIOS_JSON = os.path.join(P.MIGRATE, "scenarios.json")

# story-table field -> the routing CSV column it comes from. A field mapped to
# null is not in this type's CSV and loads as NULL, which is what the schema's
# nullable columns are for: events has no department and no shared entities.
COLUMNS = dict({
    "id": "news_id",
    "published_date": "published_date",
    "region": "region",
    "entity": "entity",
    "entity_short": "entity_short",
    "department": "department",
    "placement": "level",
    "surface_global": "surface_global",
    "region_source": "region_source",
    "entity_source": "entity_source",
    "target_folder": "folder_path",
    "target_full_slug": "sb_path",
}, **(TRACK.get("columns") or {}))

# Where the asset rows come from inside a built payload. News keeps every file
# in media[] and richtext_media[], both lists of objects. Events has neither for
# its heroes -- the banner is a bare filename on content.banner -- so a source
# may name a scalar field and the role it carries.
ASSET_SOURCES = TRACK.get("assets") or [{"field": "media"},
                                        {"field": "richtext_media"}]

DEFAULTS = {"host": "localhost", "port": 5432, "user": "postgres",
            "password": "postgres", "dbname": "aku_news_migration"}


def settings():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    env = {"host": "PGHOST", "port": "PGPORT", "user": "PGUSER",
           "password": "PGPASSWORD", "dbname": "PGDATABASE"}
    for k, e in env.items():
        if os.environ.get(e):
            cfg[k] = os.environ[e]
    return cfg


def dsn(cfg, dbname=None):
    return (f"host={cfg['host']} port={cfg['port']} user={cfg['user']} "
            f"password={cfg['password']} dbname={dbname or cfg['dbname']}")


def connect(dbname=None):
    return psycopg.connect(dsn(settings(), dbname), autocommit=False)


# ------------------------------------------------------------------ init

def cmd_init():
    cfg = settings()
    # CREATE DATABASE cannot run inside a transaction
    with psycopg.connect(dsn(cfg, "postgres"), autocommit=True) as c:
        exists = c.execute("SELECT 1 FROM pg_database WHERE datname = %s",
                           (cfg["dbname"],)).fetchone()
        if exists:
            print(f"  database {cfg['dbname']} already exists")
        else:
            c.execute(f'CREATE DATABASE "{cfg["dbname"]}"')
            print(f"  created database {cfg['dbname']}")

    with open(SCHEMA_SQL, encoding="utf-8") as f:
        ddl = f.read()
    with connect() as c:
        c.execute(ddl)
        c.commit()
        n = c.execute("""SELECT count(*) FROM information_schema.tables
                         WHERE table_schema = 'migration'""").fetchone()[0]
        v = c.execute("""SELECT count(*) FROM information_schema.views
                         WHERE table_schema = 'migration'""").fetchone()[0]
    print(f"  schema 'migration' ready: {n} tables, {v} views")


# ------------------------------------------------------------------ load

def classify_link(href):
    h = (href or "").strip()
    if not h:
        return "empty"
    low = h.lower()
    if low.startswith("mailto:"):
        return "email"
    if low.startswith("tel:"):
        return "tel"
    if low.startswith("#"):
        return "anchor"
    if re.search(r"\.(pdf|docx?|xlsx?|pptx?|zip)(\?|$)", low):
        return "document"
    if low.startswith("/") or "aku.edu" in low:
        return "internal"
    if low.startswith("http"):
        return "external"
    return "other"


def collect_links(doc):
    """(href, text, count) for every link mark in a richtext document."""
    found = {}

    def walk(n, inherited=None):
        if isinstance(n, list):
            for x in n:
                walk(x, inherited)
            return
        if not isinstance(n, dict):
            return
        href = inherited
        for m in n.get("marks") or []:
            if isinstance(m, dict) and m.get("type") == "link":
                a = m.get("attrs") or {}
                href = a.get("href") or a.get("url") or ""
                if a.get("anchor"):
                    href = f"{href}#{a['anchor']}"
        if n.get("type") == "text" and href:
            k = href
            txt = n.get("text") or ""
            if k in found:
                found[k]["count"] += 1
                if txt and txt not in found[k]["text"]:
                    found[k]["text"] = (found[k]["text"] + " " + txt)[:300]
            else:
                found[k] = {"text": txt[:300], "count": 1}
        walk(n.get("content") or [], href)

    walk(doc.get("content") or [])
    return [(h, v["text"], v["count"]) for h, v in found.items()]


def _col(row, key):
    """One routing-CSV column, by the role it plays rather than its name.

    A role mapped to null in the profile is absent from this type's CSV and
    loads as NULL -- events has no department column and no shared entities.
    """
    name = COLUMNS.get(key)
    return row.get(name) if name else None


def _destination(row, sid, title):
    """(target_full_slug, target_slug) -- where this story is meant to end up.

    News's taxonomy writes the whole path, so both come straight from the CSV.
    Events' records the destination FOLDER and nothing else, because its routing
    decides placement only; the slug comes from the title at upload time. Left
    at NULL the upload still works -- upload.py falls back to target_folder --
    but everything built on top of it quietly stops meaning anything:

        run_migration.py in_expected_place   uploaded == NULL, so all 2,710
                                             report as misplaced, and that is
                                             the check that catches a story
                                             someone moved by hand in the UI
        run_migration.py folders report      derived from NULL
        export_internal_links.py             no target to point a link at

    The slug MUST be the one the uploader would pick, character for character:
    the same `slugify`, the same title string this table stores, and the same
    `{type}-{id}` fallback for a title that slugifies to nothing. A slug that
    merely looks right turns in_expected_place into false alarms, which is
    worse than leaving it null.
    """
    full = _col(row, "target_full_slug")
    if full:
        return full, full.rsplit("/", 1)[-1] or None
    folder = _col(row, "target_folder")
    if not folder:
        return None, None
    slug = slugify(title)
    if not slug:
        slug = f"{P.type}-{sid}"                 # already carries the id
    elif TRACK.get("slug_suffix") == "id":
        # Titles are not unique when the events recur: 26 events are called
        # "EdTech Lounge Online" and land in one folder. Without a suffix they
        # share a slug, and the uploader's with_slug guard finds the first and
        # PUTs over it -- 542 events collapsing into 201, silently.
        slug = f"{slug}-{sid}"
    return f"{folder}/{slug}", slug


def _asset_rows(sid, content):
    """Every file one payload references, as (sid, role, type, name, ...) rows.

    Reads the fields named by ASSET_SOURCES. A source is either a list of media
    objects (news's media[] / richtext_media[]) or, with "scalar": true, a field
    holding a bare filename -- which is how events carries its banner. Getting
    this wrong is quiet rather than loud: the load succeeds, the uploader finds
    no rows to send, and every story publishes with an empty image field.
    """
    out = []
    for src in ASSET_SOURCES:
        value = content.get(src["field"])
        if not value:
            continue
        if src.get("scalar"):
            items = [{"filename": value, "role": src.get("role") or src["field"],
                      "media_type": src.get("media_type") or "image"}]
        else:
            items = value
        for m in items:
            fn = m.get("filename") or m.get("src") or ""
            if not fn:
                continue
            out.append((
                int(sid), m.get("role") or src.get("role") or "richtext",
                m.get("media_type"), fn, m.get("source_key"),
                fn if fn.lower().startswith("http") else None,
                m.get("caption"), m.get("alt"),
            ))
    return out


def cmd_load():
    if not os.path.exists(ROUTING_CSV):
        sys.exit(f"missing {ROUTING_CSV} — run run_taxonomy.py first")

    with open(ROUTING_CSV, encoding="utf-8-sig") as f:
        routes = {r[COLUMNS["id"]]: r for r in csv.DictReader(f)}
    shares = {}
    if os.path.exists(STORY_PATHS):
        with open(STORY_PATHS, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                shares[r["story_id"]] = [r[k] for k in r
                                         if k.startswith("shared_path_") and r[k]]

    story_rows, asset_rows, link_rows, share_rows = [], [], [], []
    files = sorted(n for n in os.listdir(STORIES_DIR) if n.endswith(".json"))
    for name in files:
        sid = name[:-5]
        r = routes.get(sid)
        if not r:
            continue
        with open(os.path.join(STORIES_DIR, name), encoding="utf-8") as f:
            st = json.load(f)
        c = st.get("content") or {}

        title = c.get("title") or "(untitled)"
        full_slug, slug = _destination(r, sid, title)
        story_rows.append((
            int(sid), c.get("sequence_number"), title,
            _col(r, "published_date") or None,
            _col(r, "region"), _col(r, "entity"), _col(r, "entity_short"),
            _col(r, "department") or None, _col(r, "placement"),
            _col(r, "surface_global") == "True",
            _col(r, "region_source"), _col(r, "entity_source"),
            _col(r, "target_folder"),
            slug,
            full_slug,
        ))

        asset_rows.extend(_asset_rows(sid, c))

        body = c.get("body") if isinstance(c.get("body"), dict) else {}
        for href, text, cnt in collect_links(body):
            link_rows.append((int(sid), classify_link(href), href, text, cnt))

        for p in shares.get(sid, []):
            parts = p.split("/")
            ent = parts[3] if len(parts) > 3 else None
            reg = parts[1] if len(parts) > 1 else None
            share_rows.append((int(sid), reg, ent, p))

    with connect() as c:
        c.execute("SET search_path TO migration, public")
        with c.cursor() as cur:
            cur.executemany("""
                INSERT INTO story (sharepoint_id, sequence_number, title,
                    published_date, region, entity, entity_short, department,
                    placement, surface_global, region_source, entity_source,
                    target_folder, target_slug, target_full_slug)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (sharepoint_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    region = EXCLUDED.region, entity = EXCLUDED.entity,
                    entity_short = EXCLUDED.entity_short,
                    department = EXCLUDED.department,
                    placement = EXCLUDED.placement,
                    surface_global = EXCLUDED.surface_global,
                    region_source = EXCLUDED.region_source,
                    entity_source = EXCLUDED.entity_source,
                    target_folder = EXCLUDED.target_folder,
                    target_slug = EXCLUDED.target_slug,
                    target_full_slug = EXCLUDED.target_full_slug,
                    updated_at = now()
            """, story_rows)

            cur.executemany("""
                INSERT INTO asset (sharepoint_id, role, media_type,
                    source_filename, source_path, source_url, caption, alt)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (sharepoint_id, role, source_filename)
                DO NOTHING
            """, asset_rows)

            cur.execute("TRUNCATE link")
            cur.executemany("""
                INSERT INTO link (sharepoint_id, kind, raw_href, link_text,
                                  occurrences)
                VALUES (%s,%s,%s,%s,%s)
            """, link_rows)

            cur.executemany("""
                INSERT INTO share_target (sharepoint_id, ref_region,
                                          ref_entity, ref_full_slug)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (sharepoint_id, ref_full_slug) DO NOTHING
            """, share_rows)
        c.commit()

    print(f"  stories {len(story_rows)}  assets {len(asset_rows)}  "
          f"links {len(link_rows)}  shares {len(share_rows)}")


def cmd_sample():
    if not os.path.exists(SCENARIOS_JSON):
        sys.exit(f"missing {SCENARIOS_JSON} — run select_scenarios.py --json")
    with open(SCENARIOS_JSON, encoding="utf-8") as f:
        sc = json.load(f)
    rows = [(sorted(v), int(k)) for k, v in sc["coverage"].items()]
    with connect() as c:
        c.execute("SET search_path TO migration, public")
        with c.cursor() as cur:
            cur.execute("UPDATE story SET is_sample = false, scenarios = '{}'")
            cur.executemany("""UPDATE story
                               SET is_sample = true, scenarios = %s,
                                   updated_at = now()
                               WHERE sharepoint_id = %s""", rows)
        c.commit()
    print(f"  flagged {len(rows)} sample stories covering "
          f"{len(sc['feature_counts'])} features")


def cmd_status():
    with connect() as c:
        c.execute("SET search_path TO migration, public")
        def show(title, sql):
            rows = c.execute(sql).fetchall()
            print(f"\n  {title}")
            if not rows:
                print("    (none)")
            for r in rows:
                print("    " + "  ".join("" if x is None else str(x) for x in r))
        show("stories by status", "SELECT * FROM progress")
        show("assets by status", "SELECT status, assets FROM asset_progress")
        show("links by kind",
             """SELECT kind, count(*), count(*) FILTER (WHERE resolved)
                FROM link GROUP BY kind ORDER BY 2 DESC""")
        show("sample", """SELECT sharepoint_id, status,
                          cardinality(scenarios), coalesce(upload_full_slug,'-')
                          FROM story WHERE is_sample ORDER BY sharepoint_id""")
        show("recent errors",
             """SELECT sharepoint_id, stage, left(message, 80)
                FROM event WHERE level = 'error'
                ORDER BY at DESC LIMIT 10""")


def cmd_reset():
    if os.environ.get("MIGRATION_FORCE_RESET") != "yes":
        sys.exit("refusing: set MIGRATION_FORCE_RESET=yes to drop the schema")
    with connect() as c:
        c.execute("DROP SCHEMA IF EXISTS migration CASCADE")
        c.commit()
    print("  dropped schema 'migration'")


COMMANDS = {"init": cmd_init, "load": cmd_load, "sample": cmd_sample,
            "status": cmd_status, "reset": cmd_reset}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd not in COMMANDS:
        sys.exit(f"usage: db.py [{' | '.join(COMMANDS)}]")
    COMMANDS[cmd]()
