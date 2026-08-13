#!/usr/bin/env python3
"""
sb_storage.py — where asset binaries are kept. Imported, never run.

Two backends behind one interface:

    local    a folder, a mounted bucket, a UNC share
    azure    Azure Blob Storage, straight from Storyblok to the container

The three spaces hold ~42 GB of media against GitHub's 1 GB of large-file
storage, so the bytes live here and the repo keeps the index: every file's
relative path and sha256 in manifest_assets.csv. That split only works if the
halves can be proved to match, which is what sha256() and the audit are for.

Configured per site in config/sites.json:

    "assets": {"backend": "azure",
               "connection_string": "...",   or AZURE_STORAGE_CONNECTION_STRING
               "container": "storyblok-backup",
               "prefix": "AKUH"}

    "assets_dir": "D:/path/or/mount"         the local backend, shorthand
"""

import hashlib
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sb_common import sha256_file

CHUNK = 1 << 16


# --------------------------------------------------------------------------

def _hash_and_spool(chunks, expected=None):
    """Write an HTTP chunk stream to a temp file, hashing in one pass.

    Deliberately not piping the socket straight into the upload. The Azure SDK
    may retry a block, and a hash taken over a non-seekable stream that gets
    re-read is silently wrong -- which is the one failure this whole design
    exists to detect. Spooling one file at a time costs a few hundred megabytes
    of scratch at worst and keeps the checksum trustworthy; nothing is staged
    for the whole 42 GB.
    """
    h = hashlib.sha256()
    size = 0
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".sbpart")
    try:
        with tmp:
            for chunk in chunks:
                if chunk:
                    tmp.write(chunk)
                    h.update(chunk)
                    size += len(chunk)
    except BaseException:
        os.unlink(tmp.name)
        raise
    if expected and size != expected:
        os.unlink(tmp.name)
        raise OSError(f"truncated download: got {size} bytes, expected {expected}")
    return tmp.name, h.hexdigest(), size


class LocalBackend:
    """A folder. Also covers a mounted bucket or a network share."""

    external = True          # set False by the caller when it is inside the repo

    def __init__(self, root, external=True):
        self.root = root
        self.external = external
        self.label = root

    def _p(self, rel):
        return os.path.join(self.root, rel.replace("/", os.sep))

    def size(self, rel):
        p = self._p(rel)
        return os.path.getsize(p) if os.path.exists(p) else None

    def write(self, rel, chunks, content_type=None, expected=None):
        tmp, digest, size = _hash_and_spool(chunks, expected)
        dest = self._p(rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(tmp, dest)      # atomic-ish; never a half file at `dest`
        return digest, size

    def sha256(self, rel):
        p = self._p(rel)
        # One implementation, in sb_common, so the audit and the backup can
        # never disagree about what a file's checksum is.
        return sha256_file(p) if os.path.exists(p) else None

    def download_to(self, rel, dest):
        p = self._p(rel)
        if not os.path.exists(p):
            return None
        if os.path.abspath(p) != os.path.abspath(dest):
            shutil.copyfile(p, dest)
        return dest

    def list_all(self):
        """{rel: size} for everything stored, in one pass. See AzureBackend."""
        out = {}
        for dirpath, _, files in os.walk(self.root):
            for fn in files:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, self.root).replace(os.sep, "/")
                out[rel] = os.path.getsize(full)
        return out

    def ensure(self):
        os.makedirs(self.root, exist_ok=True)


