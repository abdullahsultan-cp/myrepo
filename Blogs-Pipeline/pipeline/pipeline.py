"""BlogsPipeline — the blogs migration.

Blogs differ from news in ways that are real, so each override below says why.

    python Blogs-Pipeline/pipeline/run.py
"""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "pipeline"))
from base import ContentPipeline


class BlogsPipeline(ContentPipeline):
    type = "blogs"

    # skip_steps lives in config/types/blogs.json, not here: it is a fact about
    # the blogs export rather than something that has to be computed, and JSON
    # keeps it beside the rest of the type's configuration.

    # TODO once the layout is signed off:
    #
    # def extract_pull_quote(self, item):
    #     """Blogs mark quotes inline with a {pullquote} marker in the body,
    #     where news has PullQuote / PullQuoteAuthor columns. 17 blogs have the
    #     column populated AND markers in the text, so the two have to be
    #     reconciled rather than one picked."""
