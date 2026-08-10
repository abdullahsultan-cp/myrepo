#!/usr/bin/env python3
"""run.py — run the blogs pipeline.

    python Blogs-Pipeline/pipeline/run.py            every step, in order
    python Blogs-Pipeline/pipeline/run.py <step>     one step
    python Blogs-Pipeline/pipeline/run.py --describe what this type overrides

Identical to `python pipeline/run_pipeline.py --type blogs`; this exists so each
content type has one obvious entry point inside its own folder.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "pipeline"))
from pipeline import BlogsPipeline

if __name__ == "__main__":
    p = BlogsPipeline()
    if "--describe" in sys.argv:
        print(p.describe())
    else:
        args = [a for a in sys.argv[1:] if not a.startswith("-")]
        sys.exit(p.run(args[0] if args else None))
