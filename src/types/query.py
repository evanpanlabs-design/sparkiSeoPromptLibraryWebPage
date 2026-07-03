"""Query planning and metrics types."""

from dataclasses import dataclass, field


@dataclass
class QueryCandidate:
    """A search query candidate for crawling."""
    text: str                           # The search keyword/string
    source: str                         # "seed" | "expansion" | "author_followup"
    scroll_budget: int = 20             # How many scroll cycles to run
    priority: float = 1.0               # 0.0–1.0, higher = more important
    negative_keywords: list[str] = field(default_factory=list)  # from engagement.yaml

    # Populated after crawl
    tweets_raw: int = 0
    tweets_filtered: int = 0
    error_message: str | None = None


@dataclass
class QueryMetrics:
    """Metrics and statistics for a query across runs."""
    query_text: str
    scrape_run_id: int

    # Funnel counts
    tweets_raw: int = 0
    tweets_filtered: int = 0             # After Round-1 (likes) + Round-2 (followers/views)
    prompts_extracted: int = 0
    qualified_prompts: int = 0          # quality_score >= min_overall threshold

    # Rates
    qualified_rate: float = 0.0         # qualified_prompts / tweets_filtered
    prompt_yield_rate: float = 0.0     # prompts_extracted / tweets_filtered

    # History
    run_count: int = 1
    last_run_at: str = ""               # ISO8601

    # Planner hints (set by feedback_node)
    scroll_budget_hint: int = 20        # Recommended scroll_budget for next run
    is_active: bool = True              # False → prune from future runs
