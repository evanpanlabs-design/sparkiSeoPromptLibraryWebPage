"""CLI wrapper for the Veo Prompt Library publish phase (build HTML + git push).

This wrapper does NOT re-implement publishing. It loads environment variables,
resolves the project root, and delegates to the existing `tool_publish()` skill
in `src/agent/skills/core_tools.py`.

The wrapper adds a `--dry-run` flag that runs the HTML rebuild step but skips
the `git commit` and `git push` — the underlying `tool_publish` does not have
this guard, so the wrapper enforces it (see `core_tools.py:691-750` for the
no-guard original).

Run from project root:

    # Smoke test (rebuild HTML, no git operations)
    python publish/scripts/publish.py --dry-run

    # Real run (commits + pushes to gh-pages)
    python publish/scripts/publish.py --message "Update prompt library"
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _project_root() -> Path:
    """Resolve the 16_NewCrawler project root.

    The skill package lives at `<project>/skills/publish/`, so the parent
    of `skills/` is the project root. `--project-root` overrides this default.
    """
    here = Path(__file__).resolve()
    # here = .../skills/publish/scripts/publish.py
    # parents: [0]=scripts, [1]=publish, [2]=skills, [3]=project root
    return here.parents[3]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build Veo Prompt Library HTML and push to GitHub Pages (gh-pages). "
            "Use --dry-run to rebuild HTML without git commit/push."
        )
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help=(
            "Path to the 16_NewCrawler project root. "
            "Defaults to the parent of skills/publish/."
        ),
    )
    parser.add_argument(
        "--repo",
        default=None,
        help=(
            "Path to the git working tree (cwd for git subprocesses). "
            "Default: <project_root>/.git — almost always leave as-is."
        ),
    )
    parser.add_argument(
        "--message",
        default="Update prompt library",
        help='Commit message for `git commit -m`. Default: "Update prompt library".',
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Rebuild outputs/index.html and outputs/prompts/*.html via "
            "scripts/build_html.py --sync-images, but SKIP the git commit "
            "and git push steps. Use this to preview what would change "
            "before pushing to GitHub Pages."
        ),
    )
    return parser.parse_args()


def _build_html_only(project_root: Path) -> tuple[bool, str]:
    """Run the HTML build step directly so --dry-run can short-circuit git ops.

    Mirrors the subprocess call inside `tool_publish()` (core_tools.py:704-709)
    so the dry-run output is identical to the real run up to the git point.
    Returns (ok, output_text).
    """
    proc = subprocess.run(
        ["python", "scripts/build_html.py", "--sync-images"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if proc.returncode != 0:
        return False, proc.stderr or proc.stdout
    return True, proc.stdout


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
        # python-dotenv is optional — env may already be exported in the shell.
        pass

    if args.dry_run:
        print("[dry-run] Rebuilding HTML only; skipping git commit + git push.")
        ok, output = _build_html_only(root)
        if not ok:
            print(f"HTML build failed: {output}", file=sys.stderr)
            return 1
        # Echo the build_html.py output so the operator can see what changed.
        sys.stdout.write(output)
        print("[dry-run] git commit/push skipped. Use without --dry-run to publish.")
        return 0

    from src.agent.skills.core_tools import tool_publish

    payload: dict = {"message": args.message}
    if args.repo:
        payload["repo"] = args.repo

    result = tool_publish(payload)

    print(result)
    # tool_publish never starts with "错误:" — it uses "HTML build failed:" /
    # "Git operations failed:" prefixes. Treat any of those as failure.
    if isinstance(result, str) and (
        result.startswith("错误:")
        or result.startswith("HTML build failed:")
        or result.startswith("Git operations failed:")
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
