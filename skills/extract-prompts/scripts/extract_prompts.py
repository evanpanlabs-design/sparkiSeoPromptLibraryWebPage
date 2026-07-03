"""CLI wrapper for the Veo Prompt Library extract_prompts phase.

This wrapper does NOT re-implement LLM extraction. It loads environment
variables, resolves the project root, and delegates to the existing
`tool_extract_prompts()` skill in `src/agent/skills/core_tools.py`.

Run from project root:

    # Smoke test (no LLM, no DB writes)
    python extract-prompts/scripts/extract_prompts.py --batch 5 --dry-run

    # Real run (requires Vertex AI auth)
    python extract-prompts/scripts/extract_prompts.py --batch 50
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _project_root() -> Path:
    """Resolve the 16_NewCrawler project root.

    The skill package lives at `<project>/skills/extract-prompts/`, so the parent
    of `skills/` is the project root. `--project-root` overrides this default.
    """
    here = Path(__file__).resolve()
    # here = .../skills/extract-prompts/scripts/extract_prompts.py
    # parents: [0]=scripts, [1]=extract-prompts, [2]=skills, [3]=project root
    return here.parents[3]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run extract_prompts (three-pass LLM) for the Veo Prompt Library."
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Path to the 16_NewCrawler project root. Defaults to the parent of skills/extract-prompts/.",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=50,
        help="Max tweets to process in this call (default: 50).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run the pre-LLM content filter only, count how many tweets would "
            "pass, and exit. Does NOT call the LLM and does NOT write to the DB. "
            "Use this for offline smoke testing."
        ),
    )
    return parser.parse_args()


def _dry_run(project_root: Path, batch: int) -> int:
    """Reproduce the pre-LLM content filter from `_content_filter()` and report.

    Mirrors the logic in `src/worker/extractor.py:92-105` (case-insensitive
    "veo" + 15-word floor) so the operator can verify what *would* hit the
    LLM in a real run.
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
        SELECT tweet_id, text, short_text
        FROM tweets
        WHERE prompt_text IS NULL
        ORDER BY likes_count DESC
        LIMIT ?
        """,
        (batch,),
    ).fetchall()

    if not rows:
        print("Would extract: 0/0 — 没有需要提取的推文")
        return 0

    REQUIRED = ["veo"]           # case-insensitive, from extractor.py:33
    MIN_WORDS = 15               # from extractor.py:34

    would_pass = 0
    would_skip = 0
    sample_skip = None
    for row in rows:
        text = (row["text"] or row["short_text"] or "").strip()
        t = text.lower()
        if all(kw in t for kw in REQUIRED) and len(text.split()) >= MIN_WORDS:
            would_pass += 1
        else:
            would_skip += 1
            if sample_skip is None:
                sample_skip = (row["tweet_id"], text[:80])

    print(
        f"Would extract: {would_pass}/{len(rows)} tweets (passed content filter) "
        f"[skipped by filter: {would_skip}]"
    )
    if sample_skip:
        print(
            f"  sample skip: tweet_id={sample_skip[0]} "
            f"text='{sample_skip[1]}...'"
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

    from src.agent.skills.core_tools import tool_extract_prompts

    payload = {"batch": args.batch}
    result = tool_extract_prompts(payload)

    print(result)
    return 1 if isinstance(result, str) and result.startswith("错误:") else 0


if __name__ == "__main__":
    raise SystemExit(main())
