"""observe_node — V3 ReAct Agent: result evaluation + loop control."""

from src.agent.state import AgentState

# Phase completion markers and their next step mapping
_PHASE_NEXT_MAP = {
    "crawl_tweets 完成": "extract_prompts",
    "extract_prompts 完成": "score_prompts",
    "score_prompts 完成": "generate_images",
    "generate_images 完成": "sync_images",
    "sync_images 完成": "build_html",
    "build_html 完成": "publish",
    "publish 完成": None,  # Pipeline ends
}


def _rule_based_continue(tool_result: str, current_thought: str) -> bool | None:
    """Use rules to determine continue flag when LLM is uncertain.

    Returns:
        True  — rule says continue
        False — rule says stop
        None  — no rule matched, caller should use LLM decision
    """
    if not tool_result:
        return None

    result_lower = tool_result.lower()

    # Check for phase completion markers
    for marker, next_phase in _PHASE_NEXT_MAP.items():
        if marker.lower() in result_lower:
            # Phase complete: continue if there's a next phase
            return next_phase is not None

    # Check for explicit completion signals
    if any(kw in result_lower for kw in ["完成", "done", "success", "成功"]):
        if any(kw in result_lower for kw in ["pipeline", "全部", "全程", "结束"]):
            return False  # Explicit end signal

    # Check for error signals
    if any(kw in result_lower for kw in ["错误", "error", "失败", "失败"]):
        return False  # Stop on errors

    return None  # No rule matched


def _infer_next_phase_from_result(tool_result: str) -> str | None:
    """Infer the next phase from tool result content."""
    if not tool_result:
        return None

    result_lower = tool_result.lower()

    if "爬取" in result_lower or "crawl" in result_lower:
        return "extract_prompts"
    if "抽取" in result_lower or "extract" in result_lower:
        return "score_prompts"
    if "评分" in result_lower or "score" in result_lower:
        return "generate_images"
    if "生成" in result_lower or "图片" in result_lower:
        return "sync_images"
    if "同步" in result_lower or "sync" in result_lower:
        return "build_html"
    if "构建" in result_lower or "html" in result_lower:
        return "publish"

    return None

OBSERVE_SYSTEM_PROMPT = """你是 Sparki VPS Manager的结果评估器。

工具执行结果:
{tool_result}

基于这个结果，任务完成了吗？还需要更多步骤吗？

之前的推理: {current_thought}
已执行步骤数: {step_count}
最大步数: {max_steps}

请判断：
- 如果任务已完成，回复：continue: false
- 如果还需要更多步骤（查状态、生成更多图等），回复：continue: true

回复格式：
continue: true/false
next_thought: <基于结果的下一步推理>"""


def _build_observe_prompt(state: AgentState) -> str:
    steps_summary = len(state.steps)

    return OBSERVE_SYSTEM_PROMPT.format(
        tool_result=state.tool_result or "",
        current_thought=state.current_thought or "",
        step_count=steps_summary,
        max_steps=state.max_steps,
    )


def _parse_observe_response(response: str) -> dict:
    """Parse LLM response into continue flag + next_thought."""
    continue_flag = False
    next_thought = ""

    for line in response.split("\n"):
        line = line.strip()
        if line.startswith("continue:"):
            val = line[len("continue:"):].strip().lower()
            continue_flag = val == "true"
        elif line.startswith("next_thought:"):
            next_thought = line[len("next_thought:"):].strip()

    return {"continue": continue_flag, "next_thought": next_thought}


def observe_node(state: AgentState) -> AgentState:
    """Evaluate tool result and decide whether to continue the loop.

    Reads:
        state.tool_result
        state.current_thought
        state.steps
        state.max_steps

    Writes:
        state.need_more_steps
        state.scratchpad (append)
    """
    # Rule-based fast path for Pipeline mode phase completion
    rule_decision = _rule_based_continue(state.tool_result or "", state.current_thought or "")

    if rule_decision is not None:
        # Use rule-based decision when confident
        state.need_more_steps = rule_decision
        result_preview = (state.tool_result or "")[:100]
        suffix = "(继续)" if rule_decision else "(完成)"
        state.scratchpad += f"\n  → {result_preview}... {suffix}"
        state.current_step += 1

        if state.current_step >= state.max_steps:
            state.need_more_steps = False

        return state

    # Fall back to LLM decision when rules don't apply
    prompt = _build_observe_prompt(state)

    response = state.llm.complete(system=OBSERVE_SYSTEM_PROMPT, prompt=prompt)
    parsed = _parse_observe_response(response)

    state.need_more_steps = parsed["continue"]

    # Append observation to scratchpad
    result_preview = (state.tool_result or "")[:100]
    suffix = "(继续)" if parsed["continue"] else "(完成)"
    state.scratchpad += f"\n  → {result_preview}... {suffix}"

    # Increment step counter
    state.current_step += 1

    # Enforce max_steps limit
    if state.current_step >= state.max_steps:
        state.need_more_steps = False

    return state