#!/usr/bin/env python3
"""
sb_common.py — shared plumbing for sb_backup.py and sb_restore.py.

Config, HTTP with retries, credential scrubbing, deterministic JSON writing,
asset path mirroring, and the git wrapper. Imported, never run.

AKUH, AKU and AKUEB are three separate Storyblok spaces with three separate
component libraries, and each one backs up to its own repo. Nothing here is
allowed to assume they share a schema.
"""

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import unquote, urlsplit

try:
    import requests
except ImportError:
    sys.exit("pip install -r requirements.txt")

HERE = os.path.dirname(os.path.abspath(__file__))


def _repo_root():
    """Walk up looking for config/types, rather than counting dirname() calls.

    That rule is in this repo because counting has broken four times, and each
    time it resolved to somewhere plausible and wrong with no error at all --
    paths_root.py returning pipeline/, storyblok_config.py returning
    space_id: None so every call came back 401. Anchor on something only the
    target has.

    Returns None when there is no pipeline above us, which is the normal case
    when these scripts run from a backup repo's tools/ folder. That is the whole
    point of copying them there: the repo has to restore with nothing but
    itself, so not finding the pipeline is not an error.
    """
    d = HERE
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "config", "types")):
            return d
        d = os.path.dirname(d)
    return None


ROOT = _repo_root()
# In the pipeline: config/sites.json, beside config/storyblok.json, which is the
# convention this repo already uses for gitignored credentials. Standalone in a
# backup repo: beside the scripts.
DEFAULT_CONFIG = (os.path.join(ROOT, "config", "sites.json") if ROOT
                  else os.path.join(HERE, "sites.json"))

# Scripts copied into every backup repo, so a repo can be restored with nothing
# but itself and Python. Edited here, in one place.
TOOL_FILES = ["sb.py", "sb_common.py", "sb_backup.py", "sb_restore.py",
              "sb_storage.py", "sb_portal.py", "sb_indexdb.py"]

# Written into every backup repo so it stands alone: the deps it needs, and a
# double-clickable wrapper on each platform. A backup repo that needs another
# checkout to be useful has a dependency that will be missing on the day it
# matters.
TOOL_EXTRAS = {
    # Line endings, and the exception that matters. Everything generated here is
    # written LF, and the backup depends on staying that way: if git checks files
    # out as CRLF the next run rewrites them as LF and all 5,700 look modified,
    # which destroys the "no commit when nothing changed" property.
    #
    # backup.cmd is the exception. cmd.exe mis-parses a batch file with bare LF
    # endings, so a blanket eol=lf silently breaks the one-click wrapper on
    # checkout -- it was written correctly and then converted.
    ".gitattributes": (
        "# Written by sb_backup.py — do not edit.\n"
        "* text=auto eol=lf\n"
        "\n"
        "# cmd.exe needs CRLF; with LF it mis-parses the file.\n"
        "*.cmd text eol=crlf\n"
        "\n"
        "# Binary, so git never tries to translate anything inside them.\n"
        "*.sqlite binary\n"
        "*.png binary\n"
        "*.jpg binary\n"
        "*.jpeg binary\n"
        "*.gif binary\n"
        "*.webp binary\n"
        "*.pdf binary\n"
        "*.mp4 binary\n"
        "*.mov binary\n"
    ),
    "tools/requirements.txt": (
        "# Everything tools/ needs. Nothing else.\n"
        "requests>=2.31\n"
        "azure-storage-blob>=12.19\n"
    ),
    # CRLF on purpose: cmd.exe mis-parses a .cmd file with bare LF endings.
    "backup.cmd": (
        "@echo off\r\n"
        "REM One click: back this space up and commit.\r\n"
        "REM Pass --push to push, or --no-commit to only write files.\r\n"
        "cd /d \"%~dp0\"\r\n"
        "python tools\\sb.py backup %*\r\n"
        "pause\r\n"
    ),
    "backup.sh": (
        "#!/usr/bin/env bash\n"
        "# One click: back this space up and commit.\n"
        "# Pass --push to push, or --no-commit to only write files.\n"
        "set -euo pipefail\n"
        "cd \"$(dirname \"$0\")\"\n"
        "exec python tools/sb.py backup \"$@\"\n"
    ),
}

# Storyblok runs one Management API host per region. An EU token sent to the US
# host does not say "wrong region" -- it 401s, which reads like a bad token and
# sends you looking in the wrong place.
REGION_HOSTS = {
    "eu": "https://mapi.storyblok.com/v1",
    "us": "https://api-us.storyblok.com/v1",
    "ca": "https://api-ca.storyblok.com/v1",
    "ap": "https://api-ap.storyblok.com/v1",
    "cn": "https://app.storyblokchina.cn/v1",
}

