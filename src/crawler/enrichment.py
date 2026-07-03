"""Enrichment — visits author profile and tweet detail pages to fetch extra data."""

import asyncio
import random
from datetime import datetime, timezone

from playwright.async_api import BrowserContext

from src.crawler.extraction import TweetExtractor


async def enrich_tweet(
    context: BrowserContext,
    tweet_dict: dict,
    min_followers: int = 0,
    min_views: int = 0,
    delay_ms: tuple[int, int] = (100, 600),
) -> dict | None:
    """Enrich a single tweet by visiting author profile and tweet detail pages.

    Args:
        context: Playwright browser context
        tweet_dict: Raw tweet dict from extract_search_tweets
        min_followers: Minimum followers threshold (filter if below)
        min_views: Minimum views threshold (filter if below)
        delay_ms: Random delay range between page visits

    Returns:
        Enriched tweet dict with followers_count, full text, view_count,
        author_enriched=True, detail_enriched=True; or None if filtered out.
    """
    screen = tweet_dict["author_screen"]


    # ── Step 1: Visit author profile to get followers_count ──────────────────
    await asyncio.sleep(random.uniform(delay_ms[0], delay_ms[1]) / 1000.0)
    followers = await _get_follower_count(context, tweet_dict["profile_url"])
    print(f"  @{screen} followers={followers}", end=" | ", flush=True)

    if min_followers > 0 and followers < min_followers:
        print("FILTERED (followers)")
        return None

    # ── Step 2: Visit tweet detail to get full text and views ───────────────
    await asyncio.sleep(random.uniform(delay_ms[0], delay_ms[1]) / 1000.0)
    full_text, detail_views = await _get_tweet_detail(
        context, tweet_dict["tweet_url"]
    )
    view_count = detail_views if detail_views > 0 else tweet_dict["view_count"]
    print(f"views={view_count}", end=" | ", flush=True)

    if view_count > 0 and min_views > 0 and view_count < min_views:
        print("FILTERED (views)")
        return None

    if not full_text:
        full_text = tweet_dict["short_text"]

    print(f"  @{screen} text: {full_text[:120]}", end=" | ", flush=True)

    # ── Step 3: Build enriched tweet dict ────────────────────────────────────
    enriched = {
        "tweet_id": tweet_dict["tweet_id"],
        "url": f"https://x.com{tweet_dict['tweet_url']}",
        "text": full_text,
        "short_text": tweet_dict["short_text"],
        "author": {
            "name": tweet_dict["author_name"],
            "screen_name": screen,
            "profile_url": tweet_dict["profile_url"],
            "followers_count": followers,
        },
        "created_at": tweet_dict["created_at"],
        "favorite_count": tweet_dict["favorite_count"],
        "retweet_count": tweet_dict["retweet_count"],
        "reply_count": tweet_dict["reply_count"],
        "view_count": view_count,
        "author_enriched": True,
        "detail_enriched": True,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }
    print(f"  text: {full_text[:100]}...")
    print("PASSED")
    return enriched


async def _get_follower_count(context: BrowserContext, profile_url: str) -> int:
    """Visit author profile page and parse follower count."""
    try:
        page = await context.new_page()
        await page.goto(
            f"https://x.com{profile_url}",
            timeout=30_000,
            wait_until="domcontentloaded",
        )
        await asyncio.sleep(3)
        body = await page.locator("body").inner_text()
        await page.close()

        return TweetExtractor.extract_follower_count(body)
    except Exception:
        try:
            await page.close()
        except Exception:
            pass
        return 0


async def _get_tweet_detail(context: BrowserContext, tweet_url: str) -> tuple[str, int]:
    """Visit tweet detail page and extract full text + view count."""
    try:
        page = await context.new_page()
        await page.goto(
            f"https://x.com{tweet_url}",
            timeout=30_000,
            wait_until="domcontentloaded",
        )
        await page.wait_for_selector(
            "[data-testid='tweetText']",
            timeout=15_000,
        )
        full_text = await page.locator("[data-testid='tweetText']").first.inner_text()

        view_count = 0
        try:
            view_elem = await page.query_selector("[data-testid='viewCount']")
            if view_elem:
                view_count = TweetExtractor.parse_metric(await view_elem.inner_text())
        except Exception:
            pass

        await page.close()
        return full_text, view_count
    except Exception:
        try:
            await page.close()
        except Exception:
            pass
        return "", 0