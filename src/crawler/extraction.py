"""TweetExtractor — DOM parsing for X.com search results."""

import re
from typing import TypedDict

from playwright.async_api import Page


class TweetExtractor:
    """Parses [data-testid='tweet'] elements from X.com search pages."""

    @staticmethod
    def parse_metric(text: str) -> int:
        """Parse metric strings like '1.29K', '3.5M', '1,234' to an integer."""
        if not text:
            return 0
        text = text.strip().replace(",", "")
        if not text:
            return 0
        mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
        if text[-1] in mult:
            try:
                return int(float(text[:-1]) * mult[text[-1]])
            except ValueError:
                return 0
        try:
            return int(text)
        except ValueError:
            return 0

    @staticmethod
    def text_matches_all_keywords(text: str, keywords: list[str]) -> bool:
        """Return True if text contains ALL keywords (case-insensitive)."""
        text_lower = text.lower()
        return all(kw.lower() in text_lower for kw in keywords)

    @staticmethod
    async def extract_search_tweets(page: Page) -> list[dict]:
        """Extract all [data-testid='tweet'] elements currently in the DOM.

        Returns list of raw tweet dicts with fields:
          tweet_id, tweet_url, profile_url, author_name, author_screen,
          short_text, created_at, favorite_count, retweet_count,
          reply_count, view_count
        """
        results = []
        tweets = await page.query_selector_all('[data-testid="tweet"]')

        for tweet in tweets:
            try:
                user_name_elem = await tweet.query_selector('[data-testid="User-Name"]')
                if not user_name_elem:
                    continue

                # Find profile URL (not /status/ links)
                profile_url = None
                links = await user_name_elem.query_selector_all("a")
                for link in links:
                    href = await link.get_attribute("href") or ""
                    if "/status/" not in href and href not in ("/", "") and "?" not in href:
                        profile_url = href
                        break
                if not profile_url:
                    continue

                # Extract display name and screen name from spans
                spans = await user_name_elem.query_selector_all("span")
                display_name = ""
                screen_name = ""
                for span in spans:
                    t = await span.inner_text()
                    if display_name == "" and t:
                        display_name = t
                    if t.startswith("@"):
                        screen_name = t.lstrip("@")
                        break

                # Extract tweet URL and ID
                tweet_url = None
                all_links = await tweet.query_selector_all("a")
                for link in all_links:
                    href = await link.get_attribute("href") or ""
                    if "/status/" in href and "/analytics" not in href:
                        tweet_url = href
                        break
                if not tweet_url:
                    continue
                tweet_id = tweet_url.split("/status/")[-1].split("?")[0]

                # Extract text
                text_elem = await tweet.query_selector('[data-testid="tweetText"]')
                short_text = await text_elem.inner_text() if text_elem else ""

                # Extract engagement metrics
                like_count = await TweetExtractor._get_metric(
                    tweet, "[data-testid='like']"
                )
                rt_count = await TweetExtractor._get_metric(
                    tweet, "[data-testid='retweet']"
                )
                reply_count = await TweetExtractor._get_metric(
                    tweet, "[data-testid='reply']"
                )
                view_count = await TweetExtractor._get_metric(
                    tweet, "[data-testid='viewCount']"
                )

                # Extract timestamp
                time_elem = await tweet.query_selector("time")
                created_at = await time_elem.get_attribute("datetime") if time_elem else None

                results.append({
                    "tweet_id": tweet_id,
                    "tweet_url": tweet_url,
                    "profile_url": profile_url,
                    "author_name": display_name,
                    "author_screen": screen_name,
                    "short_text": short_text,
                    "created_at": created_at,
                    "favorite_count": like_count,
                    "retweet_count": rt_count,
                    "reply_count": reply_count,
                    "view_count": view_count,
                })
            except Exception:
                continue

        return results

    @staticmethod
    async def _get_metric(tweet, selector: str) -> int:
        """Extract metric value from a tweet element."""
        try:
            el = await tweet.query_selector(selector)
            if el:
                text = await el.inner_text()
                return TweetExtractor.parse_metric(text)
        except Exception:
            pass
        return 0

    @staticmethod
    def extract_tweet_detail_text(page: Page) -> str:
        """Extract full tweet text from a tweet detail page."""
        try:
            text_elem = page.locator("[data-testid='tweetText']").first
            return text_elem.inner_text()
        except Exception:
            return ""

    @staticmethod
    def extract_view_count(page: Page) -> int:
        """Extract view count from a tweet detail page."""
        try:
            view_elem = page.locator("[data-testid='viewCount']").first
            return TweetExtractor.parse_metric(view_elem.inner_text())
        except Exception:
            return 0

    @staticmethod
    def extract_follower_count(body_text: str) -> int:
        """Parse follower count from profile page body text.

        Looks for a line containing 'Followers' and returns the number before it.
        """
        for line in body_text.split("\n"):
            if "Followers" in line:
                parts = line.strip().split()
                if parts:
                    return TweetExtractor.parse_metric(parts[0])
        return 0