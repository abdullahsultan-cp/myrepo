#!/usr/bin/env python3
"""
paths.py — where everything lives, for the migration stage.

Every script here used to compute the repo root as `__file__/../..`, which meant
that filing a script one directory deeper silently pointed it at the wrong tree.
So the root is found by walking up until the repo's own landmarks appear, and
depth stops mattering.

Importing this module also puts `scripts/migrate/` and `scripts/` on sys.path,
so a script in `download/` or `upload/` can `import db` and
`from storyblok_config import load_config` the same way a script at the migrate
root always could.

    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from paths import BASE, MEDIA_DIR
"""

import os
import sys

MIGRATE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(MIGRATE)


def _find_base(start):
    """Walk up to the directory that holds both data/ and scripts/."""
    d = start
    while True:
        if (os.path.isdir(os.path.join(d, "data"))
                and os.path.isdir(os.path.join(d, "scripts"))):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            # No landmark anywhere above us. Fall back to the historical guess
            # rather than raising — a status command should still print.
            return os.path.abspath(os.path.join(start, ".."))
        d = parent


BASE = _find_base(MIGRATE)

# ---------------------------------------------------------------- directories
DATA = os.path.join(BASE, "data")
ASSETS = os.path.join(BASE, "assets")
CONFIG = os.path.join(BASE, "config")

# stage 1 output — one JSON per story, per stage
RAW = os.path.join(DATA, "news")
STORIES = os.path.join(DATA, "storyblok_stories")

# stage 2 output
TAXONOMY = os.path.join(DATA, "taxonomy")
FOLDERS_JSON = os.path.join(TAXONOMY, "seed", "folders.json")

# stage 3 working files
MIGRATE_DATA = os.path.join(DATA, "migrate")
MEDIA_DIR = os.path.join(ASSETS, "News", "media")
MEDIA_URLS = os.path.join(MIGRATE_DATA, "media_urls.json")
ASSET_MAP = os.path.join(MIGRATE_DATA, "asset_map.csv")
FAILURES = os.path.join(MIGRATE_DATA, "failures.csv")
LOCK = os.path.join(MIGRATE_DATA, ".media.lock")

# ------------------------------------------------------------------- sys.path
for _p in (MIGRATE, SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)


if __name__ == "__main__":
    for k, v in sorted(globals().items()):
        if k.isupper() and isinstance(v, str):
            mark = "" if os.path.exists(v) else "   (missing)"
            print(f"{k:<14} {v}{mark}")