class AzureBackend:
    """Azure Blob Storage.

    One blob per asset, keyed by the same mirrored path the manifest records, so
    a blob can be found from manifest_assets.csv alone.
    """

    external = True

    def __init__(self, conn, container, prefix="", tier="Cool"):
        try:
            from azure.storage.blob import BlobServiceClient
        except ImportError:
            sys.exit("pip install azure-storage-blob")
        self._svc = BlobServiceClient.from_connection_string(conn)
        self.container = container
        self.prefix = (prefix or "").strip("/")
        # Cool by default, because this is write-once-read-almost-never data and
        # it stores at roughly half the price of Hot. NOT Archive: that is
        # cheaper again but needs hours of rehydration before a file can be
        # read, and a backup you cannot read for hours is not a backup you can
        # restore from during an incident.
        #
        # Resolved to the enum here, once. upload_blob does `tier.value`
        # internally, so handing it the plain string from the config raises
        # AttributeError on every single file -- which looks like a credentials
        # or network problem and is neither.
        self.tier = self._resolve_tier(tier)
        self._cc = self._svc.get_container_client(container)
        self.label = (f"azure://{self._svc.account_name}/{container}"
                      + (f"/{self.prefix}" if self.prefix else ""))

    @staticmethod
    def _resolve_tier(tier):
        """"Cool" -> StandardBlobTier.Cool, refusing anything unrecognised."""
        if not tier:
            return None
        from azure.storage.blob import StandardBlobTier
        if not isinstance(tier, str):
            return tier
        for candidate in StandardBlobTier:
            if candidate.value.lower() == tier.strip().lower():
                if candidate.value.lower() == "archive":
                    print("    !! tier Archive: files need hours of rehydration "
                          "before they can be read. A restore will not be quick.")
                return candidate
        sys.exit(f"unknown Azure blob tier {tier!r} - one of "
                 f"{', '.join(t.value for t in StandardBlobTier)}")

    def _name(self, rel):
        rel = rel.replace(os.sep, "/").lstrip("/")
        return f"{self.prefix}/{rel}" if self.prefix else rel

    def ensure(self):
        from azure.core.exceptions import ResourceExistsError
        try:
            self._cc.create_container()
            print(f"    created container {self.container}")
        except ResourceExistsError:
            pass

    def size(self, rel):
        from azure.core.exceptions import ResourceNotFoundError
        try:
            return self._cc.get_blob_client(self._name(rel)) \
                .get_blob_properties().size
        except ResourceNotFoundError:
            return None

    def list_all(self):
        """{rel: size} for every blob under the prefix, in one paged listing.

        Exists because asking per file does not scale: building the manifest with
        one get_blob_properties() per asset is 5,767 sequential round-trips for
        AKUH and 16,334 for AKUEB, which turns a finished upload into a run that
        looks hung for half an hour. One listing returns 5,000 at a time.

        Zero-byte directory placeholders are dropped -- this account has
        hierarchical namespace enabled, so the listing includes an entry for
        every folder, and those are not files.
        """
        out = {}
        pre = f"{self.prefix}/" if self.prefix else ""
        for b in self._cc.list_blobs(name_starts_with=pre):
            if not b.size:
                continue
            out[b.name[len(pre):] if pre else b.name] = b.size
        return out

    def write(self, rel, chunks, content_type=None, expected=None):
        from azure.core.exceptions import AzureError, ServiceRequestError, ServiceResponseError
        from azure.storage.blob import ContentSettings
        tmp, digest, size = _hash_and_spool(chunks, expected)
        try:
            settings = ContentSettings(content_type=content_type) \
                if content_type else None
            # Retried, because a several-hundred-megabyte video upload times out
            # on a slow link often enough to matter -- two of AKUH's did. The
            # retry is nearly free: the bytes are already spooled to `tmp`, so
            # only the upload repeats, never the download. Seek back to the start
            # or the second attempt sends nothing.
            last = None
            for attempt in range(3):
                try:
                    with open(tmp, "rb") as f:
                        self._cc.get_blob_client(self._name(rel)).upload_blob(
                            f, overwrite=True, content_settings=settings,
                            max_concurrency=4, standard_blob_tier=self.tier,
                            connection_timeout=600,
                            # The sha256 is ours and lives in the manifest; this
                            # puts it on the blob too, so the container can be
                            # audited from metadata alone. Reading 31 GB back out
                            # of Azure would cost egress every time.
                            metadata={"sha256": digest})
                    return digest, size
                except (ServiceResponseError, ServiceRequestError,
                        AzureError) as e:
                    last = e
                    time.sleep(2 * (attempt + 1))
            raise last
        finally:
            os.unlink(tmp)

    def sha256(self, rel):
        from azure.core.exceptions import ResourceNotFoundError
        bc = self._cc.get_blob_client(self._name(rel))
        try:
            h = hashlib.sha256()
            stream = bc.download_blob(max_concurrency=2)
            for chunk in stream.chunks():
                h.update(chunk)
            return h.hexdigest()
        except ResourceNotFoundError:
            return None

    def stored_sha256(self, rel):
        """The checksum recorded on the blob at upload time, if any.

        Cheaper than re-reading 31 GB out of the container: a metadata read is
        one small request. It proves what we uploaded, not what is there now, so
        the full sha256() re-read is still the real integrity check.
        """
        from azure.core.exceptions import ResourceNotFoundError
        try:
            p = self._cc.get_blob_client(self._name(rel)).get_blob_properties()
            return (p.metadata or {}).get("sha256")
        except ResourceNotFoundError:
            return None

    def download_to(self, rel, dest):
        from azure.core.exceptions import ResourceNotFoundError
        try:
            with open(dest, "wb") as f:
                self._cc.get_blob_client(self._name(rel)) \
                    .download_blob(max_concurrency=2).readinto(f)
            return dest
        except ResourceNotFoundError:
            if os.path.exists(dest):
                os.unlink(dest)
            return None


# --------------------------------------------------------------------------

def make_backend(site, outdir, cli_dir=None):
    """Build the backend for a site. Returns (backend, external).

    Precedence: --assets-dir on the command line, then an "assets" block, then
    "assets_dir", then the repo itself.
    """
    if cli_dir:
        return LocalBackend(_abspath(cli_dir)), True

    spec = site.get("assets") or {}
    backend = (spec.get("backend") or "").lower()

    if backend == "azure":
        conn = (spec.get("connection_string")
                or os.environ.get("AZURE_STORAGE_CONNECTION_STRING"))
        if not conn or "YOUR_" in conn:
            sys.exit(f"{site['name']}: assets.backend is azure but no "
                     f"connection_string, and AZURE_STORAGE_CONNECTION_STRING "
                     f"is not set")
        if not spec.get("container"):
            sys.exit(f"{site['name']}: assets.backend is azure but no container")
        return AzureBackend(conn, spec["container"],
                            spec.get("prefix", site["name"]),
                            spec.get("tier", "Cool")), True

    if backend and backend != "local":
        sys.exit(f"{site['name']}: unknown assets backend {backend!r} "
                 f"(local, azure)")

    d = spec.get("dir") or site.get("assets_dir")
    if d:
        return LocalBackend(_abspath(d)), True

    # Nothing configured: binaries are committed into the repo, via Git LFS.
    return LocalBackend(os.path.join(outdir, "assets"), external=False), False


def _abspath(d):
    return os.path.abspath(os.path.expanduser(os.path.expandvars(d)))
