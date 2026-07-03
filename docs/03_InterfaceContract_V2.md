# Sparki V2 Interface Contract

> **Version**: 2.0 | **Purpose**: Data & tool contracts for the Chat Agent + Prompt Pool architecture

---

## 1. Design Principles (V2 Additions)

1. **Tools are pure functions** — same input always produces same output (DB state aside)
2. **All tool results are strings** — human-readable, feed directly into LLM context
3. **Agent state is conversation-scoped** — not pipeline-scoped; LangGraph state is independent
4. **Pool is the source of truth** — prompts table IS the state machine
5. **V1 contracts preserved** — `AgentState` and pipeline types unchanged; new types are additive

---

## 2. Tool Function Contracts

### 2.1 Tool Signature Standard

```python
def tool_<name>(args: dict) -> str:
    """
    CONTRACT:
      INPUT:  args dict with documented keys
      OUTPUT: Human-readable result string (Chinese or English)
      ERRORS: Never raises — returns error string on failure
    """
```

### 2.2 `tool_pool_status`

```python
def tool_pool_status(args: dict) -> str:
    """
    INPUT:  {} (empty dict, no arguments)
    OUTPUT: String like:
            "Prompt Pool 状态:
             pending:    134 条 (等待生成封面图)
             generating:   3 条 (正在生成中)
             done:        39 条 (已生成，可发布)
             failed:     130 条 (生成失败，可重试)
             published:    0 条 (已发布)
             总计:       306 条"
    """
```

### 2.3 `tool_crawl`

```python
def tool_crawl(args: dict) -> str:
    """
    INPUT:  {
        "queries": ["veo prompt", ...] | None,  # override default queries
        "from_cache": bool,                       # default True, use last crawl cache
    }
    OUTPUT: String like:
            "爬取完成: 6 个搜索词, 1422 条推文
             提取 Prompt: 203 条
             已入池 (pending): 187 条 (16 条为重复跳过)
             发现新类别建议: 10 条 (需要审核)"
    SIDE EFFECTS:
        - Inserts/updates rows in prompts table
        - Writes to scrape_runs, queries, authors tables
        - Writes crawl cache to outputs/last_crawl.json
    """
```

### 2.4 `tool_generate_images`

```python
def tool_generate_images(args: dict) -> str:
    """
    INPUT:  {
        "batch": int,          # default 8, how many images to generate
        "sort_by": str,        # default "score", also accepts "newest"
        "model": str | None,   # default "gemini-2.5-flash-image"
    }
    OUTPUT: String like:
            "图片生成完成: 8/10 成功, 2/10 失败 (已回池)
             模型: gemini-2.5-flash-image
             耗时: 4 分 32 秒
             当前池状态: 126 pending, 47 done, 132 failed"
    SIDE EFFECTS:
        - Updates prompts.image_status: pending→done or pending→failed
        - Updates prompts.image_gcs_url on success
        - Uploads to GCS: gs://sparki-op-test/prompts/{cat}/{yyyy-mm}/{tweet_id}.png
    """
```

### 2.5 `tool_retry_failed`

```python
def tool_retry_failed(args: dict) -> str:
    """
    INPUT:  {
        "batch": int,          # default 8, max images to retry
    }
    OUTPUT: String like:
            "已重置 130 条 failed → pending
             开始生成 8 张...
             图片生成完成: 6/8 成功, 2/8 失败
             当前池状态: 124 pending, 53 done, 2 failed"
    SIDE EFFECTS:
        - UPDATE prompts SET image_status='pending' WHERE image_status='failed'
        - Then calls tool_generate_images internally
    """
```

### 2.6 `tool_publish`

```python
def tool_publish(args: dict) -> str:
    """
    INPUT:  {} (empty dict, no arguments)
    OUTPUT: String like:
            "发布完成!
             已发布 49 条 Prompt
             HTML: outputs/veo3-prompt-library.html
             在线: https://sparki-ai.github.io/veo-prompt-station
             49 条已标记为 published"
    SIDE EFFECTS:
        - Builds HTML from all prompts WHERE image_status='done'
        - Clones/pulls sparki-ai/veo-prompt-station (gh-pages branch)
        - Copies index.html + generated_images/ to repo
        - Git commit + push
        - UPDATE prompts SET image_status='published' WHERE image_status='done'
    """
```

