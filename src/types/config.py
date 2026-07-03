"""Pipeline configuration types, merged from configs/*.yaml."""

from dataclasses import dataclass, field
from enum import Enum


# Re-export ImageModel enum from pipeline module for convenience
class ImageModel(Enum):
    """Available Gemini image generation models."""
    GEMINI_3_PRO_IMAGE_PREVIEW     = "gemini-3-pro-image-preview"
    GEMINI_3_1_FLASH_IMAGE_PREVIEW = "gemini-3.1-flash-image-preview"
    GEMINI_2_5_FLASH_IMAGE          = "gemini-2.5-flash-image"


@dataclass
class PipelineConfig:
    """Merged configuration from all YAML config files."""
    queries: "QueriesConfig"
    engagement: "EngagementConfig"
    crawler: "CrawlerConfig"
    llm: "LLMConfig"
    gemini: "GeminiConfig"
    quality: "QualityConfig"


@dataclass
class QueriesConfig:
    """Query planning configuration."""
    seed_queries: list[str]
    negative_keywords: list[str]
    expansion: "ExpansionConfig"


@dataclass
class ExpansionConfig:
    """Query expansion configuration."""
    top_n_queries: int = 5
    new_query_count: int = 8
    min_yield_threshold: float = 0.01


@dataclass
class EngagementConfig:
    """Engagement thresholds for filtering tweets."""
    min_likes: int = 50
    min_followers: int = 1000
    min_views: int = 1000
    max_tweets_per_query: int = 200


@dataclass
class CrawlerConfig:
    """Crawler behavior configuration."""
    max_scrolls: int = 20
    stale_threshold: int = 3
    delay_ms_min: int = 100
    delay_ms_max: int = 500
    page_goto_timeout_ms: int = 60000
    selector_wait_ms: int = 15000
    scroll_wait_ms: int = 5000
    proxy_enabled: bool = True
    proxy_server: str = "http://127.0.0.1:7897"
    cookie_age_days: int = 7
    max_search_contexts: int = 3
    max_enrichment_tasks: int = 5
    # Apify integration
    type: str = "browser"  # "browser" or "apify"
    apify_actor_id: str = "nfp1fpt5gUlBwPcor"
    apify_api_token_env: str = "APIFY_API_TOKEN"
    apify_timeout_ms: int = 600_000  # 10 min — enough for $1 budget (~36 pages)
    apify_max_retries: int = 2
    apify_retry_delay_s: int = 30
    apify_max_cost_usd: float = 1.0


@dataclass
class LLMConfig:
    """LLM API configuration."""
    provider: str = "minimax"  # "minimax" or "gemini"
    api_base: str = "https://api.minimaxi.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    default_model: str = "MiniMax-M2.7"
    extraction_timeout: int = 60
    scoring_timeout: int = 45
    query_expansion_timeout: int = 30
    extraction_concurrency: int = 15
    scoring_concurrency: int = 10
    query_expansion_concurrency: int = 1
    # Vertex AI Gemini text-generation settings (provider == "gemini")
    gemini_project: str = "sparki-op"
    gemini_location: str = "global"
    gemini_default_model: str = "gemini-3.5-flash"


@dataclass
class GeminiConfig:
    """Gemini image generation configuration."""
    project: str = "sparki-op"
    location: str = "global"
    gcs_bucket: str = "sparki-op-test"
    image_models: list[str] = field(default_factory=lambda: [
        "gemini-3-pro-image-preview",
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-image",
    ])
    generation_concurrency: int = 3
    max_retries_per_model: int = 3
    retry_delay_base: int = 5
    style_keywords: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class QualityConfig:
    """Quality scoring configuration."""
    weights: "QualityWeights"
    thresholds: "QualityThresholds"


@dataclass
class QualityWeights:
    """Weights for computing overall quality score."""
    specificity: float = 0.25
    visual_detail: float = 0.30
    novelty: float = 0.20
    generatable: float = 0.25


@dataclass
class QualityThresholds:
    """Thresholds for quality filtering."""
    min_overall: float = 0.40
    good_overall: float = 0.60
    min_specificity: float = 0.30
    min_visual_detail: float = 0.20
