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

def ensure():
    """Put every pipeline folder on sys.path. Idempotent.

    Callers write:

        import _bootstrap
        _bootstrap.ensure()

    rather than relying on import side effects alone. Both work -- the module
    does its job on import too -- but the explicit call means the import is
    genuinely used, so `ruff check --fix` cannot delete it as unused. It had 290
    of these in its sights, and removing one silently breaks that step with a
    ModuleNotFoundError the next time anybody runs it.
    """
    for name in (PIPELINE,) + tuple(os.path.join(PIPELINE, f) for f in FOLDERS):
        if os.path.isdir(name) and name not in sys.path:
            sys.path.insert(0, name)
    return PIPELINE


ensure()
