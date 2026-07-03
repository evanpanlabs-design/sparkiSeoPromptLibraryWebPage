# PRD V3: Sparki ReAct Agent — Intent-Driven Conversational Control

> **Version**: 3.0 | **Predecessor**: [01_PRD_V2.md](01_PRD_V2.md) v2.0
> **Framework**: ReAct (Reasoning + Acting) with LangGraph Orchestration

---

## 1. Vision

Sparki V3 是一个**意图驱动的 ReAct Agent**。用户用自然语言描述目标，Agent 自动进行：

```
意图解析 → 推理思考 → 任务规划 → 工具调用 → 结果评估 → 响应用户
```

支持多轮对话，具备**短期记忆**（Session 内）和**长期记忆**（Embedding 语义检索），可扩展接入更多 Skills。

```
用户: "帮我找最近关于 Veo 3 的高质量 Prompt，然后生成 5 张封面图发布到网站"

Agent (ReAct Loop):
  Thought: 用户想要①找 Veo3 相关的高质量 Prompt ②生成图 ③发布。需要先查池子状态，再决定爬新数据还是用现有数据。
  Action: tool=pool_status, args={}
  Observation: pending=134, done=39, failed=130。池子里没有专门标记"Veo 3"的分类，需要先看看有没有相关 prompt。
  Thought: 池子里的 prompt 没有明确标注，需要先用 embedding 搜索找到和"Veo 3 cinematic"相关的 prompt。
  Action: tool=search_prompts, args={"query": "Veo 3 cinematic video", "top_k": 10}
  Observation: 找到 8 条相关 prompt，质量分 0.65-0.82。先用这些生成图。
  Action: tool=generate_images, args={"batch": 5, "filter": {"min_score": 0.65}}
  Observation: 5/5 成功，耗时 12 分钟。
  Thought: 图片生成完毕，可以发布了。
  Action: tool=publish, args={}
  Observation: 已发布 44 条到 GitHub Pages。
  Final: 完成！发布了 5 张新图，网站现有 44 条 Prompt。
```

---

## 2. ReAct Framework

### 2.1 ReAct Loop

ReAct = **Reasoning + Acting** 交替执行，直到任务完成。

```
┌──────────────────────────────────────────────────────────────────┐
│                        ReAct Loop                                 │
│                                                                   │
│   ┌─────────────┐    ┌──────────────┐    ┌───────────────────┐   │
│   │   THINK     │───▶│    PLAN      │───▶│      ACT          │   │
│   │ (意图解析)   │    │ (任务规划)    │    │ (工具调用)        │   │
│   └─────────────┘    └──────────────┘    └─────────┬─────────┘   │
│         ▲                                           │           │
│         │                                           ▼           │
│         │              ┌────────────────────┐   ┌───────────┐    │
│         └──────────────│    OBSERVE         │◀──│  RESULT   │    │
│                        │ (结果评估+记忆)    │   └───────────┘    │
│                        └────────────────────┘                   │
└──────────────────────────────────────────────────────────────────┘
```

**每个 Step 的输出写入短期记忆（messages），供下一步使用。**

### 2.2 Thought-Action-Observation Format

```json
{
  "step": 1,
  "thought": "用户想要...我需要先...",
  "action": {"tool": "tool_name", "args": {...}},
  "observation": "工具返回结果..."
}
```

LLM 生成 `thought`，工具执行产生 `observation`，下一轮 LLM 根据 `observation` 继续推理。

### 2.3 ReAct vs V2 的区别

| | V2 (Simple Tool Use) | V3 (ReAct) |
|---|---|---|
| 推理链 | 无，LLM 直接输出工具调用 | 显式 `thought` + `action` + `observation` |
| 任务规划 | 无，用户说啥做啥 | LLM 自己规划多步任务链 |
| 记忆 | 仅上下文注入 | 每个 step 写入 messages，可追溯 |
| 多步规划 | 需用户明确说"先 X 再 Y" | Agent 自己决定步骤 |
| 适合场景 | 单工具调用 | 复杂多步任务 |

---

## 3. Memory Architecture

### 3.1 短期记忆 (Short-term Memory)

Session 内的对话历史，每个 ReAct Step 的 `thought-action-observation` 链都记录在这里。

| 组件 | 实现 | 内容 |
|---|---|---|
| `messages` | `list[dict]` in AgentState | 完整的 ReAct 链，格式见 §2.3 |
| `scratchpad` | `str` in AgentState | LLM 的推理过程笔记，下一步的 context |

**生命周期**：Session 结束（Agent 重启）时，清空 `messages`（或选择性存档到长期记忆）。

