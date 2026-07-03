# Sparki V3 Interface Contract — ReAct Agent + LangGraph

> **Version**: 3.0 | **Purpose**: Strict contracts for ReAct nodes, Skill registry, Memory system

---

## 1. Design Principles

1. **ReAct Thought-Action-Observation as first-class contract** — every loop step has explicit typed fields
2. **Skill as unit of extensibility** — every tool is a `Skill` with schema, registered at startup
3. **State flows through LangGraph** — each node declares inputs and outputs as AgentState fields
4. **Memory is explicit** — short-term = `AgentState.messages`, long-term = SQLite tables
5. **No implicit string parsing** — LLM outputs use structured JSON within defined schemas

---

## 2. AgentState Contract (V3)

```python
@dataclass
class AgentState:
    """LangGraph state — all fields updated by nodes."""

    # ── Runtime ────────────────────────────────────────────────────────────────
    llm: Any = None
    db_conn: Any = None
    skill_registry: Any = None           # SkillRegistry instance

    # ── Input ───────────────────────────────────────────────────────────────────
    latest_message: str = ""

    # ── Intent (set by think_node) ─────────────────────────────────────────────
    intent_type: str = "TASK_EXECUTION"   # STATUS_QUERY | TASK_EXECUTION | SEARCH | MULTI_STEP | CLARIFICATION | CHITCHAT

    # ── ReAct Loop ──────────────────────────────────────────────────────────────
    scratchpad: str = ""                  # Accumulated reasoning across steps
    current_thought: str = ""             # Current step's thought text
    steps: list[dict] = field(default_factory=list)  # ReAct steps
    current_step: int = 0
    max_steps: int = 10

    # ── Node Outputs ─────────────────────────────────────────────────────────────
    pending_action: dict | None = None    # {"tool": "...", "args": {...}}
    tool_result: str | None = None       # Result from act_node
    final_reply: str | None = None       # Text reply to user
    error: str | None = None

    # ── Loop Control ────────────────────────────────────────────────────────────
    need_more_steps: bool = False
    is_done: bool = False

    # ── Memory (injected at each step) ─────────────────────────────────────────
    pool_summary: "PoolSummary" = None
    recent_history: list[dict] = field(default_factory=list)
```

---

## 3. Intent Type Enum

```python
class IntentType(Enum):
    STATUS_QUERY    = "STATUS_QUERY"    # User asks about pool status, counts
    TASK_EXECUTION  = "TASK_EXECUTION"  # User requests a concrete action (generate, crawl, publish)
    SEARCH          = "SEARCH"          # User wants to search/find something
    MULTI_STEP     = "MULTI_STEP"      # Complex task requiring multiple steps
    CLARIFICATION  = "CLARIFICATION"   # Intent unclear, need to ask user
    CHITCHAT       = "CHITCHAT"        # Casual conversation, no tool needed
```

---

## 4. ReAct Step Schema

```python
@dataclass
class ReActStep:
    """Single step in ReAct loop."""
    step_number: int
    thought: str                          # LLM reasoning
    action: dict | None = None           # {"tool": "...", "args": {...}}
    observation: str | None = None         # Tool execution result
    tool_name: str | None = None
    tool_args: dict | None = None
    result: str | None = None             # Formatted result
    error: str | None = None
    timestamp: str = ""                   # ISO8601
```

**Valid State Transitions per Step:**
```
think_node → plan_node → act_node → observe_node
                                          ↑
              (if need_more_steps=True) ──┘
```

---

## 5. Node Input/Output Contracts

### 5.1 `start_node`

| Reads | Writes |
|---|---|
| `latest_message` | `steps=[]`, `current_step=0`, `scratchpad=""`, `is_done=False`, `error=None`, `pending_action=None`, `tool_result=None`, `final_reply=None`, `need_more_steps=False` |

### 5.2 `think_node`

| Reads | Writes |
|---|---|
| `latest_message` | `current_thought`, `intent_type`, `scratchpad` |
| `scratchpad` | |
| `pool_summary`, `recent_history` | |

**LLM Prompt Contract**: Think prompt must produce:
```
thought: <reasoning string>
intent_type: <IntentType value>
```

### 5.3 `plan_node`

| Reads | Writes |
|---|---|
| `current_thought` | `pending_action` OR `final_reply` |
| `scratchpad` | |
| `available_tools` (from skill_registry) | |

**Output contract:**
- If `pending_action` is set → next node is `act_node`
- If `final_reply` is set → next node is `final_reply_node`

### 5.4 `act_node`

| Reads | Writes |
|---|---|
| `pending_action` | `tool_result` |
| `skill_registry` | `steps` (append current step) |

