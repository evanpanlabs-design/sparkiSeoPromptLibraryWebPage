# Sparki V3 Developer Guide — ReAct Agent with LangGraph

> **Version**: 3.0 | **Framework**: ReAct (Reasoning + Acting) + LangGraph | **Audience**: Engineers building V3

---

## 1. Architecture

### 1.1 System Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Sparki ReAct Agent                                     │
│                                                                              │
│  User Input ────▶ ┌────────────────────────────────────────────────────────┐ │
│                   │                  LangGraph StateGraph                   │ │
│                   │                                                         │ │
│                   │  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌────────┐ │ │
│                   │  │  START  │───▶│  THINK  │───▶│  PLAN   │───▶│  ACT   │ │ │
│                   │  └─────────┘    │(意图解析)│    │(任务规划)│    │(工具调用)│ │ │
│                   │                 └────┬────┘    └────┬────┘    └────┬────┘ │ │
│                   │                      │              │              │      │ │
│                   │                      ▼              ▼              ▼      │ │
│                   │                 ┌─────────┐    ┌─────────┐    ┌────────┐ │ │
│                   │                 │ OBSERVE │◀───│ MEMORY  │◀───│ RESULT │ │ │
│                   │                 │(结果评估)│    │(短期+长期)│    │        │ │ │
│                   │                 └────┬────┘    └─────────┘    └────────┘ │ │
│                   │                      │                               │      │ │
│                   │         ┌────────────┴────────────┐                     │      │ │
│                   │         ▼                         ▼                     │      │ │
│                   │  ┌─────────────┐          ┌──────────────┐             │      │ │
│                   │  │ FINAL_REPLY │          │  (next step)  │             │      │ │
│                   │  │  (回复用户)  │          └──────┬───────┘             │      │ │
│                   │  └──────┬──────┘                 │                     │      │ │
│                   └─────────┼─────────────────────────┘                     │      │ │
│                             │                                               │      │
└─────────────────────────────┼───────────────────────────────────────────────┘
                              │
          ┌──────────────────┬┴──────────────────┬───────────────────┐
          ▼                  ▼                   ▼                   ▼
   ┌─────────────┐   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
   │   SQLite    │   │  LLM Client │    │  Skill Reg. │    │  GCS / Apify│
   │  (记忆系统)  │   │  (Gemini)   │    │  (工具注册) │    │  (外部服务)  │
   └─────────────┘   └─────────────┘    └─────────────┘    └─────────────┘
```

### 1.2 ReAct Loop Detail

```
Step N:
  Think:   "用户想要...我需要先...然后..."
  Plan:    {"tool": "xxx", "args": {...}}
  Act:     execute(xxx)
  Observe: "结果...说明...下一步应该..."
  ↓ (if not done)
Step N+1:
  Think:   "根据上一步结果...现在应该..."
  ...
```

---

## 2. Project Structure (V3)

```
16_NewCrawler/
├── configs/
│
├── src/
│   ├── main.py                     # V1 pipeline (kept)
│   │
│   ├── agent/                      # V3 ReAct Agent
│   │   ├── __init__.py
│   │   ├── state.py               # AgentState dataclass (V3)
│   │   ├── graph.py               # LangGraph StateGraph definition
│   │   ├── nodes/
│   │   │   ├── __init__.py
│   │   │   ├── start_node.py       # Entry point
│   │   │   ├── think_node.py       # Intent parsing + thought generation
│   │   │   ├── plan_node.py        # Task planning + action selection
│   │   │   ├── act_node.py         # Tool execution
│   │   │   ├── observe_node.py     # Result evaluation + loop control
│   │   │   ├── final_reply_node.py # Organize reply to user
│   │   │   └── error_node.py       # Error handling
│   │   ├── chat.py                 # CLI chat entry point
│   │   ├── chat_agent.py           # SparkiReActAgent (high-level class)
│   │   │
│   │   ├── skills/                 # Skill Registry
│   │   │   ├── __init__.py
│   │   │   ├── registry.py         # SkillRegistry class
│   │   │   ├── base.py             # Skill, Parameter dataclasses
│   │   │   ├── core_tools.py       # 9 core tool implementations
│   │   │   ├── memory_tools.py     # search_prompts, save_preference, etc.
│   │   │   └── examples/           # Example skills (TikTok, SEO blog)
│   │   │
│   │   ├── memory/                 # Memory system
│   │   │   ├── short_term.py       # Session messages (AgentState.messages)
│   │   │   ├── long_term.py        # SQLite history + embeddings
│   │   │   └── embedding.py        # Gemini embedding utilities
│   │   │
│   │   └── react/
│   │       ├── formatter.py        # ReAct format helpers
│   │       ├── parser.py           # Parse LLM output into thought/action
│   │       └── prompt.py           # ReAct system prompt templates
│   │
│   ├── crawler/                   # V1 (unchanged)
│   ├── worker/                    # V1 (unchanged)
│   ├── llm/                       # V1 (unchanged)
│   ├── image_gen/                 # V1 (unchanged) + RateLimitSafeGenerator
│   ├── memory/                    # V2 DB schema (enhanced)
│   ├── api/                       # (future web UI)
│   └── types/
│       ├── __init__.py
│       ├── chat.py               # V2 types (ToolName, etc.)
│       └── react.py              # NEW: ReActStep, IntentType, etc.
│
├── tests/
│   ├── unit/
│   │   └── agent/
│   │       ├── test_think_node.py
│   │       ├── test_plan_node.py
│   │       ├── test_act_node.py
│   │       └── test_react_parser.py
│   └── integration/
│       └── test_v3_agent.py
│
└── docs/
    ├── 01_PRD_V3.md
    ├── 02_DevGuide_V3.md          # This file
    ├── 03_InterfaceContract_V3.md
    └── 04_ParallelDevCommands_V3.md