### 3.2 长期记忆 (Long-term Memory)

持久化存储，用于：
- 记住用户偏好
- 存储历史任务结果
- Embedding 语义检索（找相关 Prompt）

| 表 | 用途 | 实现 |
|---|---|---|
| `conversation_history` | 跨 Session 对话存档 | SQLite |
| `user_preferences` | 用户偏好 KV 存储 | SQLite |
| `prompt_embeddings` | Prompt 的 embedding 向量 | SQLite (BLOB) + Gemini embeddings |
| `task_history` | 历史任务执行记录 | SQLite |

### 3.3 Embedding 工作流

```
新 Prompt 入池 → Gemini embedding → 存到 prompt_embeddings 表
用户搜索 → query embedding → 余弦相似度 → top-k 结果
```

```sql
CREATE TABLE IF NOT EXISTS prompt_embeddings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id     INTEGER NOT NULL REFERENCES prompts(id),
    embedding     BLOB NOT NULL,          -- 768维 float32 vector
    model         TEXT NOT NULL,          -- 'gemini-embedding-exp-03-07'
    created_at    TEXT NOT NULL
);
```

---

## 4. Tool Architecture (ReAct Tools)

### 4.1 Core Tools (V3 必须实现)

| Tool | Description | Category |
|---|---|---|
| `pool_status` | 查询 Prompt 池各状态数量 | 状态查询 |
| `search_prompts` | Embedding 语义搜索 Prompt（新增 V3） | 状态查询 |
| `crawl` | 爬取 X.com → 入池 | 数据采集 |
| `extract` | 从缓存提取 Prompt（V3 独立工具） | 数据采集 |
| `score` | 对 Prompt 进行质量评分 | 数据处理 |
| `generate_images` | 生成封面图（串行安全模式） | AI 生图 |
| `retry_failed` | 重试失败的图片生成 | AI 生图 |
| `publish` | 发布网页到 GitHub Pages | 网站维护 |
| `show_history` | 查看历史任务和对话 | 系统 |

### 4.2 Keyword Strategy Tools (V3 扩展)

| Tool | Description | Category |
|---|---|---|
| `analyze_keyword_yield` | 分析历史漏斗，返回各 keyword 的 raw/filtered/extracted/qualified 数量和比率 | 数据分析 |
| `generate_keyword_suggestions` | 基于历史表现 + 质量分布，生成下一批建议关键词 | 数据分析 |
| `confirm_keywords` | 用户确认/否决 AI 建议的关键词（手动确认后才能用于爬虫） | 数据分析 |
| `crawl_with_keywords` | 使用指定关键词执行爬虫（优先级：用户指定 > 确认的推荐 > seed） | 数据采集 |

### 4.3 Skill Registry (可扩展)

```python
class SkillRegistry:
    """可扩展的工具注册表，支持动态加载 Skill。"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, name: str, tool: "Tool") -> None:
        """注册一个新 Tool。"""
        self._tools[name] = tool

    def get(self, name: str) -> "Tool | None":
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def list_by_category(self, category: str) -> list["Tool"]:
        return [t for t in self._tools.values() if t.category == category]
```

**Skill 接口标准：**
```python
@dataclass
class Tool:
    name: str
    description: str
    category: str                    # "data_collection" | "ai_generation" | "web_maintenance" | ...
    parameters: list[Parameter]       # JSON Schema for args
    execute: Callable[[dict], str]   # (args) -> result_string
    examples: list[str] = field(default_factory=list)  # 用例示例
```

### 4.3 Skill Registry (可扩展)

ReAct 的工具和 V2 不同：LLM 必须输出 `thought`（推理），然后才是 `action`（工具调用）。

**LLM 输出格式：**
```json
{
  "thought": "用户的目的是...我需要先...然后...",
  "action": {"tool": "tool_name", "args": {"arg1": "value1"}}
}
```

不再是纯 JSON 工具调用，而是 `{thought, action}` 结构。

---

## 4B. Keyword Strategy Optimization

### 4B.1 Concept

Agent 自动追踪每次爬取的漏斗数据（raw → filtered → extracted → qualified），定期复盘历史表现，生成新的关键词优化建议。**用户必须手动确认**后才能将建议的关键词用于下次爬取。

**Keyword 优先级规则：**

```
1. 用户明确指定关键词 → 直接使用，不触发建议
2. 用户无指定，但有已确认的推荐关键词 → 使用已确认的推荐
3. 无用户指定且无已确认推荐 → 使用 seed keywords
4. 用户询问"有什么优化建议"时 → 生成建议，等待确认
```

### 4B.2 Funnel Tracking