# The Content Delivery API, which is a different host from the Management API and
# the only place a story's PUBLISHED version exists. The Management API always
# returns the draft, and the two differ for any story with unpublished changes --
# 231 of them on AKUH.
CDN_HOSTS = {
    "eu": "https://api.storyblok.com/v2/cdn",
    "us": "https://api-us.storyblok.com/v2/cdn",
    "ca": "https://api-ca.storyblok.com/v2/cdn",
    "ap": "https://api-ap.storyblok.com/v2/cdn",
    "cn": "https://app.storyblokchina.cn/v2/cdn",
}

# Dropped from every payload before it is written. Storyblok returns a
# preview_token on each story and a first_token on the space; both are live
# credentials, and this output goes to a git remote.
SECRET_KEYS = {
    "first_token", "preview_token", "api_key", "management_token",
    "password", "real_email", "alt_email", "personal_access_token",
}

# `secret` is NOT in the set above, and must not be: it is a perfectly ordinary
# name for a story field, and scrubbing it globally would quietly delete real
# content. But /webhook_endpoints returns the HMAC signing secret under exactly
# that key, and this output goes to a git remote. So it is scrubbed for that one
# resource, by name, and RESTORE.md says the secrets must be re-set by hand.
PER_RESOURCE_SECRET_KEYS = {"webhook_endpoints": {"secret"}}

# A PUT on an asset and a DELETE on a folder both answer 204. Treating only
# (200, 201) as success is how a run that moved everything correctly reports
# that everything failed.
OK_STATUS = (200, 201, 204)

_local = threading.local()


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

def load_sites(path=None):
    path = path or os.environ.get("SB_SITES") or DEFAULT_CONFIG
    if not os.path.exists(path):
        example = (os.path.join(ROOT, "config", "sites.example.json") if ROOT
                   else "sites.example.json")
        sys.exit(f"no {path}\n"
                 f"copy {example} to {path} and fill it in")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    sites = cfg.get("sites") or []
    if not sites:
        sys.exit(f"{path} has no 'sites' array")
    for s in sites:
        for field in ("name", "space_id", "repo"):
            if not s.get(field):
                sys.exit(f"a site in {path} is missing '{field}'")
    return sites


def pick_sites(sites, wanted):
    """`wanted` is a site name, a comma list, or 'all'. Case-insensitive."""
    if wanted.lower() == "all":
        return sites
    names = [w.strip().lower() for w in wanted.split(",") if w.strip()]
    chosen = [s for s in sites if s["name"].lower() in names]
    missing = set(names) - {s["name"].lower() for s in chosen}
    if missing:
        sys.exit(f"no site named {', '.join(sorted(missing))} - "
                 f"have: {', '.join(s['name'] for s in sites)}")
    return chosen


def token_for(site):
    """Token from the environment first, so CI never needs the file on disk."""
    env = "SB_TOKEN_" + re.sub(r"[^A-Z0-9]", "_", site["name"].upper())
    return os.environ.get(env) or site.get("management_token")


def api_base(site):
    region = (site.get("region") or "eu").lower()
    if region not in REGION_HOSTS:
        sys.exit(f"{site['name']}: unknown region {region!r} - "
                 f"one of {', '.join(REGION_HOSTS)}")
    return REGION_HOSTS[region]


def space_api(site):
    return f"{api_base(site)}/spaces/{site['space_id']}"


def repo_paths(site):
    """(repo root, snapshot dir) for a site, both absolute."""
    repo = os.path.abspath(os.path.expanduser(site["repo"]))
    return repo, os.path.join(repo, site.get("subdir", "storyblok"))


# An asset URL anywhere in text, and the stable part of one.
#
# The same asset is served under more than one host: assets.json returns the S3
# form (s3.amazonaws.com/a.storyblok.com/f/<space>/...) while story content
# carries the CDN form (a.storyblok.com/f/<space>/...), and paid plans can add a
# custom domain. Only the path after /f/<space id>/ is stable, so that is the
# key. Matching whole URLs instead silently matched 892 of ~5,800 references, and
# would have left every image in a rebuilt space pointing at the old one.
ASSET_URL_RE = re.compile(r"""https?://[^\s"'<>)\]]*?/f/\d+/[^\s"'<>)\]]*""")
_AFTER_F = re.compile(r"/f/\d+/(.+)$")


