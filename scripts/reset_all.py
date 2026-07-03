#!/usr/bin/env python3
"""Reset all Sparki data: local DB, local images, and GCS bucket.

CAUTION: This deletes data irreversibly.

Usage:
    python scripts/reset_all.py           # interactive (asks confirmation)
    python scripts/reset_all.py --force   # skip confirmation
    python scripts/reset_all.py --keep-gcs  # skip GCS deletion
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "veo_prompts.db"
LOCAL_IMAGES_DIR = PROJECT_ROOT / "outputs" / "images"
GCS_BUCKET = "sparki-op-test"


def _confirm(prompt: str) -> bool:
    print(f"\n⚠️  {prompt}")
    reply = input("Type 'yes' to confirm: ").strip().lower()
    return reply == "yes"


def _reset_db() -> bool:
    import sqlite3

    if not DB_PATH.exists():
        print("  [DB] No database file found — skipping")
        return True

    if not _confirm(f"Delete database file {DB_PATH}?"):
        print("  [DB] Skipped.")
        return False

    # Re-init schema (delete and recreate)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("SELECT 1")  # verify can connect

    # Delete and recreate via init_db
    conn.close()

    import os
    os.remove(DB_PATH)
    print(f"  [DB] Deleted {DB_PATH}")

    # Re-init empty DB
    from src.memory.schema import init_db
    init_db()
    print("  [DB] Re-initialized empty schema.")
    return True


def _reset_local_images() -> bool:
    if not LOCAL_IMAGES_DIR.exists():
        print("  [images] No local images directory — skipping")
        return True

    if not _confirm(f"Delete all files in {LOCAL_IMAGES_DIR}?"):
        print("  [images] Skipped.")
        return False

    import shutil
    shutil.rmtree(LOCAL_IMAGES_DIR)
    print(f"  [images] Deleted {LOCAL_IMAGES_DIR}")
    return True


def _reset_gcs() -> bool:
    if not _confirm(f"Delete ALL blobs in gs://{GCS_BUCKET}/prompts/?"):
        print("  [GCS] Skipped.")
        return False

    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET)

    blobs = list(bucket.list_blobs(prefix="prompts/"))
    if not blobs:
        print("  [GCS] No blobs found — skipping")
        return True

    print(f"  [GCS] Deleting {len(blobs)} blobs...")
    for blob in blobs:
        blob.delete()
    print(f"  [GCS] Deleted {len(blobs)} blobs.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset all Sparki data")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompts")
    parser.add_argument("--keep-gcs", action="store_true", help="Skip GCS deletion")
    args = parser.parse_args()

    print("=" * 60)
    print("SParki Data Reset")
    print("=" * 60)
    print(f"DB:          {DB_PATH}")
    print(f"Local images: {LOCAL_IMAGES_DIR}")
    print(f"GCS bucket:  gs://{GCS_BUCKET}/prompts/")
    print("=" * 60)

    if not args.force:
        if not _confirm("Delete ALL of the above?"):
            print("Aborted.")
            return

    print()

    db_ok = _reset_db()
    img_ok = _reset_local_images()
    gcs_ok = True
    if not args.keep_gcs:
        gcs_ok = _reset_gcs()

    print()
    print("=== Reset Summary ===")
    print(f"  DB:          {'✓ deleted' if db_ok else '✗ skipped'}")
    print(f"  Local images: {'✓ deleted' if img_ok else '✗ skipped'}")
    print(f"  GCS blobs:   {'✓ deleted' if gcs_ok else '✗ skipped'}")
    print("=====================")


if __name__ == "__main__":
    main()