**Tool execution contract:**
- Returns `tool_result: str` — human-readable result
- Never raises exception — errors converted to `tool_result` string

### 5.5 `observe_node`

| Reads | Writes |
|---|---|
| `tool_result` | `need_more_steps` |
| `current_thought` | `scratchpad` (append observation) |
| `steps` | |

**LLM Prompt Contract**: Observe prompt must produce:
```
continue: true/false
next_thought: <string, required if continue=true>
```

### 5.6 `final_reply_node`

| Reads | Writes |
|---|---|
| `steps` | `final_reply` (final text) |
| `final_reply` (if already set) | `is_done=True` |

---

## 6. Skill Registry Contract

### 6.1 Skill Dataclass

```python
@dataclass
class Skill:
    name: str                                    # Unique identifier, e.g. "pool_status"
    description: str                              # Human-readable description for LLM
    category: str                                 # "system" | "data_collection" | "ai_generation" | "web_maintenance" | "memory"
    parameters: list["Parameter"] = field(default_factory=list)
    execute: Callable[[dict], str]                # (args: dict) -> str
    examples: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)  # Custom metadata (version, author, etc.)

@dataclass
class Parameter:
    name: str
    type: str                                     # "string" | "integer" | "boolean" | "array" | "object"
    description: str
    required: bool = False
    default: Any = None
    enum: list[str] | None = None                # For constrained values
```

### 6.2 SkillRegistry Interface

```python
class SkillRegistry:
    def register(self, skill: Skill) -> None:
        """Register a skill. Raises ValueError if name already exists."""
        if skill.name in self._tools:
            raise ValueError(f"Skill '{skill.name}' already registered")
        self._tools[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        """Get skill by name."""

    def list_all(self) -> list[str]:
        """List all registered skill names."""

    def list_by_category(self, category: str) -> list[Skill]:
        """List all skills in a category."""

    def get_tool_schemas(self) -> list[dict]:
        """Return JSON schema list for all tools (for LLM function calling)."""
        # Format: [{"name": "...", "description": "...", "parameters": {...}}, ...]

    def get_categories(self) -> list[str]:
        """Return all unique categories."""
```

### 6.3 Skill JSON Schema (for LLM)

Each skill's parameters follow this JSON Schema format:

```json
{
  "name": "generate_images",
  "description": "为 Prompt 池中的项目生成封面图",
  "parameters": {
    "type": "object",
    "properties": {
      "batch": {
        "type": "integer",
        "description": "生成图片数量，默认8",
        "default": 8
      },
      "sort_by": {
        "type": "string",
        "description": "排序方式",
        "enum": ["score", "newest", "relevance"]
      },
      "filter": {
        "type": "object",
        "description": "过滤条件（如 min_score）",
        "default": null
      }
    },
    "required": []
  }
}
```

---

## 7. Tool Contracts (Core 9 Tools)

### 7.1 `pool_status`

```python
Skill(
    name="pool_status",
    description="查询 Prompt 池的当前状态——各状态的数量统计",
    category="system",
    parameters=[],
    execute=lambda args: tool_pool_status(args),
    examples=["池子状态怎么样？", "还有多少图没生成？"]
)
# INPUT:  {}
# OUTPUT: "Prompt Pool 状态:\n  pending:    134\n  generating:   3\n  done:       39\n  failed:    130\n  published:   0"
```

### 7.2 `search_prompts`

```python
Skill(
    name="search_prompts",
    description="通过语义Embedding搜索Prompt库，找到与关键词最相关的Prompt",
    category="memory",
    parameters=[
        Parameter("query", "string", "语义搜索的关键词", required=True),
        Parameter("top_k", "integer", "返回数量，默认5", default=5),
        Parameter("min_score", "float", "最低质量分筛选", default=None),
    ],
    execute=lambda args: tool_search_prompts(args),
    examples=["找Veo 3相关的prompt", "搜索动画风格高质量提示词"]
)
# INPUT:  {"query": "cinematic video", "top_k": 10}
# OUTPUT: "找到 10 条相关Prompt（按相关性排序）:\n  1. [0.89] \"Cinematic mountain...\"\n  2. [0.85] \"Dramatic lighting...\""
```

### 7.3 `crawl`

