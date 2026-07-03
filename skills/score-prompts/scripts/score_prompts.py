"""CLI wrapper for the Veo Prompt Library score_prompts phase.

This wrapper does NOT re-implement LLM scoring. It loads environment
variables, resolves the project root, and delegates to the existing
`tool_score_prompts()` skill in `src/agent/skills/core_tools.py`.

Run from project root:

    # Smoke test (no LLM, no DB writes)
    python score-prompts/scripts/score_prompts.py --batch 5 --dry-run

    # Real run (requires Vertex AI auth)
    python score-prompts/scripts/score_prompts.py --batch 50

    # Stricter filter
    python score-prompts/scripts/score_prompts.py --batch 50 --min-score 0.6
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _project_root() -> Path:
    """Resolve the 16_NewCrawler project root.

    The skill package lives at `<project>/skills/score-prompts/`, so the parent
    of `skills/` is the project root. `--project-root` overrides this default.
    """
    here = Path(__file__).resolve()
    # here = .../skills/score-prompts/scripts/score_prompts.py
    # parents: [0]=scripts, [1]=score-prompts, [2]=skills, [3]=project root
    return here.parents[3]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run score_prompts (four-dim LLM scoring) for the Veo Prompt Library."
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Path to the 16_NewCrawler project root. Defaults to the parent of skills/score-prompts/.",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=50,
        help="Max prompts to score in this call (default: 50).",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.4,
        help="Minimum overall score to count as qualified (default: 0.4).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Preview scoring candidates without calling the LLM: just count and "
            "sample the prompts that WOULD be scored. Does NOT call the LLM and "
            "does NOT write to the DB. Use this for offline smoke testing."
        ),
    )
    return parser.parse_args()


def _dry_run(project_root: Path, batch: int, min_score: float) -> int:
    """Reproduce the SELECT from `tool_score_prompts()` and report.

    Mirrors the SQL at `core_tools.py:287-298` (filter on
    `quality_scores IS NULL AND prompt_text IS NOT NULL`, order by
    `likes_count DESC`, limit `batch`) so the operator can see what
    *would* hit the LLM in a real run.
    """
    sys.path.insert(0, str(project_root))
    try:
        from dotenv import load_dotenv
        load_dotenv(project_root / ".env")
    except ImportError:
        pass

    from src.memory.schema import _conn

    conn = _conn()
    rows = conn.execute(
        """
        SELECT id, tweet_id, category, title, prompt_text,
               likes_count, quality_scores
        FROM prompts
        WHERE quality_scores IS NULL AND prompt_text IS NOT NULL
        ORDER BY likes_count DESC
        LIMIT ?
        """,
        (batch,),
    ).fetchall()

    if not rows:
        print(f"Would score: 0/0 — 没有待评分的 prompts (min_score={min_score}, batch={batch})")
        return 0

    print(
        f"Would score: {len(rows)}/{batch} prompts (passed candidate filter) "
        f"[min_score={min_score}]"
    )
    # Show up to 3 sample candidates with a short preview of prompt_text
    sample_n = min(3, len(rows))
    for i, row in enumerate(rows[:sample_n], 1):
        preview = (row["prompt_text"] or "").strip().replace("\n", " ")
        if len(preview) > 90:
            preview = preview[:90] + "..."
        print(
            f"  sample {i}: id={row['id']} cat={row['category']} "
            f"likes={row['likes_count']} | {preview}"
        )
    if len(rows) > sample_n:
        print(f"  ... and {len(rows) - sample_n} more")

    # Also show how many would be qualified at the requested min_score.
    # We can't predict the LLM output, but we can count how many ALREADY-scored
    # rows would qualify — useful as a sanity check for the threshold.
    qualified_baseline = conn.execute(
        """
        SELECT COUNT(*) FROM prompts
        WHERE quality_scores IS NOT NULL
          AND CAST(quality_scores AS REAL) >= ?
        """,
        (min_score,),
    ).fetchone()[0]
    if qualified_baseline:
        print(
            f"  (baseline: {qualified_baseline} already-scored rows would qualify "
            f"under min_score={min_score} — note: CAST reads specificity, not overall, see SKILL.md drift #4)"
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
        return _dry_run(root, args.batch, args.min_score)

    # Make `src.*` importable, then load .env from the project root.
    sys.path.insert(0, str(root))
    try:
        from dotenv import load_dotenv
        load_dotenv(root / ".env")
    except ImportError:
        # python-dotenv is optional — the env var may already be exported in the shell.
        pass

    from src.agent.skills.core_tools import tool_score_prompts

    payload = {"batch": args.batch, "min_score": args.min_score}
    result = tool_score_prompts(payload)

    print(result)
    return 1 if isinstance(result, str) and result.startswith("错误:") else 0


if __name__ == "__main__":
    raise SystemExit(main())