每次 `crawl` 或 `crawl_with_keywords` 执行后，自动写入漏斗数据：

```
用户: "用 AI video prompt 跑一轮"
  ↓
爬取: raw_tweets = 300
  ↓
硬过滤: filtered_tweets = 89
  ↓
LLM 提取: extracted_prompts = 23
  ↓
质量评分: qualified_prompts = 8
  ↓
记录 keyword_yields → yield_score = 8/300 = 2.7%
```

### 4B.3 Keyword Suggestion Logic

Agent 定期分析 `keyword_yields`：
- 高 qualified_rate (≥5%) → 扩展词根
- 低 yield_score (<1%) → 标记为低效
- 从未测试过的词根 → 生成变体建议

### 4B.4 Confirmation Workflow

```
Agent: "建议新增：1. Veo 3.1 prompt  2. AI video cinematic shot  3. Google Veo experimental"
用户: "确认第1和第3个"
Agent: "已确认，当前活跃：[seed...] + [已确认推荐...]"
用户: "开始爬取"
Agent: [使用已确认的关键词执行 crawl_with_keywords]
```

### 4B.5 Database Tables

```sql
-- 漏斗记录
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

-- AI 建议的关键词（待确认）
CREATE TABLE IF NOT EXISTS keyword_suggestions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    suggested_keyword TEXT NOT NULL,
    reason          TEXT,
    based_on_keyword TEXT,
    status          TEXT DEFAULT 'pending',
    created_at      TEXT NOT NULL
);

-- 已确认用于爬取的关键词
CREATE TABLE IF NOT EXISTS approved_keywords (
    keyword         TEXT PRIMARY KEY,
    source          TEXT,
    approved_at     TEXT NOT NULL,
    note            TEXT
);
```

### 4B.6 Intent Expansion

| Intent | Description | ReAct Behavior |
|---|---|---|
| `KEYWORD_ANALYSIS` | "分析一下关键词效果" | think → analyze_keyword_yield → final |
| `KEYWORD_SUGGEST` | "有什么优化建议" | think → generate_keyword_suggestions → final |
| `KEYWORD_CONFIRM` | "确认用这几个词" | think → confirm_keywords → final |
| `CRAWL_WITH_KEYWORDS` | 用户指定关键词爬虫 | think → crawl_with_keywords → final |

---

## 5. Agent State Machine (LangGraph)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   START     │────▶│   THINK     │────▶│    PLAN     │
└─────────────┘     │  (意图解析)  │     │  (任务规划)  │
                    └──────┬──────┘     └──────┬──────┘
                           │                   │
                           ▼                   ▼
                    ┌─────────────┐     ┌─────────────┐
                    │   ACT       │◀────│  OBSERVE    │
                    │  (工具调用)  │     │  (结果评估)  │
                    └──────┬──────┘     └──────┬──────┘
                           │                   │
                           └───────────────────┘
                                      │
                          ┌───────────┴───────────┐
                          ▼                       ▼
                    ┌─────────────┐          ┌─────────────┐
                    │   DONE      │          │   MORE      │
                    │  (回复用户) │          │  (继续循环)  │
                    └─────────────┘          └─────────────┘
```

### 5.1 LangGraph Nodes

| Node | LangGraph Role | Description |
|---|---|---|
| `start` | Entry point | 接收用户消息，初始化 state |
| `think_node` | ReAct Think | 解析意图，生成 `thought` |
| `plan_node` | ReAct Plan | 决定下一步工具调用 |
| `act_node` | ReAct Act | 执行工具，更新记忆 |
| `observe_node` | ReAct Observe | 评估结果，决定是否继续 |
| `final_reply_node` | Terminal | 组织最终回复给用户 |
| `error_node` | Error handling | 捕获异常，记录到记忆 |

### 5.2 State Transitions

```
think_node → plan_node → act_node → observe_node
     ↑                                           │
     └─────────── (if more steps needed) ────────┘
                          │
                          ▼ (if done)
                   final_reply_node → END