```

---

## 3. AgentState (V3)

```python
from dataclasses import dataclass, field
from typing import Any, Literal

@dataclass
class AgentState:
    """LangGraph state — all fields updated by nodes."""

    # ── LLM Client ─────────────────────────────────────────────────────────────
    llm: Any = None                             # GeminiClient instance

    # ── Database ───────────────────────────────────────────────────────────────
    db_conn: Any = None                         # sqlite3.Connection

    # ── User Input ─────────────────────────────────────────────────────────────
    latest_message: str = ""                    # Current user message

    # ── Intent Classification ───────────────────────────────────────────────────
    intent_type: str = "TASK_EXECUTION"          # STATUS_QUERY | TASK_EXECUTION | SEARCH | MULTI_STEP | CLARIFICATION | CHITCHAT

    # ── ReAct Loop ──────────────────────────────────────────────────────────────
    scratchpad: str = ""                         # LLM reasoning notes (free-form)
    current_thought: str = ""                    # Current step's thought text
    steps: list[dict] = field(default_factory=list)  # [ {"step": 1, "thought": "...", "action": {...}, "observation": "..."} ]
    current_step: int = 0
    max_steps: int = 10                          # Prevent infinite loops

    # ── Node Outputs ────────────────────────────────────────────────────────────
    pending_action: dict | None = None          # {"tool": "...", "args": {...}}
    tool_result: str | None = None              # Result from act_node
    final_reply: str | None = None             # Final text to user
    error: str | None = None                    # Error message from error_node

    # ── Loop Control ────────────────────────────────────────────────────────────
    need_more_steps: bool = False               # Set by observe_node
    is_done: bool = False                       # Set by final_reply_node

    # ── Memory (injected at each step) ─────────────────────────────────────────
    pool_summary: "PoolSummary" = None          # Latest pool counts
    recent_history: list[dict] = field(default_factory=list)  # Last 20 turns


@dataclass
class ReActStep:
    """Single step in ReAct loop."""
    step_number: int
    thought: str
    action: dict | None = None       # {"tool": "...", "args": {...}}
    observation: str | None = None
    tool_name: str | None = None
    tool_args: dict | None = None
    result: str | None = None
    error: str | None = None
