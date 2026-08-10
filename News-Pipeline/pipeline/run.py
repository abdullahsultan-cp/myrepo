#!/usr/bin/env python3
"""run.py — run the news pipeline.

    python News-Pipeline/pipeline/run.py            every step, in order
    python News-Pipeline/pipeline/run.py <step>     one step
    python News-Pipeline/pipeline/run.py --describe what this type overrides

Identical to `python pipeline/run_pipeline.py --type news`; this exists so each
content type has one obvious entry point inside its own folder.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "pipeline"))
from pipeline import NewsPipeline

if __name__ == "__main__":
    p = NewsPipeline()
    if "--describe" in sys.argv:
        print(p.describe())
    else:
        args = [a for a in sys.argv[1:] if not a.startswith("-")]
        sys.exit(p.run(args[0] if args else None))
