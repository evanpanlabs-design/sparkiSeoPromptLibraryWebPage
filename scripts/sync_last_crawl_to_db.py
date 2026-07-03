#!/usr/bin/env python3
"""Sync last_crawl.json data into tweets/prompts tables.

Converts Twitter timestamp format → ISO, then upserts into tweets table
and backfills prompts.author_followers.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

CRAWL_JSON = PROJECT_ROOT / "outputs" / "last_crawl.json"
DB_PATH = PROJECT_ROOT / "data" / "veo_prompts.db"


def parse_twitter_time(s: str) -> str:
    """'Thu May 21 05:30:21 +0000 2026' → '2026-05-21T05:30:21+00:00'"""
    if not s:
        return ""
    try:
        dt = datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")
        return dt.isoformat()
    except Exception:
        return ""


def sync():
    if not CRAWL_JSON.exists():
        print(f"[ERROR] {CRAWL_JSON} not found")
        return

    with open(CRAWL_JSON, encoding="utf-8") as f:
        data = json.load(f)

    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    tweets_updated, prompts_updated = 0, 0

    for category, items in data.items():
        for item in items:
            tweet_id = item.get("tweet_id", "")
            if not tweet_id:
                continue

            author = item.get("author") or {}
            followers = int(author.get("followers_count", 0) or 0)
            created_at = parse_twitter_time(item.get("created_at", ""))
            likes = int(item.get("favorite_count", 0) or 0)
            retweets = int(item.get("retweet_count", 0) or 0)
            replies = int(item.get("reply_count", 0) or 0)
            views = int(item.get("view_count", 0) or 0)

            # Upsert tweets table: preserve existing url/text, update author/engagement/date
            existing = conn.execute(
                "SELECT url FROM tweets WHERE tweet_id = ?", (tweet_id,)
            ).fetchone()

            if existing:
                # UPDATE only the fields from last_crawl.json
                conn.execute(
                    """
                    UPDATE tweets SET
                        author_name = ?,
                        author_screen = ?,
                        author_followers = ?,
                        likes_count = ?,
                        retweet_count = ?,
                        reply_count = ?,
                        view_count = ?,
                        created_at = ?
                    WHERE tweet_id = ?
                    """,
                    (author.get("name", ""), author.get("screen_name", ""),
                     followers, likes, retweets, replies, views,
                     created_at, tweet_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO tweets
                      (tweet_id, url, author_name, author_screen, author_followers,
                       likes_count, retweet_count, reply_count, view_count,
                       created_at, scraped_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (tweet_id,
                     item.get("url", f"https://x.com/{author.get('screen_name','')}/status/{tweet_id}"),
                     author.get("name", ""), author.get("screen_name", ""),
                     followers, likes, retweets, replies, views, created_at),
                )
            tweets_updated += 1

            # Backfill prompts.author_followers
            conn.execute(
                """
                UPDATE prompts
                SET author_followers = ?
                WHERE tweet_id = ?
                """,
                (followers, tweet_id),
            )
            if conn.total_changes > 0:
                prompts_updated += 1

    conn.commit()
    conn.close()

    print(f"  tweets upserted: {tweets_updated}")
    print(f"  prompts backfilled: {prompts_updated}")


if __name__ == "__main__":
    print(f"Syncing {CRAWL_JSON} → DB...")
    sync()
    print("Done.")