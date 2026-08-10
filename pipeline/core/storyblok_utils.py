import os as _os
import re
import sys as _sys
import uuid

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import _bootstrap

_bootstrap.ensure()


def slugify(text, fallback="item"):
    if not text:
        return fallback
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or fallback


def generate_uid(seed=None):
    if seed is None:
        return str(uuid.uuid4()).replace("-", "")[:16]
    return str(uuid.uuid5(uuid.NAMESPACE_OID, str(seed))).replace("-", "")[:16]


def story_uuid(sharepoint_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"aku-news:{sharepoint_id}"))


def normalize_sequence_number(value):
    if not value:
        return None
    return str(value).strip().upper()


def absolute_sharepoint_url(path, base_url="https://www.aku.edu"):
    if not path:
        return path
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base_url.rstrip('/')}{path}"
