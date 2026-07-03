"""Sparki V3 Agent Memory system.

short_term : Session-scoped helpers operating on AgentState.messages
long_term  : SQLite CRUD for cross-session persistence
embedding  : Gemini embedding API + cosine similarity search
"""

from src.agent.memory.short_term import save_turn, load_recent_history, clear_session
from src.agent.memory.long_term import (
    save_preference,
    get_preference,
    get_pool_summary,
    save_task_history,
    load_task_history,
    search_prompts_by_embedding,
)
from src.agent.memory.embedding import embed_text, cosine_similarity, search_prompts, embed_pending_prompts

__all__ = [
    # short_term
    "save_turn",
    "load_recent_history",
    "clear_session",
    # long_term
    "save_preference",
    "get_preference",
    "get_pool_summary",
    "save_task_history",
    "load_task_history",
    "search_prompts_by_embedding",
    # embedding
    "embed_text",
    "cosine_similarity",
    "search_prompts",
    "embed_pending_prompts",
]
