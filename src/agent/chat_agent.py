"""SparkiReActAgent — high-level ReAct Agent wrapper for Sparki V3."""

from typing import Any

from src.agent.state import AgentState
from src.agent.graph import build_react_graph


class SparkiReActAgent:
    """High-level conversational ReAct Agent.

    Wraps a compiled LangGraph graph and provides a simple run() interface
    that initializes state and drives the ReAct loop to completion.

    Usage:
        agent = SparkiReActAgent(llm=llm, db_conn=conn, skill_registry=reg)
        reply = agent.run("池子状态怎么样？")
    """

    def __init__(
        self,
        llm: Any,
        db_conn: Any,
        skill_registry: Any,
        max_steps: int = 10,
        session_id: str = "cli-session",
    ):
        """Initialize the agent.

        Args:
            llm: LLM client (e.g. GeminiClient with complete() method).
            db_conn: sqlite3.Connection instance.
            skill_registry: SkillRegistry with registered tools.
            max_steps: Max ReAct loop iterations (default 10).
            session_id: Checkpointer thread_id for cross-turn state persistence.
        """
        self.llm = llm
        self.db_conn = db_conn
        self.skill_registry = skill_registry
        self.max_steps = max_steps
        self.session_id = session_id

        # Build compiled graph — no checkpointer needed for CLI REPL.
        # Each agent.run() call re-injects runtime objects (llm, db_conn,
        # skill_registry) fresh via AgentState.__init__(). The same
        # SparkiReActAgent instance is reused across REPL turns, so state
        # is preserved in memory without needing LangGraph checkpointer.
        self.graph = build_react_graph(skill_registry)

    def run(self, user_message: str) -> str:
        """Run the ReAct loop for a single user message.

        Args:
            user_message: The user's input string.

        Returns:
            The final reply string from the agent.
        """
        state = AgentState(
            llm=self.llm,
            db_conn=self.db_conn,
            skill_registry=self.skill_registry,
            latest_message=user_message,
            max_steps=self.max_steps,
        )

        config = {"configurable": {"thread_id": self.session_id}}

        try:
            # Invoke the graph — LangGraph runs start→think→plan→...→final_reply
            result: dict = self.graph.invoke(state, config=config)
            final_reply = result.get("final_reply") if isinstance(result, dict) else result.final_reply
            if final_reply:
                return final_reply
            # Fallback: if is_done but no final_reply, synthesize from scratchpad
            scratchpad = result.get("scratchpad") if isinstance(result, dict) else result.scratchpad
            if scratchpad:
                return scratchpad.strip()
            return "（无回复）"
        except Exception as e:
            # Per §11 Error Handling: never raise, return error string
            return f"执行出错，请重试：{type(e).__name__}: {e}"

    def get_history(self, limit: int = 20) -> list[dict]:
        """Load recent conversation history from SQLite.

        Args:
            limit: Max number of entries to return (default 20).

        Returns:
            List of dicts with keys: id, role, content, tool_name, tool_args, created_at.
        """
        rows = self.db_conn.execute(
            """
            SELECT role, content
            FROM conversation_history
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]