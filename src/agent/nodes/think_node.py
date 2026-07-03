"""think_node — V3 ReAct Agent: intent parsing + thought generation."""

from src.agent.state import AgentState

THINK_SYSTEM_PROMPT = """你是 Sparki VPS Manager，一个意图驱动的 ReAct Agent（Veo Prompts Station 管理器）。

根据用户消息，生成推理（thought）并判断意图类型（intent_type）。

可用 intent_type：
- STATUS_QUERY: 用户询问池子状态、数量等
- TASK_EXECUTION: 用户请求执行具体操作（生成、爬取、发布等）
- SEARCH: 用户想要搜索/查找内容
- MULTI_STEP: 复杂任务需要多步
- CLARIFICATION: 意图不明确需要追问
- CHITCHAT: 闲聊，无需工具

回复格式（中文）：
thought: <你的推理>
intent_type: <上述类型之一>"""


def _build_think_prompt(state: AgentState) -> str:
    pool_str = state.pool_summary.to_str() if state.pool_summary else "（无数据）"
    history_str = "\n".join(
        f"  - [{t['role']}] {t['content'][:80]}"
        for t in (state.recent_history or [])[-5:]
    ) or "（无历史）"

    return f"""当前任务: {state.latest_message}

你的 Pool 状态:
{pool_str}

最近对话:
{history_str}

之前的推理步骤:
{state.scratchpad or "（无）"}

请分析用户意图，生成一段推理（thought）。"""


def _parse_think_response(response: str) -> dict:
    """Parse LLM response into thought + intent_type."""
    thought = ""
    intent_type = "TASK_EXECUTION"

    for line in response.split("\n"):
        line = line.strip()
        if line.startswith("thought:"):
            thought = line[len("thought:"):].strip()
        elif line.startswith("intent_type:"):
            intent_type = line[len("intent_type:"):].strip()

    return {"thought": thought, "intent_type": intent_type}


_pipeline_keywords = ["全程", "完整流程", "一键", "跑一遍", "更新全部", "全流程"]


def _keyword_intent(msg: str) -> str | None:
    """Fast-path keyword match when LLM intent is ambiguous.

    Returns intent type if a clear keyword match is found, else None.
    This catches cases like '查询一下任务池状态' where the LLM
    might overthink and return CLARIFICATION.
    """
    msg_lower = msg.lower()
    # STATUS_QUERY — pool/status related
    if any(kw in msg_lower for kw in ["池子", "pool", "状态", "状态怎么样", "状态如何"]):
        return "STATUS_QUERY"
    # SEARCH — search/find/look up
    if any(kw in msg_lower for kw in ["找", "搜索", "search", "查找", "搜"]):
        return "SEARCH"
    # CHITCHAT — greetings and casual
    if any(kw in msg_lower for kw in ["你好", "hi", "hello", "早上好", "下午好", "晚上好", "嗨", "hey"]):
        return "CHITCHAT"
    # EXIT — quit signals
    if msg_lower.strip() in ["退出", "exit", "quit", "再见", "结束"]:
        return "EXIT"
    # MULTI_STEP — Pipeline mode trigger
    if any(kw in msg for kw in _pipeline_keywords):
        return "MULTI_STEP"
    return None


def think_node(state: AgentState) -> AgentState:
    """Parse intent and generate thought via LLM.

    Reads:
        state.latest_message
        state.scratchpad
        state.pool_summary
        state.recent_history

    Writes:
        state.current_thought
        state.intent_type
        state.scratchpad (append)
    """
    prompt = _build_think_prompt(state)

    response = state.llm.complete(
        system=THINK_SYSTEM_PROMPT,
        prompt=prompt,
    )

    parsed = _parse_think_response(response)
    state.current_thought = parsed["thought"]
    intent_type = parsed.get("intent_type", "TASK_EXECUTION")

    # Keyword fast-path: catches cases where LLM returns CLARIFICATION for obvious intents
    keyword_intent = _keyword_intent(state.latest_message)
    if keyword_intent and intent_type in ("CLARIFICATION", "TASK_EXECUTION", "CHITCHAT"):
        # Only override if keyword match is strong (STATUS_QUERY / SEARCH / EXIT / MULTI_STEP)
        if keyword_intent in ("STATUS_QUERY", "SEARCH", "EXIT", "MULTI_STEP"):
            intent_type = keyword_intent
        elif keyword_intent == "CHITCHAT" and intent_type == "CLARIFICATION":
            intent_type = "CHITCHAT"

    state.intent_type = intent_type
    state.scratchpad += f"\nStep {state.current_step + 1}: {parsed['thought']}"

    return state