"""CLI wrapper for the Veo Prompt Library semantic search phase.

This wrapper does NOT re-implement embedding search. It loads environment
variables, resolves the project root, and delegates to the existing
`tool_search_prompts()` skill in `src/agent/skills/core_tools.py`.

Run from project root:

    # Smoke test (no LLM call, no DB write — just preview the call shape)
    python search-prompts/scripts/search_prompts.py \\
        --query "cinematic drone shot" --dry-run

    # Real run (requires Vertex AI auth + populated prompt_embeddings)
    python search-prompts/scripts/search_prompts.py \\
        --query "cinematic drone shot" --top-k 5

Exit codes:
    0 = results returned (or successful --dry-run, or --help)
    1 = stub message / empty results / 错误: string
    2 = project root not located
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# The exact stub string that `tool_search_prompts()` returns from its
# `except (ImportError, AttributeError)` branch at core_tools.py:513-514.
STUB_MESSAGE = "Embedding搜索暂不可用（等待Code-4实现），请稍后再试。"


def _project_root() -> Path:
    """Resolve the 16_NewCrawler project root.

    The skill package lives at `<project>/skills/search-prompts/`, so the parent
    of `skills/` is the project root. `--project-root` overrides this default.
    """
    here = Path(__file__).resolve()
    # here = .../skills/search-prompts/scripts/search_prompts.py
    # parents: [0]=scripts, [1]=search-prompts, [2]=skills, [3]=project root
    return here.parents[3]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run search_prompts (Gemini embedding semantic search) for the "
            "Veo Prompt Library. Delegates to tool_search_prompts()."
        )
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Path to the 16_NewCrawler project root. Defaults to the parent of skills/search-prompts/.",
    )
    parser.add_argument(
        "--query",
        default="",
        help="Natural-language search query. Required for a real run.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of top-similarity results to return. Default: 5.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help="Optional cosine-similarity floor (0-1). Rows below are dropped.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Preview the call shape: which tool would be invoked, with which "
            "args, against which DB. Does NOT call the embedding API and does "
            "NOT return search results. Use this for offline smoke testing."
        ),
    )
    return parser.parse_args()


def _dry_run(project_root: Path, args: argparse.Namespace) -> int:
    """Print the shape of the call without actually embedding or querying."""
    db_path = project_root / "data" / "veo_prompts.db"
    print("[dry-run] tool_search_prompts payload:")
    print(f"  query      = {args.query!r}")
    print(f"  top_k      = {args.top_k}")
    print(f"  min_score  = {args.min_score}")
    print()
    print(f"[dry-run] DB path: {db_path}  (exists={db_path.exists()})")
    if db_path.exists():
        try:
            import sqlite3
            c = sqlite3.connect(str(db_path))
            n_emb = c.execute("SELECT COUNT(*) FROM prompt_embeddings").fetchone()[0]
            n_done = c.execute(
                "SELECT COUNT(*) FROM prompts WHERE embedding_status='embedded'"
            ).fetchone()[0]
            n_pend = c.execute(
                "SELECT COUNT(*) FROM prompts WHERE embedding_status='pending'"
            ).fetchone()[0]
            print(f"[dry-run] prompt_embeddings rows: {n_emb}")
            print(f"[dry-run] prompts.embedding_status: embedded={n_done}, pending={n_pend}")
        except Exception as e:
            print(f"[dry-run] (could not read counts: {type(e).__name__}: {e})")
    print()
    print("[dry-run] No embedding API call was made.")
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
        # python-dotenv is optional — the env var may already be exported in the shell.
        pass

    from src.agent.skills.core_tools import tool_search_prompts

    payload: dict = {
        "query": args.query,
        "top_k": args.top_k,
    }
    if args.min_score is not None:
        payload["min_score"] = args.min_score

    result = tool_search_prompts(payload)

    print(result)

    # Distinguish three failure surfaces:
    #   - STUB_MESSAGE          → wrapper returns the "Code-4 not implemented" string
    #   - startswith "错误:"    → real exception bubbled out
    #   - startswith "未找到"   → empty result (still exit 1, not 0)
    #   - everything else       → success (exit 0)
    if isinstance(result, str):
        if result == STUB_MESSAGE:
            return 1
        if result.startswith("错误:"):
            return 1
        if result.startswith("未找到"):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