```python
Skill(
    name="crawl",
    description="从X.com爬取推文，提取高质量Prompt并入池",
    category="data_collection",
    parameters=[
        Parameter("queries", "array", "搜索关键词列表，默认使用configs/queries.yaml", default=None),
        Parameter("from_cache", "boolean", "是否使用上次缓存（跳过爬取）", default=True),
        Parameter("max_cost", "float", "最大消费（USD）", default=0.10),
    ],
    execute=lambda args: tool_crawl(args),
    examples=["爬取最新数据", "从缓存提取", "用新的搜索词跑一轮"]
)
# INPUT:  {"queries": ["veo prompt"], "from_cache": False}
# OUTPUT: "爬取完成: 6 个搜索词, 1422 条推文\n提取 Prompt: 203 条\n已入池 (pending): 187 条"
```

### 7.4 `generate_images`

```python
Skill(
    name="generate_images",
    description="为池中pending的Prompt生成封面图（串行安全模式，15s间隔）",
    category="ai_generation",
    parameters=[
        Parameter("batch", "integer", "生成数量，默认8", default=8),
        Parameter("sort_by", "string", "排序方式：score（质量分）/ newest（最新）/ relevance（相关性）", default="score"),
        Parameter("filter", "object", "过滤条件，如 {\"min_score\": 0.6}", default=None),
    ],
    execute=lambda args: tool_generate_images(args),
    examples=["生成10张图", "按分数生成前5张"]
)
# INPUT:  {"batch": 10, "sort_by": "score"}
# OUTPUT: "图片生成完成: 8/10 成功, 2/10 失败（已回池）\n模型: gemini-2.5-flash-image\n耗时: 4分32秒\n当前池: 126 pending, 47 done, 132 failed"
```

### 7.5 `retry_failed`

```python
Skill(
    name="retry_failed",
    description="重试之前图片生成失败的Prompt",
    category="ai_generation",
    parameters=[
        Parameter("batch", "integer", "最大重试数量，默认8", default=8),
    ],
    execute=lambda args: tool_retry_failed(args),
    examples=["重试失败的图", "把失败的再跑一遍"]
)
# INPUT:  {"batch": 10}
# OUTPUT: "已重置 130 条 failed → pending\n开始生成 8 张...\n图片生成完成: 6/8 成功, 2/8 失败\n当前池: 124 pending, 53 done, 2 failed"
```

### 7.6 `publish`

```python
Skill(
    name="publish",
    description="将池中done状态的Prompt发布到GitHub Pages网站",
    category="web_maintenance",
    parameters=[],
    execute=lambda args: tool_publish(args),
    examples=["发布网页", "更新网站"]
)
# INPUT:  {}
# OUTPUT: "发布完成!\n已发布 49 条 Prompt\nHTML: outputs/veo3-prompt-library.html\n在线: https://sparki-ai.github.io/veo-prompt-station\n49 条已标记为 published"
```

### 7.7 `show_history`

```python
Skill(
    name="show_history",
    description="查看最近的任务执行历史和对话记录",
    category="system",
    parameters=[
        Parameter("limit", "integer", "显示数量，默认5", default=5),
        Parameter("include_conversation", "boolean", "是否包含对话历史", default=True),
    ],
    execute=lambda args: tool_show_history(args),
    examples=["之前做了什么", "看看历史"]
)
# INPUT:  {"limit": 10}
# OUTPUT: "最近 10 次运行:\n  #6 | 2026-05-20 17:30 | 203 prompts | 39 images | DONE\n  #5 | 2026-05-20 14:00 | 198 prompts | 0 images | DONE"
```

### 7.8 `save_preference`

```python
Skill(
    name="save_preference",
    description="保存用户偏好设置",
    category="memory",
    parameters=[
        Parameter("key", "string", "偏好键名", required=True),
        Parameter("value", "string", "偏好值", required=True),
    ],
    execute=lambda args: tool_save_preference(args),
    examples=["记住我偏好10张一批", "设置默认模型为gemini-2.5"]
)
# INPUT:  {"key": "default_batch_size", "value": "10"}
# OUTPUT: "已保存: default_batch_size = 10"
```

### 7.9 `get_preference`

```python
Skill(
    name="get_preference",
    description="读取用户偏好设置",
    category="memory",
    parameters=[
        Parameter("key", "string", "偏好键名", required=True),
    ],
    execute=lambda args: tool_get_preference(args),
    examples=["我之前偏好是什么", "默认批次大小是多少"]
)
# INPUT:  {"key": "default_batch_size"}
# OUTPUT: "default_batch_size = 10"
```

### 7.10 `analyze_keyword_yield`

