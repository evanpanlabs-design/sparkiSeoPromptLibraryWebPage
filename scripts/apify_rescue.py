#!/usr/bin/env python3
"""Abort all active Apify runs for the actor, then fetch dataset from a specific run.

Usage:
    python scripts/apify_rescue.py
    python scripts/apify_rescue.py --run-id DlHNlS5Hr6kz8dsZ7
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def abort_active_runs(token: str) -> list[str]:
    """Abort all RUNNING runs for the twitter-scraper-lite actor."""
    from apify_client import ApifyClient

    client = ApifyClient(token=token)
    actor_id = "nfp1fpt5gUlBwPcor"

    # List runs with status RUNNING
    runs = client.actor(actor_id).runs().list(status="RUNNING")
    aborted = []
    for run in runs.items:
        run_id = run["id"]
        client.actor(actor_id).run(run_id).abort()
        print(f"  Aborted: {run_id}")
        aborted.append(run_id)
    return aborted


def fetch_dataset(token: str, run_id: str, query: str) -> list[dict]:
    """Fetch all items from a completed run's dataset and map to tweet format."""
    from apify_client import ApifyClient

    client = ApifyClient(token=token)

    # Get the run to find its dataset
    run = client.actor("nfp1fpt5gUlBwPcor").run(run_id).get()
    dataset_id = run.get("datasetId")
    if not dataset_id:
        raise RuntimeError(f"No datasetId for run {run_id}")

    print(f"  Dataset ID: {dataset_id}")

    # List items
    items_response = client.datasets(dataset_id).list_items()
    raw_items = items_response.items
    print(f"  Total items in dataset: {len(raw_items)}")

    # Map to tweet format
    def map_item(item: dict) -> dict | None:
        try:
            tweet_id = str(item.get("id") or "")
            if not tweet_id:
                return None
            author = item.get("author") or {}
            return {
                "tweet_id": tweet_id,
                "url": item.get("url") or f"https://x.com/{author.get('userName', '')}/status/{tweet_id}",
                "text": item.get("text") or item.get("fullText") or "",
                "short_text": item.get("text") or item.get("fullText") or "",
                "author": {
                    "name": author.get("name", ""),
                    "screen_name": author.get("userName", ""),
                    "profile_url": author.get("url") or f"https://x.com/{author.get('userName', '')}",
                    "followers_count": int(author.get("followers", 0)),
                },
                "created_at": item.get("createdAt") or None,
                "favorite_count": int(item.get("likeCount") or 0),
                "retweet_count": int(item.get("retweetCount") or 0),
                "reply_count": int(item.get("replyCount") or 0),
                "view_count": int(item.get("viewCount") or 0),
                "scraped_at": "",
                "author_enriched": False,
                "detail_enriched": False,
            }
        except Exception:
            return None

    tweets = []
    for item in raw_items:
        mapped = map_item(item)
        if mapped:
            tweets.append(mapped)

    print(f"  Mapped tweets: {len(tweets)}")
    return tweets


def save_to_cache(tweets: list[dict], query: str, output_path: Path) -> None:
    """Save tweets to last_crawl.json."""
    import json

    # Structure: {"query_key": [tweets...]}
    cache = {query: tweets}

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    print(f"  Saved {len(tweets)} tweets to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Abort active Apify runs and rescue dataset")
    parser.add_argument("--run-id", default="DlHNlS5Hr6kz8dsZ7", help="Run ID to rescue dataset from")
    parser.add_argument("--query", default="prompt: cinematic", help="Query key for output file")
    parser.add_argument("--skip-abort", action="store_true", help="Skip aborting active runs")
    args = parser.parse_args()

    # Load .env
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    token = os.environ.get("APIFY_API_TOKEN", "")
    if not token:
        print("ERROR: APIFY_API_TOKEN not set in .env")
        sys.exit(1)

    print(f"Token: {token[:10]}...{token[-4:]}")
    print()

    # Step 1: Abort active runs
    if not args.skip_abort:
        print("Step 1: Aborting active runs...")
        aborted = abort_active_runs(token)
        print(f"  Aborted {len(aborted)} runs")
        if not aborted:
            print("  No active runs to abort")
    else:
        print("Step 1: Skipped (--skip-abort)")

    # Step 2: Fetch dataset
    print()
    print(f"Step 2: Fetching dataset from run {args.run_id}...")
    try:
        tweets = fetch_dataset(token, args.run_id, args.query)
        print(f"  Retrieved {len(tweets)} tweets")
    except Exception as e:
        print(f"  ERROR fetching dataset: {e}")
        tweets = []

    if not tweets:
        print("No tweets retrieved.")
        return

    # Step 3: Save
    print()
    print("Step 3: Saving to last_crawl.json...")
    output_path = PROJECT_ROOT / "outputs" / "last_crawl.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_to_cache(tweets, args.query, output_path)

    # Summary
    print()
    print("=== Rescue Summary ===")
    print(f"  Run ID:       {args.run_id}")
    print(f"  Tweets:      {len(tweets)}")
    print(f"  Saved to:    {output_path}")
    print("=======================")


if __name__ == "__main__":
    main()