"""Async scroll-and-extract loop for X.com search pages."""

import asyncio
import random

from playwright.async_api import Page

from src.crawler.extraction import TweetExtractor


async def scroll_and_extract(
    page: Page,
    max_scrolls: int = 20,
    stale_threshold: int = 5,
    delay_ms: tuple[int, int] = (100, 500),
) -> list[dict]:
    """Scroll-to-bottom loop with extraction at each step.

    Stops early when no new tweets appear for stale_threshold consecutive scrolls.
    Returns deduplicated list of all extracted tweets.

    Args:
        page: Playwright Page object
        max_scrolls: Maximum number of scroll operations
        stale_threshold: Stop after this many consecutive scrolls with no new tweets
        delay_ms: Random delay range between scrolls (min, max)

    Returns:
        Deduplicated list of tweet dicts from extract_search_tweets
    """
    all_tweets = []
    seen_ids = set()
    stale_count = 0

    for i in range(max_scrolls):
        # Jump to bottom — X.com loads content from bottom-up
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        # Adaptive wait: fast initially, slow when content is drying up
        base_delay = 1.5
        if stale_count >= 1:
            base_delay = 3.0  # At bottom, give more time for lazy load
        await asyncio.sleep(random.uniform(base_delay, base_delay + 1.0))

        tweets = await TweetExtractor.extract_search_tweets(page)

        new_count = 0
        for t in tweets:
            if t["tweet_id"] not in seen_ids:
                seen_ids.add(t["tweet_id"])
                all_tweets.append(t)
                new_count += 1

        print(f"    Scroll {i+1}/{max_scrolls} — {len(tweets)} in DOM, {new_count} new, total: {len(all_tweets)}")

        if new_count == 0:
            stale_count += 1
            if stale_count >= stale_threshold:
                print(f"  No new tweets for {stale_threshold} scrolls — stopping early.")
                break
        else:
            stale_count = 0

        # Random delay between scrolls
        await asyncio.sleep(random.uniform(delay_ms[0], delay_ms[1]) / 1000.0)

    return all_tweets