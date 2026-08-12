#!/usr/bin/env python3
"""link_routing.py — where a SharePoint link should point once the site is gone.

Imported, never run. `classify()` and `rewrite_href()` are the whole interface.

**SharePoint is being decommissioned.** Every link into it — `/qtl/Pages/x.aspx`,
`https://www.aku.edu/news/some-story` — stops resolving the day it is switched
off. The articles keep the link, the reader gets a 404, and by then there is no
site left to look the target up in. So links are rerouted while both ends still
exist.

Four outcomes, and the URL decides which:

| the link is                | becomes                                        |
|----------------------------|------------------------------------------------|
| a news or blog page        | that story in Storyblok — an internal link     |
| a document (pdf, docx…)    | the file uploaded to Storyblok, linked as asset|
| an .aspx site page         | left exactly as it is                          |
| anything off aku.edu       | left exactly as it is                          |

**An .aspx page is left alone deliberately.** Faculty profiles, section home
pages and programme pages are the Pages migration's content, not ours. Rewriting
them would mean guessing a destination that does not exist yet, and a wrong link
is worse than a dead one because nobody goes looking for it. They are counted
and reported so Pages can pick them up.

## How a story is found

News pages carry their slug: `/news/aku-pledges-commitment-to-every-woman…`
matches the story's own slug, which is how 241 of them resolve.

Blogs are addressed by id — `/blogs/pages/detail-page.aspx?pid=42` is blog 42 —
so `pid` is read from the query string rather than the path. That is also why
the blog case must be checked **before** the .aspx case: every blog link is an
.aspx URL and would otherwise be dismissed as a site page.

## Counts at the time of writing

    news    241 news pages, 2 blog pages, 76 documents, 345 site pages
    blogs     0 story links,             5 documents,  17 site pages

Blogs links nothing to a story at all, which is worth knowing before anybody
goes looking for a bug in the blogs rewriting.
"""

import os
import re
from urllib.parse import parse_qs, unquote, urlparse

DOCUMENT_SUFFIXES = (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
                     ".csv", ".zip")

# Hosts that are SharePoint. A link anywhere else is somebody else's site and is
# never touched.
AKU_HOSTS = ("www.aku.edu", "aku.edu")

NEWS_PATH = re.compile(r"^/news/(?P<slug>[^/?#]+)/?$", re.I)
BLOG_PID = re.compile(r"^/blogs?/", re.I)


def is_ours(href):
    """True when the URL points into SharePoint, relative or absolute."""
    href = (href or "").strip()
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return False
    parts = urlparse(href)
    if not parts.netloc:
        return href.startswith("/")
    return parts.netloc.lower() in AKU_HOSTS


def classify(href):
    """('story'|'document'|'site page'|'external', detail).

    `detail` is a slug for a news page, an integer id for a blog page, the
    filename for a document, and None otherwise.
    """
    if not is_ours(href):
        return "external", None
    parts = urlparse((href or "").strip())
    path = unquote(parts.path or "")

    # Blogs first: every blog link is also an .aspx URL and would otherwise be
    # written off as a site page.
    if BLOG_PID.match(path):
        pid = (parse_qs(parts.query or "").get("pid")
               or parse_qs(parts.query or "").get("PostID"))
        if pid and str(pid[0]).strip().isdigit():
            return "story", int(str(pid[0]).strip())

    news = NEWS_PATH.match(path)
    if news:
        return "story", news.group("slug").lower()

    if path.lower().endswith(DOCUMENT_SUFFIXES):
        return "document", os.path.basename(path)

    if path.lower().endswith(".aspx") or path.count("/") >= 1:
        return "site page", None
    return "site page", None


def rewrite_href(href, *, story_slugs=None, blog_ids=None, assets=None):
    """The href this link should carry, and why. Never invents a destination.

    story_slugs  {news slug: storyblok full_slug}
    blog_ids     {sharepoint blog id: storyblok full_slug}
    assets       {source filename: uploaded asset url}

    Returns (new_href, reason). `new_href` is None when nothing should change,
    which is the answer for every .aspx page and everything off aku.edu.
    """
    kind, detail = classify(href)
    if kind == "external":
        return None, "not a SharePoint link"
    if kind == "site page":
        return None, "site page — belongs to the Pages migration"

    if kind == "story":
        table = blog_ids if isinstance(detail, int) else story_slugs
        target = (table or {}).get(detail)
        if target:
            return "/" + target.lstrip("/"), f"story {detail}"
        return None, f"no migrated story for {detail!r}"

    if kind == "document":
        url = (assets or {}).get(detail)
        if url:
            return url, f"asset {detail}"
        return None, f"document {detail!r} not uploaded yet"
    return None, "unclassified"
