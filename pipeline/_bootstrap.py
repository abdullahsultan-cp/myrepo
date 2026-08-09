"""_bootstrap.py — put every pipeline folder on sys.path.

The steps are run as scripts, not imported as a package:

    python pipeline/content/normalize_html.py
    python pipeline/run_pipeline.py normalize-html

so Python only puts the script's *own* directory on the path, and a step in
`content/` cannot see a helper in `core/`. Two lines at the top of each step fix
that for every folder at once:

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import _bootstrap  # noqa: F401

Kept deliberately dumb: no imports of our own modules, no side effects beyond
sys.path, so it cannot fail in a way that hides the real error.
"""

import os
import sys

PIPELINE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(PIPELINE)

# Every folder that holds importable steps or helpers. `taxonomy` and `migrate`
# are entry points with their own path handling and are not added here.
FOLDERS = ("core", "content", "media", "analyze")

for _name in (PIPELINE,) + tuple(os.path.join(PIPELINE, f) for f in FOLDERS):
    if os.path.isdir(_name) and _name not in sys.path:
        sys.path.insert(0, _name)
