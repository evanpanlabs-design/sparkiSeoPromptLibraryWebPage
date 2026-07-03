"""Exception hierarchy for Sparki pipeline.

All exceptions raised inside nodes are caught and converted to PipelineError
and collected in AgentState.node_errors. Only ConfigError is allowed to
propagate as a fatal exception.
"""


class CrawlError(Exception):
    """Base exception for crawler-related errors."""
    pass


class TooManyRequestsError(CrawlError):
    """Rate limit exceeded during crawling. Retryable with 15min wait."""
    pass


class EnrichmentError(CrawlError):
    """Error during tweet/author enrichment. Non-retryable."""
    pass


class LLMError(Exception):
    """Base exception for LLM-related errors."""

    def __init__(self, message: str = "", is_retryable: bool = False):
        super().__init__(message)
        self.is_retryable = is_retryable


class LLMParseError(LLMError):
    """Failed to parse LLM response. Non-retryable."""
    pass


class ScoringError(Exception):
    """Error during quality scoring. Retryable with 2 retries."""
    pass


class ImageGenError(Exception):
    """Base exception for image generation errors."""
    pass


class RateLimitError(ImageGenError):
    """Rate limit exceeded during image generation. Retryable at model level."""
    pass


class GCSError(Exception):
    """Error interacting with Google Cloud Storage. Non-retryable."""
    pass


class DeduplicationError(Exception):
    """Error during tweet deduplication. Non-retryable."""
    pass


class ConfigError(Exception):
    """Configuration error (missing/invalid config). Fatal - pipeline fails."""
    pass


class DBError(Exception):
    """Database error. Non-retryable."""
    pass
