"""Sparki pipeline CLI entry point.

DEPRECATED: phase-based pipeline removed in V3.2
Use V3 Agent for data collection: python -m src.agent.chat

Usage:
  python -m src.main init-db
  python -m src.main status
  python -m src.main status --scrape-id 1
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env file into environment
load_dotenv(PROJECT_ROOT / ".env")

from src.memory.schema import init_db


def show_status(scrape_id: int | None = None):
    """Show pipeline status."""
    from src.memory.schema import _conn

    conn = _conn()
    if scrape_id:
        row = conn.execute(
            "SELECT * FROM scrape_runs WHERE id = ?", (scrape_id,)
        ).fetchone()
        if row:
            print(f"Scrape Run #{row['id']}")
            print(f"  Run ID: {row['run_id']}")
            print(f"  Phase: {row['phase']}")
            print(f"  Status: {row['status']}")
            print(f"  Started: {row['started_at']}")
            print(f"  Completed: {row['completed_at'] or 'N/A'}")
            print(f"  Tweets: {row['total_tweets']}")
            print(f"  Prompts: {row['total_prompts']}")
            print(f"  Images: {row['total_images']}")
        else:
            print(f"No scrape run found with ID {scrape_id}")
    else:
        rows = conn.execute("SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 10").fetchall()
        if rows:
            print("Recent Scrape Runs:")
            for row in rows:
                print(f"  #{row['id']} | {row['phase']:15} | {row['status']:10} | {row['started_at'][:19]}")
        else:
            print("No scrape runs found.")


def main():
    parser = argparse.ArgumentParser(description="Sparki Pipeline CLI (V3.2)")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # run subcommand (DEPRECATED, kept for clear error message)
    run_parser = subparsers.add_parser("run", help="[DEPRECATED] Use python -m src.agent.chat")
    run_parser.add_argument("--all", action="store_true", help="[DEPRECATED] Run all phases")
    run_parser.add_argument("--phase", type=int, help="[DEPRECATED] Start from specific phase (1-9)")
    run_parser.add_argument("--scrape-id", type=int, help="[DEPRECATED] Resume from specific scrape ID")
    run_parser.add_argument("--dry-run", action="store_true", help="[DEPRECATED] Dry run (no actual scraping)")
    run_parser.add_argument("--interactive", action="store_true", help="[DEPRECATED] Interactive mode")
    run_parser.add_argument("--headed", action="store_true", help="[DEPRECATED] Run browser in visible (headed) mode")
    run_parser.add_argument("--from-cache", action="store_true", help="[DEPRECATED] Skip crawling, load tweets from outputs/last_crawl.json")

    # status subcommand
    status_parser = subparsers.add_parser("status", help="Show pipeline status")
    status_parser.add_argument("--scrape-id", type=int, help="Specific scrape run ID")

    # init-db subcommand
    init_parser = subparsers.add_parser("init-db", help="Initialize the database")
    init_parser.add_argument("--force", action="store_true", help="Force re-initialization")

    args = parser.parse_args()

    if args.command == "run":
        print("=" * 60)
        print("  [V3.2 DEPRECATED] V1 pipeline is removed.")
        print("  Use V3 Agent for data collection:")
        print("    python -m src.agent.chat")
        print("=" * 60)
        sys.exit(1)
    elif args.command == "status":
        show_status(scrape_id=args.scrape_id)
    elif args.command == "init-db":
        print("Initializing database...")
        init_db()
        print("Database initialized successfully.")
    else:
        # Default — show help
        parser.print_help()


if __name__ == "__main__":
    main()