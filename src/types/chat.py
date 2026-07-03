"""V2-era types preserved for backwards compatibility."""

from dataclasses import dataclass, field
from typing import Literal

# Tool names used by V1/V2 pipeline
ToolName = Literal[
    "pool_status",
    "search_prompts",
    "crawl",
    "extract",
    "score",
    "generate_images",
    "retry_failed",
    "publish",
    "show_history",
]


@dataclass
class PoolSummary:
    """Summary of prompt pool counts by status."""
    pending: int = 0
    generating: int = 0
    done: int = 0
    failed: int = 0
    published: int = 0

    def to_str(self) -> str:
        return (
            f"Prompt Pool 状态:\n"
            f"  pending:    {self.pending}\n"
            f"  generating: {self.generating}\n"
            f"  done:       {self.done}\n"
            f"  failed:     {self.failed}\n"
            f"  published:  {self.published}"
        )