from json import dump, load
from os.path import abspath, dirname, join
import mimetypes
import sys

SCRIPTS_DIR = abspath(dirname(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from storyblok_config import load_config
from storyblok_utils import absolute_sharepoint_url

try:
    import requests
except ImportError:
    requests = None


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return load(f)


def upload_asset(session, api_base, space_id, asset, base_url, dry_run=True):
    absolute_url = asset["sharepoint_absolute_url"]
    filename = asset["filename"]

    if dry_run or not requests:
        return {
            **asset,
            "upload_status": "dry_run",
            "storyblok_url": absolute_url,
        }

    response = session.get(absolute_url, timeout=60)
    response.raise_for_status()

    sign_response = session.post(
        f"{api_base}/spaces/{space_id}/assets/",
        data={"filename": filename},
        timeout=60,
    )
    sign_response.raise_for_status()
    signed = sign_response.json()

    fields = signed.get("fields") or {}
    post_url = signed.get("post_url")
    asset_data = signed.get("asset") or signed

    files = {"file": (filename, response.content, mimetypes.guess_type(filename)[0] or "application/octet-stream")}
    post_fields = {key: value for key, value in fields.items()}
    upload_response = requests.post(post_url, data=post_fields, files=files, timeout=120)
    upload_response.raise_for_status()

    asset_id = asset_data.get("id")
    finalize_response = session.get(
        f"{api_base}/spaces/{space_id}/assets/{asset_id}/finish_upload",
        timeout=60,
    )
    finalize_response.raise_for_status()
    finalized = finalize_response.json()

    return {
        **asset,
        "upload_status": "uploaded",
        "storyblok_asset_id": finalized.get("id") or asset_id,
        "storyblok_filename": finalized.get("filename") or filename,
        "storyblok_url": finalized.get("filename") and f"https://a.storyblok.com/{finalized['filename']}",
    }


def upload_assets(catalog_path, asset_map_path, config):
    catalog = load_json(catalog_path)
    assets = catalog.get("assets") or []
    config = config or load_config()

    if not config.get("upload_assets"):
        print("Asset upload skipped (upload_assets=false in config).")
        return catalog, {item["sharepoint_src"]: item for item in assets}

    if not requests:
        raise RuntimeError("requests is required for asset upload. Install with: pip install requests")

    if not config.get("space_id") or not config.get("management_token"):
        raise RuntimeError("Storyblok space_id and management_token are required for asset upload.")

    from storyblok_config import management_api_base

    api_base = management_api_base(config)
    session = requests.Session()
    session.headers.update({"Authorization": config["management_token"]})

    updated_assets = []
    asset_map = {}
    for asset in assets:
        if not asset["sharepoint_src"].startswith("/"):
            updated = {**asset, "upload_status": "external_skipped"}
        else:
            updated = upload_asset(
                session,
                api_base,
                config["space_id"],
                asset,
                config["sharepoint_base_url"],
                dry_run=config.get("dry_run", True),
            )
        updated_assets.append(updated)
        asset_map[updated["sharepoint_src"]] = {
            "storyblok_asset_id": updated.get("storyblok_asset_id"),
            "storyblok_url": updated.get("storyblok_url") or absolute_sharepoint_url(
                updated["sharepoint_src"], config["sharepoint_base_url"]
            ),
            "upload_status": updated.get("upload_status"),
        }

    catalog["assets"] = updated_assets
    catalog["summary"]["uploaded_assets"] = sum(
        1 for item in updated_assets if item.get("upload_status") == "uploaded"
    )
    return catalog, asset_map


if __name__ == "__main__":
    base_path = abspath(join(dirname(__file__), ".."))
    catalog_path = join(base_path, "data", "storyblok_asset_catalog.json")
    asset_map_path = join(base_path, "data", "storyblok_asset_map.json")

    config = load_config()
    catalog, asset_map = upload_assets(catalog_path, asset_map_path, config)

    with open(catalog_path, "w", encoding="utf-8") as f:
        dump(catalog, f, indent=2, ensure_ascii=False)
    with open(asset_map_path, "w", encoding="utf-8") as f:
        dump(asset_map, f, indent=2, ensure_ascii=False)

    print("Storyblok asset upload")
    print("=" * 72)
    print(f"Unique assets: {catalog['summary']['unique_assets']:,}")
    print(f"Uploaded assets: {catalog['summary'].get('uploaded_assets', 0):,}")
    print(f"Catalog updated at {catalog_path}")
    print(f"Asset map updated at {asset_map_path}")
