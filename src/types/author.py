"""Author metrics types."""

from dataclasses import dataclass


@dataclass
class AuthorMetrics:
    """Metrics tracking an author's contribution quality over time."""
    screen_name: str
    display_name: str
    profile_url: str

    followers_count: int = 0

    # Prompt history
    total_prompts: int = 0
    qualified_prompts: int = 0
    high_value_ratio: float = 0.0       # qualified_prompts / total_prompts

    last_active_at: str = ""            # ISO8601 of most recent prompt tweet
    last_crawled_at: str = ""           # ISO8601 of last crawl that included this author

    is_high_value: bool = False        # True if high_value_ratio > 0.5 and total >= 3
