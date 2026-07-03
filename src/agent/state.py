"""V3 AgentState dataclass for Sparki ReAct Agent."""

from dataclasses import dataclass, field
from typing import Any

from src.types.react import PoolSummary


@dataclass
class AgentState:
    """LangGraph state for the Sparki ReAct Agent.

    All fields are updated by nodes as documented in docs/03_InterfaceContract_V3.md §2.
    """

    # ── Runtime ────────────────────────────────────────────────────────────────
    llm: Any = None                           # GeminiClient / LLM client instance
    db_conn: Any = None                       # sqlite3.Connection
    skill_registry: Any = None                # SkillRegistry instance

    # ── Input ───────────────────────────────────────────────────────────────────
    latest_message: str = ""                  # Current user message

    # ── Intent (set by think_node) ─────────────────────────────────────────────
    intent_type: str = "TASK_EXECUTION"       # STATUS_QUERY | TASK_EXECUTION | SEARCH | MULTI_STEP | CLARIFICATION | CHITCHAT

    # ── ReAct Loop ──────────────────────────────────────────────────────────────
    scratchpad: str = ""                      # Accumulated reasoning across steps
    current_thought: str = ""                 # Current step's thought text
    steps: list[dict] = field(default_factory=list)  # [ {"step": N, "thought": "...", "action": {...}, "observation": "..."} ]
    current_step: int = 0
    max_steps: int = 10                      # Prevent infinite loops

    # ── Node Outputs ─────────────────────────────────────────────────────────────
    pending_action: dict | None = None        # {"tool": "...", "args": {...}}
    tool_result: str | None = None           # Result from act_node
    final_reply: str | None = None           # Final text reply to user
    error: str | None = None                 # Error message from error_node

    # ── Loop Control ───────────────────────────────────────────────────────────
    need_more_steps: bool = False            # Set by observe_node
    is_done: bool = False                    # Set by final_reply_node

    # ── Memory (injected at each step) ─────────────────────────────────────────
    pool_summary: "PoolSummary | None" = None  # Latest pool counts
    recent_history: list[dict] = field(default_factory=list)  # Last 20 turns


# ── Runtime State Singleton ─────────────────────────────────────────────────
# Holds non-serializable objects (llm, db_conn, skill_registry) that the
# checkpointer cannot serialize. Used by start_node to re-inject them after
# a checkpointer restore so LangGraph can continue working on resumed state.
# ───────────────────────────────────────────────────────────────────────────────


class _RuntimeState:
    """Process-global singleton for non-serializable runtime objects."""

    _instance: "_RuntimeState | None" = None

    def __init__(self):
        self.llm: Any = None
        self.db_conn: Any = None
        self.skill_registry: Any = None

    @classmethod
    def get(cls) -> "_RuntimeState":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def register(cls, llm: Any, db_conn: Any, skill_registry: Any) -> None:
        rs = cls.get()
        rs.llm = llm
        rs.db_conn = db_conn
        rs.skill_registry = skill_registry