```python
Skill(
    name="analyze_keyword_yield",
    description="分析历史漏斗表现，返回各关键词的 raw/filtered/extracted/qualified 数量和比率",
    category="keyword_strategy",
    parameters=[
        Parameter("top_n", "integer", "返回数量，默认10", default=10),
        Parameter("scrape_run_id", "integer", "限定某次爬取（可选）", default=None),
    ],
    execute=lambda args: tool_analyze_keyword_yield(args),
    examples=["分析关键词效果", "哪些关键词表现最好？"]
)
# INPUT:  {"top_n": 10}
# OUTPUT: "关键词漏斗分析（按综合漏斗率排序）:\n  AI video prompt: 300 raw → 89 filtered → 23 extracted → 8 qualified (综合漏斗率: 2.7%)\n  Veo 3 prompt: 280 raw → 75 filtered → 18 extracted → 5 qualified (1.8%)"
```

### 7.11 `generate_keyword_suggestions`

```python
Skill(
    name="generate_keyword_suggestions",
    description="基于历史漏斗表现生成新的关键词建议（需要用户确认后才能用于爬虫）",
    category="keyword_strategy",
    parameters=[
        Parameter("top_n", "integer", "建议数量，默认5", default=5),
        Parameter("based_on_high_yield", "boolean", "是否基于高 yield 词扩展", default=True),
    ],
    execute=lambda args: tool_generate_keyword_suggestions(args),
    examples=["有什么优化建议？", "推荐新的关键词"]
)
# INPUT:  {"top_n": 5}
# OUTPUT: "建议新增关键词（待确认）:\n  1. Veo 3.1 prompt | 基于 'Veo 3 prompt'，qualified rate 2.7% → 推测更高\n  2. AI video cinematic shot | 基于高 qualified 词组合\n  3. Google Veo experimental | 变体探索"
```

### 7.12 `confirm_keywords`

```python
Skill(
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
)
# INPUT:  {"keywords": ["Veo 3.1 prompt", "Google Veo experimental"], "action": "confirm"}
# OUTPUT: "已确认 2 个关键词：['Veo 3.1 prompt', 'Google Veo experimental']\n当前活跃关键词：[seed...] + [已确认推荐...]"
```

### 7.13 `show_approved_keywords`

```python
Skill(
    name="show_approved_keywords",
    description="查看当前已确认用于爬取的关键词列表",
    category="keyword_strategy",
    parameters=[],
    execute=lambda args: tool_show_approved_keywords(args),
    examples=["当前有哪些已确认的关键词？", "看看活跃的关键词"]
)
# INPUT:  {}
# OUTPUT: "已确认用于爬取的关键词（共 5 个）:\n  1. Veo 3.1 prompt (agent_recommendation, 2026-05-20)\n  2. Google Veo experimental (agent_recommendation, 2026-05-20)\n  3. AI video prompt (seed)\n  ..."
```

### 7.14 `crawl_with_keywords`

```python
Skill(
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
)
# INPUT:  {"keywords": ["Veo 3.1 prompt", "Google Veo experimental"]}
# OUTPUT: "爬取完成: 2 个关键词, 456 条推文\n提取 Prompt: 67 条\n已入池 (pending): 61 条\n已记录漏斗: Veo 3.1 prompt (180 raw → 52 filtered → 14 extracted → 5 qualified, 2.8%)\n           Google Veo experimental (276 raw → 89 filtered → 23 extracted → 8 qualified, 2.9%)"
```

---

## 8. Memory Schema + Keyword Tables

### 8.1 Table: `conversation_history`

```sql
CREATE TABLE IF NOT EXISTS conversation_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    role        TEXT NOT NULL CHECK (role IN ('user', 'agent', 'tool')),
    content     TEXT NOT NULL,
    tool_name   TEXT,
    tool_args   TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversation_created ON conversation_history(created_at DESC);
```

### 8.2 Table: `user_preferences`

```sql
CREATE TABLE IF NOT EXISTS user_preferences (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
```

### 8.3 Table: `prompt_embeddings`

```sql
CREATE TABLE IF NOT EXISTS prompt_embeddings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id   INTEGER NOT NULL REFERENCES prompts(id),
    embedding   BLOB NOT NULL,        -- JSON-encoded float32 list
    model       TEXT NOT NULL,        -- e.g. "gemini-embedding-exp-03-07"
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prompt_emb_prompt_id ON prompt_embeddings(prompt_id);
```

### 8.4 Table: `task_history`

```sql
CREATE TABLE IF NOT EXISTS task_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    description     TEXT NOT NULL,
    steps_json      TEXT NOT NULL,    -- JSON array of ReActStep
    result_summary  TEXT,
    created_at      TEXT NOT NULL,
    completed_at    TEXT
);
```

### 8.5 Table: `prompts` (V3 Enhancement)

```sql
-- V3: image_status column (from V2)
ALTER TABLE prompts ADD COLUMN image_status TEXT DEFAULT 'pending'
    CHECK (image_status IN ('pending','generating','done','failed','published'));

-- V3: Add embedding status
ALTER TABLE prompts ADD COLUMN embedding_status TEXT DEFAULT 'pending'
    CHECK (embedding_status IN ('pending','embedded','failed'));
```

