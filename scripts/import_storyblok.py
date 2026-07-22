from json import dump, load
from os import listdir
from os.path import abspath, dirname, join
import sys
import time

SCRIPTS_DIR = abspath(dirname(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from storyblok_config import load_config, management_api_base

try:
    import requests
except ImportError:
    requests = None


def load_json(path):
    with open(path, "r") as f:
        return load(f)


def story_payload_for_api(story):
    return {
        "story": {
            "name": story["name"],
            "slug": story["slug"],
            "parent_id": story.get("parent_id", 0),
            "is_startpage": story.get("is_startpage", False),
            "tag_list": story.get("tag_list") or [],
            "content": story["content"],
        }
    }


def import_story(session, api_base, space_id, story, dry_run=True):
    payload = story_payload_for_api(story)
    if dry_run:
        return {"status": "dry_run", "slug": story["slug"]}

    response = session.post(
        f"{api_base}/spaces/{space_id}/stories/",
        json=payload,
        timeout=60,
    )
    if response.status_code == 422 and "already taken" in response.text.lower():
        lookup = session.get(
            f"{api_base}/spaces/{space_id}/stories/",
            params={"with_slug": story["slug"]},
            timeout=60,
        )
        lookup.raise_for_status()
        existing = lookup.json().get("stories") or []
        if not existing:
            response.raise_for_status()
        story_id = existing[0]["id"]
        update_response = session.put(
            f"{api_base}/spaces/{space_id}/stories/{story_id}",
            json=payload,
            timeout=60,
        )
        update_response.raise_for_status()
        return {"status": "updated", "slug": story["slug"], "story_id": story_id}

    response.raise_for_status()
    created = response.json().get("story") or {}
    return {
        "status": "created",
        "slug": story["slug"],
        "story_id": created.get("id"),
    }


def import_stories(stories_folder, config, limit=None, sleep_seconds=0.2):
    config = config or load_config()
    dry_run = config.get("dry_run", True)

    if not dry_run:
        if not requests:
            raise RuntimeError("requests is required for Storyblok import. Install with: pip install requests")
        if not config.get("space_id") or not config.get("management_token"):
            raise RuntimeError("Storyblok space_id and management_token are required for import.")

    session = None
    api_base = management_api_base(config)
    if not dry_run:
        session = requests.Session()
        session.headers.update(
            {
                "Authorization": config["management_token"],
                "Content-Type": "application/json",
            }
        )

    json_files = sorted(
        filename for filename in listdir(stories_folder) if filename.endswith(".json")
    )
    if limit:
        json_files = json_files[:limit]

    results = []
    for filename in json_files:
        with open(join(stories_folder, filename), "r") as f:
            story = load(f)
        result = import_story(
            session,
            api_base,
            config.get("space_id"),
            story,
            dry_run=dry_run,
        )
        result["file"] = filename
        results.append(result)
        if sleep_seconds and not dry_run:
            time.sleep(sleep_seconds)

    status_counts = {}
    for result in results:
        status_counts[result["status"]] = status_counts.get(result["status"], 0) + 1

    return {
        "summary": {
            "files_processed": len(results),
            "dry_run": config.get("dry_run", True),
            "status_counts": status_counts,
        },
        "results": results,
    }


if __name__ == "__main__":
    base_path = abspath(join(dirname(__file__), ".."))
    stories_folder = join(base_path, "data", "storyblok_stories")
    report_path = join(base_path, "data", "storyblok_import_report.json")

    config = load_config()
    report = import_stories(stories_folder, config)

    with open(report_path, "w") as f:
        dump(report, f, indent=2, ensure_ascii=False)

    summary = report["summary"]
    print("Storyblok import")
    print("=" * 72)
    print(f"Files processed: {summary['files_processed']:,}")
    print(f"Dry run: {summary['dry_run']}")
    print(f"Status counts: {summary['status_counts']}")
    print(f"Report exported to {report_path}")
