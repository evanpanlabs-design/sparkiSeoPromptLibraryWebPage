#!/usr/bin/env python3
"""Master pipeline run: crawl → filter → import → generate → sync.

Usage:
    python scripts/run_master.py              # interactive step-by-step
    python scripts/run_master.py --from-cache  # skip crawl, use last_crawl.json
    python scripts/run_master.py --dry-run     # show what would happen
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Helpers ────────────────────────────────────────────────────────────────────


def run(cmd: list[str], label: str) -> bool:
    print(f"\n{'=' * 60}")
    print(f"STEP: {label}")
    print(f"CMD:  {' '.join(cmd)}")
    print("=" * 60)
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    ok = result.returncode == 0
    print(f"[{'✓' if ok else '✗'}] {label} {'succeeded' if ok else 'FAILED'}")
    return ok


def confirm_step(label: str, skip: bool = False) -> bool:
    if skip:
        print(f"[SKIP] {label}")
        return True
    print(f"\n--- {label} ---")
    reply = input("Proceed with this step? [Y/n]: ").strip().lower()
    return reply != "n"


# ── Steps ─────────────────────────────────────────────────────────────────────


def step_crawl(from_cache: bool = False, dry_run: bool = False) -> bool:
    if from_cache:
        print("[SKIP] Crawl step — using outputs/last_crawl.json")
        return True
    if dry_run:
        print("[DRY-RUN] Would run: python -m src.main run")
        return True
    return run(
        [sys.executable, "-m", "src.main", "run", "--from-cache"],
        "Crawl (Apify)",
    )


def step_filter(dry_run: bool = False) -> bool:
    """Run import_v2_data.py with dry-run to check how many pass filters."""
    if dry_run:
        result = subprocess.run(
            [sys.executable, "scripts/import_v2_data.py", "--dry-run"],
            cwd=PROJECT_ROOT,
            capture_output=True,
        )
        print(result.stdout.decode("utf-8", errors="replace"))
        return result.returncode == 0
    return run(
        [sys.executable, "scripts/import_v2_data.py", "--dry-run"],
        "Filter preview (dry-run)",
    )


def step_import(dry_run: bool = False) -> bool:
    if dry_run:
        print("[DRY-RUN] Skipping actual import")
        return True
    return run(
        [sys.executable, "scripts/import_v2_data.py"],
        "Import to DB (engagement gate + LLM extraction + scoring)",
    )


def step_generate_images(dry_run: bool = False) -> bool:
    if dry_run:
        print("[DRY-RUN] Would run generate_images tool")
        return True
    # Generate images via the agent tool
    result = subprocess.run(
        [
            sys.executable, "-c",
            (
                "import sys; sys.path.insert(0,'.'); "
                "from src.agent.skills.core_tools import tool_generate_images; "
                "r = tool_generate_images({'batch': 20}); print(r)"
            ),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
    )
    ok = result.returncode == 0
    print(f"[{'✓' if ok else '✗'}] Image generation: {result.stdout.decode('utf-8', errors='replace')[:200]}")
    return ok


def step_sync_images(dry_run: bool = False) -> bool:
    if dry_run:
        print("[DRY-RUN] Would sync images from GCS to local")
        return True
    return run(
        [sys.executable, "scripts/sync_images_from_gcs.py"],
        "Sync images from GCS to outputs/images/",
    )


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Sparki master pipeline run")
    parser.add_argument("--from-cache", action="store_true", help="Use last_crawl.json, skip crawl")
    parser.add_argument("--dry-run", action="store_true", help="Preview what would run")
    parser.add_argument("--skip-generate", action="store_true", help="Skip image generation")
    parser.add_argument("--skip-sync", action="store_true", help="Skip GCS sync")
    args = parser.parse_args()

    print("=" * 60)
    print("Sparki Master Pipeline")
    print("=" * 60)
    print(f"  from-cache:   {args.from_cache}")
    print(f"  dry-run:      {args.dry_run}")
    print(f"  skip-generate:{args.skip_generate}")
    print(f"  skip-sync:    {args.skip_sync}")
    print("=" * 60)

    steps = [
        ("1. Crawl",          lambda: step_crawl(from_cache=args.from_cache, dry_run=args.dry_run)),
        ("2. Filter preview", lambda: step_filter(dry_run=args.dry_run)),
        ("3. Import to DB",   lambda: step_import(dry_run=args.dry_run)),
        ("4. Generate images", lambda: step_generate_images(dry_run=args.dry_run) if not args.skip_generate else True),
        ("5. Sync to local", lambda: step_sync_images(dry_run=args.dry_run) if not args.skip_sync else True),
    ]

    results = []
    for label, fn in steps:
        ok = fn()
        results.append((label, ok))
        if not ok:
            print(f"\n⚠️  Step '{label}' failed — stopping.")
            break
        # Brief pause between steps
        time.sleep(1)

    print("\n" + "=" * 60)
    print("Pipeline Summary")
    print("=" * 60)
    for label, ok in results:
        print(f"  {'✓' if ok else '✗'} {label}")
    all_ok = all(ok for _, ok in results)
    print("=" * 60)
    print(f"Overall: {'✓ ALL STEPS PASSED' if all_ok else '✗ SOME STEPS FAILED'}")


if __name__ == "__main__":
    main()