---

## 9. Node Dependency Map

```
START ──▶ THINK ──▶ PLAN
                │         │
           ┌────┘         └──────┐
           ▼                     ▼
        ACT                  FINAL_REPLY
           │
           ▼
        OBSERVE ◀─────────────┐
           │                  │
     ┌─────┴─────┐            │
     ▼           ▼            │
  (continue)  (done)          │
   THINK      FINAL_REPLY      │
     │                       │
     └───────────────────────┘
```

| Node | Reads from State | Writes to State |
|---|---|---|
| `start` | `latest_message` | All loop fields reset |
| `think` | `latest_message`, `scratchpad`, `pool_summary`, `recent_history` | `current_thought`, `intent_type`, `scratchpad` |
| `plan` | `current_thought`, `scratchpad` | `pending_action` OR `final_reply` |
| `act` | `pending_action`, `skill_registry` | `tool_result`, `steps` |
| `observe` | `tool_result`, `current_thought`, `steps` | `need_more_steps`, `scratchpad` |
| `final_reply` | `steps`, `final_reply` | `final_reply`, `is_done=True` |
| `error` | `error` | `final_reply`, `is_done=True` |

---

## 10. ReAct Prompt Schemas

### 10.1 Think Prompt (输入 → 输出)

**Input variables:**
- `latest_message`: str
- `pool_summary_str`: str
- `history_str`: str
- `scratchpad`: str

**Output schema:**
```
thought: <reasoning string, Chinese>
intent_type: <STATUS_QUERY|TASK_EXECUTION|SEARCH|MULTI_STEP|CLARIFICATION|CHITCHAT>
```

### 10.2 Plan Prompt

**Input variables:**
- `current_thought`: str
- `scratchpad`: str
- `tool_schemas`: list[dict]

**Output schema:**
```
action: {"tool": "tool_name", "args": {"arg1": "value1"}}
```
OR
```
reply: <direct text reply to user>
```

### 10.3 Observe Prompt

**Input variables:**
- `tool_result`: str
- `current_thought`: str
- `steps_summary`: str
- `max_steps`: int

**Output schema:**
```
continue: true/false
next_thought: <string, only if continue=true>
```

---

## 11. Error Handling Contract

| Error Type | Source | Handling |
|---|---|---|
| `ToolNotFoundError` | act_node | Write `"错误: 未找到工具 '{name}'"` to `tool_result` |
| `ToolExecutionError` | act_node | Write `"错误: {type}: {msg}"` to `tool_result` |
| `LLMError` | any node | `error_node` → `final_reply` = `"执行出错，请重试"` |
| `MaxStepsExceeded` | observe_node | `need_more_steps = False`, final reply = `"任务复杂，已执行最大步数，请简化请求"` |
| `IntentUnclear` | think_node | `intent_type = CLARIFICATION` → `final_reply` = ask user |

---

## 12. File Locations (V3)

```
src/
├── agent/
│   ├── __init__.py
│   ├── state.py              # AgentState dataclass
│   ├── graph.py              # build_react_graph()
│   ├── chat.py               # CLI entry point
│   ├── chat_agent.py         # SparkiReActAgent class
│   ├── nodes/
│   │   ├── __init__.py
│   │   ├── start_node.py      # Entry point
│   │   ├── think_node.py     # Intent + thought
│   │   ├── plan_node.py      # Action selection
│   │   ├── act_node.py       # Tool execution
│   │   ├── observe_node.py   # Loop control
│   │   ├── final_reply_node.py
│   │   └── error_node.py
│   ├── skills/
│   │   ├── __init__.py
│   │   ├── registry.py        # SkillRegistry
│   │   ├── base.py            # Skill, Parameter dataclasses
│   │   └── core_tools.py      # 9 core tool implementations
│   ├── memory/
│   │   ├── short_term.py      # AgentState.messages helpers
│   │   ├── long_term.py       # SQLite CRUD
│   │   └── embedding.py       # Gemini embeddings + cosine sim
│   └── react/
│       ├── formatter.py       # ReAct format helpers
│       ├── parser.py          # Parse LLM output → structured
│       └── prompt.py          # System prompts for each node
│
├── types/
│   ├── __init__.py
│   ├── chat.py               # V2 types (ToolName, etc.)
│   └── react.py              # NEW: ReActStep, IntentType, etc.
│
└── memory/
    └── schema.py              # Enhanced V3 schema (conversations, embeddings, tasks)
```