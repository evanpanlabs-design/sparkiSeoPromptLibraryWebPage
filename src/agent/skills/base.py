"""Skill and Parameter dataclasses for the Skill Registry system."""

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Parameter:
    """A parameter for a Skill's execute function."""

    name: str
    type: str  # "string" | "integer" | "boolean" | "array" | "object"
    description: str
    required: bool = False
    default: Any = None
    enum: list[str] | None = None  # For constrained values


@dataclass
class Skill:
    """A callable tool registered in the Skill Registry."""

    name: str  # Unique identifier, e.g. "pool_status"
    description: str  # Human-readable description for LLM
    category: str  # "system" | "data_collection" | "ai_generation" | "web_maintenance" | "memory"
    parameters: list[Parameter] = field(default_factory=list)
    execute: Callable[[dict], str] | None = None
    examples: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)  # Custom metadata (version, author, etc.)