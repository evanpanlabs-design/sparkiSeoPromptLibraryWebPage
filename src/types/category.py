"""Category suggestion types."""

from dataclasses import dataclass
from enum import Enum


class CategorySuggestionStatus(Enum):
    """Status of a category suggestion pending human review."""
    PENDING   = "pending"
    APPROVED  = "approved"
    REJECTED  = "rejected"


@dataclass
class CategorySuggestion:
    """A suggested new category requiring human approval."""
    id: int | None                      # SQLite category_suggestions.id (after insert)
    suggested_name: str
    reason: str                          # Why LLM thinks this is a new category
    suggested_by: str                    # "MiniMax-M2.7" or "human"
    sample_prompt_text: str             # The triggering prompt text (first 200 chars)
    suggested_desc: str = ""
    status: CategorySuggestionStatus = CategorySuggestionStatus.PENDING
    reviewed_at: str | None = None
    reviewed_by: str | None = None
    created_at: str = ""                # ISO8601
