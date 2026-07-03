"""ReAct Agent types — IntentType, ReActStep, PoolSummary, ToolCallResult."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IntentType(Enum):
    STATUS_QUERY = "STATUS_QUERY"
    TASK_EXECUTION = "TASK_EXECUTION"
    SEARCH = "SEARCH"
    MULTI_STEP = "MULTI_STEP"
    CLARIFICATION = "CLARIFICATION"
    CHITCHAT = "CHITCHAT"


@dataclass
class ReActStep:
    """Single step in ReAct loop."""
    step_number: int = 0
    thought: str = ""
    action: dict | None = None
    observation: str | None = None
    tool_name: str | None = None
    tool_args: dict | None = None
    result: str | None = None
    error: str | None = None
    timestamp: str = ""


@dataclass
class PoolSummary:
    """Summary of Prompt Pool state (returned by memory long_term queries)."""

    # V3 extends chat.py PoolSummary with total + last_updated — keep in sync.
    # V2 has: pending, generating, done, failed, published
    # V3 adds: total, last_updated
    pending: int = 0
    generating: int = 0
    done: int = 0
    failed: int = 0
    published: int = 0
    total: int = 0
    last_updated: str = ""


@dataclass
class ToolCallResult:
    """Result from a tool execution in act_node."""
    tool_name: str = ""
    args: dict = field(default_factory=dict)
    success: bool = True
    output: str = ""
    error: str | None = None
    duration_seconds: float = 0.0