```

---

## 4. LangGraph Nodes

### 4.1 `start_node`

**Role**: Entry point — receive user message, initialize state.

```python
def start_node(state: AgentState) -> AgentState:
    """
    INPUT:  state.latest_message (from user)
    OUTPUT: state.latest_message preserved
            state.steps = [] (reset for new task)
            state.current_step = 0
            state.scratchpad = ""
            state.is_done = False
            state.error = None
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
    return state
```

### 4.2 `think_node`

**Role**: 意图解析 + 推理。LLM 生成 `thought`，同时判断 `intent_type`。

```python
def think_node(state: AgentState) -> AgentState:
    """
    INPUT:  state.latest_message
            state.scratchpad (previous reasoning, empty on first step)
            state.pool_summary
            state.recent_history
    OUTPUT: state.current_thought (str) — LLM 生成的推理
            state.intent_type — 意图分类
            state.scratchpad — 更新推理笔记
    """
    prompt = build_think_prompt(
        message=state.latest_message,
        scratchpad=state.scratchpad,
        pool_summary=state.pool_summary,
        history=state.recent_history,
        steps=state.steps,
    )
    response = state["llm"].complete(
        system=THINK_SYSTEM_PROMPT,
        prompt=prompt,
    )
    # Parse response into thought + intent
    parsed = parse_think_response(response)
    state.current_thought = parsed["thought"]
    state.intent_type = parsed.get("intent_type", "TASK_EXECUTION")
    state.scratchpad += f"\nStep {state.current_step + 1}: {parsed['thought']}"
    return state
```

### 4.3 `plan_node`

**Role**: 任务规划。LLM 根据 `thought` 决定下一步调用哪个工具（或直接回复）。

```python
def plan_node(state: AgentState) -> AgentState:
    """
    INPUT:  state.current_thought
            state.scratchpad
            state.available_tools (from SkillRegistry)
    OUTPUT: state.pending_action — {"tool": "...", "args": {...}}
            OR state.final_reply — 直接回复用户（无需工具）
    """
    if state.intent_type in ("CHITCHAT", "CLARIFICATION"):
        # No tool needed — direct reply
        state.final_reply = generate_direct_reply(state)
        return state

    prompt = build_plan_prompt(
        thought=state.current_thought,
        scratchpad=state.scratchpad,
        available_tools=skill_registry.list_tools(),
    )
    response = state["llm"].complete(
        system=PLAN_SYSTEM_PROMPT,
        prompt=prompt,
    )
    parsed = parse_plan_response(response)
    if parsed.get("action"):
        state.pending_action = parsed["action"]
    else:
        state.final_reply = parsed.get("reply", "好的，我明白了。")
    return state
```

### 4.4 `act_node`

**Role**: 执行工具，生成 `observation`。

```python
def act_node(state: AgentState) -> AgentState:
    """
    INPUT:  state.pending_action
    OUTPUT: state.tool_result — 工具执行结果字符串
            state.steps — 添加当前 step 的 action + result
    """
    action = state.pending_action
    tool_name = action["tool"]
    args = action["args"]

    try:
        tool = skill_registry.get(tool_name)
        if not tool:
            result = f"错误: 未找到工具 '{tool_name}'"
        else:
            result = tool.execute(args)
        state.tool_result = result
    except Exception as e:
        state.tool_result = f"错误: {type(e).__name__}: {str(e)}"

    # Record step
    step = {
        "step": state.current_step + 1,
        "thought": state.current_thought,
        "action": action,
        "observation": state.tool_result,
    }
    state.steps.append(step)
    return state
```

### 4.5 `observe_node`

**Role**: 结果评估。LLM 判断任务是否完成，还是需要更多步骤。

```python
def observe_node(state: AgentState) -> AgentState:
    """
    INPUT:  state.tool_result
            state.current_thought
            state.steps
    OUTPUT: state.need_more_steps — True = continue loop; False = done
            state.scratchpad — 更新推理笔记
    """
    prompt = build_observe_prompt(
        tool_result=state.tool_result,
        current_thought=state.current_thought,
        steps=state.steps,
        max_steps=state.max_steps,
    )
    response = state["llm"].complete(
        system=OBSERVE_SYSTEM_PROMPT,
        prompt=prompt,
    )
    parsed = parse_observe_response(response)
    state.need_more_steps = parsed["continue"]
    state.scratchpad += f"\n  → {state.tool_result[:100]}... {'(继续)' if parsed['continue'] else '(完成)'}"
    return state
```

### 4.6 `final_reply_node`

**Role**: 组织最终回复给用户。

```python
def final_reply_node(state: AgentState) -> AgentState:
    """
    INPUT:  state.steps (all ReAct steps)
            state.final_reply (if set by plan_node directly)
    OUTPUT: state.is_done = True
            Save all to conversation_history in DB
    """
    if state.final_reply:
        reply = state.final_reply
    else:
        reply = build_final_reply(state.steps)

    state.final_reply = reply
    state.is_done = True
    save_conversation_turn(state["db_conn"], role="agent", content=reply)
    return state
```

### 4.7 `error_node`

```python
def error_node(state: AgentState) -> AgentState:
    """Catch all exceptions, record to history, set final reply."""
    state.error = str(state.last_error)
    state.final_reply = f"执行出错: {state.error}"
    state.is_done = True
    save_conversation_turn(state["db_conn"], role="agent", content=f"[ERROR] {state.error}")
    return state
```

---

## 5. Graph Edges

```python
def build_react_graph(skill_registry: SkillRegistry):
    graph = StateGraph(AgentState)

    # Add all nodes
    graph.add_node("start", start_node)
    graph.add_node("think", think_node)
    graph.add_node("plan", plan_node)
    graph.add_node("act", act_node)
    graph.add_node("observe", observe_node)
    graph.add_node("final_reply", final_reply_node)
    graph.add_node("error", error_node)

    # Edges
    graph.add_edge("start", "think")
    graph.add_edge("think", "plan")

    # Conditional: plan → act OR plan → final_reply
    graph.add_conditional_edges(
        "plan",
        lambda state: "act" if state.pending_action else "final_reply",
        {"act": "act", "final_reply": "final_reply"}
    )

    # act → observe
    graph.add_edge("act", "observe")

    # Conditional: observe → plan (loop) OR final_reply (end)
    graph.add_conditional_edges(
        "observe",
        lambda state: "think" if state.need_more_steps else "final_reply",
        {"think": "think", "final_reply": "final_reply"}
    )

    # error → final_reply
    graph.add_edge("error", "final_reply")

    # Set entry point
    graph.set_entry_point("start")

    # Compile with checkpointer for memory
    return graph.compile(checkpointer=MemorySaver())
```

---

## 6. ReAct Prompts

### 6.1 Think Prompt

```
你是 Sparki，一个意图驱动的 ReAct Agent。

当前任务: {latest_message}

你的 Pool 状态:
{pool_summary_str}

最近对话:
{history_str}

之前的推理步骤:
{scratchpad}

请分析用户意图，生成一段推理（thought）：
- 用户真正想要什么？
- 目前知道什么信息？
- 下一步应该做什么？

用中文回复，格式：
thought: <你的推理>
intent_type: <STATUS_QUERY|TASK_EXECUTION|SEARCH|MULTI_STEP|CLARIFICATION|CHITCHAT>
```

### 6.2 Plan Prompt

```
根据以下推理，制定行动计划：

推理: {current_thought}

当前 scratchpad:
{scratchpad}

可用工具:
{tool_list}

请决定下一步做什么：
- 如果需要调用工具，回复：
  action: {{"tool": "工具名", "args": {{"参数": "值"}}}}
- 如果已经足够回答用户，回复：
  reply: <你的直接回复>

用中文回复。
```

### 6.3 Observe Prompt

```
工具执行结果:
{tool_result}

基于这个结果，任务完成了吗？还需要更多步骤吗？

之前的推理: {current_thought}
已执行步骤: {steps_summary}

请判断：
- 如果任务已完成，回复：continue: false
- 如果还需要更多步骤（查状态、生成更多图等），回复：continue: true

回复格式：
continue: true/false
next_thought: <基于结果的下一步推理>
```

---

## 7. Memory System

### 7.1 Short-term Memory (Session)

```python
class ShortTermMemory:
    """In-session messages stored in AgentState.messages."""

    def __init__(self, state: AgentState):
        self.state = state

    def add_turn(self, role: str, content: str) -> None:
        self.state.steps.append({
            "role": role,
            "content": content,
            "step": len(self.state.steps) + 1,
        })

    def get_history(self, limit: int = 20) -> list[dict]:
        return self.state.steps[-limit:]

    def clear(self) -> None:
        self.state.steps = []
```

### 7.2 Long-term Memory (SQLite)

```python
class LongTermMemory:
    """Cross-session persistence via SQLite."""

    def save_turn(self, role, content, tool_name=None, tool_args=None):
        """Save one turn to conversation_history table."""

    def load_history(self, limit=20):
        """Load recent conversation history."""

    def save_preference(self, key, value):
        """Save a user preference."""

    def get_preference(self, key):
        """Get a user preference."""

    def search_prompts_by_embedding(self, query_text, top_k=5):
        """Semantic search prompts by embedding similarity."""

    def get_pool_summary(self):
        """Get current pool status counts."""

    def save_task_history(self, task_description, steps, result):
        """Archive completed task for future reference."""
```

### 7.3 Embedding Search

```python
def embed_text(text: str) -> list[float]:
    """Use Gemini embeddings API."""
    response = gemini_client.models.embed_content(
        model="gemini-embedding-exp-03-07",
        content=text,
    )
    return response.embeddings[0].values


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    import math
    dot = sum(x*y for x,y in zip(a,b))
    norm_a = math.sqrt(sum(x*x for x in a))
    norm_b = math.sqrt(sum(x*x for x in b))
    return dot / (norm_a * norm_b)


def search_prompts(query: str, top_k: int = 5) -> list[dict]:
    """Search prompts by semantic similarity."""
    query_vec = embed_text(query)
    conn = get_db_conn()
    rows = conn.execute(
        "SELECT prompt_id, embedding FROM prompt_embeddings"
    ).fetchall()
    scored = []
    for row in rows:
        emb = json.loads(row["embedding"])  # stored as JSON list
        score = cosine_similarity(query_vec, emb)
        scored.append((score, row["prompt_id"]))
    scored.sort(reverse=True)
    top_ids = [pid for _, pid in scored[:top_k]]
    # Fetch prompt details from prompts table
    ...
```

---

## 8. Skill Registry

### 8.1 SkillRegistry

```python
@dataclass
class Skill:
    name: str
    description: str
    category: str
    parameters: list["Parameter"]
    execute: Callable[[dict], str]
    examples: list[str] = field(default_factory=list)

@dataclass
class Parameter:
    name: str
    type: str           # "string" | "integer" | "boolean" | "array"
    description: str
    required: bool = False
    default: Any = None


class SkillRegistry:
    def __init__(self):
        self._tools: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._tools[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._tools.get(name)

    def list_all(self) -> list[str]:
        return list(self._tools.keys())

    def list_by_category(self, category: str) -> list[Skill]:
        return [s for s in self._tools.values() if s.category == category]

    def get_tool_schemas(self) -> list[dict]:
        """Return JSON schema for all tools (for LLM function calling)."""
        return [
            {
                "name": s.name,
                "description": s.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        p.name: {"type": p.type, "description": p.description}
                        for p in s.parameters
                    },
                    "required": [p.name for p in s.parameters if p.required],
                }
            }
            for s in self._tools.values()
        ]
```

### 8.2 Core Tools (注册到 Registry)

```python
def register_core_tools(registry: SkillRegistry):
    registry.register(Skill(
        name="pool_status",
        description="查看 Prompt 池各状态的当前数量",
        category="system",
        parameters=[],
        execute=lambda args: tool_pool_status(args),
        examples=["池子状态怎么样？", "还有多少图没生成？"]
    ))
    registry.register(Skill(
        name="search_prompts",
        description="通过语义Embedding搜索Prompt库，找到相关的Prompt",
        category="memory",
        parameters=[
            Parameter("query", "string", "搜索关键词", required=True),
            Parameter("top_k", "integer", "返回数量", default=5),
        ],
        execute=lambda args: tool_search_prompts(args),
        examples=["找和Veo 3 cinematic相关的prompt", "搜索动画风格的高质量提示词"]
    ))
    # ... 7 more core tools

# ── Keyword Strategy Tools (V3 扩展) ────────────────────────────────────────
def register_keyword_tools(registry: SkillRegistry):
    """注册关键词优化相关工具。"""

    registry.register(Skill(
        name="analyze_keyword_yield",
        description="分析历史漏斗表现，返回各关键词的 raw/filtered/extracted/qualified 数量和比率",
        category="keyword_strategy",
        parameters=[
            Parameter("top_n", "integer", "返回数量，默认 10", default=10),
            Parameter("scrape_run_id", "integer", "限定某次爬取", default=None),
        ],
        execute=lambda args: tool_analyze_keyword_yield(args),
        examples=["分析关键词效果", "哪些关键词表现最好？"]
    ))

    registry.register(Skill(
        name="generate_keyword_suggestions",
        description="基于历史漏斗表现生成新的关键词建议（需要用户确认后才能用于爬虫）",
        category="keyword_strategy",
        parameters=[
            Parameter("top_n", "integer", "建议数量，默认 5", default=5),
            Parameter("based_on_high_yield", "boolean", "是否基于高 yield 词扩展", default=True),
        ],
        execute=lambda args: tool_generate_keyword_suggestions(args),
        examples=["有什么优化建议？", "推荐新的关键词"]
    ))

    registry.register(Skill(
        name="confirm_keywords",
        description="用户确认/否决 AI 建议的关键词（确认后写入 approved_keywords 表，用于下次爬虫）",
        category="keyword_strategy",
        parameters=[
            Parameter("keywords", "array", "确认的关键词列表", required=True),
            Parameter("action", "string", "confirm 或 reject", default="confirm"),
            Parameter("note", "string", "备注（可选）", default=None),
        ],
        execute=lambda args: tool_confirm_keywords(args),
        examples=["确认 Veo 3.1 prompt 和 Google Veo experimental", "否决第2个建议"]
    ))

    registry.register(Skill(
        name="show_approved_keywords",
        description="查看当前已确认用于爬取的关键词列表",
        category="keyword_strategy",
        parameters=[],
        execute=lambda args: tool_show_approved_keywords(args),
        examples=["当前有哪些已确认的关键词？", "看看活跃的关键词"]
    ))

    registry.register(Skill(
        name="crawl_with_keywords",
        description="使用指定关键词执行爬虫（优先级：用户指定 > 已确认推荐 > seed）",
        category="data_collection",
        parameters=[
            Parameter("keywords", "array", "使用的关键词列表（默认使用已确认的推荐关键词）", default=None),
            Parameter("from_cache", "boolean", "是否使用缓存", default=True),
            Parameter("record_yield", "boolean", "是否记录漏斗数据（默认 True）", default=True),
        ],
        execute=lambda args: tool_crawl_with_keywords(args),
        examples=["用已确认的关键词跑一轮", "用 Veo 3 prompt 和 AI video cinematic 爬"]
    ))


def register_all_tools(registry: SkillRegistry):
    register_core_tools(registry)
    register_keyword_tools(registry)
```

`register_all_tools(registry)` 注册所有工具（9 个 core + 5 个 keyword strategy = 14 个）。

---

## 8B. Keyword Strategy System

### 8B.1 Keyword Priority Logic

```python
def get_active_keywords(db_conn, user_specified: list[str] | None = None) -> list[str]:
    """
    Keyword 优先级：
    1. 用户明确指定 → 直接返回用户指定
    2. 用户无指定 → 查 approved_keywords 表（状态=approved）
    3. 无已确认推荐 → 使用 configs/queries.yaml 的 seed_queries
    """
    if user_specified:
        return user_specified  # 用户指定优先，跳过所有建议

    approved = db_conn.execute(
        "SELECT keyword FROM approved_keywords ORDER BY approved_at DESC"
    ).fetchall()
    if approved:
        return [r["keyword"] for r in approved]

    # fallback to seed
    import yaml
    with open("configs/queries.yaml") as f:
        data = yaml.safe_load(f)
    return data.get("queries", [])
```

### 8B.2 Funnel Recording

每次 `crawl_with_keywords` 完成后，自动记录漏斗数据：

```python
def record_keyword_yield(db_conn, keyword: str, scrape_run_id: int,
                          raw: int, filtered: int,
                          extracted: int, qualified: int) -> None:
    """将漏斗数据写入 keyword_yields 表。"""
    yield_score = qualified / raw if raw > 0 else 0
    db_conn.execute("""
        INSERT INTO keyword_yields
            (keyword, scrape_run_id, raw_tweets, filtered_tweets,
             extracted_prompts, qualified_prompts, yield_score, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [keyword, scrape_run_id, raw, filtered, extracted, qualified,
          yield_score, datetime.now(timezone.utc).isoformat()])
    db_conn.commit()
