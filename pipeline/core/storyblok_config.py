from json import load
from os import environ
from os.path import abspath, dirname, exists, join

import os as _os, sys as _sys

import os as _os, sys as _sys  # noqa: E402
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import _bootstrap  # noqa: F401,E402  -- every pipeline folder on sys.path
from paths_root import P as _P

DEFAULT_CONFIG_PATH = abspath(join(dirname(__file__), "..", "config", "storyblok.json"))
EXAMPLE_CONFIG_PATH = abspath(join(dirname(__file__), "..", "config", "storyblok.example.json"))


def load_config(config_path=None):
    path = config_path or environ.get("STORYBLOK_CONFIG") or DEFAULT_CONFIG_PATH
    file_config = {}
    if exists(path):
        with open(path, "r", encoding="utf-8") as f:
            file_config = load(f)

    return {
        "space_id": environ.get("STORYBLOK_SPACE_ID") or file_config.get("space_id"),
        "management_token": environ.get("STORYBLOK_MANAGEMENT_TOKEN")
        or file_config.get("management_token"),
        "region": environ.get("STORYBLOK_REGION") or file_config.get("region", "eu"),
        "sharepoint_base_url": file_config.get(
            "sharepoint_base_url", "https://www.aku.edu"
        ),
        # Named news_* for the config keys AKU already has on disk; the
        # default now follows the selected content type.
        "news_story_prefix": file_config.get("news_story_prefix",
                                             _P.story_prefix),
        "news_component": file_config.get("news_component", _P.component),
        "video_embed_component": file_config.get("video_embed_component", "video_embed"),
        "twitter_embed_component": file_config.get(
            "twitter_embed_component", "twitter_embed"
        ),
        "iframe_embed_component": file_config.get(
            "iframe_embed_component", "iframe_embed"
        ),
        "parent_folder_id": file_config.get("parent_folder_id", 0),
        "dry_run": _as_bool(environ.get("STORYBLOK_DRY_RUN"), file_config.get("dry_run", True)),
        "upload_assets": _as_bool(
            environ.get("STORYBLOK_UPLOAD_ASSETS"), file_config.get("upload_assets", False)
        ),
    }


def _as_bool(env_value, default):
    if env_value is None:
        return bool(default)
    return str(env_value).strip().lower() in {"1", "true", "yes", "on"}


def management_api_base(config):
    region = (config.get("region") or "eu").lower()
    if region == "us":
        return "https://api-us.storyblok.com/v1"
    if region == "cn":
        return "https://api-cn.storyblok.com/v1"
    if region == "ap":
        return "https://api-ap.storyblok.com/v1"
    return "https://mapi.storyblok.com/v1"
