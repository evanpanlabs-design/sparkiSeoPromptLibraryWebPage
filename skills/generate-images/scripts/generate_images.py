"""CLI wrapper for the Veo Prompt Library generate_images phase.

This wrapper does NOT re-implement image generation. It loads environment
variables, resolves the project root, and delegates to the existing
`tool_generate_images()` skill in `src/agent/skills/core_tools.py`.

Run from project root:

    # Smoke test (no Gemini call, no DB writes)
    python skills/generate-images/scripts/generate_images.py --batch 5 --dry-run

    # Real run (requires Vertex AI auth + GCS write access)
    python skills/generate-images/scripts/generate_images.py --batch 8
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def _project_root() -> Path:
    """Resolve the 16_NewCrawler project root.

    The skill package lives at `<project>/skills/generate-images/`, so the
    great-grandparent of this file is the project root. `--project-root`
    overrides this default.
    """
    here = Path(__file__).resolve()
    return here.parent.parent.parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run generate_images (Gemini cover-image generation) for the Veo Prompt Library."
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Path to the 16_NewCrawler project root. Defaults to the parent of skills/generate-images/.",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=8,
        help="Max prompts to process in this call (default: 8). 0 = unbounded.",
    )
    parser.add_argument(
        "--sort-by",
        choices=["score", "newest"],
        default="score",
        help="Sort order. 'score' = CAST(quality_scores AS REAL) DESC; 'newest' = id DESC. Default: score.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help=(
            "Optional quality floor. Translates to filter={'min_score': X}. "
            "NOTE: see SKILL.md Handoff Notes drift #4 — the SQL CAST reads the "
            "first CSV field (specificity), not the overall score."
        ),
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=3,
        help="ThreadPool size inside RateLimitSafeGenerator (default: 3).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Reproduce the SELECT that the tool would run (with the same filter, "
            "sort, and limit) and print what would be generated. Does NOT call "
            "Gemini and does NOT write to the DB."
        ),
    )
    return parser.parse_args()


def _build_payload(args: argparse.Namespace) -> dict:
    payload: dict = {
        "batch": args.batch,
        "sort_by": args.sort_by,
        "max_workers": args.max_workers,
    }
    if args.min_score is not None:
        payload["filter"] = {"min_score": args.min_score}
    return payload


def _dry_run(project_root: Path, args: argparse.Namespace) -> int:
    """Reproduce the SELECT the tool would run, then print what would be generated.

    Mirrors the query in `core_tools.py:531-545` exactly (same WHERE / ORDER BY /
    LIMIT) so the operator can verify what *would* hit the Gemini client.
    """
    db_path = project_root / "data" / "veo_prompts.db"
    if not db_path.exists():
        print(
            f"错误: 数据库不存在 ({db_path})。请先运行 `python -m src.main init-db`.",
            file=sys.stderr,
        )
        return 2

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    sql = (
        "SELECT id, prompt_text, category, quality_scores "
        "FROM prompts "
        "WHERE image_gcs_url IS NULL AND image_status = 'pending'"
    )
    params: list = []
    if args.min_score is not None:
        sql += " AND CAST(quality_scores AS REAL) >= ?"
        params.append(args.min_score)

    if args.sort_by == "score":
        sql += " ORDER BY CAST(quality_scores AS REAL) DESC"
    else:
        sql += " ORDER BY id DESC"

    if args.batch > 0:
        sql += f" LIMIT {args.batch}"

    rows = conn.execute(sql, params).fetchall()

    if not rows:
        print("Would generate: 0/0 — 没有需要生成图片的 pending prompt")
        return 0

    print(
        f"Would generate: {len(rows)} cover images (no Gemini call, no DB write)\n"
        f"  filter: min_score={args.min_score}  sort_by={args.sort_by}  batch={args.batch}"
    )
    print("  sample (first 5):")
    for r in rows[:5]:
        snippet = (r["prompt_text"] or "").replace("\n", " ")[:80]
        print(
            f"    id={r['id']:>4} cat={r['category']:<22} "
            f"q={r['quality_scores']!s:<18} text='{snippet}...'"
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
        return _dry_run(root, args)

    # Make `src.*` importable, then load .env from the project root.
    sys.path.insert(0, str(root))
    try:
        from dotenv import load_dotenv
        load_dotenv(root / ".env")
    except ImportError:
        # python-dotenv is optional — env vars may already be in the shell.
        pass

    from src.agent.skills.core_tools import tool_generate_images

    payload = _build_payload(args)
    result = tool_generate_images(payload)

    print(result)
    return 1 if isinstance(result, str) and result.startswith("错误:") else 0


if __name__ == "__main__":
    raise SystemExit(main())