```

### 8B.3 Keyword Suggestion Generation

```python
def generate_keyword_suggestions(db_conn, top_n: int = 5) -> list[dict]:
    """基于历史 yield 数据生成关键词建议。"""
    high_yield = db_conn.execute("""
        SELECT keyword, qualified_rate FROM keyword_yields
        WHERE qualified_rate >= 0.05
        ORDER BY qualified_rate DESC LIMIT 10
    """).fetchall()

    suggestions = []
    for r in high_yield:
        base = r["keyword"]
        for variant in [f"{base} 3.1", f"{base} experimental", f"AI {base}"]:
            suggestions.append({
                "suggested_keyword": variant,
                "reason": f"基于 '{base}' (qualified rate {r['qualified_rate']:.1%}) 扩展",
                "based_on_keyword": base,
            })
    return suggestions[:top_n]
```

### 8B.4 Confirmation Workflow

```python
def confirm_keywords(db_conn, keywords: list[str], action: str, note: str = None) -> str:
    """
    确认或否决建议的关键词。
    action='confirm' → 写入 approved_keywords
    action='reject' → 标记 keyword_suggestions.status='rejected'
    """
    if action == "confirm":
        now = datetime.now(timezone.utc).isoformat()
        for kw in keywords:
            db_conn.execute("""
                INSERT OR REPLACE INTO approved_keywords (keyword, source, approved_at, note)
                VALUES (?, 'agent_recommendation', ?, ?)
            """, [kw, now, note])
        db_conn.commit()
        return f"已确认 {len(keywords)} 个关键词：{keywords}"
    elif action == "reject":
        for kw in keywords:
            db_conn.execute(
                "UPDATE keyword_suggestions SET status='rejected' WHERE suggested_keyword=?",
                [kw]
            )
        db_conn.commit()
        return f"已否决 {len(keywords)} 个建议：{keywords}"
