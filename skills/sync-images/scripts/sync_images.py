"""CLI wrapper for the Veo Prompt Library sync_images phase (DEPRECATED).

This wrapper does NOT re-implement GCS sync. It loads environment variables,
resolves the project root, and delegates to the existing `tool_sync_images()`
skill in `src/agent/skills/core_tools.py`.

DEPRECATION: This skill wraps a GCS -> local image mirror step that is
scheduled for removal in V3.3. In V3.3, `generate_images` writes directly to
`outputs/generated_images/` and this whole phase goes away. Do not use this on
fresh V3.3+ deploys.

Run from project root:

    python skills/sync-images/scripts/sync_images.py --help
    python skills/sync-images/scripts/sync_images.py --dry-run --limit 5
    python skills/sync-images/scripts/sync_images.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _project_root() -> Path:
    """Resolve the 16_NewCrawler project root.

    The skill package lives at `<project>/skills/sync-images/`, so the parent
    of the `sync-images/` directory is the project root. `--project-root`
    overrides this default.
    """
    here = Path(__file__).resolve()
    # .../16_NewCrawler/skills/sync-images/scripts/sync_images.py
    # project root = 16_NewCrawler/
    return here.parent.parent.parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sync_images",
        description=(
            "[DEPRECATED] Sync cover images from GCS to local outputs/ for the "
            "Veo Prompt Library. This step is removed in V3.3 — use "
            "generate_images which writes directly to outputs/generated_images/."
        ),
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help=(
            "Path to the 16_NewCrawler project root. "
            "Defaults to the parent of skills/sync-images/."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Pass dry_run=True to download_all (Step 1 — GCS download). "
            "WARNING: Step 2 (copy to outputs/generated_images/) still runs "
            "and may write files. See SKILL.md Handoff Notes drift #3."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Forwarded to download_all(limit=...) to cap GCS iteration count. "
            "Default: no limit (process all blobs)."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.project_root:
        root = Path(args.project_root).resolve()
    else:
        root = _project_root()

    if not (root / "src" / "agent" / "skills" / "core_tools.py").exists():
        print(
            f"错误: 无法定位项目根目录 (期望在 {root} 找到 src/agent/skills/core_tools.py)。"
            " 请使用 --project-root 显式指定。",
            file=sys.stderr,
        )
        return 2

    # Make `src.*` importable, then load .env from the project root.
    sys.path.insert(0, str(root))
    try:
        from dotenv import load_dotenv
        load_dotenv(root / ".env")
    except ImportError:
        # python-dotenv is optional — the env var may already be exported in the shell.
        pass

    from src.agent.skills.core_tools import tool_sync_images

    payload: dict = {}
    if args.dry_run:
        payload["dry_run"] = True
    if args.limit is not None:
        payload["limit"] = args.limit

    result = tool_sync_images(payload)

    print(result)
    return 1 if isinstance(result, str) and result.startswith("错误:") else 0


if __name__ == "__main__":
    raise SystemExit(main())
