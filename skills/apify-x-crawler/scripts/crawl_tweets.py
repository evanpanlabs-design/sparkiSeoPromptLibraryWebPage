"""CLI wrapper for the Veo Prompt Library Apify crawl phase.

This wrapper does NOT re-implement Apify crawling. It loads environment
variables, resolves the project root, and delegates to the existing
`tool_crawl_tweets()` skill in `src/agent/skills/core_tools.py`.

Run from project root:

    python apify-x-crawler/scripts/crawl_tweets.py \\
        --query "Veo prompt" \\
        --max-items 20 \\
        --max-cost 0.05
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _project_root() -> Path:
    """Resolve the 16_NewCrawler project root.

    The skill package lives at `<project>/skills/apify-x-crawler/`, so the parent
    of `skills/` is the project root. `--project-root` overrides this default.
    """
    here = Path(__file__).resolve()
    # here = .../skills/apify-x-crawler/scripts/crawl_tweets.py
    # parents: [0]=scripts, [1]=apify-x-crawler, [2]=skills, [3]=project root
    return here.parents[3]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Apify X crawler for Veo Prompt Library.")
    parser.add_argument(
        "--project-root",
        default=None,
        help="Path to the 16_NewCrawler project root. Defaults to the parent of skills/apify-x-crawler/.",
    )
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="Search query. Repeat to pass multiple queries. If omitted, configs/queries.yaml is used.",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=500,
        help="Apify maxItems per query. Default: 500.",
    )
    parser.add_argument(
        "--max-cost",
        type=float,
        default=0.10,
        help="Apify max total charge per query in USD. Default: 0.10.",
    )
    parser.add_argument(
        "--sort",
        default="Latest + Top",
        choices=["Latest + Top", "Latest", "Top"],
        help="Actor sort order. Default: Latest + Top.",
    )
    parser.add_argument(
        "--include-search-terms",
        action="store_true",
        help="Whether the actor should include matched search terms in results.",
    )
    parser.add_argument(
        "--from-cache",
        action="store_true",
        help="Skip the actual crawl and just emit the cache-mode message.",
    )
    return parser.parse_args()


def _build_payload(args: argparse.Namespace) -> dict:
    payload: dict = {
        "max_items": args.max_items,
        "max_cost": args.max_cost,
        "sort": args.sort,
        "include_search_terms": args.include_search_terms,
        "from_cache": args.from_cache,
    }
    if args.queries:
        payload["queries"] = args.queries
    return payload


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

    from src.agent.skills.core_tools import tool_crawl_tweets

    payload = _build_payload(args)
    result = tool_crawl_tweets(payload)

    print(result)
    return 1 if isinstance(result, str) and result.startswith("错误:") else 0


if __name__ == "__main__":
    raise SystemExit(main())