```

### 8B.5 Database Schema (keyword tables)

```sql
CREATE TABLE IF NOT EXISTS keyword_yields (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword         TEXT NOT NULL,
    scrape_run_id   INTEGER REFERENCES scrape_runs(id),
    raw_tweets      INTEGER DEFAULT 0,
    filtered_tweets INTEGER DEFAULT 0,
    extracted_prompts INTEGER DEFAULT 0,
    qualified_prompts INTEGER DEFAULT 0,
    yield_score     REAL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS keyword_suggestions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    suggested_keyword TEXT NOT NULL,
    reason          TEXT,
    based_on_keyword TEXT,
    status          TEXT DEFAULT 'pending',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approved_keywords (
    keyword         TEXT PRIMARY KEY,
    source          TEXT,
    approved_at     TEXT NOT NULL,
    note            TEXT
);
```

---

## 9. CLI Entry Point

```bash
# Interactive REPL
python -m src.agent.chat

# Single-shot
python -m src.agent.chat --msg "池子状态怎么样？"

# With history limit
python -m src.agent.chat --msg "生成10张图" --max-history 50
```

```python
# src/agent/chat.py
def main():
    skill_registry = SkillRegistry()
    register_core_tools(skill_registry)

    llm = GeminiClient(...)
    db_conn = init_db()

    agent = SparkiReActAgent(
        llm=llm,
        db_conn=db_conn,
        skill_registry=skill_registry,
    )

    if args.msg:
        result = agent.run(args.msg)
        print(result)
    else:
        print("Sparki ReAct Agent v3.0")
        print("输入 /help 查看命令, /quit 退出\n")
        while True:
            user_input = input("\n你: ")
            if user_input == "/quit":
                break
            if user_input == "/history":
                for t in agent.get_history():
                    print(f"[{t['role']}]: {t['content'][:80]}")
                continue
            result = agent.run(user_input)
            print(f"\nSparki: {result}")
```

---

## 10. Configuration

### 10.1 V3 Agent Config (`configs/agent.yaml`)

```yaml
agent:
  model: "gemini-3.5-flash"
  max_steps: 10
  max_history: 20

  react:
    think_model: "gemini-3.5-flash"
    plan_model: "gemini-3.5-flash"
    observe_model: "gemini-3.5-flash"

  embedding:
    model: "gemini-embedding-exp-03-07"
    dimension: 768

  tools:
    concurrency: 1          # serial tool execution
    timeout_per_tool: 120   # seconds
```

---

## 11. Operational Runbook

### 11.1 启动 Chat Agent

```bash
python -m src.agent.chat
```

### 11.2 典型对话流程

```
你: 找最近关于AI视频生成的高质量prompt
Sparki [ReAct]:
  Step 1 - Think: 用户想搜索AI视频生成相关的prompt...需要用embedding搜索
  Step 1 - Plan: action={"tool": "search_prompts", "args": {"query": "AI video generation prompt", "top_k": 10}}
  Step 1 - Act: 找到 12 条相关prompt，质量分 0.71-0.89
  Step 1 - Observe: continue=false
  Final: 找到了 12 条相关prompt（质量分 0.71-0.89），按相关性排序：
         1. "Cinematic mountain landscape with dynamic lighting..." (0.89)
         2. "Anime character animation with smooth motion..." (0.85)
         ...

你: 生成前3张的封面图
Sparki [ReAct]:
  Step 1 - Think: 用户想要生成前3个prompt的封面图
  Step 1 - Plan: action={"tool": "generate_images", "args": {"batch": 3, "sort_by": "relevance"}}
  Step 1 - Act: 3/3 成功，耗时 8 分钟
  Step 1 - Observe: continue=false
  Final: 封面图生成完成！3/3 成功，已上传到 GCS。
         当前池子: 131 pending, 42 done, 130 failed
```

### 11.3 添加新 Skill

```python
# src/agent/skills/tiktok_scroll.py
from src.agent.skills.base import Skill, Parameter

def tool_tiktok_scroll(args: dict) -> str:
    """TikTok scroll skill implementation."""
    ...

tiktok_skill = Skill(
    name="tiktok_scroll",
    description="从 TikTok 爬取 AI 生成相关的短视频描述作为 Prompt",
    category="data_collection",
    parameters=[
        Parameter("keyword", "string", "搜索关键词", required=True),
        Parameter("max_videos", "integer", "最大视频数", default=20),
    ],
    execute=tool_tiktok_scroll,
    examples=["爬取TikTok上的Veo视频", "抓取AI动画相关内容"]
)

skill_registry.register(tiktok_skill)
# 无需修改 Agent 核心代码
```

---

## 12. Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| ReAct with explicit Thought | Yes | 多步任务规划必需；隐式推理无法处理复杂链 |
| Think/Plan/Observe 分开 | Yes | 各阶段职责单一，便于测试和替换 LLM |
| Serial tool execution | Yes | 避免 429 + 简化 ReAct 循环 |
| SQLite BLOB for embeddings | Yes | 无需 Pinecone 等外部依赖，单用户足够 |
| SkillRegistry 动态注册 | Yes | 新 Skill 不改 Agent 核心代码 |
| MemorySaver checkpointer | Yes | LangGraph 内置 session 恢复 |
| Intent classification in think_node | Yes | 不需要独立分类器，LLM 自己判断 |

---

## 13. Two-Mode Architecture

V3 Agent 支持两种运行模式：**Agent 模式**（自主选工具）和 **Pipeline 模式**（自动串链）。

### 13.1 模式决策

由 `think_node` 的 `intent_type` 决定：

| intent_type | 模式 | 说明 |
|---|---|---|
| `STATUS_QUERY` / `SEARCH` / `TASK_EXECUTION` / `CHITCHAT` | Agent 模式 | 单步或几步，LLM 自主选工具 |
| `MULTI_STEP` + 触发关键词 | Pipeline 模式 | Agent 自动串完整 phase 链 |

**Pipeline 触发关键词**（`_keyword_intent` 中匹配）：
`"全程"` / `"完整流程"` / `"一键"` / `"跑一遍"` / `"更新全部"` / `"全流程"`

### 13.2 Agent 模式

用户单次请求，V3 自主决定调用哪个工具（可多步 ReAct）：

```
用户: "还有哪些图没生成？" 
  → think: STATUS_QUERY
  → plan: pool_status
  → act: 返回 pending: 47, done: 42, failed: 3
  → observe: continue=false
  → final_reply: 当前 47 条待生成...

用户: "搜索 cinematic 相关的"
  → think: SEARCH
  → plan: search_prompts
  → act: 返回 5 条结果
  → observe: continue=false
  → final_reply: 找到了 5 条...

用户: "生成前 5 张封面图"
  → think: TASK_EXECUTION
  → plan: generate_images
  → act: 5/5 成功
  → observe: continue=false
  → final_reply: 5 张封面图已生成
```

### 13.3 Pipeline 模式

当用户说"跑一遍全程"时，V3 自动依次调用各 phase 工具，直到完成：

```
用户: "跑一遍完整流程"
  → think: MULTI_STEP
  → plan: crawl_tweets (from_cache=true)
  → observe: continue=true
  
  → think: 需要生成图片
  → plan: generate_images (batch=0, sort_by="score")
  → observe: continue=true
  
  → think: 需要同步图片
  → plan: sync_images
  → observe: continue=true
  
  → think: 需要构建并发布
  → plan: publish
  → observe: continue=false
  
  → final_reply: 全流程完成！爬取 0 条（from_cache），生成 15 张，发布成功
```

Pipeline 模式本质上是 ReAct 循环的多次迭代，`observe_node` 每次看到"还有未完成的 phase"就决定继续。

### 13.4 Phase Skills（方案 B — 全部拆分）

废弃 `tool_crawl`（内部跑 V1 main.py），每个 phase 变成独立 Skill：

| Skill | Category | 原子功能 |
|---|---|---|
| `crawl_tweets` | data_collection | 爬 X.com 推文，直接调 Apify API |
| `extract_prompts` | data_collection | 从爬到的推文提取 prompt（LLM extraction） |
| `score_prompts` | data_collection | 质量评分 + 过滤 |
| `generate_images` | ai_generation | 为 pending prompts 生成封面图（GCS） |
| `sync_images` | ai_generation | GCS 图片同步到本地 `generated_images/` |
| `build_html` | web_maintenance | DB + 模板 → `outputs/index.html` |
| `publish` | web_maintenance | Git add + commit + push gh-pages |
| `pool_status` | system | 查询池子状态 |
| `search_prompts` | memory | Embedding 语义搜索 |
| `retry_failed` | ai_generation | 重试 failed prompts |
| `show_history` | system | 查看任务历史 |
| `save_preference` | memory | 保存偏好 |
| `get_preference` | memory | 读取偏好 |

**总数：12 个核心 Skills**（不含 keyword strategy 5 个）

### 13.5 Phase 依赖关系

```
crawl_tweets
    ↓（写入 tweets）
extract_prompts
    ↓（写入 prompts，image_status=pending）
score_prompts
    ↓（更新 quality_scores）
generate_images
    ↓（写入 image_gcs_url，image_status=done）
sync_images
    ↓（图片到本地 generated_images/）
build_html
    ↓（生成 index.html）
publish
    ↓（Git push）
```

**原则：每个 phase 只依赖前置 phase 的输出，不做跨阶段隐式调用。**

### 13.6 V1 main.py 废弃

方案 B 废弃 `src.main run` 的 phase 调用：

- **废弃**：V1 phase 驱动（`python -m src.main run --all`）
- **保留**：`src.main init-db`（数据库初始化）
- **保留**：`src.main status`（状态查看）
- `compile_graph()` 兼容层标记为 deprecated，不被 V3 调用

### 13.7 Pipeline 自主决策逻辑

`observe_node` 在 Pipeline 模式下的决策规则：

```python
# Pipeline 模式：tool_result 包含 phase 状态关键字
tool_result = state.tool_result or ""

if "爬取完成" in tool_result or "crawl" in tool_result.lower():
    # 下一步：生成图片
    return "generate_images"

if "pending" in tool_result and "pending: 0" not in tool_result:
    # 还有 pending → 生成图片
    return "generate_images"

if "failed" in tool_result and "failed: 0" not in tool_result:
    # 有失败 → 重试
    return "retry_failed"

if "done" in tool_result and "pending: 0" in tool_result and "failed: 0" in tool_result:
    # 全完成 → 发布
    return "publish"

if "发布完成" in tool_result or "publish" in tool_result.lower():
    # 整个 Pipeline 结束
    return None  # continue=false
```

（实际由 LLM 在 `observe_node` 中根据 tool_result 判断）

### 13.8 并行开发任务

See [04_ParallelDevCommands_V3.md](04_ParallelDevCommands_V3.md)

| Code | 任务 |
|---|---|
| Code-1 | Phase Skills 拆分（crawl_tweets, extract_prompts, score_prompts, sync_images, build_html） |
| Code-2 | Pipeline 模式识别（think_node MULTI_STEP 检测）+ observe_node 决策增强 |
| Code-3 | V1 main.py 废弃 + 兼容层清理 |
| Code-4 | Embedding search 实现 |
| Code-5 | Keyword strategy tools |
| Code-6 | 测试 + 集成 |

---

## 14. Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| ReAct with explicit Thought | Yes | 多步任务规划必需；隐式推理无法处理复杂链 |
| Think/Plan/Observe 分开 | Yes | 各阶段职责单一，便于测试和替换 LLM |
| Serial tool execution | Yes | 避免 429 + 简化 ReAct 循环 |
| SQLite BLOB for embeddings | Yes | 无需 Pinecone 等外部依赖，单用户足够 |
| SkillRegistry 动态注册 | Yes | 新 Skill 不改 Agent 核心代码 |
| MemorySaver checkpointer | Yes | LangGraph 内置 session 恢复 |
| Intent classification in think_node | Yes | 不需要独立分类器，LLM 自己判断 |