"""final_reply_node — V3 ReAct Agent: organize final reply to user."""

from src.agent.state import AgentState


def _build_final_reply(steps: list[dict]) -> str:
    """Build a final reply from the ReAct steps."""
    if not steps:
        return "好的。"

    lines = []
    for step in steps:
        thought = step.get("thought", "")
        action = step.get("action")
        observation = step.get("observation", "")

        if action:
            tool_name = action.get("tool", "unknown")
            lines.append(f"执行 {tool_name}: {observation[:200]}")
        else:
            lines.append(f"思考: {thought[:200]}")

    return "\n".join(lines) if lines else "完成。"


def _save_conversation_turn(db_conn, role: str, content: str) -> None:
    """Save a conversation turn to the database."""
    if db_conn is None:
        return
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        db_conn.execute(
            "INSERT INTO conversation_history (role, content, created_at) VALUES (?, ?, ?)",
            (role, content, now),
        )
        db_conn.commit()
    except Exception:
        pass  # Silently ignore DB errors


def final_reply_node(state: AgentState) -> AgentState:
    """Organize final reply and mark session as done.

    Reads:
        state.steps
        state.final_reply (if already set by plan_node)

    Writes:
        state.final_reply
        state.is_done = True
    """
    if state.final_reply:
        reply = state.final_reply
    else:
        reply = _build_final_reply(state.steps)

    state.final_reply = reply
    state.is_done = True

    # Save to conversation history
    _save_conversation_turn(state.db_conn, role="agent", content=reply)

    return state