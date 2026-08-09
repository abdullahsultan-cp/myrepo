#!/usr/bin/env python3
"""
pipeline_paths.py — where the data for ONE content type lives.

The code is shared; the data is not. News, blogs and pages are the same job done
over different SharePoint lists, so there is one pipeline and one folder of
artefacts per type:

    News-Pipeline/     data/  assets/     3606 stories, migrated
    Blogs-Pipeline/    data/  assets/     awaiting its export
    Pages-Pipeline/    build/ portal/     a different shape, left alone

Duplicating 74 scripts per type would mean fixing every bug twice and watching
the copies drift. Sharing them without separating the data would mean one
`data/news/` folder that silently means "whatever ran last". This module is the
seam: import it, and every path resolves under the right content type.

Selecting the type, in order of precedence:

    set_content_type("blogs")           from a script, after parsing --type
    AKU_CONTENT_TYPE=blogs              from the environment
    news                                the default, so existing calls behave

Usage:

    from pipeline_paths import P
    with open(P.NEWS_JSON, encoding="utf-8") as f:   # the source export
        ...
    os.makedirs(P.STORIES, exist_ok=True)

`P` re-resolves whenever the type changes, so a script that switches type
mid-run still gets correct paths.
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Everything a content type owns. `folder` is the directory under the repo root;
# `source` is the filename of its SharePoint export; `assets` is the subfolder
# the media bundle unpacks into, which SharePoint capitalises.
# Each content type is described by a profile in config/types/. News, blogs and
# events are separate migrations that share code: each has its own folder
# hierarchy in Storyblok and can use different components, so everything that
# differs lives in a JSON file rather than in branches through the pipeline.
# Adding a type means adding a file, not editing this one.
import json as _json

TYPES_DIR = os.path.join(ROOT, "config", "types")


def _load_profiles():
    out = {}
    if not os.path.isdir(TYPES_DIR):
        return out
    for name in sorted(os.listdir(TYPES_DIR)):
        # A leading underscore marks a file that is not a type: _TEMPLATE.json is
        # the boilerplate new_type.py copies from, and loading it would offer a
        # content type called "TYPE".
        if not name.endswith(".json") or name.startswith("_"):
            continue
        with open(os.path.join(TYPES_DIR, name), encoding="utf-8") as f:
            prof = _json.load(f)
        t = prof.get("type") or name[:-5]
        # The keys the rest of the code reads, kept flat for compatibility with
        # the shape this module exposed before profiles existed.
        prof["folder"] = prof.get("folder", f"{t.capitalize()}-Pipeline")
        prof["source"] = prof.get("source", f"{t}.json")
        prof["assets"] = prof.get("assets_dir", t.capitalize())
        prof["label"] = prof.get("label", t)
        out[t] = prof
    return out


TYPES = _load_profiles()

DEFAULT_TYPE = "news"


def _slug(s):
    import re
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


class _Paths:
    """Lazily resolved paths for the currently selected content type."""

    def __init__(self):
        self._type = None

    # ------------------------------------------------------------ selection
    @property
    def type(self):
        if self._type is None:
            env = (os.environ.get("AKU_CONTENT_TYPE") or "").strip().lower()
            self._type = env if env in TYPES else DEFAULT_TYPE
        return self._type

    def use(self, content_type):
        """Select a content type. Raises rather than silently defaulting."""
        t = (content_type or "").strip().lower()
        if t not in TYPES:
            raise SystemExit(
                f"unknown content type {content_type!r}; "
                f"expected one of {', '.join(sorted(TYPES))}")
        self._type = t
        # Children run as their own processes, so the choice has to travel.
        os.environ["AKU_CONTENT_TYPE"] = t
        return t

    @property
    def spec(self):
        return TYPES[self.type]

    @property
    def label(self):
        return self.spec["label"]

    @property
    def hierarchy(self):
        """Where this type's items land. Blogs and events differ from news."""
        return self.spec.get("hierarchy") or {}

    @property
    def leaf(self):
        """The folder that holds the items: news, blogs, events."""
        return self.hierarchy.get("leaf", self.type)

    @property
    def source_urls(self):
        """Where this type lives on aku.edu -- the source, not the target.

        Distinct from `leaf`, which is where an item lands in Storyblok. They
        happen to be identical for news, which is why a hardcoded "/news" sat
        in build_link_map.py unnoticed while the rest of the pipeline was made
        generic.
        """
        d = self.spec.get("source_urls") or {}
        # detail_page is a literal filename, not a pattern: it is used both to
        # build URLs and, escaped, to match them. Storing a regex meant it could
        # only ever be used for matching.
        return {
            "prefix": d.get("prefix", f"/{self.leaf}"),
            "detail_page": d.get("detail_page", f"{self.leaf}_details.aspx"),
            "id_prefix": d.get("id_prefix", self.leaf.upper()),
        }

    @property
    def story_prefix(self):
        """The public path an item is linked at, e.g. /news/some-slug."""
        return f"/{self.leaf}"

    @property
    def storyblok(self):
        """Component name and body whitelist for this type."""
        return self.spec.get("storyblok") or {}

    @property
    def component(self):
        return self.storyblok.get("component", "news_article")

    @property
    def layout(self):
        """How source content maps onto components, including spacing."""
        return self.spec.get("layout") or {}

    @property
    def fields(self):
        """Source column names, so a differently-named export needs no editing."""
        return self.spec.get("fields") or {}

    def folder_for(self, placement, *, region=None, entity=None,
                   department=None):
        """The Storyblok folder path for one item, from this type's patterns."""
        pat = (self.hierarchy.get("patterns") or {}).get(placement)
        if not pat:
            raise SystemExit(
                f"{self.type}: no hierarchy pattern for placement "
                f"{placement!r}; add one to config/types/{self.type}.json")
        return pat.format(leaf=self.leaf, region=_slug(region),
                          entity=_slug(entity), department=_slug(department))

    # ----------------------------------------------------------- top level
    @property
    def PIPELINE(self):
        return os.path.join(ROOT, self.spec["folder"])

    @property
    def DATA(self):
        return os.path.join(self.PIPELINE, "data")

    @property
    def ASSETS(self):
        return os.path.join(self.PIPELINE, "assets")

    @property
    def CONFIG(self):
        return os.path.join(ROOT, "config")          # shared across types

    # --------------------------------------------------- stage 1: content
    @property
    def SOURCE_JSON(self):
        """The SharePoint export. The only real input."""
        return os.path.join(self.DATA, self.spec["source"])

    @property
    def RAW(self):
        return os.path.join(self.DATA, "raw")

    @property
    def CLEANED(self):
        return os.path.join(self.DATA, "cleaned")

    @property
    def NORMALIZED(self):
        return os.path.join(self.DATA, "normalized")

    @property
    def RICHTEXT(self):
        return os.path.join(self.DATA, "richtext")

    @property
    def RICHTEXT_ENHANCED(self):
        return os.path.join(self.DATA, "richtext_enhanced")

    @property
    def STORIES(self):
        """The finished payloads."""
        return os.path.join(self.DATA, "stories")

    # -------------------------------------------------- stage 2: taxonomy
    @property
    def TAXONOMY(self):
        return os.path.join(self.DATA, "taxonomy")

    @property
    def SEED(self):
        return os.path.join(self.TAXONOMY, "seed")

    @property
    def ROUTING(self):
        return os.path.join(self.TAXONOMY, "routing")

    # ------------------------------------------------- stage 3: migration
    @property
    def MIGRATE(self):
        return os.path.join(self.DATA, "migrate")

    @property
    def BACKUP(self):
        """Snapshots of the source export and of what is live in Storyblok."""
        return os.path.join(self.PIPELINE, "backup")

    @property
    def REPORTS(self):
        return os.path.join(self.MIGRATE, "reports")

    @property
    def MEDIA_DIR(self):
        return os.path.join(self.ASSETS, self.spec["assets"], "media")

    @property
    def METADATA_CSV(self):
        return os.path.join(self.ASSETS, self.spec["assets"], "Metadata.csv")

    # ------------------------------------------------------------- helpers
    def report(self, name):
        """A stage report, e.g. P.report('unicode_report.json')."""
        return os.path.join(self.DATA, name)

    def ensure(self, *paths):
        for p in paths:
            os.makedirs(p, exist_ok=True)

    def describe(self):
        return (f"content type : {self.type}\n"
                f"  pipeline   : {os.path.relpath(self.PIPELINE, ROOT)}\n"
                f"  source     : {os.path.relpath(self.SOURCE_JSON, ROOT)}\n"
                f"  stories    : {os.path.relpath(self.STORIES, ROOT)}\n"
                f"  media      : {os.path.relpath(self.MEDIA_DIR, ROOT)}")


P = _Paths()


def set_content_type(t):
    return P.use(t)


def add_type_argument(parser):
    """Give any argparse CLI a --type flag with consistent wording."""
    parser.add_argument(
        "--type", choices=sorted(TYPES), default=None,
        help="content type to operate on (default: news, or $AKU_CONTENT_TYPE)")
    return parser


def apply_type_argument(args):
    if getattr(args, "type", None):
        P.use(args.type)
    return P.type


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        P.use(sys.argv[1])
    print(P.describe())
    for t in sorted(TYPES):
        P.use(t)
        exists = "present" if os.path.isdir(P.DATA) else "not created yet"
        print(f"\n  {t:<6} -> {TYPES[t]['folder']:<16} {exists}")
