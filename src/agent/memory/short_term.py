"""Short-term memory helpers — session-scoped, operating on AgentState.messages."""

from datetime import datetime, timezone
from typing import Any

from src.types.react import ReActStep


def save_turn(
    conn,
    role: str,
    content: str,
    tool_name: str | None = None,
    tool_args: dict | None = None,
) -> None:
    """Persist one conversation turn to conversation_history table."""
    import json
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO conversation_history (role, content, tool_name, tool_args, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (role, content, tool_name, json.dumps(tool_args) if tool_args else None, now),
    )
    conn.commit()


def load_recent_history(conn, limit: int = 20) -> list[dict]:
    """Load the most recent N turns from conversation_history."""
    import json
    rows = conn.execute(
        """
        SELECT role, content, tool_name, tool_args, created_at
        FROM conversation_history
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    result = []
    for row in reversed(rows):
        result.append({
            "role": row["role"],
            "content": row["content"],
            "tool_name": row["tool_name"],
            "tool_args": json.loads(row["tool_args"]) if row["tool_args"] else None,
            "created_at": row["created_at"],
        })
    return result


def clear_session(state: Any) -> None:
    """Reset state.steps (short-term session memory)."""
    state.steps = []
