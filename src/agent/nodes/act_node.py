"""act_node — V3 ReAct Agent: tool execution."""

from src.agent.state import AgentState


def act_node(state: AgentState) -> AgentState:
    """Execute the pending tool and record the result.

    Reads:
        state.pending_action — {"tool": "...", "args": {...}}
        state.skill_registry

    Writes:
        state.tool_result
        state.steps (append current step)
    """
    action = state.pending_action
    if action is None:
        state.tool_result = "错误: 没有待执行的 action"
        return state

    tool_name = action.get("tool", "")
    args = action.get("args", {})

    # Execute via skill registry — errors propagate to graph boundary
    tool = state.skill_registry.get(tool_name)
    if not tool:
        state.tool_result = f"错误: 未找到工具 '{tool_name}'"
    else:
        state.tool_result = tool.execute(args)

    # Record step
    step = {
        "step": state.current_step + 1,
        "thought": state.current_thought,
        "action": action,
        "observation": state.tool_result,
    }
    state.steps.append(step)

    return state