def asset_url_key(url):
    """The part of an asset URL after /f/<space id>/, or None."""
    if not url or "/f/" not in url:
        return None
    m = _AFTER_F.search(unquote(urlsplit(url).path))
    return m.group(1) if m else None


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def session(token=None):
    """Pooled Session per thread, and separate sessions for authed vs anonymous.

    Per-thread because requests.Session is not documented as thread-safe.
    Pooled because a bare requests.get() per file leaves a socket in TIME_WAIT
    for each of thousands of assets, and Windows then runs out of ephemeral
    ports -- which surfaces only as the uninformative WinError 10013.

    Two sessions, because a Session keeps whatever header it was last given.
    Reusing the Management API session to fetch an asset would send the
    management token -- write access to the entire space -- to the asset host
    and to anything it redirects to. Asset URLs are public; they get a session
    that has never held a token.
    """
    kind = "authed" if token else "anon"
    cache = getattr(_local, "sessions", None)
    if cache is None:
        cache = _local.sessions = {}
    s = cache.get(kind)
    if s is None:
        s = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=16, pool_maxsize=16, max_retries=0)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        cache[kind] = s
    if token:
        s.headers["Authorization"] = token  # MAPI takes the token bare, no Bearer
    return s


def call(method, url, token=None, params=None, body=None, files=None,
         data=None, tries=5, stream=False, timeout=120):
    """One request, with backoff on 429, 5xx and transport failures.

    Connection errors are retried, not just HTTP errors: a dropped socket part
    way through several thousand requests is normal, and letting it raise
    throws away the entire run.
    """
    s = session(token)
    last = None
    r = None
    for attempt in range(tries):
        try:
            r = s.request(method, url, params=params, json=body, files=files,
                          data=data, timeout=timeout, stream=stream)
        except requests.exceptions.RequestException as e:
            last = e
            time.sleep(min(2 * (attempt + 1), 30))
            continue
        last = None      # a response arrived; report it, not a stale error
        if r.status_code == 429:
            wait = r.headers.get("Retry-After")
            time.sleep(min(int(wait) if wait and wait.isdigit()
                           else 2 * (attempt + 1), 30))
            continue
        if r.status_code >= 500 and attempt < tries - 1:
            time.sleep(min(2 * (attempt + 1), 30))
            continue
        return r
    if last:
        raise last
    return r


def get(url, token=None, params=None, tries=5, stream=False):
    return call("GET", url, token, params=params, tries=tries, stream=stream)


def fetch_list(api, path, key, paginated, token, per_page=100):
    """Return (list, error_string).

    Pagination follows the Total header rather than stopping on a short page:
    the last page is exactly full whenever the total is a multiple of per_page,
    and stopping there loses everything after it.
    """
    url = f"{api}/{path}"
    if not paginated:
        r = get(url, token)
        if r.status_code != 200:
            return None, f"{r.status_code} {r.text[:200]}"
        b = r.json()
        return (b.get(key, b) if isinstance(b, dict) else b), None

    out, page = [], 1
    while True:
        sep = "&" if "?" in path else "?"
        r = get(f"{url}{sep}per_page={per_page}&page={page}", token)
        if r.status_code != 200:
            if page == 1:
                return None, f"{r.status_code} {r.text[:200]}"
            return out, None
        chunk = r.json().get(key) or []
        out.extend(chunk)
        total = int(r.headers.get("Total", len(out)) or len(out))
        if not chunk or len(out) >= total:
            return out, None
        page += 1


# --------------------------------------------------------------------------
# reading and writing JSON
# --------------------------------------------------------------------------

def scrub(obj):
    """Drop credential and personal-data keys at every depth."""
    if isinstance(obj, list):
        return [scrub(o) for o in obj]
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items() if k not in SECRET_KEYS}
    return obj


