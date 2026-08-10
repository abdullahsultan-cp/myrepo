#!/usr/bin/env python3
"""install_hooks.py — point git at the repo's hooks, once per clone.

    python pipeline/install_hooks.py --type blogs
    python pipeline/install_hooks.py --uninstall

`.githooks/` is committed, but git does not use a committed hooks directory
until it is told to. This sets `core.hooksPath`, which is per clone, so each
person opts in on their own machine.

What the pre-push hook does: refuses a push that changes files outside your
content type's folder, and runs the tests. A deliberate shared change goes
through with `AKU_ALLOW_SHARED=1 git push`, which is one word rather than an
argument.

It also writes AKU_CONTENT_TYPE into the repo's git config so the hook knows
whose folder is yours without you exporting it in every shell.
"""

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap

_bootstrap.ensure()

from paths_root import ROOT, TYPES


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--type", choices=sorted(TYPES),
                    help="the content type you work on")
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args()

    if a.uninstall:
        git("config", "--unset", "core.hooksPath")
        print("  hooks disabled — git is back to .git/hooks")
        return 0

    hooks = os.path.join(ROOT, ".githooks")
    if not os.path.isdir(hooks):
        sys.exit(f"  no .githooks/ at {ROOT}")

    git("config", "core.hooksPath", ".githooks")
    print("  core.hooksPath -> .githooks")

    if a.type:
        # Stored in the repo's own git config, so it survives new shells and
        # cannot leak into another checkout.
        git("config", "aku.contentType", a.type)
        print(f"  aku.contentType -> {a.type}")
        print("\n  The hook reads AKU_CONTENT_TYPE. Add this to your shell profile,")
        print("  or the hook will ask for it every time:")
        print(f"      export AKU_CONTENT_TYPE={a.type}")
        print(f"      $env:AKU_CONTENT_TYPE = \"{a.type}\"      # PowerShell")
    else:
        print(f"\n  Pass --type <{'|'.join(sorted(TYPES))}> to record which folder is yours.")

    py = sys.executable
    git("config", "aku.python", py)
    print("\n  On push, the hook will:")
    print("    1. refuse changes outside your folder  (AKU_ALLOW_SHARED=1 to override)")
    print("    2. run the tests")
    print("\n  Undo any time:  python pipeline/install_hooks.py --uninstall")
    return 0


if __name__ == "__main__":
    sys.exit(main())
