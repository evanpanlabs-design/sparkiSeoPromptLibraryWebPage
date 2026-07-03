"""Pipeline-level types: phases, stats, errors, and routing."""

from dataclasses import dataclass, field
from enum import Enum


class PipelinePhase(Enum):
    """Current phase of the pipeline."""
    INITIALIZING   = "initializing"
    QUERY_PLANNING = "query_planning"
    CRAWLING       = "crawling"
    EXTRACTING     = "extracting"
    SCORING        = "scoring"
    IMAGING        = "imaging"
    COMPOSING      = "composing"
    DONE           = "done"
    FAILED         = "failed"
    WAITING_HUMAN  = "waiting_human"   # paused at router_node


class RouterDecision(Enum):
    """Decision made by the router node."""
    CONTINUE        = "continue"        # Proceed to next phase
    RETRY           = "retry"          # Retry current node (with backoff)
    SKIP            = "skip"           # Skip this item, continue
    WAIT_HUMAN      = "wait_human"     # Pause for human review
    EARLY_DONE      = "early_done"     # No more data, finish cleanly
    ERROR           = "error"          # Unrecoverable error


class NodeStatus(Enum):
    """Status of a node execution."""
    SUCCESS   = "success"
    RETRYING  = "retrying"
    FAILED    = "failed"
    SKIPPED   = "skipped"


@dataclass
class PipelineStats:
    """Statistics maintained by all nodes."""
    phase_started_at: str = ""          # ISO8601 of current phase start
    phase_elapsed_seconds: float = 0.0

    # Counts (cumulative)
    tweets_collected: int = 0
    tweets_deduped: int = 0
    prompts_extracted: int = 0
    prompts_scored: int = 0
    images_generated: int = 0
    images_failed: int = 0
    categories_pending: int = 0

    # Cost estimation (USD)
    estimated_llm_cost_usd: float = 0.0
    estimated_image_gen_cost_usd: float = 0.0

    # Phase-level counts (reset per phase)
    phase_tweets_processed: int = 0
    phase_items_succeeded: int = 0
    phase_items_failed: int = 0

    def current_phase_duration(self) -> float:
        """Return the duration of the current phase."""
        return self.phase_elapsed_seconds


@dataclass
class PipelineError:
    """An error collected during pipeline execution."""
    phase: PipelinePhase               # Phase during which error occurred
    node: str                          # Node function name (e.g. "crawler_node")
    error_type: str                     # "CrawlError" | "LLMError" | "ImageGenError" | etc.
    error_message: str
    item_id: str | None = None         # tweet_id, prompt_id, etc. if applicable
    timestamp: str = ""                 # ISO8601

    def is_retryable(self) -> bool:
        """Check if this error is retryable."""
        return self.error_type in {
            "TooManyRequestsError",
            "RateLimitError",
            "TimeoutError",
            "TemporaryGCSError",
        }
