"""start_node — V3 ReAct Agent entry point."""

from src.agent.state import AgentState


def start_node(state: AgentState) -> AgentState:
    """Entry point: initialize state for a new user message.

    Reads:
        state.latest_message (from user input)

    Writes:
        state.steps = []
        state.current_step = 0
        state.scratchpad = ""
        state.is_done = False
        state.error = None
        state.pending_action = None
        state.tool_result = None
        state.final_reply = None
        state.need_more_steps = False

    Note: Non-serializable runtime objects (llm, db_conn, skill_registry) are
    re-injected here after checkpointer restore — they are None in saved state
    because dataclasses can't serialize arbitrary objects.
    """
    state.steps = []
    state.current_step = 0
    state.scratchpad = ""
    state.is_done = False
    state.error = None
    state.pending_action = None
    state.tool_result = None
    state.final_reply = None
    state.need_more_steps = False

    # Restore runtime objects that checkpointer couldn't serialize.
    # These come from the SparkiReActAgent instance passed at construction.
    # Re-inject them from the singleton so resumed state can continue.
    if state.llm is None:
        from src.agent.state import _RuntimeState
        rs = _RuntimeState.get()
        if rs.llm is not None:
            state.llm = rs.llm
        if rs.db_conn is not None:
            state.db_conn = rs.db_conn
        if rs.skill_registry is not None:
            state.skill_registry = rs.skill_registry

    return state