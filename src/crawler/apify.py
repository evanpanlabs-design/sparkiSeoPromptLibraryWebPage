"""ApifyCrawler — Apify Actor-based X.com scraper.

satisfies the same interface as Playwright crawl:
  async def crawl(query: str) -> list[dict]

Each returned dict follows the TweetExtractor.extract_search_tweets format:
  tweet_id, tweet_url, profile_url, author_name, author_screen,
  short_text, created_at, favorite_count, retweet_count, reply_count, view_count
"""

import asyncio
import os
from dotenv import load_dotenv
load_dotenv()
import time
from dataclasses import dataclass
from typing import Any


def _apify_client_available() -> bool:
    try:
        import apify_client  # noqa: F401
        return True
    except ImportError:
        return False


@dataclass
class ApifyConfig:
    """Apify-specific configuration."""
    actor_id: str
    api_token: str
    timeout_ms: int = 120_000
    max_retries: int = 2
    retry_delay_s: int = 30


class ApifyCrawler:
    """Crawler that delegates to an Apify Actor instead of Playwright.

    The Actor is expected to return tweets in the same format as
    TweetExtractor.extract_search_tweets (see extraction.py).
    """

    def __init__(
        self,
        actor_id: str,
        api_token: str,
        timeout_ms: int = 600_000,
        max_retries: int = 2,
        retry_delay_s: int = 30,
    ):
        self.actor_id = actor_id
        self.api_token = api_token or os.environ.get("APIFY_API_TOKEN", "")
        self.config = ApifyConfig(
            actor_id=actor_id,
            api_token=self.api_token,
            timeout_ms=timeout_ms,
            max_retries=max_retries,
            retry_delay_s=retry_delay_s,
        )
        self._client: Any | None = None

    def _get_client(self) -> Any:
        """Lazily init and return the Apify client."""
        if self._client is None:
            from apify_client import ApifyClient
            self._client = ApifyClient(token=self.api_token)
        return self._client

    def _map_actor_item(self, item: dict) -> dict | None:
        """Map an Apify twitter-scraper-lite output item to TweetExtractor format.

        Apify twitter-scraper-lite output fields (confirmed from live run):
          id, url, twitterUrl, text, fullText, source,
          likeCount, retweetCount, replyCount, quoteCount, viewCount, bookmarkCount,
          createdAt, lang, isReply, isRetweet, isQuote,
          author: { userName, url, twitterUrl, id, name, isBlueVerified,
                    followers, following, description, ... }
        """
        try:
            tweet_id = str(item.get("id") or "")
            if not tweet_id:
                return None

            # Resolve author object
            author = item.get("author") or {}
            author_screen = author.get("userName") or ""
            author_name = author.get("name") or ""
            author_url = author.get("url") or f"https://x.com/{author_screen}"

            # Tweet URL — prefer x.com URL
            tweet_url = item.get("url") or f"https://x.com/{author_screen}/status/{tweet_id}"

            # Text
            text = item.get("text") or item.get("fullText") or ""

            # Engagement
            favorite_count = int(item.get("likeCount") or 0)
            retweet_count = int(item.get("retweetCount") or 0)
            reply_count = int(item.get("replyCount") or 0)
            view_count = int(item.get("viewCount") or 0)

            # Timestamp — Apify returns "Tue May 19 23:09:01 +0000 2026"
            created_at = item.get("createdAt") or None

            return {
                "tweet_id": tweet_id,
                "url": tweet_url,                   # full https://x.com/... URL (Playwright format)
                "text": text,                         # full text = short_text for Apify (no detail visit)
                "short_text": text,
                "author": {                           # nested dict (Playwright format)
                    "name": author_name,
                    "screen_name": author_screen,
                    "profile_url": author_url,
                    "followers_count": int(author.get("followers", 0)),
                },
                "created_at": created_at,
                "favorite_count": favorite_count,
                "retweet_count": retweet_count,
                "reply_count": reply_count,
                "view_count": view_count,
                "scraped_at": "",                     # filled by caller if needed
                "author_enriched": False,             # Apify provides followers from search context
                "detail_enriched": False,
            }
        except Exception:
            return None

    async def crawl(
        self,
        query: str,
        max_cost_usd: float = 0.05,
        max_items: int = 100,
        sort: str = "Latest + Top",
        include_search_terms: bool = False,
    ) -> list[dict]:
        """Run the Apify Actor for a single query and return tweet dicts.

        Args:
            query: Search term for X.com (used as searchTerms item).
            max_cost_usd: Max spend per run (~$0.05 = ~10 tweets on this Actor).
            max_items: Maximum number of tweets to collect (Apify maxItems).
            sort: Sort order — "Latest + Top" | "Latest" | "Top".
            include_search_terms: Whether to include searchTerms in results.

        Returns:
            list of tweet dicts in TweetExtractor format.
        """
        if not _apify_client_available():
            raise RuntimeError(
                "apify-client is not installed. Install with: pip install apify-client"
            )

        client = self._get_client()
        timeout_secs = self.config.timeout_ms // 1000

        last_error: str | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                print(f"  [Apify] Starting actor run for query: '{query}' (attempt {attempt + 1})")
                # Use .call() — blocks until Actor finishes, then returns with dataset
                result = client.actor(self.actor_id).call(
                    run_input={
                        "searchTerms": [query],
                        "maxItems": max_items,
                        "sort": sort,
                        "includeSearchTerms": include_search_terms,
                    },
                    max_total_charge_usd=max_cost_usd,
                    timeout_secs=timeout_secs,
                )

                status = result.get("status", "")
                if status not in ("SUCCEEDED", "TIMED-OUT"):
                    raise RuntimeError(
                        f"Actor run {status}: {result.get('statusMessage', 'unknown')}"
                    )

                # Dataset ID is at the top level of the call result
                dataset_id = result.get("defaultDatasetId")
                if not dataset_id:
                    # Fallback: fetch from run object
                    run = client.actor(self.actor_id).run(result["id"]).get()
                    dataset_id = run.get("defaultDatasetId")

                # TIMED-OUT still has data in dataset — fetch it even on timeout
                if not dataset_id:
                    raise RuntimeError("No dataset ID returned from Actor run")

                items_response = client.dataset(dataset_id).list_items()
                raw_items = items_response.items

                tweets = []
                for item in raw_items:
                    mapped = self._map_actor_item(item)
                    if mapped:
                        tweets.append(mapped)

                print(f"  [Apify] Got {len(tweets)} tweets for '{query}' (cost: ${max_cost_usd})")
                return tweets

            except Exception as e:
                last_error = str(e)
                print(f"  [Apify] Attempt {attempt + 1} failed: {e}")
                if attempt < self.config.max_retries:
                    await asyncio.sleep(self.config.retry_delay_s)

        raise RuntimeError(f"Apify crawl failed after {self.config.max_retries + 1} attempts: {last_error}")