```

### 5.3 Conditional Routing

```python
graph.add_conditional_edges(
    "observe_node",
    lambda state: "plan_node" if state["need_more_steps"] else "final_reply_node",
    {
        "plan_node": "plan_node",
        "final_reply_node": "final_reply_node",
    }
)
```

---

## 6. Intent Classification

当用户发送消息时，Agent 需要先理解**意图类型**，再决定 ReAct 行为。

### 6.1 Intent Types

| Intent | Description | ReAct Behavior |
|---|---|---|
| `STATUS_QUERY` | "池子状态"、"还有多少" | think → pool_status → final |
| `TASK_EXECUTION` | "生成10张图"、"爬一轮" | think → plan → act(s) → observe → final |
| `SEARCH` | "找和 Veo 3 相关的 Prompt" | think → search_prompts → final |
| `MULTI_STEP` | 复杂任务需要多步 | think → plan → act → observe → act → ... → final |
| `CLARIFICATION` | 意图不明确需要追问 | final (ask user) |
| `CHITCHAT` | 闲聊 | final (direct reply) |

### 6.2 Intent Parser

Intent 由 `think_node` 的 LLM 调用解析，不需要单独的分类器。LLM 在生成 `thought` 时同时判断意图类型，写入 `state.intent_type`。

```python
@dataclass
class AgentState:
    # ... existing fields ...
    
    # Intent classification (set by think_node)
    intent_type: str = "TASK_EXECUTION"  # STATUS_QUERY | TASK_EXECUTION | SEARCH | MULTI_STEP | CLARIFICATION | CHITCHAT
    
    # ReAct fields
    scratchpad: str = ""                # LLM reasoning notes
    current_thought: str = ""           # Current step's thought
    steps: list[dict] = field(default_factory=list)  # [ {"step": 1, "thought": "...", "action": {...}, "observation": "..."} ]
    
    # Loop control
    need_more_steps: bool = False       # Set by observe_node
    max_steps: int = 10                # Prevent infinite loops
    current_step: int = 0
```

---

## 7. Skill System (Extensibility)

### 7.1 Skill 定义

每个 Skill 是一个 Python 类，可注册到 `SkillRegistry`。

```python
@dataclass
class Skill:
    name: str
    description: str
    category: str
    parameters: list[Parameter]
    execute: Callable[[dict], str]
    examples: list[str] = field(default_factory=list)

@dataclass
class Parameter:
    name: str
    type: str               # "string" | "integer" | "boolean" | "array"
    description: str
    required: bool = False
    default: Any = None
```

### 7.2 内置 Skill Categories

| Category | 说明 | 示例 |
|---|---|---|
| `data_collection` | 数据采集 | `crawl`, `extract` |
| `data_processing` | 数据处理 | `score`, `dedup` |
| `ai_generation` | AI 生图 | `generate_images`, `retry_failed` |
| `web_maintenance` | 网站维护 | `publish`, `check_website` |
| `memory` | 记忆系统 | `search_prompts`, `save_preference` |
| `system` | 系统工具 | `show_history`, `pool_status` |
| `keyword_strategy` | 关键词优化 | `analyze_keyword_yield`, `generate_keyword_suggestions`, `confirm_keywords` |

### 7.3 动态 Skill 注册

```python
# 在 src/agent/skills/ 目录下添加新 Skill
src/agent/skills/
├── __init__.py
├── core_tools.py        # 内置 9 个核心工具
├── sparki_seo_blog.py    # (未来) TikTok/IG SEO blog creator
├── tiktok_scroll.py      # (未来) TikTok 爬虫
└── custom_skills.py      # 用户自定义 Skill
```

新 Skill 添加后，自动出现在 Agent 的工具列表中，无需修改 Agent 核心代码。

---

## 8. Success Metrics

| Metric | V2 Baseline | V3 Target |
|---|---|---|
| 多步任务完成率 | N/A（无多步） | > 85% |
| ReAct 循环次数/任务 | N/A | 平均 2-4 步 |
| 用户澄清请求次数 | N/A | < 10%（意图不明的情况） |
| Embedding 搜索准确率 | N/A | > 90% top-k relevance |
| Skill 扩展耗时 | N/A | < 30 分钟/新 Skill |
| 对话历史可追溯性 | 仅当前 session | 跨 Session 可查 |

---

## 9. Out of Scope (V3)

- Web UI（CLI only for V3）
- 多用户并发
- 自动调度（cron）
- 向量数据库（Pinecone 等，SQLite BLOB 足够）
- Real-time streaming

---

## 10. Milestones

| Phase | Deliverable | Files |
|---|---|---|
| **P1** | ReAct Agent 核心：state + nodes + graph | `chat_agent.py`, `graph.py`, `state.py` |
| **P2** | 短期记忆 + ReAct loop（think/plan/act/observe） | `nodes.py` |
| **P3** | 长期记忆：Embedding 搜索 + preference | `memory.py`, `schema.py` |
| **P4** | 9 个 Core Tools 实现 | `tools/core_tools.py` |
| **P5** | Skill Registry + 可扩展性框架 | `skills/registry.py` |
| **P6** | 集成测试 + V2 数据迁移 | `tests/integration/`, `import_v2.py` |