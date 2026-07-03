"""Tweet and Author type definitions."""

from dataclasses import dataclass, field


@dataclass
class AuthorRef:
    """Reference to a tweet author."""
    name: str                           # Display name
    screen_name: str                    # Handle (without @)
    profile_url: str                    # /{screen_name}
    followers_count: int = 0
    is_blue_verified: bool = False


@dataclass
class Tweet:
    """A tweet scraped from X.com."""
    tweet_id: str                       # X.com status ID (e.g. "1234567890")
    url: str                             # Full https://x.com/user/status/{id}
    text: str                            # Full tweet text (after enrichment visit)
    short_text: str                      # Truncated text from search card (pre-enrichment)
    author: AuthorRef                    # Always non-null after enrichment
    created_at: str | None = None       # ISO8601 datetime
    favorite_count: int = 0              # Likes
    retweet_count: int = 0
    reply_count: int = 0
    view_count: int = 0                  # 0 if unavailable
    source_query: str = ""               # Which search query found this tweet
    scraped_at: str = ""                 # ISO8601, set at scrape time
    author_enriched: bool = False        # Profile page visited, followers fetched
    detail_enriched: bool = False       # Tweet detail page visited, views fetched

    def dedup_key(self) -> str:
        """Return the deduplication key for this tweet."""
        return self.tweet_id
