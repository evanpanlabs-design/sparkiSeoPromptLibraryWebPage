"""Shared type schemas for Sparki Agent pipeline."""

from src.types.tweet import Tweet, AuthorRef
from src.types.prompt import ExtractedPrompt, ScoredPrompt, QualityScores
from src.types.image import ImageResult, ImageGenStatus
from src.types.query import QueryCandidate, QueryMetrics
from src.types.author import AuthorMetrics
from src.types.category import CategorySuggestion, CategorySuggestionStatus
from src.types.pipeline import (
    PipelineStats,
    PipelineError,
    PipelinePhase,
    RouterDecision,
    NodeStatus,
)
from src.types.config import (
    PipelineConfig,
    QueriesConfig,
    ExpansionConfig,
    EngagementConfig,
    CrawlerConfig,
    LLMConfig,
    GeminiConfig,
    QualityConfig,
    QualityWeights,
    QualityThresholds,
)
from src.types.react import IntentType, ReActStep, ToolCallResult

__all__ = [
    # Tweet types
    "Tweet",
    "AuthorRef",
    # Prompt types
    "ExtractedPrompt",
    "ScoredPrompt",
    "QualityScores",
    # Image types
    "ImageResult",
    "ImageGenStatus",
    # Query types
    "QueryCandidate",
    "QueryMetrics",
    # Author types
    "AuthorMetrics",
    # Category types
    "CategorySuggestion",
    "CategorySuggestionStatus",
    # Pipeline types
    "PipelineStats",
    "PipelineError",
    "PipelinePhase",
    "RouterDecision",
    "NodeStatus",
    # Config types
    "PipelineConfig",
    "QueriesConfig",
    "ExpansionConfig",
    "EngagementConfig",
    "CrawlerConfig",
    "LLMConfig",
    "GeminiConfig",
    "QualityConfig",
    "QualityWeights",
    "QualityThresholds",
    # React types
    "IntentType",
    "ReActStep",
    "ToolCallResult",
]