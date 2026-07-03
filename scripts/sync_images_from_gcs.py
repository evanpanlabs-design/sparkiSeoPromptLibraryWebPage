#!/usr/bin/env python3
"""Download generated images from GCS to local filesystem.

GCS path:  gs://sparki-op-test/prompts/{prompt_id}.png
Local path: outputs/images/{category}/{yyyy-mm}/{prompt_id}.png

Usage:
    python scripts/sync_images_from_gcs.py           # sync all
    python scripts/sync_images_from_gcs.py --limit 10  # first 10 only (dry-run preview)
    python scripts/sync_images_from_gcs.py --dry-run    # preview what would be downloaded
"""

from __future__ import annotations

import argparse
import re
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LOCAL_OUTPUT = PROJECT_ROOT / "outputs" / "images"


def _get_gcs_blobs():
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket("sparki-op-test")
    return list(bucket.list_blobs(prefix="prompts/"))


def _sync_db_info():
    """Fetch id -> (tweet_id, category, title) from local DB."""
    import sqlite3

    conn = sqlite3.connect(PROJECT_ROOT / "data" / "veo_prompts.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, tweet_id, category, title FROM prompts WHERE image_status = 'done'"
    ).fetchall()
    # Key by id (int) since GCS blob uses DB id
    return {r["id"]: (str(r["tweet_id"]), r["category"], r["title"]) for r in rows}


def download_all(dry_run: bool = False, limit: int | None = None) -> dict:
    blobs = _get_gcs_blobs()
    db_info = _sync_db_info()

    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket("sparki-op-test")

    downloaded = 0
    skipped = 0
    errors = 0

    for blob in blobs:
        name = blob.name  # e.g. "prompts/cinematic-scene/2026-05/123456789.png"
        if not name.endswith(".png"):
            continue

        # Parse: prompts/{category...}/{yyyy-mm}/{id}.png
        # category may contain '/' (e.g. "Action/Suspense" → 5 path segments)
        # minimum structure: prompts/{cat_min}/2026-05/{id}.png (4 segments)
        parts = name.split("/")
        if len(parts) < 4 or not parts[-1].endswith(".png"):
            continue

        # last segment must be {db_id}.png; second-to-last must be yyyy-mm
        try:
            db_id = int(parts[-1][:-4])  # "1" → 1 (DB primary key)
        except ValueError:
            continue

        yyyy_mm = parts[-2]            # "2026-05"
        if not (len(yyyy_mm) == 7 and yyyy_mm[4] == '-' and yyyy_mm[:4].isdigit()):
            # not a real date-looking segment, skip
            continue

        category = "/".join(parts[1:-2])  # "cinematic-scene" or "Action/Suspense"

        # Look up tweet_id and title from DB by db_id
        if db_id in db_info:
            tweet_id, cat_from_db, title = db_info[db_id]
        else:
            tweet_id = str(db_id)
            cat_from_db = category
            title = str(db_id)

        # Build local path: outputs/images/{category}/{yyyy-mm}/{tweet_id}.png
        safe_cat = re.sub(r'[<>:"/\\|?*]', '_', cat_from_db)
        local_dir = LOCAL_OUTPUT / safe_cat / yyyy_mm
        local_path = local_dir / f"{tweet_id}.png"

        if dry_run:
            print(f"[DRY-RUN] Would download: gs://sparki-op-test/{name}")
            print(f"         → {local_path}")
            downloaded += 1
            if limit and downloaded >= limit:
                break
            continue

        # Ensure directory exists
        local_dir.mkdir(parents=True, exist_ok=True)

        # Download if not exists or size mismatch
        should_download = True
        if local_path.exists() and local_path.stat().st_size == blob.size:
            should_download = False
            skipped += 1
        else:
            try:
                with open(local_path, "wb") as f:
                    blob.download_to_file(f)
                downloaded += 1
            except Exception as e:
                print(f"ERROR downloading {name}: {e}")
                errors += 1
                continue

        if limit and (downloaded + skipped) >= limit:
            break

        if (downloaded + skipped) % 20 == 0:
            print(f"  Progress: {downloaded} downloaded, {skipped} skipped")

    return {
        "downloaded": downloaded,
        "skipped": skipped,
        "errors": errors,
        "total_gcs_blobs": len(blobs),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync images from GCS to local outputs/")
    parser.add_argument("--dry-run", action="store_true", help="Preview without downloading")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of files to process")
    args = parser.parse_args()

    print(f"Syncing images from gs://sparki-op-test/prompts/")
    print(f"Local destination: {LOCAL_OUTPUT}")
    if args.dry_run:
        print("[DRY-RUN MODE]")
    print()

    stats = download_all(dry_run=args.dry_run, limit=args.limit)

    print()
    print("=== Sync Results ===")
    print(f"  GCS total blobs:   {stats['total_gcs_blobs']}")
    print(f"  Downloaded:        {stats['downloaded']}")
    print(f"  Skipped (exists):  {stats['skipped']}")
    print(f"  Errors:            {stats['errors']}")
    print(f"  Local output:      {LOCAL_OUTPUT}")
    print("=====================")


if __name__ == "__main__":
    main()