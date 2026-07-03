"""plan_node — V3 ReAct Agent: task planning + action selection."""

from src.agent.state import AgentState

PLAN_SYSTEM_PROMPT = """你是 Sparki VPS Manager的任务规划器。

根据以下推理，决定下一步做什么：

推理: {current_thought}

当前 scratchpad:
{scratchpad}

可用工具:
{tool_list}

决策规则：
- 如果需要调用工具，回复：
  action: {{"tool": "工具名", "args": {{"参数": "值"}}}}
- 如果已经足够回答用户，或者不需要工具，回复：
  reply: <你的直接回复>

用中文回复。"""


def _build_plan_prompt(state: AgentState) -> str:
    tools = state.skill_registry.list_all()
    tool_list = "\n".join(f"  - {t}" for t in tools) or "（无可用工具）"

    return PLAN_SYSTEM_PROMPT.format(
        current_thought=state.current_thought,
        scratchpad=state.scratchpad or "（无）",
        tool_list=tool_list,
    )


def _parse_plan_response(response: str) -> dict:
    """Parse LLM response into action or reply."""
    for line in response.split("\n"):
        line = line.strip()
        if line.startswith("action:"):
            try:
                # Extract JSON after "action:"
                json_str = line[len("action:"):].strip()
                import json
                return {"action": json.loads(json_str)}
            except Exception:
                return {"action": None, "reply": response}
        elif line.startswith("reply:"):
            return {"action": None, "reply": line[len("reply:"):].strip()}

    return {"action": None, "reply": response}


def _intent_to_reply(intent_type: str) -> str:
    """Return a contextually appropriate reply for each intent type."""
    if intent_type == "CHITCHAT":
        return "你好！有什么我可以帮你的吗？你可以问我池子状态、搜索提示词、或者生成图片等任务。"
    if intent_type == "CLARIFICATION":
        return "我需要确认一下你的需求。你想要：\n1. 查询任务池状态\n2. 搜索提示词\n3. 生成图片\n4. 其他操作\n请回复数字或描述你的需求。"
    return None  # let LLM decide for other intents


def plan_node(state: AgentState) -> AgentState:
    """Decide tool to call or direct reply.

    Reads:
        state.current_thought
        state.scratchpad
        state.intent_type

    Writes:
        state.pending_action OR state.final_reply
    """
    if state.intent_type == "CHITCHAT":
        state.final_reply = _intent_to_reply("CHITCHAT")
        return state

    if state.intent_type == "CLARIFICATION":
        state.final_reply = _intent_to_reply("CLARIFICATION")
        return state

    # SEARCH intent: extract keywords then search
    if state.intent_type == "SEARCH":
        msg = state.latest_message
        # Strip command prefix if any: "search_prompts: xxx" or "search xxx"
        if ":" in msg:
            query = msg.split(":", 1)[1].strip()
        else:
            # Remove common search prefixes to get at the actual search terms
            stripped = msg
            for prefix in ["搜索", "找", "查找", "search", "找一下", "搜一下"]:
                if stripped.lower().startswith(prefix.lower()):
                    stripped = stripped[len(prefix):].strip()
            query = stripped if stripped else msg
        # Truncate very long queries (likely full sentences not keywords)
        if len(query) > 50:
            query = query[:50]
        state.pending_action = {"tool": "search_prompts", "args": {"query": query, "top_k": 5}}
        return state

    # Pipeline mode: force first step to crawl_tweets
    if state.intent_type == "MULTI_STEP" and state.current_step == 0:
        state.pending_action = {"tool": "crawl_tweets", "args": {}}
        return state

    prompt = _build_plan_prompt(state)
    response = state.llm.complete(system=PLAN_SYSTEM_PROMPT, prompt=prompt)
    parsed = _parse_plan_response(response)

    if parsed.get("action"):
        state.pending_action = parsed["action"]
    else:
        state.final_reply = parsed.get("reply", "好的，我明白了。")

    return state