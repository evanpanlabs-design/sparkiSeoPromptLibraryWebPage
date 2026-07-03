"""error_node — V3 ReAct Agent: error handling."""

from src.agent.state import AgentState


def _save_error_turn(db_conn, error: str) -> None:
    """Save error to conversation history."""
    if db_conn is None:
        return
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        db_conn.execute(
            "INSERT INTO conversation_history (role, content, created_at) VALUES (?, ?, ?)",
            ("agent", f"[ERROR] {error}", now),
        )
        db_conn.commit()
    except Exception:
        pass


def error_node(state: AgentState) -> AgentState:
    """Catch all exceptions, record to history, set final reply.

    Reads:
        state.error (set by graph boundary)

    Writes:
        state.final_reply
        state.is_done = True
    """
    error_msg = state.error or "未知错误"
    state.final_reply = f"执行出错: {error_msg}"
    state.is_done = True

    _save_error_turn(state.db_conn, error_msg)

    return state