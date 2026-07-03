"""Prompt extraction and quality scoring types."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.types.image import ImageGenStatus
from src.types.tweet import AuthorRef

if TYPE_CHECKING:
    pass


@dataclass
class QualityScores:
    """Quality scores for a prompt, all ranging 0.0 (worst) to 1.0 (best)."""
    specificity: float = 0.0            # Detail level of visual description
    visual_detail: float = 0.0         # Camera, lighting, composition terms
    novelty: float = 0.0                # Uniqueness/rarity of structure
    generatable: float = 0.0            # Can this directly drive generation?

    # Computed
    overall: float = 0.0                # Weighted average (weights in quality.yaml)

    def is_qualified(self, threshold: float = 0.40) -> bool:
        """Check if prompt meets the minimum quality threshold."""
        return self.overall >= threshold

    def should_generate_image(self, threshold: float = 0.40) -> bool:
        """Check if an image should be generated for this prompt."""
        return self.overall >= threshold


@dataclass
class ExtractedPrompt:
    """A prompt extracted from a tweet."""
    tweet_id: str                       # Foreign key to source Tweet
    url: str                            # https://x.com/user/status/{id}
    category: str                       # e.g. "video-generation", "cinematic"
    title: str                          # Short descriptive title (≤ 60 chars)
    prompt_text: str                    # The actual prompt content
    author: AuthorRef                    # Author who posted the tweet
    notes: str = ""                      # LLM explanation of why this qualifies
    likes_count: int = 0                # Likes on the source tweet
    retweet_count: int = 0              # Retweets on the source tweet
    reply_count: int = 0                # Replies on the source tweet
    view_count: int = 0                 # Views on the source tweet
    extracted_at: str = ""               # ISO8601, set by worker_node
    quality_scores: "QualityScores | None" = None  # Populated by quality_scorer_node
    needs_image: bool = True            # Set False for low-quality or duplicate
    image_status: ImageGenStatus = ImageGenStatus.PENDING
    is_structured: bool = False         # True if extracted from structured format
    structured_format: str | None = None  # "json" | "shot_list" | "prompt_marker"
    is_recheck: bool = False            # True = second-pass LLM call was needed
    repair_attempted: bool = False      # True = validation/repair was triggered


# Type alias for clarity in code - same class as ExtractedPrompt after scoring
ScoredPrompt = ExtractedPrompt