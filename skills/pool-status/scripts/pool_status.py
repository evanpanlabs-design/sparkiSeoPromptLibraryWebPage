"""CLI wrapper for the Veo Prompt Library `pool_status` skill.

This wrapper does NOT re-implement the status query. It loads environment
variables, resolves the project root, and delegates to the existing
`tool_pool_status()` skill in `src/agent/skills/core_tools.py`.

Run from project root:

    # Text output (default — matches the tool's Chinese status string)
    python pool-status/scripts/pool_status.py

    # JSON output (machine-readable, useful for CI / dashboards)
    python pool-status/scripts/pool_status.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def _project_root() -> Path:
    """Resolve the 16_NewCrawler project root.

    The skill package lives at `<project>/skills/pool-status/`, so the parent
    of `skills/` is the project root. `--project-root` overrides this default.
    """
    here = Path(__file__).resolve()
    # here = .../skills/pool-status/scripts/pool_status.py
    # parents: [0]=scripts, [1]=pool-status, [2]=skills, [3]=project root
    return here.parents[3]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Query the Veo Prompt Library prompt pool status counts by "
            "prompts.image_status (read-only)."
        )
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Path to the 16_NewCrawler project root. Defaults to the parent of skills/pool-status/.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON object {state: count, ..., total: N} instead of the text table.",
    )
    return parser.parse_args()


# Matches lines like "  pending    :   12" produced by `tool_pool_status`.
_ROW_RE = re.compile(r"^\s*([A-Za-z_]+)\s*:\s*(\d+)\s*$")


def _parse_status_output(text: str) -> dict[str, int] | None:
    """Parse the Chinese status string from `tool_pool_status()` into a dict.

    Returns None if the string is not in the expected format (e.g. an error).
    """
    counts: dict[str, int] = {}
    for line in text.splitlines():
        m = _ROW_RE.match(line)
        if m:
            label, n = m.group(1), int(m.group(2))
            if label == "总计":
                counts["total"] = n
            else:
                counts[label] = n
    return counts or None


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
        # python-dotenv is optional — this skill does not need any env vars.
        pass

    from src.agent.skills.core_tools import tool_pool_status

    result = tool_pool_status({})

    # Detect an error string from the tool.
    is_error = isinstance(result, str) and result.startswith("错误:")

    if args.json:
        parsed = _parse_status_output(result)
        if is_error or parsed is None:
            # Fall back to {"error": <message>} so callers can still parse JSON.
            payload = {"error": result}
        else:
            payload = parsed
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(result)

    return 1 if is_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
