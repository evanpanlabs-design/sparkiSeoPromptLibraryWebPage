"""Image generation types."""

from dataclasses import dataclass
from enum import Enum


class ImageGenStatus(Enum):
    """Status of image generation for a prompt."""
    PENDING    = "pending"
    GENERATING = "generating"
    COMPLETED  = "completed"
    FAILED     = "failed"
    SKIPPED    = "skipped"              # quality below threshold


@dataclass
class ImageResult:
    """Result of image generation for a prompt."""
    prompt_id: int                      # SQLite prompts.id (after insert)
    tweet_id: str                       # Foreign key

    status: ImageGenStatus
    model_used: str | None = None      # Which Gemini model succeeded
    gcs_url: str | None = None          # gs://sparki-op-test/prompts/...
    local_path: str | None = None       # Local fallback if GCS disabled
    error_message: str | None = None

    generated_at: str = ""              # ISO8601
    category_path: str | None = None    # GCS blob path (prompts/{cat}/{yyyy-mm}/...)