def write_json(path, obj):
    """Write one JSON file, deterministically.

    sort_keys and a stable list order matter more than they look: the value of
    this backup is `git diff` between two snapshots, and any ordering the API
    happens to vary turns into a diff that means nothing. JSON objects are
    unordered, so sorting keys loses no information.
    """
    if isinstance(obj, list):
        obj = sort_by_id(obj)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(scrub(obj), f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    return len(obj) if isinstance(obj, list) else 1


def save(outdir, name, obj):
    extra = PER_RESOURCE_SECRET_KEYS.get(name)
    if extra:
        obj = _drop_keys(obj, extra)
    return write_json(os.path.join(outdir, f"{name}.json"), obj)


def _drop_keys(obj, keys):
    if isinstance(obj, list):
        return [_drop_keys(o, keys) for o in obj]
    if isinstance(obj, dict):
        return {k: _drop_keys(v, keys) for k, v in obj.items() if k not in keys}
    return obj


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sort_by_id(items):
    if items and all(isinstance(i, dict) and "id" in i for i in items):
        return sorted(items, key=lambda i: (str(type(i["id"])), i["id"]))
    return items


# --------------------------------------------------------------------------
# assets on disk
# --------------------------------------------------------------------------

_UNSAFE = re.compile(r'[<>:"|?*\x00-\x1f]')


def asset_path(asset, space_id):
    """Relative local path for an asset, mirroring its URL.

        https://a.storyblok.com/f/12345/1200x800/abcdef0123/photo.jpg
                                        ^-----------------------------
        -> assets/1200x800/abcdef0123/photo.jpg

    Keyed on the URL rather than the asset id, because the URL is what every
    story's content actually points at -- which is what makes a restore able to
    rewrite references mechanically.
    """
    url = asset.get("filename") or ""
    rest = ""
    if url:
        path = unquote(urlsplit(url).path)
        marker = f"/f/{space_id}/"
        if marker in path:
            rest = path.split(marker, 1)[1]
        elif "/f/" in path:
            rest = path.split("/f/", 1)[1]
            rest = rest.split("/", 1)[1] if "/" in rest else rest
    if not rest:
        rest = f"by-id/{asset.get('id')}/{os.path.basename(url) or 'asset.bin'}"

    parts = []
    for seg in rest.split("/"):
        seg = _UNSAFE.sub("_", seg).strip(" .")
        if seg and seg not in (".", ".."):
            parts.append(seg[:120])
    if not parts:
        return None
    return os.path.join("assets", *parts)


# --------------------------------------------------------------------------
# folder trees
# --------------------------------------------------------------------------

def folder_path_map(items, name_key="name"):
    """{folder id: "a/b/c"} for anything with id / parent_id / a name.

    Used for both namespaces -- asset folders and story folders -- because they
    are the same shape and the same question: where does this thing live?

    Depth is bounded rather than recursive on trust. A parent_id cycle is not
    hypothetical in this space: asset folders once reached 769 entries with 7
    `regions` roots, and a cycle there would hang a run with no output.
    """
    by_id = {i["id"]: i for i in items if i.get("id") is not None}
    out = {}
    for fid, item in by_id.items():
        parts, seen, cur = [], set(), item
        while cur is not None and cur["id"] not in seen:
            seen.add(cur["id"])
            parts.append(str(cur.get(name_key) or cur.get("slug") or cur["id"]))
            parent = cur.get("parent_id")
            cur = by_id.get(parent) if parent else None
        out[fid] = "/".join(reversed(parts))
    return out


def write_csv(path, header, rows):
    """A committed CSV, deterministic and Excel-safe.

    newline="" plus an explicit \\n terminator, because csv writes \\r\\n on
    Windows by default and the same data would then diff against a snapshot
    taken on Linux. utf-8-sig so Excel opens accented names correctly -- these
    files are read by people, and 711 non-ASCII characters in this corpus are
    real content.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    return len(rows)


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------

def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", repo, *args], check=False,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed ({r.returncode})\n"
                           f"{(r.stderr or r.stdout or '').strip()}")
    return r


def have_lfs():
    try:
        return subprocess.run(["git", "lfs", "version"], capture_output=True,
                              check=False).returncode == 0
    except FileNotFoundError:
        return False


def install_tools(repo):
    """Copy the scripts into <repo>/tools/.

    Each site's repo has to be restorable on its own: a backup you can only
    read with a checkout of some other repository is a backup with a hidden
    dependency, and that dependency will be missing on the day it matters.
    """
    dest = os.path.join(repo, "tools")
    os.makedirs(dest, exist_ok=True)
    copied = 0
    for fn in TOOL_FILES:
        src = os.path.join(HERE, fn)
        if not os.path.exists(src):
            continue
        dst = os.path.join(dest, fn)
        if not os.path.exists(dst) or \
                open(src, "rb").read() != open(dst, "rb").read():
            shutil.copy2(src, dst)
            copied += 1
    for rel, body in TOOL_EXTRAS.items():
        path = os.path.join(repo, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        current = ""
        if os.path.exists(path):
            with open(path, encoding="utf-8", newline="") as f:
                current = f.read()
        if current != body:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(body)
            copied += 1
    if copied:
        print(f"    tools/: refreshed {copied} file(s)")
    return copied


def relpath(path, start):
    try:
        return os.path.relpath(path, start)
    except ValueError:          # different drive on Windows
        return path
