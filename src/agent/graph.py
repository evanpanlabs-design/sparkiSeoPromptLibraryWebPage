"""V3 LangGraph StateGraph definition for Sparki ReAct Agent.

This module builds the ReAct graph per docs/02_DevGuide_V3.md §5.

Edge logic:
  start → think → plan → (act | final_reply) → observe → (think | final_reply) → END

Usage:
  graph = build_react_graph(skill_registry)
  compiled = graph.compile(checkpointer=MemorySaver())
  result = compiled.invoke(initial_state, config={"configurable": {"session_id": "my-session"}})
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from src.agent.state import AgentState
from src.agent.nodes import (
    start_node,
    think_node,
    plan_node,
    act_node,
    observe_node,
    final_reply_node,
    error_node,
)


def _plan_route(state: AgentState) -> str:
    """Conditional edge: plan → act (if pending_action) else final_reply."""
    return "act" if state.pending_action else "final_reply"


def _observe_route(state: AgentState) -> str:
    """Conditional edge: observe → think (if more steps) else final_reply."""
    return "think" if state.need_more_steps else "final_reply"


def build_react_graph(
    skill_registry,
    checkpointer: "MemorySaver | None" = None,
) -> StateGraph:
    """Build and return the LangGraph StateGraph for the Sparki ReAct Agent.

    Args:
        skill_registry: SkillRegistry instance with registered tools.

    Returns:
        Compiled graph with MemorySaver checkpointer.
    """
    graph = StateGraph(AgentState)

    # ── Add all 7 nodes ──────────────────────────────────────────────────────────
    graph.add_node("start", start_node)
    graph.add_node("think", think_node)
    graph.add_node("plan", plan_node)
    graph.add_node("act", act_node)
    graph.add_node("observe", observe_node)
    graph.add_node("final_reply", final_reply_node)
    graph.add_node("error", error_node)

    # ── Edges ────────────────────────────────────────────────────────────────────
    # start → think
    graph.add_edge("start", "think")

    # think → plan
    graph.add_edge("think", "plan")

    # plan → act OR plan → final_reply (conditional)
    graph.add_conditional_edges(
        "plan",
        _plan_route,
        {"act": "act", "final_reply": "final_reply"},
    )

    # act → observe
    graph.add_edge("act", "observe")

    # observe → think (loop) OR final_reply (end) (conditional)
    graph.add_conditional_edges(
        "observe",
        _observe_route,
        {"think": "think", "final_reply": "final_reply"},
    )

    # error → final_reply
    graph.add_edge("error", "final_reply")

    # final_reply → END
    graph.add_edge("final_reply", END)

    # ── Entry point ─────────────────────────────────────────────────────────────
    graph.set_entry_point("start")

    # ── Compile ────────────────────────────────────────────────────────────────
    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()


# Module-level exported instance (use this for direct import checks)
graph = None  # lazily initialized below


def _init_graph():
    global graph
    if graph is None:
        # Dummy registry for import verification — real usage passes actual registry
        class _DummySkill:
            name = "dummy"
            description = ""
            category = "system"
            parameters = []
            def execute(self, args): return "dummy"
            def list_all(self): return []
        class _DummyRegistry:
            def get(self, name): return None
            def list_all(self): return []
        graph = build_react_graph(_DummyRegistry())
    return graph


# Verification-friendly: allow `from src.agent.graph import graph`
if __name__ == "__main__" or True:
    graph = _init_graph()


# Module-level dummy registry (for compile_graph shim)
class _DummyRegistry:
    def get(self, name): return None
    def list_all(self): return []


def compile_graph():
    """DEPRECATED: Use build_react_graph(registry) directly for V3.

    Compatibility shim — build and return a compiled graph with a dummy registry.
    Used by src.main (V1 pipeline entry point) which does not use the SkillRegistry.
    """
    return build_react_graph(_DummyRegistry())


__all__ = ["build_react_graph", "compile_graph", "graph"]