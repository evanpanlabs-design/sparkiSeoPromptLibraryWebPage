"""CLI wrapper for the Veo Prompt Library retry_failed phase.

This wrapper does NOT re-implement retry logic. It loads environment
variables, resolves the project root, and delegates to the existing
`tool_retry_failed()` skill in `src/agent/skills/core_tools.py`.

Run from project root:

    # Smoke test: see candidate failed rows, no DB writes, no LLM/GCS calls
    python skills/retry-failed/scripts/retry_failed.py --batch 5 --dry-run

    # Real run (requires Vertex AI auth + GCS write access)
    python skills/retry-failed/scripts/retry_failed.py --batch 8
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _project_root() -> Path:
    """Resolve the 16_NewCrawler project root.

    The skill package lives at `<project>/skills/retry-failed/`, so the parent
    of `skills/` is the project root. `--project-root` overrides this default.
    """
    here = Path(__file__).resolve()
    # here = .../skills/retry-failed/scripts/retry_failed.py
    # parents: [0]=scripts, [1]=retry-failed, [2]=skills, [3]=project root
    return here.parents[3]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Retry cover-image generation for prompts whose image_status='failed' "
            "in the Veo Prompt Library. Sequential (not parallel) re-run via "
            "RateLimitSafeGenerator.generate()."
        )
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Path to the 16_NewCrawler project root. Defaults to the parent of skills/retry-failed/.",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=8,
        help="Max failed prompts to retry in this call (default: 8).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "SELECT the next batch of image_status='failed' rows, print a small "
            "sample, and exit. Does NOT call the generator and does NOT mutate "
            "the DB. Use this for offline triage."
        ),
    )
    return parser.parse_args()


def _dry_run(project_root: Path, batch: int) -> int:
    """Print the next batch of failed rows without writing or generating."""
    sys.path.insert(0, str(project_root))
    try:
        from dotenv import load_dotenv
        load_dotenv(project_root / ".env")
    except ImportError:
        # python-dotenv is optional — the env var may already be exported in the shell.
        pass

    from src.memory.schema import _conn

    conn = _conn()
    rows = conn.execute(
        "SELECT id, tweet_id, category, image_gcs_url, image_status, image_generated_at "
        "FROM prompts WHERE image_status = 'failed' LIMIT ?",
        (batch,),
    ).fetchall()

    total_failed = conn.execute(
        "SELECT COUNT(*) as cnt FROM prompts WHERE image_status = 'failed'"
    ).fetchone()["cnt"]

    if not rows:
        print(f"Dry-run: 0/{total_failed} — 没有需要重试的 failed prompt")
        return 0

    print(f"Dry-run: would retry {len(rows)} of {total_failed} failed prompts:")
    for row in rows:
        snippet = (row["image_gcs_url"] or "<no prior URL>")[:60]
        print(
            f"  id={row['id']} tweet_id={row['tweet_id']} "
            f"category={row['category']} gcs_url={snippet}"
        )
    return 0


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

    if args.dry_run:
        return _dry_run(root, args.batch)

    # Make `src.*` importable, then load .env from the project root.
    sys.path.insert(0, str(root))
    try:
        from dotenv import load_dotenv
        load_dotenv(root / ".env")
    except ImportError:
        # python-dotenv is optional — the env var may already be exported in the shell.
        pass

    from src.agent.skills.core_tools import tool_retry_failed

    payload = {"batch": args.batch}
    result = tool_retry_failed(payload)

    print(result)
    return 1 if isinstance(result, str) and result.startswith("错误:") else 0


if __name__ == "__main__":
    raise SystemExit(main())
