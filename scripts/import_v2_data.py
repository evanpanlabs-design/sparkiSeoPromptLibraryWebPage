#!/usr/bin/env python3
"""Import V1/V2 tweet data into V3 SQLite schema.

Pipeline:
  last_crawl.json (1422条)
      ↓
  Engagement gate: favorite>50, views>1000, followers>1000
      ↓
  PromptExtractor (parallel, concurrency=10) → LLM判断是否是prompt
      ↓
  QualityScorer (parallel, concurrency=10) → LLM打4维度质量分
      ↓
  qualified (overall>=0.40) → prompts表 + embedding

Usage:
    python scripts/import_v2_data.py
    python scripts/import_v2_data.py --dry-run
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CRAWL_JSON = PROJECT_ROOT / "outputs" / "last_crawl.json"

CATEGORY_NORM = {
    "Commercial / Product": "product-photography",
    "Text-to-Video": "video-generation",
}


def _norm_category(raw: str | None) -> str:
    """Normalize LLM-assigned category to one of the 5 standard categories."""
    if not raw:
        return "other"
    return CATEGORY_NORM.get(raw, raw)


# Engagement gate thresholds
MIN_LIKES = 50
MIN_VIEWS = 1000
MIN_FOLLOWERS = 1000

# LLM parallel concurrency
EXTRACTOR_CONCURRENCY = 10
SCORER_CONCURRENCY = 10

# Embedding model
EMBEDDING_MODEL = "gemini-embedding-2"


# ── Gemini LLM adapter ───────────────────────────────────────────────────────


class GeminiLLMAdapter:
    """Wraps GeminiClient to satisfy LLMClientLike interface used by worker modules."""

    def complete(self, prompt, system=None, model=None, temperature=0.0, max_tokens=500):
        from src.llm.gemini_client import GeminiClient

        return GeminiClient(
            project="sparki-op", location="global"
        ).complete(
            prompt=prompt,
            system=system,
            model="gemini-3.5-flash",
            temperature=temperature,
            max_tokens=max_tokens,
        )


# ── Tweet loader ───────────────────────────────────────────────────────────────


def _load_crawl_tweets() -> list[dict]:
    """Load tweets from last_crawl.json into flat list."""
    if not CRAWL_JSON.exists():
        logger.error("Crawl file not found: %s", CRAWL_JSON)
        sys.exit(1)

    with open(CRAWL_JSON, encoding="utf-8") as f:
        data = json.load(f)

    tweets = []
    for query_key, tweet_list in data.items():
        if isinstance(tweet_list, list):
            for t in tweet_list:
                t["_query"] = query_key
                tweets.append(t)
    return tweets


def _engagement_gate(tweets: list[dict]) -> list[dict]:
    """Filter tweets by engagement thresholds."""
    return [
        t for t in tweets
        if t.get("favorite_count", 0) >= MIN_LIKES
        and t.get("view_count", 0) >= MIN_VIEWS
        and (t.get("author") or {}).get("followers_count", 0) >= MIN_FOLLOWERS
    ]


def _dict_to_tweet(d: dict) -> Any:
    """Convert raw tweet dict to src.types.tweet.Tweet."""
    from src.types.tweet import Tweet, AuthorRef

    author = d.get("author") or {}
    return Tweet(
        tweet_id=str(d.get("tweet_id", "")),
        url=d.get("url", ""),
        text=d.get("text", ""),
        short_text=d.get("short_text", ""),
        author=AuthorRef(
            name=author.get("name", ""),
            screen_name=author.get("screen_name", ""),
            profile_url=author.get("profile_url", ""),
            followers_count=int(author.get("followers_count", 0)),
        ),
        created_at=d.get("created_at"),
        favorite_count=int(d.get("favorite_count", 0)),
        retweet_count=int(d.get("retweet_count", 0)),
        reply_count=int(d.get("reply_count", 0)),
        view_count=int(d.get("view_count", 0)),
        source_query=d.get("_query", ""),
    )


# ── Parallel LLM processing ─────────────────────────────────────────────────


def _extract_and_score(tweet) -> dict | None:
    """Run extractor then scorer on a single tweet. Returns tweet_dict or None."""
    from src.worker.extractor import PromptExtractor
    from src.worker.scorer import QualityScorer
    from src.types.prompt import ExtractedPrompt
    from src.types.config import QualityConfig, QualityWeights, QualityThresholds

    qual_cfg = QualityConfig(
        weights=QualityWeights(
            specificity=0.25, visual_detail=0.30, novelty=0.20, generatable=0.25
        ),
        thresholds=QualityThresholds(
            min_overall=0.40, good_overall=0.60,
            min_specificity=0.30, min_visual_detail=0.20,
        ),
    )
    extractor = PromptExtractor(
        llm_client=GeminiLLMAdapter(),
        categories=[
            "cinematic", "video-generation", "other",
            "character-design", "product-photography",
        ],
    )
    scorer = QualityScorer(llm_client=GeminiLLMAdapter(), quality_config=qual_cfg)

    try:
        er = extractor.extract(tweet)
        if not er.is_prompt:
            return None

        ep = ExtractedPrompt(
            tweet_id=tweet.tweet_id,
            url=tweet.url,
            category=er.category or "other",
            title=er.title or tweet.short_text[:60],
            prompt_text=er.prompt_text or tweet.text[:200],
            author=tweet.author,
            likes_count=tweet.favorite_count,
            retweet_count=tweet.retweet_count,
            reply_count=tweet.reply_count,
            view_count=tweet.view_count,
        )
        qs = scorer.score(ep)
        if qs.overall < 0.40:
            return None

        tweet_dict = {
            "tweet_id": tweet.tweet_id,
            "url": tweet.url,
            "category": _norm_category(er.category),
            "title": er.title or tweet.short_text[:60],
            "prompt_text": er.prompt_text or tweet.text[:200],
            "author_name": tweet.author.name,
            "author_screen": tweet.author.screen_name,
            "likes_count": tweet.favorite_count,
            "retweet_count": tweet.retweet_count,
            "reply_count": tweet.reply_count,
            "view_count": tweet.view_count,
            "quality_scores": str(qs.overall),
        }
        return tweet_dict
    except Exception as e:
        logger.warning("Extract/score failed for %s: %s", tweet.tweet_id, e)
        return None


def _embed_prompt(prompt_dict: dict, conn) -> bool:
    """Generate and store embedding for a prompt. Returns True on success."""
    from src.agent.memory.embedding import embed_text

    row = conn.execute(
        "SELECT id FROM prompts WHERE tweet_id = ?", (prompt_dict["tweet_id"],)
    ).fetchone()
    if not row:
        return False
    prompt_id = row["id"]
    text = f"{prompt_dict['title']}: {prompt_dict['prompt_text']}"
    try:
        vec = embed_text(text)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO prompt_embeddings (prompt_id, embedding, model, created_at) VALUES (?, ?, ?, ?)",
            (prompt_id, json.dumps(vec), EMBEDDING_MODEL, now),
        )
        conn.execute(
            "UPDATE prompts SET embedding_status = 'embedded' WHERE id = ?",
            (prompt_id,),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.warning("Embedding failed for prompt_id=%s: %s", prompt_id, e)
        conn.execute(
            "UPDATE prompts SET embedding_status = 'failed' WHERE id = ?",
            (prompt_id,),
        )
        conn.commit()
        return False


# ── Main import ────────────────────────────────────────────────────────────────


def import_data(dry_run: bool = False) -> dict[str, int]:
    """Run the full import pipeline. Returns stats dict."""
    from src.memory.schema import init_db

    all_tweets = _load_crawl_tweets()
    logger.info("Loaded %d tweets from crawl file", len(all_tweets))

    gate_passed = _engagement_gate(all_tweets)
    logger.info(
        "Engagement gate: %d/%d passed (likes>=%d, views>=%d, followers>=%d)",
        len(gate_passed), len(all_tweets), MIN_LIKES, MIN_VIEWS, MIN_FOLLOWERS,
    )

    if not gate_passed:
        logger.warning("No tweets passed engagement gate")
        return {"total": 0, "gate_passed": 0, "qualified": 0, "embedded": 0}

    tweets = [_dict_to_tweet(d) for d in gate_passed]

    # Parallel extract + score
    results: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=EXTRACTOR_CONCURRENCY) as ex:
        futures = {ex.submit(_extract_and_score, t): i for i, t in enumerate(tweets)}
        done = 0
        for fut in as_completed(futures):
            result = fut.result()
            idx = futures[fut]
            if result is not None:
                results[idx] = result
            done += 1
            if done % 20 == 0:
                logger.info("  Extract/score: %d/%d done", done, len(tweets))

    qualified = list(results.values())
    logger.info("Qualified after extract/score: %d/%d", len(qualified), len(gate_passed))

    if dry_run:
        for q in qualified:
            logger.info(
                "[DRY-RUN] tweet_id=%s category=%s score=%s",
                q["tweet_id"], q["category"], q["quality_scores"],
            )
        return {
            "total": len(all_tweets),
            "gate_passed": len(gate_passed),
            "qualified": len(qualified),
            "embedded": 0,
        }

    conn = init_db()
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    embedded_ok = 0
    embedded_fail = 0

    for q in qualified:
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO prompts (
                    tweet_id, url, category, title, prompt_text,
                    author_name, author_screen,
                    likes_count, retweet_count, reply_count, view_count,
                    quality_scores, extracted_at, image_status, embedding_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'pending')
                """,
                (
                    q["tweet_id"], q["url"], q["category"],
                    q["title"], q["prompt_text"],
                    q.get("author_name"), q.get("author_screen"),
                    q["likes_count"], q["retweet_count"],
                    q["reply_count"], q["view_count"],
                    q["quality_scores"], now,
                ),
            )
            conn.commit()
        except Exception as e:
            logger.warning("DB insert failed for %s: %s", q["tweet_id"], e)
            continue

        if _embed_prompt(q, conn):
            embedded_ok += 1
        else:
            embedded_fail += 1
        inserted += 1

    return {
        "total": len(all_tweets),
        "gate_passed": len(gate_passed),
        "qualified": len(qualified),
        "inserted": inserted,
        "embedded_ok": embedded_ok,
        "embedded_fail": embedded_fail,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Import V1/V2 tweet data into V3 schema")
    parser.add_argument("--dry-run", action="store_true", help="Run without writing to DB")
    args = parser.parse_args()

    logger.info("Starting import pipeline")
    stats = import_data(dry_run=args.dry_run)

    print("\n=== Import Statistics ===")
    print(f"  Total tweets in file:     {stats['total']}")
    print(f"  Passed engagement gate:  {stats['gate_passed']}")
    print(f"  Qualified (LLM filter):   {stats['qualified']}")
    print(f"  Written to DB:           {stats.get('inserted', 0)}")
    print(f"  Embedding succeeded:    {stats.get('embedded_ok', 0)}")
    print(f"  Embedding failed:       {stats.get('embedded_fail', 0)}")
    print("=============================")

    if args.dry_run:
        logger.info("[DRY-RUN] No data was written.")


if __name__ == "__main__":
    main()