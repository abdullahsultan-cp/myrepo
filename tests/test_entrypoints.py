"""Every entry point still imports, and every content type still resolves.

This exists because `ruff check --fix` sorted the imports in `new_type.py` and
put `from paths_root import ...` above the `_bootstrap.ensure()` that puts
paths_root on sys.path. The file was broken for a day and the 33 tests all
passed, because none of them imported it.

A test that only asks "does this module load" looks thin. It is the cheapest
possible guard against the whole class of breakage this repo keeps producing:
a module moves, a path is computed by counting directories, and something no
test covers stops working silently.
"""

import os
import subprocess
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PIPELINE = os.path.join(ROOT, "pipeline")
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

import _bootstrap

_bootstrap.ensure()

from paths_root import TYPES

# Runnable entry points. `run_pipeline` and `base` are the ones that matter
# most; the rest are tools people reach for when something has gone wrong,
# which is exactly when a broken import costs the most.
ENTRY_POINTS = [
    "pipeline/run_pipeline.py",
    "pipeline/base.py",
    "pipeline/new_type.py",
    "pipeline/check_before_push.py",
    "pipeline/install_hooks.py",
    "pipeline/core/steps.py",
    "pipeline/core/fields.py",
    "pipeline/core/paths_root.py",
    "pipeline/content/import_source.py",
]


PROBE = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("probe", sys.argv[1])
m = importlib.util.module_from_spec(spec)
sys.modules["probe"] = m
try:
    spec.loader.exec_module(m)
except SystemExit:
    pass
"""


def _import_in_clean_process(rel):
    """Import one file the way a person runs it: in a fresh interpreter.

    Importing it inside this process would prove nothing. This test module has
    already called `_bootstrap.ensure()`, so `paths_root` is on sys.path for
    anything loaded afterwards — and the first version of this test passed
    happily against a file with its bootstrap deleted. A subprocess starts with
    the sys.path a real invocation gets, which is the only thing worth
    asserting.
    """
    return subprocess.run(
        [sys.executable, "-c", PROBE, os.path.join(ROOT, rel)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})


class EntryPointTests(unittest.TestCase):
    def test_every_entry_point_imports(self):
        for rel in ENTRY_POINTS:
            with self.subTest(entry_point=rel):
                self.assertTrue(os.path.exists(os.path.join(ROOT, rel)),
                                f"{rel} does not exist")
                done = _import_in_clean_process(rel)
                self.assertEqual(
                    done.returncode, 0,
                    f"{rel} does not import in a fresh interpreter:\n"
                    f"{done.stderr.strip()[-600:]}")


class ContentTypeTests(unittest.TestCase):
    def test_every_type_resolves_its_paths_and_steps(self):
        import steps as steps_module
        from paths_root import P

        for name in sorted(TYPES):
            with self.subTest(content_type=name):
                P.use(name)
                self.assertTrue(P.PIPELINE.endswith(TYPES[name]["folder"]))
                self.assertIn(P.leaf, P.folder_for("region", region="Kenya"))
                got = steps_module.for_type(name)
                self.assertGreater(len(got), 0, f"{name} has no steps")
                for step in got:
                    self.assertTrue(step.get("script"), f"{name}: a step has no script")
                    for path in step["requires"] + step["produces"]:
                        self.assertTrue(os.path.isabs(path),
                                        f"{name}: {path!r} did not resolve")

    def test_every_type_has_a_pipeline_class(self):
        from base import load

        for name in sorted(TYPES):
            with self.subTest(content_type=name):
                obj = load(name)
                self.assertEqual(obj.type, name)
                self.assertTrue(obj.describe())

    def test_no_two_types_share_a_data_folder(self):
        """The whole separation rests on this."""
        from paths_root import P

        seen = {}
        for name in sorted(TYPES):
            P.use(name)
            self.assertNotIn(P.DATA, seen,
                             f"{name} and {seen.get(P.DATA)} share {P.DATA}")
            seen[P.DATA] = name


if __name__ == "__main__":
    unittest.main()
