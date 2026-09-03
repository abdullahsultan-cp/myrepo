#!/usr/bin/env python3
"""
test_pipeline.py — end-to-end tests for sb_backup.py and sb_restore.py.

No network, no tokens, no real space. Stands up a stateful fake Management API
on localhost, points a copy of the pipeline at it, and exercises the whole
thing: three sites backing up to three separate repos, LFS conversion,
credential scrubbing, in-place restore, and a full rebuild into an empty space
with asset and link remapping.

Every assertion here exists because the thing it checks was wrong at some point,
or would be silent if it broke. The LFS ones caught .gitattributes being written
at the repo root, where its anchored patterns cannot match storyblok/assets/ --
LFS reported success while git stored the raw bytes.

    python test_pipeline.py
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOL = os.path.dirname(os.path.abspath(__file__))
SRC = "555"          # the space that gets backed up
TGT = "999"          # the empty space a rebuild goes into

PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 4000
PDF = b"%PDF-1.4\n" + b"x" * 2000
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\xff" * 500

OLD_PNG_URL = "http://HOST/f/555/800x600/aaaa1111/pic.png"
OLD_PDF_URL = "http://HOST/f/555/x/bbbb2222/doc.pdf"

# Content deliberately holds the same asset reference three ways, because
# Storyblok does: an asset object with id+filename, a rich-text image node, and
# a bare url inside prose. A remapper that only fixes the tidy object case
# leaves a rebuilt space full of broken images.
STORY_101 = {
    "component": "news_article",
    "title": "First",
    "hero": {"id": 9001, "filename": OLD_PNG_URL, "fieldtype": "asset"},
    "body": {"type": "doc", "content": [
        {"type": "image", "attrs": {"id": 9001, "src": OLD_PNG_URL}},
        {"type": "paragraph", "content": [
            {"type": "text", "text": f"see {OLD_PDF_URL} for details"}]},
    ]},
    "link": {"linktype": "story", "id": "uuid-102", "cached_url": "news/b"},
}

STORIES = {
    "10": {"id": 10, "name": "News", "slug": "news", "full_slug": "news",
           "is_folder": True, "parent_id": 0, "uuid": "uuid-10",
           "content": {}},
    "101": {"id": 101, "name": "A", "slug": "a", "full_slug": "news/a",
            "parent_id": 10, "uuid": "uuid-101", "published": True,
            "tag_list": ["x"], "content": STORY_101},
    "102": {"id": 102, "name": "B", "slug": "b", "full_slug": "news/b",
            "parent_id": 10, "uuid": "uuid-102", "published": False,
            "tag_list": [], "content": {"component": "news_article",
                                        "title": "Second"}},
}

ASSETS = [
    {"id": 9001, "filename": OLD_PNG_URL, "content_length": len(PNG),
     "content_type": "image/png", "alt": "A picture", "asset_folder_id": 70},
    {"id": 9002, "filename": OLD_PDF_URL, "content_length": len(PDF),
     "content_type": "application/pdf", "asset_folder_id": None},
    {"id": 9003, "filename": "http://HOST/f/555/x/cccc3333/logo.svg",
     "content_length": len(SVG), "content_type": "image/svg+xml"},
    {"id": 9004, "filename": "http://HOST/f/555/x/dddd4444/PHOTO.HEIC",
     "content_length": len(HEIC), "content_type": "image/heic"},
]

COMPONENTS = [
    {"id": 2, "name": "news_article", "display_name": "News Article",
     "schema": {"title": {"type": "text"}}, "is_root": True,
     "component_group_uuid": "grp-1"},
    {"id": 1, "name": "page", "schema": {}, "is_root": True},
]
GROUPS = [{"id": 5, "uuid": "grp-1", "name": "Content Types"}]
ASSET_FOLDERS = [{"id": 70, "name": "photos", "parent_id": None},
                 {"id": 71, "name": "2024", "parent_id": 70}]
DATASOURCES = [{"id": 7, "name": "Colors", "slug": "colors"}]
DENTRIES = [{"id": 71, "name": "Red", "value": "red", "datasource_id": 7}]

state = {"puts": [], "created": {}, "next_id": 5000, "target_stories": []}
LOCK = threading.Lock()


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, obj=b"", ctype="application/json", extra=None):
        b = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _host(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def _fix(self, obj):
        """Fake asset hosts point at this server, so downloads really happen."""
        return json.loads(json.dumps(obj).replace("HOST", self._host()[7:]))

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        p, host = self.path.split("?")[0], self._host()

        # The Content Delivery API: the only place a story's PUBLISHED version
        # exists. Returns deliberately different content from the draft, so a
        # backup that quietly saved drafts in both places fails the test.
        if p.startswith("/v2/cdn/stories/"):
            sid = p.rsplit("/", 1)[1]
            if self.path.find("token=LEAKED_TOKEN") < 0:
                return self._send(401, {"error": "bad token"})
            if sid not in STORIES or not STORIES[sid].get("published"):
                return self._send(404, {"error": "not found"})
            st = dict(self._fix(STORIES[sid]))
            st["content"] = dict(st.get("content") or {},
                                 title="PUBLISHED VERSION")
            return self._send(200, {"story": st})

        if p == f"/v1/spaces/{SRC}":
            return self._send(200, {"space": {
                "id": int(SRC), "name": "Fake Source", "plan": "starter",
                "first_token": "LEAKED_TOKEN", "owner": {"email": "x@y.z"}}})
        if p == f"/v1/spaces/{SRC}/webhook_endpoints":
            # The real endpoint returns the HMAC signing secret, which must not
            # reach a git remote.
            return self._send(200, {"webhook_endpoints": [
                {"id": 1, "name": "deploy", "endpoint": "https://ci/hook",
                 "secret": "LEAKED_WEBHOOK_SECRET", "actions": ["story.published"]}]})
        if p == f"/v1/spaces/{TGT}":
            return self._send(200, {"space": {"id": int(TGT),
                                              "name": "Fake Target",
                                              "plan": "starter"}})

        if p == f"/v1/spaces/{SRC}/components":
            return self._send(200, {"components": COMPONENTS},
                              extra={"Total": str(len(COMPONENTS))})
        if p == f"/v1/spaces/{SRC}/component_groups":
            return self._send(200, {"component_groups": GROUPS})
        if p == f"/v1/spaces/{SRC}/asset_folders":
            return self._send(200, {"asset_folders": ASSET_FOLDERS})
        if p == f"/v1/spaces/{SRC}/datasources":
            return self._send(200, {"datasources": DATASOURCES},
                              extra={"Total": "1"})
        if p == f"/v1/spaces/{SRC}/datasource_entries":
            return self._send(200, {"datasource_entries": DENTRIES},
                              extra={"Total": "1"})
        if p == f"/v1/spaces/{SRC}/assets":
            return self._send(200, self._fix({"assets": ASSETS}),
                              extra={"Total": str(len(ASSETS))})
        if p == f"/v1/spaces/{SRC}/stories":
            lst = [{k: v for k, v in s.items() if k != "content"}
                   for s in STORIES.values()]
            return self._send(200, {"stories": lst},
                              extra={"Total": str(len(lst))})
        if p.startswith(f"/v1/spaces/{SRC}/stories/"):
            sid = p.rsplit("/", 1)[1]
            if sid not in STORIES:
                return self._send(404, {"error": "not found"})
            st = dict(self._fix(STORIES[sid]))
            st["preview_token"] = "LEAKED_PREVIEW"   # must be scrubbed
            return self._send(200, {"story": st})

        # ---- target space
        if p == f"/v1/spaces/{TGT}/stories":
            with LOCK:
                return self._send(200, {"stories": list(state["target_stories"])},
                                  extra={"Total": str(len(state["target_stories"]))})
        if p.endswith("/finish_upload"):
            return self._send(200, {"ok": True})
        for sp in (TGT, SRC):
            if p.startswith(f"/v1/spaces/{sp}/assets/"):
                aid = p.rsplit("/", 1)[1]
                if not aid.isdigit():
                    break
                return self._send(200, {"asset": {
                    "id": int(aid),
                    "filename": f"{host}/f/{sp}/new/{aid}/file.bin"}})

        # Asset binaries. The check is scoped to these paths on purpose: put it
        # on the fallthrough and every unmatched Management API endpoint answers
        # 599, which the tool correctly retries five times with backoff -- so
        # the suite takes minutes and the failure looks like a hang.
        for suffix, body in ((".png", PNG), (".pdf", PDF), (".svg", SVG),
                             (".HEIC", HEIC)):
            if p.endswith(suffix):
                if self.headers.get("Authorization"):
                    return self._send(599,
                                      {"error": "token leaked to asset host"})
                return self._send(200, body, "application/octet-stream")

        # Everything else: what a real space-level token does on an endpoint it
        # cannot reach. 403, not 5xx, so there is nothing to retry.
        return self._send(403, {"error": "unsupported for this token type"})

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        p, body, host = self.path.split("?")[0], self._body(), self._host()

        if p == "/fake-s3":
            return self._send(204)

        if p in (f"/v1/spaces/{TGT}/assets", f"/v1/spaces/{SRC}/assets"):
            space = TGT if TGT in p else SRC
            sent = body.get("asset", body) if isinstance(body, dict) else {}
            with LOCK:
                state["next_id"] += 1
                new = state["next_id"]
                # Recorded so a test can assert the folder it went into.
                state["created"].setdefault("asset", []).append(
                    dict(sent, id=new))
            return self._send(200, {"id": new, "post_url": f"{host}/fake-s3",
                                    "fields": {"key": f"f/{space}/{new}"}})

        m = {f"/v1/spaces/{TGT}/component_groups": ("component_group", "uuid"),
             f"/v1/spaces/{TGT}/components": ("component", None),
             f"/v1/spaces/{TGT}/asset_folders": ("asset_folder", None),
             f"/v1/spaces/{TGT}/datasources": ("datasource", None),
             f"/v1/spaces/{TGT}/datasource_entries": ("datasource_entry", None),
             f"/v1/spaces/{TGT}/internal_tags": ("internal_tag", None),
             f"/v1/spaces/{TGT}/stories": ("story", "uuid")}
        if p in m:
            key, extra = m[p]
            sent = body.get(key, {}) if isinstance(body, dict) else {}
            with LOCK:
                state["next_id"] += 1
                new = state["next_id"]
                state["created"].setdefault(key, []).append(sent)
                out = dict(sent, id=new)
                if extra == "uuid":
                    # Storyblok assigns its own uuid on create -- the case that
                    # forces the relink pass. Honouring the sent one would let a
                    # broken remapper pass.
                    out["uuid"] = f"new-{new}"
                if key == "story":
                    state["target_stories"].append({"id": new})
            return self._send(200, {key: out})

        return self._send(403, {"error": "unsupported"})

    # ---------------------------------------------------------------- PUT
    def do_PUT(self):
        p, body = self.path.split("?")[0], self._body()
        if p.startswith(f"/v1/spaces/{SRC}/stories/") or \
                p.startswith(f"/v1/spaces/{TGT}/stories/") or \
                p.startswith(f"/v1/spaces/{TGT}/assets/"):
            with LOCK:
                state["puts"].append((p, body))
            return self._send(200, {"story": {"id": 1}, "asset": {"id": 1}})
        return self._send(403, {"error": "unsupported"})


# --------------------------------------------------------------------------

def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    tmp = tempfile.mkdtemp(prefix="sbpipe-")
    work = os.path.join(tmp, "pipeline")
    shutil.copytree(TOOL, work, ignore=shutil.ignore_patterns(
        "__pycache__", "sites.json", ".git"))

    # point the EU host at the fake server
    # Both hosts, not just the Management API. Redirecting only REGION_HOSTS let
    # the published-content fetch escape to the real api.storyblok.com, where it
    # 401'd -- so the feature looked broken and the test looked like it had
    # covered it.
    cpath = os.path.join(work, "sb_common.py")
    with open(cpath, encoding="utf-8") as f:
        src = f.read()
    src = src.replace('"eu": "https://mapi.storyblok.com/v1"',
                      f'"eu": "http://127.0.0.1:{port}/v1"')
    src = src.replace('"eu": "https://api.storyblok.com/v2/cdn"',
                      f'"eu": "http://127.0.0.1:{port}/v2/cdn"')
    with open(cpath, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)

    repos = {n: os.path.join(tmp, f"{n.lower()}-backup")
             for n in ("AKUH", "AKU", "AKUEB")}
    with open(os.path.join(work, "sites.json"), "w", encoding="utf-8") as f:
        json.dump({"sites": [
            {"name": n, "space_id": SRC, "management_token": "TESTTOKEN",
             "region": "eu", "repo": repos[n]} for n in repos]}, f)

    fails = []

    def ck(label, cond, detail=""):
        print(("  PASS  " if cond else "  FAIL  ") + label
              + ("" if cond else f"\n          {detail}"))
        if not cond:
            fails.append(label)

    def run(script, *a):
        return subprocess.run(
            [sys.executable, os.path.join(work, script), *a],
            cwd=work, capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))

    # ================================================== BACKUP
    print("\n=== backup: three sites, three repos ===")
    r = run("sb_backup.py", "--site", "all")
    ck("exit 0", r.returncode == 0, (r.stdout + r.stderr)[-1500:])

    for name, repo in repos.items():
        sb = os.path.join(repo, "storyblok")
        ck(f"{name}: snapshot written",
           os.path.exists(os.path.join(sb, "components.json")))
        ck(f"{name}: 3 story files",
           len([f for f in os.listdir(os.path.join(sb, "stories"))
                if f.endswith(".json")]) == 3)
        ck(f"{name}: tools/ copied for standalone restore",
           os.path.exists(os.path.join(repo, "tools", "sb_restore.py")))
        ck(f"{name}: own git repo", os.path.isdir(os.path.join(repo, ".git")))

    ck("repos are separate checkouts",
       len({os.path.realpath(p) for p in repos.values()}) == 3)

    sb = os.path.join(repos["AKU"], "storyblok")
    ck("datasource entries captured",
       (json.load(open(os.path.join(sb, "datasource_entries.json"),
                       encoding="utf-8")) or [{}])[0].get("name") == "Red")

    # ---- the readable manifests: which story is where, where every asset went
    import csv as _csv

    def read_csv(name):
        with open(os.path.join(sb, name), encoding="utf-8-sig",
                  newline="") as f:
            return list(_csv.DictReader(f))

    srows = read_csv("manifest_stories.csv")
    ck("story manifest has a row per story and folder", len(srows) == 3,
       str([r["full_slug"] for r in srows]))
    by_slug = {r["full_slug"]: r for r in srows}
    ck("manifest names the folder a story sits in",
       by_slug["news/a"]["parent_folder"] == "news",
       str(by_slug.get("news/a")))
    ck("manifest marks folders as folders",
       by_slug["news"]["kind"] == "folder" and
       by_slug["news"]["parent_folder"] == "(root)", str(by_slug["news"]))
    ck("manifest records the component",
       by_slug["news/a"]["component"] == "news_article",
       by_slug["news/a"]["component"])
    ck("manifest records published vs draft",
       by_slug["news/a"]["state"] == "published"
       and by_slug["news/b"]["state"] == "draft",
       f"{by_slug['news/a']['state']} / {by_slug['news/b']['state']}")
    ck("manifest counts the assets a story references",
       by_slug["news/a"]["assets_referenced"] == "2",
       by_slug["news/a"]["assets_referenced"])
    ck("manifest points at the backup file for the story",
       by_slug["news/a"]["backup_file"] == "stories/101.json",
       by_slug["news/a"]["backup_file"])
    ck("manifest is sorted by slug (stable diffs)",
       [r["full_slug"] for r in srows]
       == sorted(r["full_slug"] for r in srows),
       str([r["full_slug"] for r in srows]))

    arows = read_csv("manifest_assets.csv")
    ck("asset manifest has a row per asset", len(arows) == 4, str(len(arows)))
    a_by = {r["filename"]: r for r in arows}
    ck("asset manifest gives the folder path in the space",
       a_by["pic.png"]["asset_folder"] == "photos",
       a_by["pic.png"]["asset_folder"])
    # Always relative to the assets root, never to the repo -- that is what lets
    # the same manifest describe media in storyblok/assets/ and media on a
    # bucket. assets_location.json records which root applies.
    ck("asset manifest path is relative to the assets root",
       a_by["pic.png"]["backup_file"] == "800x600/aaaa1111/pic.png",
       a_by["pic.png"]["backup_file"])
    loc_in = json.load(open(os.path.join(sb, "assets_location.json"),
                            encoding="utf-8"))
    ck("in-repo run records assets as internal, pointing at storyblok/assets/",
       loc_in["external"] is False
       and loc_in["backup_file_paths_are_relative_to"] == "storyblok/assets/",
       str(loc_in))
    ck("asset manifest confirms every binary is present",
       all(r["file_present"] == "yes" for r in arows),
       str([(r["filename"], r["file_present"]) for r in arows]))
    ck("asset manifest carries the alt text",
       a_by["pic.png"]["alt"] == "A picture", a_by["pic.png"]["alt"])
    ck("asset manifest records a sha256 per file",
       all(len(r["sha256"]) == 64 for r in arows),
       str([(r["filename"], r["sha256"][:12]) for r in arows]))
    ck("the recorded sha256 is the real one",
       a_by["pic.png"]["sha256"]
       == hashlib.sha256(PNG).hexdigest(), a_by["pic.png"]["sha256"])
    ck("manifests are LF-terminated, not CRLF",
       b"\r\n" not in open(os.path.join(sb, "manifest_stories.csv"), "rb").read())

    # ---- the documents that travel with the backup
    for doc in ("README.md", "CLAUDE.md", "RESTORE.md"):
        p = os.path.join(repos["AKU"], doc)
        ck(f"{doc} written into the repo", os.path.exists(p))
    restore_md = open(os.path.join(repos["AKU"], "RESTORE.md"),
                      encoding="utf-8").read()
    ck("RESTORE.md names this space id", SRC in restore_md)
    ck("RESTORE.md covers both restore modes",
       "--mode in-place" in restore_md and "--mode rebuild" in restore_md)
    ck("RESTORE.md lists reinstalling apps as a manual step",
       "marketplace" in restore_md.lower(), "")
    ck("RESTORE.md warns that --apply is required",
       "--apply" in restore_md)
    claude_md = open(os.path.join(repos["AKU"], "CLAUDE.md"),
                     encoding="utf-8").read()
    ck("CLAUDE.md forbids hand-editing the snapshot",
       "Never hand-edit" in claude_md)
    ck("docs carry no timestamp (so they do not churn every run)",
       "20" + "26-" not in restore_md.replace(SRC, ""),
       [l for l in restore_md.splitlines() if "2026-" in l][:3])

    leaked = []
    for root, _, files in os.walk(repos["AKU"]):
        if ".git" in root:
            continue
        for fn in files:
            try:
                t = open(os.path.join(root, fn), encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            for needle in ("LEAKED_TOKEN", "LEAKED_PREVIEW", "TESTTOKEN",
                           "x@y.z", "LEAKED_WEBHOOK_SECRET"):
                if needle in t:
                    leaked.append(f"{fn}:{needle}")
    ck("no credentials, owner email or webhook secret written", not leaked,
       str(leaked))
    hooks = json.load(open(os.path.join(sb, "webhook_endpoints.json"),
                           encoding="utf-8"))
    ck("webhook captured but its signing secret stripped",
       hooks and hooks[0]["endpoint"] == "https://ci/hook"
       and "secret" not in hooks[0], str(hooks))

    # ---- published versions: a draft-only backup would restore the wrong thing
    pub_dir = os.path.join(sb, "stories_published")
    ck("published versions captured separately", os.path.isdir(pub_dir))
    pub_ids = sorted(f[:-5] for f in os.listdir(pub_dir)
                     if f.endswith(".json")) if os.path.isdir(pub_dir) else []
    ck("only published stories have a published file", pub_ids == ["101"],
       str(pub_ids))
    if pub_ids:
        p101 = json.load(open(os.path.join(pub_dir, "101.json"),
                              encoding="utf-8"))
        d101 = json.load(open(os.path.join(sb, "stories", "101.json"),
                              encoding="utf-8"))
        ck("published content is the PUBLISHED one, not the draft",
           p101["content"]["title"] == "PUBLISHED VERSION",
           p101["content"].get("title"))
        ck("draft is still stored separately and differs",
           d101["content"]["title"] != p101["content"]["title"],
           f"{d101['content'].get('title')} vs {p101['content'].get('title')}")
        ck("the delivery token is not written into the published file",
           "LEAKED_TOKEN" not in json.dumps(p101))

    # ---- the portal
    portal_path = os.path.join(repos["AKU"], "assets-portal.html")
    ck("assets-portal.html written", os.path.exists(portal_path))
    portal = open(portal_path, encoding="utf-8").read()
    ck("portal is self-contained (no external requests for structure)",
       "<script src" not in portal and "<link rel=\"stylesheet\"" not in portal)
    ck("portal embeds the folder tree", '"folders"' in portal)
    ck("portal names a real asset folder", "photos" in portal, "")
    ck("portal carries the storage path and checksum",
       "800x600/aaaa1111/pic.png" in portal
       and hashlib.sha256(PNG).hexdigest() in portal, "")
    ck("portal does not leak the management token",
       "TESTTOKEN" not in portal and "LEAKED" not in portal)

    lfs = subprocess.run(["git", "-C", repos["AKU"], "lfs", "ls-files"],
                         capture_output=True, text=True).stdout
    ck("png in LFS", "pic.png" in lfs, lfs)
    ck("pdf in LFS", "doc.pdf" in lfs, lfs)
    ck("unlisted .HEIC in LFS", "PHOTO.HEIC" in lfs, lfs)
    ck("svg NOT in LFS (diffs as text)", "logo.svg" not in lfs, lfs)
    blob = subprocess.run(
        ["git", "-C", repos["AKU"], "show",
         "HEAD:storyblok/assets/800x600/aaaa1111/pic.png"],
        capture_output=True, text=True).stdout
    ck("committed png is an LFS pointer",
       blob.startswith("version https://git-lfs"), blob[:100])

    print("\n=== backup: second run is a no-op ===")
    r = run("sb_backup.py", "--site", "AKU")
    ck("no commit when nothing changed", "nothing to commit" in r.stdout,
       r.stdout[-600:])
    log = subprocess.run(["git", "-C", repos["AKU"], "log", "--oneline"],
                         capture_output=True, text=True).stdout
    ck("still one commit", len(log.strip().splitlines()) == 1, log)

    # ============================ ASSETS OUTSIDE THE REPO (the bucket setup)
    # This is the arrangement actually chosen: ~42 GB of media across the three
    # spaces against GitHub's 1 GB, so the bytes go to a bucket and the repo
    # keeps the index plus a checksum per file.
    print("\n=== media outside the repo (bucket) ===")
    bucket = os.path.join(tmp, "bucket", "AKUEB")
    ext_repo = os.path.join(tmp, "akueb-external")
    with open(os.path.join(work, "sites-ext.json"), "w", encoding="utf-8") as f:
        json.dump({"sites": [{"name": "AKUEB", "space_id": SRC,
                              "management_token": "TESTTOKEN", "region": "eu",
                              "repo": ext_repo, "assets_dir": bucket}]}, f)
    r = run("sb_backup.py", "--config",
            os.path.join(work, "sites-ext.json"), "--site", "AKUEB")
    ck("exit 0", r.returncode == 0, (r.stdout + r.stderr)[-1200:])
    ck("says where the media went", "outside the repo" in r.stdout,
       r.stdout[-700:])

    esb = os.path.join(ext_repo, "storyblok")
    ck("binaries landed in the bucket, not the repo",
       os.path.exists(os.path.join(bucket, "800x600", "aaaa1111", "pic.png")),
       str(os.listdir(bucket) if os.path.isdir(bucket) else "no bucket dir"))
    ck("repo has NO assets directory",
       not os.path.exists(os.path.join(esb, "assets")))
    ck("repo still has the asset index",
       os.path.exists(os.path.join(esb, "manifest_assets.csv")))
    ck("no LFS used when media is external",
       not subprocess.run(["git", "-C", ext_repo, "lfs", "ls-files"],
                          capture_output=True, text=True).stdout.strip())
    loc = json.load(open(os.path.join(esb, "assets_location.json"),
                         encoding="utf-8"))
    ck("assets_location.json records that media is external",
       loc["external"] is True, str(loc))
    ck("no absolute bucket path is committed (it differs per machine)",
       bucket.replace("\\", "/") not in json.dumps(loc).replace("\\", "/"),
       json.dumps(loc))

    with open(os.path.join(esb, "manifest_assets.csv"),
              encoding="utf-8-sig", newline="") as f:
        erows = {r_["filename"]: r_ for r_ in _csv.DictReader(f)}
    ck("manifest paths are relative to the bucket root",
       erows["pic.png"]["backup_file"] == "800x600/aaaa1111/pic.png",
       erows["pic.png"]["backup_file"])
    ck("manifest confirms the bucket files are present",
       all(r_["file_present"] == "yes" for r_ in erows.values()),
       str([(k, v["file_present"]) for k, v in erows.items()]))

    print("\n=== verify: checksums prove the two halves match ===")
    r = run("sb_backup.py", "--config", os.path.join(work, "sites-ext.json"),
            "--site", "AKUEB", "--only", "assets", "--verify-assets",
            "--no-commit")
    ck("verify passes on an intact bucket",
       r.returncode == 0 and "missing 0" in r.stdout and "changed 0" in r.stdout,
       r.stdout[-700:])

    # corrupt one file and one delete: verify must catch both
    with open(os.path.join(bucket, "800x600", "aaaa1111", "pic.png"), "r+b") as f:
        f.seek(0)
        f.write(b"CORRUPT!")
    os.remove(os.path.join(bucket, "x", "bbbb2222", "doc.pdf"))
    r = run("sb_backup.py", "--config", os.path.join(work, "sites-ext.json"),
            "--site", "AKUEB", "--only", "assets", "--verify-assets",
            "--no-commit")
    ck("verify detects a corrupted file", "CHANGED" in r.stdout,
       r.stdout[-800:])
    ck("verify detects a deleted file", "MISSING" in r.stdout, r.stdout[-800:])

    # The corruption above kept the file's size (8 bytes over 8 bytes), so the
    # ordinary skip-by-size path will never re-fetch it. That is exactly the
    # blind spot --repair exists to cover.
    r = run("sb_backup.py", "--config", os.path.join(work, "sites-ext.json"),
            "--site", "AKUEB", "--only", "assets", "--no-commit")
    r2 = run("sb_backup.py", "--config", os.path.join(work, "sites-ext.json"),
             "--site", "AKUEB", "--only", "assets", "--verify-assets",
             "--no-commit")
    ck("a plain re-run does NOT heal same-size corruption (known blind spot)",
       "CHANGED" in r2.stdout, r2.stdout[-600:])

    r = run("sb_backup.py", "--config", os.path.join(work, "sites-ext.json"),
            "--site", "AKUEB", "--only", "assets", "--repair", "--no-commit")
    ck("--repair reports what it is re-fetching",
       "forcing re-fetch" in r.stdout, r.stdout[-700:])
    r = run("sb_backup.py", "--config", os.path.join(work, "sites-ext.json"),
            "--site", "AKUEB", "--only", "assets", "--verify-assets",
            "--no-commit")
    ck("--repair healed the corrupted and the deleted file",
       "missing 0" in r.stdout and "changed 0" in r.stdout, r.stdout[-700:])

    print("\n=== audit: proves the backup covers the live space ===")
    r = run("sb_backup.py", "--config", os.path.join(work, "sites-ext.json"),
            "--site", "AKUEB", "--audit")
    ck("audit passes on a complete backup",
       r.returncode == 0 and "AUDIT PASSED" in r.stdout,
       (r.stdout + r.stderr)[-1400:])
    ck("audit compares against the live space, not its own counts",
       "space" in r.stdout and "backup" in r.stdout, r.stdout[-500:])

    # An audit that cannot fail is worse than no audit. Delete a story file and
    # a blob, and it must notice both.
    victim = os.path.join(esb, "stories", "101.json")
    shutil.move(victim, victim + ".hidden")
    os.remove(os.path.join(bucket, "x", "cccc3333", "logo.svg"))
    r = run("sb_backup.py", "--config", os.path.join(work, "sites-ext.json"),
            "--site", "AKUEB", "--audit")
    ck("audit FAILS when a story file is missing",
       r.returncode != 0 and "AUDIT FAILED" in r.stdout,
       (r.stdout + r.stderr)[-1200:])
    ck("audit names the missing story", "101" in r.stdout, r.stdout[-900:])
    ck("audit notices the deleted blob",
       "no stored bytes" in r.stdout or "MISSING" in r.stdout,
       r.stdout[-900:])
    shutil.move(victim + ".hidden", victim)

    print("\n=== apps and extensions captured ===")
    ck("apps recorded as unavailable rather than skipped silently",
       "apps" in open(os.path.join(sb, "_summary.json"),
                      encoding="utf-8").read(), "")

    # ================================================== RESTORE in-place
    print("\n=== restore in-place ===")
    r = run("sb_restore.py", "--site", "AKU", "--mode", "in-place")
    ck("in-place refuses without --all or --story",
       r.returncode != 0 and "needs --all" in (r.stdout + r.stderr),
       (r.stdout + r.stderr)[-400:])

    r = run("sb_restore.py", "--site", "AKU", "--mode", "in-place", "--all")
    ck("dry run: space matches snapshot, nothing to write",
       r.returncode == 0 and "nothing to write" in r.stdout,
       r.stdout[-800:])

    # the space drifts: someone edits story 101
    STORIES["101"]["content"] = dict(STORY_101, title="EDITED IN THE SPACE")
    with LOCK:
        state["puts"].clear()

    r = run("sb_restore.py", "--site", "AKU", "--mode", "in-place", "--all")
    ck("dry run detects the drift",
       "differ 1" in r.stdout and "DRY RUN" in r.stdout, r.stdout[-900:])
    with LOCK:
        ck("dry run wrote nothing", not state["puts"], str(state["puts"])[:300])

    r = run("sb_restore.py", "--site", "AKU", "--mode", "in-place",
            "--story", "101", "--apply")
    with LOCK:
        puts = list(state["puts"])
    ck("--apply issued exactly one PUT", len(puts) == 1, str(puts)[:300])
    if puts:
        path, body = puts[0]
        ck("PUT targeted story 101", path.endswith("/stories/101"), path)
        ck("PUT restored the backed-up title",
           body["story"]["content"]["title"] == "First",
           str(body["story"]["content"])[:200])
        ck("PUT published, mirroring the snapshot", body.get("publish") == 1,
           str(body)[:200])
        ck("PUT did not touch slug or parent (no --with-structure)",
           "slug" not in body["story"] and "parent_id" not in body["story"],
           str(list(body["story"])))

    # a hard-deleted story cannot be restored in place, and must not be created
    del STORIES["102"]
    with LOCK:
        state["puts"].clear()
    r = run("sb_restore.py", "--site", "AKU", "--mode", "in-place", "--all",
            "--apply")
    ck("hard-deleted story reported, not recreated",
       "hard-deleted 1" in r.stdout, r.stdout[-900:])
    with LOCK:
        ck("no create attempted for the deleted story",
           all("/stories/102" in p or p.endswith("/stories/101")
               for p, _ in state["puts"]), str(state["puts"])[:300])
    STORIES["102"] = {"id": 102, "name": "B", "slug": "b",
                      "full_slug": "news/b", "parent_id": 10,
                      "uuid": "uuid-102", "published": False, "tag_list": [],
                      "content": {"component": "news_article",
                                  "title": "Second"}}

    # wrong-space guard
    other = dict(json.load(open(os.path.join(work, "sites.json"),
                                encoding="utf-8")))
    other["sites"][1] = dict(other["sites"][1], space_id="777")
    alt = os.path.join(work, "sites-wrong.json")
    json.dump(other, open(alt, "w", encoding="utf-8"))
    r = run("sb_restore.py", "--site", "AKU", "--config", alt,
            "--mode", "in-place", "--all", "--apply")
    ck("in-place refuses to write one space's backup into another",
       r.returncode != 0 and "in-place would write" in (r.stdout + r.stderr),
       (r.stdout + r.stderr)[-400:])

    # --from-rev reads history
    r = run("sb_restore.py", "--site", "AKU", "--mode", "in-place", "--all",
            "--from-rev", "HEAD")
    ck("--from-rev reads the snapshot from git",
       r.returncode == 0 and "commit HEAD" in r.stdout, r.stdout[-500:])

    # ===================== RESTORE assets (deleted image -> bucket -> space)
    # The operation this whole two-half design exists to make possible: an image
    # is deleted in Storyblok, the bytes are still in the bucket, and the stories
    # that used it must end up pointing at the re-uploaded copy.
    print("\n=== restore assets: bucket -> Storyblok, and repoint stories ===")
    with LOCK:
        state["created"].clear(); state["puts"].clear()

    r = run("sb_restore.py", "--config", os.path.join(work, "sites-ext.json"),
            "--site", "AKUEB", "--mode", "assets")
    ck("nothing to restore while every asset is present",
       r.returncode == 0 and "nothing to restore" in r.stdout,
       (r.stdout + r.stderr)[-700:])

    # delete the png from the SPACE (the bucket keeps the bytes)
    gone = [a for a in ASSETS if a["id"] == 9001]
    ASSETS[:] = [a for a in ASSETS if a["id"] != 9001]
    try:
        r = run("sb_restore.py", "--config",
                os.path.join(work, "sites-ext.json"), "--site", "AKUEB",
                "--mode", "assets")
        ck("dry run finds the asset deleted from the space",
           r.returncode == 0 and "9001" in r.stdout, r.stdout[-900:])
        ck("dry run says the bytes are in the bucket",
           "in bucket" in r.stdout, r.stdout[-900:])
        ck("dry run counts the stories that referenced it",
           "used by 1 story" in r.stdout, r.stdout[-900:])
        ck("dry run writes nothing", "DRY RUN" in r.stdout, r.stdout[-400:])
        with LOCK:
            ck("dry run really wrote nothing",
               not state["created"] and not state["puts"], "")

        r = run("sb_restore.py", "--config",
                os.path.join(work, "sites-ext.json"), "--site", "AKUEB",
                "--mode", "assets", "--apply")
        print((r.stdout + r.stderr)[-900:])
        ck("apply exits 0", r.returncode == 0, (r.stdout + r.stderr)[-700:])
        with LOCK:
            uploaded = list(state["created"].get("asset", []))
            puts = [(p, b) for p, b in state["puts"]
                    if f"/spaces/{SRC}/stories/" in p]
        ck("the file was uploaded back to the space", len(uploaded) == 1,
           str(uploaded)[:200])
        ck("uploaded into the same asset folder",
           uploaded and uploaded[0].get("asset_folder_id") == 70,
           str(uploaded)[:200])
        ck("exactly the one referencing story was rewritten", len(puts) == 1,
           str([p for p, _ in puts]))
        if puts:
            content = json.dumps(puts[0][1].get("story", {}).get("content", {}))
            ck("the old asset url is gone from that story",
               OLD_PNG_URL.replace("HOST", "") .split("/f/")[1] not in content
               or "/new/" in content, content[:300])
            ck("the story now points at the re-uploaded file",
               "/new/" in content, content[:300])
    finally:
        ASSETS.extend(gone)
        ASSETS.sort(key=lambda a: a["id"])

    # ================================================== RESTORE rebuild
    print("\n=== restore rebuild ===")
    r = run("sb_restore.py", "--site", "AKU", "--mode", "rebuild",
            "--into", SRC)
    ck("rebuild refuses to target the site's own space",
       r.returncode != 0 and "own space" in (r.stdout + r.stderr),
       (r.stdout + r.stderr)[-400:])

    with LOCK:
        state["created"].clear()
        state["puts"].clear()
        state["target_stories"].clear()
    r = run("sb_restore.py", "--site", "AKU", "--mode", "rebuild",
            "--into", TGT)
    ck("rebuild dry run reports the plan",
       r.returncode == 0 and "DRY RUN" in r.stdout, r.stdout[-800:])
    with LOCK:
        ck("rebuild dry run created nothing", not state["created"],
           str(list(state["created"]))[:200])

    r = run("sb_restore.py", "--site", "AKU", "--mode", "rebuild",
            "--into", TGT, "--apply")
    print((r.stdout + r.stderr)[-2000:])
    ck("rebuild exit 0", r.returncode == 0, (r.stdout + r.stderr)[-800:])
    with LOCK:
        created = {k: list(v) for k, v in state["created"].items()}

    ck("component group created", len(created.get("component_group", [])) == 1,
       str(created.get("component_group")))
    ck("both components created", len(created.get("component", [])) == 2,
       str([c.get("name") for c in created.get("component", [])]))
    ck("component group uuid remapped to the new one",
       any(c.get("component_group_uuid", "").startswith("new-")
           for c in created.get("component", [])
           if c.get("component_group_uuid")),
       str([c.get("component_group_uuid")
            for c in created.get("component", [])]))
    ck("asset folders created parent-first",
       len(created.get("asset_folder", [])) == 2
       and created["asset_folder"][0]["name"] == "photos",
       str(created.get("asset_folder")))
    ck("datasource and entry created",
       len(created.get("datasource", [])) == 1
       and len(created.get("datasource_entry", [])) == 1,
       str(created.get("datasource_entry")))

    made = created.get("story", [])
    folders = [s for s in made if s.get("is_folder")]
    leaves = [s for s in made if not s.get("is_folder")]
    ck("story folder created", len(folders) == 1, str(folders)[:200])
    ck("both stories created", len(leaves) == 2, str(len(leaves)))

    a = next((s for s in leaves if s["content"].get("title") == "First"), None)
    ck("story 101 was created", a is not None, str(leaves)[:300])
    if a:
        c = a["content"]
        dumped = json.dumps(c)
        ck("no old asset url survives anywhere in content",
           "/f/555/" not in dumped, dumped[:400])
        ck("asset object url remapped",
           "/f/999/" in c["hero"]["filename"], str(c["hero"]))
        ck("asset object id remapped",
           c["hero"]["id"] != 9001 and isinstance(c["hero"]["id"], int),
           str(c["hero"]))
        img = c["body"]["content"][0]["attrs"]
        ck("rich-text image src remapped", "/f/999/" in img["src"], str(img))
        ck("rich-text image id remapped", img["id"] != 9001, str(img))
        prose = c["body"]["content"][1]["content"][0]["text"]
        ck("url inside prose remapped", "/f/999/" in prose, prose)
        # At create time the target of the link does not exist yet, so the link
        # is still the old uuid here. Pass 9 is what fixes it -- assert on the
        # relink PUT, which is the state the space ends up in.
        ck("link still unremapped at create time (pass 9's job)",
           c["link"]["id"] == "uuid-102", str(c["link"]))

    with LOCK:
        relinks = [(p, b) for p, b in state["puts"]
                   if f"/spaces/{TGT}/stories/" in p]
    ck("relink pass ran for the changed uuids", len(relinks) >= 1,
       str(state["puts"])[:300])
    ck("relink PUT points the link at the new uuid",
       any(b.get("story", {}).get("content", {})
            .get("link", {}).get("id", "").startswith("new-")
           for _, b in relinks),
       str([b.get("story", {}).get("content", {}).get("link")
            for _, b in relinks])[:300])
    ck("relink PUT kept the remapped asset urls",
       all("/f/555/" not in json.dumps(b.get("story", {}).get("content", {}))
           for _, b in relinks),
       str(relinks)[:300])
    ck("only the story with an internal link was re-PUT (no redundant writes)",
       len(relinks) == 1, f"{len(relinks)} PUTs: "
                          f"{[p for p, _ in relinks]}")

    ck("id maps written",
       any(f.startswith("rebuild-") for f in os.listdir(
           os.path.join(repos["AKU"], "restore_maps"))),
       str(os.listdir(os.path.join(repos["AKU"], "restore_maps"))))

    with LOCK:
        state["target_stories"] = [{"id": 1}]
    r = run("sb_restore.py", "--site", "AKU", "--mode", "rebuild",
            "--into", TGT)
    ck("rebuild refuses a non-empty target",
       r.returncode != 0 and "already holds" in (r.stdout + r.stderr),
       (r.stdout + r.stderr)[-400:])

    srv.shutdown()
    print(f"\n{'=' * 70}")
    print("ALL PASSED" if not fails
          else f"{len(fails)} FAILURE(S):\n  " + "\n  ".join(fails))
    print(f"scratch: {tmp}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