### 2.7 `tool_show_history`

```python
def tool_show_history(args: dict) -> str:
    """
    INPUT:  {
        "limit": int,          # default 5, number of recent runs to show
    }
    OUTPUT: String like:
            "最近 5 次运行:
              #6 | 2026-05-20 17:30 | 6 queries | 203 prompts | 39 images | DONE
              #5 | 2026-05-20 14:00 | 6 queries | 198 prompts | 0 images  | DONE
              ...

             最近对话:
              17:30 - 用户: 池子状态
              17:31 - 助手: 当前 134 pending, 39 done...
              17:32 - 用户: 生成 10 张
              17:37 - 助手: 10/10 成功..."
    SIDE EFFECTS: None (read-only)
    """
```

---

## 3. New Database Schema Contracts

### 3.1 `prompts.image_status` — State Machine

```
       ┌──────────┐
       │ pending  │  ← prompt enters pool after extraction+scoring
       └────┬─────┘
            │ generate_images()
            ▼
       ┌──────────┐
       │generating│  ← transient state during generation
       └────┬─────┘
            │
       ┌────┴────┐
       ▼         ▼
   ┌──────┐  ┌──────┐
   │ done │  │failed│
   └──┬───┘  └──┬───┘
      │         │ retry_failed()
      │         └──► pending (reset)
      │ publish()
      ▼
   ┌───────────┐
   │ published │
   └───────────┘
```

**Valid transitions:**
| From | To | Trigger |
|---|---|---|
| `pending` | `generating` | `generate_images` or `retry_failed` (internal) |
| `generating` | `done` | Image gen success |
| `generating` | `failed` | Image gen failure (429, model error, GCS error) |
| `failed` | `pending` | `retry_failed` |
| `done` | `published` | `publish` |

**Invalid transitions (must be rejected):**
- `published` → anything (immutable)
- `done` → `failed` (once done, always done)
- `pending` → `published` (must pass through generating→done)

### 3.2 `conversation_history` Table

```sql
CREATE TABLE IF NOT EXISTS conversation_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    role        TEXT NOT NULL CHECK (role IN ('user', 'agent', 'tool')),
    content     TEXT NOT NULL,
    tool_name   TEXT,                -- only for role='tool'
    tool_args   TEXT,                -- JSON, only for role='tool'
    created_at  TEXT NOT NULL        -- ISO8601 UTC
);
```

**Contract:**
- `role='user'`: content = raw user message
- `role='agent'`: content = final text response to user (not intermediate tool calls)
- `role='tool'`: content = tool result string, tool_name = function name, tool_args = JSON args

### 3.3 `user_preferences` Table

```sql
CREATE TABLE IF NOT EXISTS user_preferences (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
```

**Known keys:**
| Key | Value Example | Set By |
|---|---|---|
| `default_batch_size` | `"10"` | Agent after user confirmation |
| `preferred_model` | `"gemini-2.5-flash-image"` | Agent |
| `auto_publish_after_gen` | `"false"` | Agent |
| `last_crawl_queries` | `["veo prompt", ...]` | tool_crawl |

---

## 4. Agent LLM Protocol

### 4.1 System Prompt Contract

The system prompt is stored in `src/agent/chat_agent.py` as `SYSTEM_PROMPT`. It defines:
1. Agent identity and role
2. Available tools with descriptions
3. Tool calling format
4. Behavioral rules

**Tool calling format (injected into system prompt):**
```
当你需要执行操作时，用以下 JSON 格式回复（放在单独一行）：
{"tool": "tool_name", "args": {"arg1": "value1"}}

可用工具：
- pool_status: 查看 Prompt 池状态。参数: {}
- generate_images: 生成封面图。参数: {"batch": int, "sort_by": "score"|"newest"}
- crawl: 爬取新 Prompt。参数: {"queries": ["..."] | null, "from_cache": bool}
- retry_failed: 重试失败图片。参数: {"batch": int}
- publish: 发布网页。参数: {}
- show_history: 查看历史。参数: {"limit": int}
```

