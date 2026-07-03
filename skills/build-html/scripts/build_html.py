"""CLI wrapper for the Veo Prompt Library build_html phase.

This wrapper does NOT re-implement HTML rendering. It loads environment
variables, resolves the project root, and either:

  * Delegates to the existing `scripts.build_html.build()` function
    directly (bypassing `tool_build_html` because the V3.2 wrapper has
    a broken import — see SKILL.md handoff note #3), or

  * On `--dry-run`, runs only the SELECT and reports how many prompts
    *would* be rendered, without touching `outputs/index.html` or the
    per-prompt detail pages.

Run from project root:

    # Help
    python skills/build-html/scripts/build_html.py --help

    # Dry-run (no file writes, just SELECT count)
    python skills/build-html/scripts/build_html.py --dry-run

    # Real build (V3.2 default — runs the deprecated GCS sync step first)
    python skills/build-html/scripts/build_html.py

    # Real build, skip the deprecated sync_images step (V3.3 forward-compat)
    python skills/build-html/scripts/build_html.py --no-sync-images

    # Filters
    python skills/build-html/scripts/build_html.py \\
        --category cinematic \\
        --min-score 0.5 \\
        --limit 20 \\
        --no-sync-images
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _project_root() -> Path:
    """Resolve the 16_NewCrawler project root.

    The skill package lives at `<project>/skills/build-html/`, so the
    grandparent of the script directory is the project root.
    `--project-root` overrides this default.
    """
    here = Path(__file__).resolve()
    # here = .../skills/build-html/scripts/build_html.py
    # parents: [0]=scripts, [1]=build-html, [2]=skills, [3]=project root
    return here.parents[3]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the Veo Prompt Library landing page: outputs/index.html "
            "and outputs/prompts/{slug}.html detail pages (1 + N)."
        )
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help=(
            "Path to the 16_NewCrawler project root. Defaults to the "
            "grandparent of skills/build-html/."
        ),
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Filter prompts by category (exact match, e.g. 'cinematic').",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help=(
            "Filter prompts by minimum quality score "
            "(CAST(quality_scores AS REAL) >= ?)."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of prompts rendered (after ORDER BY quality DESC).",
    )
    parser.add_argument(
        "--no-sync-images",
        action="store_true",
        help=(
            "Skip the deprecated sync_images step (V3.3 forward-compatible). "
            "Without this flag, the legacy GCS → flat-dir copy runs first "
            "(V3.2 default behaviour, matches tool_build_html)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run only the SELECT (with all filters applied), print the row "
            "count, and exit. Does NOT write outputs/index.html, the detail "
            "pages, or copy any images. Use this for offline smoke testing."
        ),
    )
    return parser.parse_args()


def _dry_run(
    project_root: Path,
    category: str | None,
    min_score: float | None,
    limit: int | None,
) -> int:
    """Run the SELECT only — mirrors `fetch_all_prompts()` in build_html.py.

    Does NOT touch any output file. Used for offline smoke tests.
    """
    sys.path.insert(0, str(project_root))
    try:
        from dotenv import load_dotenv
        load_dotenv(project_root / ".env")
    except ImportError:
        pass

    import sqlite3

    db_path = project_root / "data" / "veo_prompts.db"
    if not db_path.exists():
        print(
            f"错误: SQLite database not found at {db_path}. "
            "Run `python -m src.main init-db` first.",
            file=sys.stderr,
        )
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    sql = (
        "SELECT COUNT(*) AS cnt FROM prompts p "
        "LEFT JOIN tweets t ON p.tweet_id = t.tweet_id "
        "WHERE p.image_status = 'done' AND p.image_gcs_url IS NOT NULL"
    )
    params: list = []
    if category:
        sql += " AND p.category = ?"
        params.append(category)
    if min_score is not None:
        sql += " AND CAST(p.quality_scores AS REAL) >= ?"
        params.append(min_score)

    cnt = conn.execute(sql, params).fetchone()["cnt"]
    conn.close()

    capped = min(cnt, limit) if limit else cnt

    print(
        f"Would build: {capped}/{cnt} prompts "
        f"(category={category!r}, min_score={min_score!r}, limit={limit!r})"
    )
    print("  → outputs/index.html: WOULD be written")
    print(f"  → outputs/prompts/*.html: WOULD be written ({capped} detail pages)")
    print("  → outputs/index.html: NOT modified (dry-run)")
    return 0


def main() -> int:
    args = parse_args()

    if args.project_root:
        root = Path(args.project_root).resolve()
    else:
        root = _project_root()

    if not (root / "src" / "agent" / "skills" / "core_tools.py").exists():
        print(
            f"错误: 无法定位项目根目录 (期望在 {root} 找到 "
            f"src/agent/skills/core_tools.py)。请使用 --project-root 显式指定。",
            file=sys.stderr,
        )
        return 2

    if not (root / "scripts" / "build_html.py").exists():
        print(
            f"错误: 找不到 {root}/scripts/build_html.py — 项目结构不完整。",
            file=sys.stderr,
        )
        return 2

    if args.dry_run:
        return _dry_run(root, args.category, args.min_score, args.limit)

    # Make `scripts.*` and `src.*` importable, then load .env from project root.
    sys.path.insert(0, str(root))
    try:
        from dotenv import load_dotenv
        load_dotenv(root / ".env")
    except ImportError:
        pass

    # NOTE: We intentionally bypass `tool_build_html()` from
    # `src/agent/skills/core_tools.py` because in V3.2 it imports
    # `build_html` and `_sync_images_to_flat_dir` from `scripts.build_html`,
    # neither of which exists (real names: `build` and
    # `sync_images_to_flat_dir`). See SKILL.md "Handoff Notes #3".
    #
    # Once core_tools.py is patched (rename import + drop `only_with_image`
    # kwarg + read `total_prompts` instead of `source_rows`), this wrapper
    # can revert to delegating via `tool_build_html`.
    try:
        from scripts.build_html import build
    except Exception as e:
        print(f"错误: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    sync_images = not args.no_sync_images

    try:
        stats = build(
            sync_images=sync_images,
            category=args.category,
            min_score=args.min_score,
            limit=args.limit,
        )
    except Exception as e:
        print(f"错误: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    index_written = stats.get("index", 0)
    detail_written = stats.get("details", 0)
    total = stats.get("total_prompts", 0)

    print(
        f"Built HTML: {total} prompts "
        f"(index={index_written}, details={detail_written})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