### 4.2 Context Injection Format

Before each LLM call, the agent injects a context block:

```
[系统上下文]
当前时间: 2026-05-20 18:30:00 UTC

Prompt Pool 状态:
  pending: 134 | generating: 0 | done: 39 | failed: 130 | published: 0

最近对话:
  用户: 池子状态?
  助手: 当前 134 条 pending, 39 条 done...
```

### 4.3 Tool Result Format

Tool results are formatted as:
```
[工具执行结果: {tool_name}]
{result_string}

请用自然语言向用户报告这个结果。如果需要更多操作，请说明。
```

---

## 5. V1 Compatibility

### 5.1 Preserved Types

All V1 types in `src/types/` remain unchanged:
- `Tweet`, `AuthorRef`
- `ExtractedPrompt`, `ScoredPrompt`, `QualityScores`
- `ImageResult`, `ImageGenStatus`
- `QueryCandidate`, `QueryMetrics`
- `AuthorMetrics`, `CategorySuggestion`
- `PipelineStats`, `PipelineError`
- `PipelinePhase`, `RouterDecision`, `NodeStatus`

### 5.2 V1 Pipeline Preservation

The V1 pipeline (`src/main.py run --from-cache`) still works. The only change:
- `image_gen_node` is bypassed (phase IMAGING removed from graph)
- Prompts are inserted with `image_status='pending'` instead of generating immediately

### 5.3 New Types (Additive)

```python
# src/types/chat.py (NEW)
from dataclasses import dataclass
from enum import Enum

class ToolName(Enum):
    POOL_STATUS     = "pool_status"
    CRAWL           = "crawl"
    GENERATE_IMAGES = "generate_images"
    RETRY_FAILED    = "retry_failed"
    PUBLISH         = "publish"
    SHOW_HISTORY    = "show_history"

@dataclass
class ToolCall:
    tool: str           # ToolName value
    args: dict          # Tool-specific arguments

@dataclass
class ConversationTurn:
    role: str           # 'user' | 'agent' | 'tool'
    content: str
    tool_name: str | None = None
    tool_args: str | None = None   # JSON string
    created_at: str = ""

@dataclass
class PoolSummary:
    pending: int = 0
    generating: int = 0
    done: int = 0
    failed: int = 0
    published: int = 0

    def total(self) -> int:
        return self.pending + self.generating + self.done + self.failed + self.published
```

---

## 6. File Locations (V2)

```
src/
├── agent/
│   ├── state.py          # AgentState (V1, unchanged)
│   ├── nodes.py          # Pipeline nodes (V1, IMAGING removed)
│   ├── graph.py          # Pipeline graph (V1, IMAGING removed)
│   ├── config.py         # Node config (unchanged)
│   ├── chat.py           # NEW: CLI chat entry point
│   ├── chat_agent.py     # NEW: SparkiAgent class
│   ├── tools.py          # NEW: All tool implementations
│   └── memory.py         # NEW: Conversation history CRUD
│
├── types/
│   ├── ...               # V1 types (unchanged)
│   └── chat.py           # NEW: ToolName, ToolCall, ConversationTurn, PoolSummary
│
├── memory/
│   └── schema.py         # MODIFIED: +conversation_history, +user_preferences,
│                          #   +image_status migration
│
├── image_gen/
│   └── client.py         # MODIFIED: RateLimitSafeGenerator added
│
└── main.py               # MODIFIED: IMAGING phase removed from graph
```

---

## 7. Strict Rules

1. **Tools never modify AgentState** — they operate on DB directly, return strings
2. **Agent never calls tools in parallel** — serial execution only (tool → result → LLM → next tool)
3. **All tool args have defaults** — LLM can omit optional args, tools handle missing keys
4. **Tool results are idempotent from user's view** — same request produces same visible outcome
5. **Pool queries are read-committed** — no stale reads within a single tool call
6. **Conversation history is append-only** — never update or delete past turns
