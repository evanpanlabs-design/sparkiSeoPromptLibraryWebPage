# Sparki V2 Developer Guide

> **Version**: 2.0 | **Audience**: Engineers building the Chat Agent + Prompt Pool architecture

---

## 1. Architecture Overview

### 1.1 System Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Sparki Chat Agent (REPL)                       │
│                                                                       │
│  python -m src.agent.chat                                              │
│       │                                                                │
│       ▼                                                                │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                    SparkiAgent (chat_agent.py)                    │ │
│  │                                                                   │ │
│  │  System Prompt ──▶ Gemini LLM ──▶ Response Parser                 │ │
│  │       │                │                │                         │ │
│  │       ▼                ▼                ▼                         │ │
│  │  Context Builder   Tool Schema      ┌──────────┐                  │ │
│  │  (history+pool)    (JSON format)    │ text?    │──▶ "池子里134条"  │ │
│  │                                     │ tool?    │                  │ │
│  │                                     └────┬─────┘                  │ │
│  │                                          │                         │ │
│  │                                          ▼                         │ │
│  │                               ┌──────────────────┐                │ │
│  │                               │   Tool Executor   │                │ │
│  │                               │   (tools.py)      │                │ │
│  │                               │                   │                │ │
│  │                               │ pool_status       │                │ │
│  │                               │ crawl             │                │ │
│  │                               │ extract           │                │ │
│  │                               │ score             │                │ │
│  │                               │ generate_images   │                │ │
│  │                               │ retry_failed      │                │ │
│  │                               │ publish           │                │ │
│  │                               │ show_history      │                │ │
│  │                               └───────┬──────────┘                │ │
│  └───────────────────────────────────────┼───────────────────────────┘ │
│                                          │                             │
└──────────────────────────────────────────┼─────────────────────────────┘
                                           │
                    ┌──────────────────────┼──────────────────────┐
                    ▼                      ▼                      ▼
            ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
            │   SQLite DB  │     │  Apify/      │     │  Vertex AI   │
            │  (Prompt     │     │  Crawler     │     │  Gemini      │
            │   Pool)      │     │              │     │  (Image Gen) │
            └──────────────┘     └──────────────┘     └──────────────┘
```

### 1.2 Two-Loop Architecture

**Loop 1 — Collection (fast, on-demand):**
```
Crawl → Extract → Score → Insert to Pool (status=pending)
```
Runs when user says "爬一轮" or "更新数据". Typically 5-10 minutes.

**Loop 2 — Image Generation (slow, steady):**
```
Pop N pending → Serial gen (15s interval) → Update status (done/failed)
```
Runs when user says "生成10张" or on cron schedule. ~2 min/batch of 8.

**Loop 3 — Agent Chat (always on):**
```
User message → Context build → LLM → Tool exec → Response
```

---

## 2. Project Structure (V2)

```
16_NewCrawler/
├── configs/                        # Unchanged from V1
│
├── src/
│   ├── main.py                     # V1 CLI (kept for collection pipeline)
│   │
│   ├── agent/                      # Agent core (NEW + MODIFIED)
│   │   ├── state.py                # AgentState + PoolState dataclasses
│   │   ├── nodes.py                # V1 pipeline nodes (kept, image gen removed)
│   │   ├── graph.py                # V1 graph (kept, IMAGING phase removed)
│   │   ├── config.py               # Node config (unchanged)
│   │   ├── chat.py                 # NEW: CLI chat entry point (REPL loop)
│   │   ├── chat_agent.py           # NEW: SparkiAgent class (LLM + tool loop)
│   │   ├── tools.py                # NEW: All tool function implementations
│   │   └── memory.py               # NEW: Conversation history CRUD
│   │
│   ├── crawler/                    # Unchanged from V1
│   ├── worker/                     # Unchanged from V1
│   ├── llm/                        # Unchanged from V1
│   ├── image_gen/                  # MODIFIED: rate-limit-safe serial mode
│   ├── memory/                     # MODIFIED: schema migration + pool queries
│   ├── api/                        # Kept for future web UI
│   └── types/                      # MODIFIED: new types for V2
│
├── docs/                           # V2 docs added
│   ├── 01_PRD_V2.md
│   ├── 02_DevGuide_V2.md           # This file
│   ├── 03_InterfaceContract_V2.md
│   └── 04_ParallelDevCommands_V2.md
│
└── outputs/                        # Unchanged
```

---

## 3. Module Specifications (NEW)

### 3.1 Chat Agent (`src/agent/chat_agent.py`)

```python
class SparkiAgent:
    """Conversational agent with tool access and memory."""

    def __init__(
        self,
        llm_client: GeminiClient,
        db_conn: sqlite3.Connection,
        tools: dict[str, Callable],
        system_prompt: str,
    ):
        """Initialize agent with LLM, DB connection, tool registry."""

    def chat(self, user_message: str) -> str:
        """
        Main entry point for one conversation turn.
        1. Load conversation history from DB
        2. Build context (history + pool summary)
        3. Call LLM with system prompt + context + tools schema + user msg
        4. Parse response: text reply or tool_call JSON
        5. If tool_call: execute, save result to history, feed back to LLM
        6. Return final text response
        7. Save turn to conversation_history table
        """

    def _build_context(self) -> str:
        """Build context block: recent history + current pool state summary."""

    def _parse_response(self, text: str) -> dict | str:
        """
        Parse LLM response.
        Returns dict if tool_call (with "tool" and "args" keys),
        returns str if plain text reply.
        """

    def _execute_tool(self, tool_call: dict) -> str:
        """Look up tool by name, execute with args, return result as text."""

    def _summarize_pool(self) -> str:
        """Return a one-line pool summary for context injection."""
```

### 3.2 Tools (`src/agent/tools.py`)

Each tool is a standalone function with signature `def tool_name(args: dict) -> str`.

```python
# All tools return a human-readable result string.

def tool_pool_status(args: dict) -> str:
    """Query prompts table, group by image_status, return counts."""

def tool_crawl(args: dict) -> str:
    """Trigger collection pipeline: crawl → extract → score → insert to pool.
    Args: queries (optional list), from_cache (bool, default True)
    """

def tool_generate_images(args: dict) -> str:
    """Generate cover images for top-N pending prompts.
    Args: batch (int, default 8), sort_by (str, default 'score')
    Uses serial execution with 15s interval to avoid 429.
    """

def tool_retry_failed(args: dict) -> str:
    """Reset failed prompts back to pending, then generate_images."""

def tool_publish(args: dict) -> str:
    """Build HTML from all done prompts, push to GitHub Pages."""

def tool_show_history(args: dict) -> str:
    """Show recent scrape runs and conversation summary."""
```

### 3.3 Memory (`src/agent/memory.py`)

```python
def init_conversation_tables(conn: sqlite3.Connection) -> None:
    """Create conversation_history and user_preferences tables."""

def save_conversation_turn(
    conn: sqlite3.Connection,
    role: str,       # 'user' | 'agent' | 'tool'
    content: str,
    tool_name: str | None = None,
    tool_args: str | None = None,
) -> None: ...

def load_recent_history(
    conn: sqlite3.Connection,
    limit: int = 20,
) -> list[dict]: ...

def get_preference(conn: sqlite3.Connection, key: str) -> str | None: ...

def set_preference(conn: sqlite3.Connection, key: str, value: str) -> None: ...
```

---

## 4. Database Changes (V2)

### 4.1 Migration: `prompts.image_status`

```sql
-- Add image_status column to prompts table
ALTER TABLE prompts ADD COLUMN image_status TEXT DEFAULT 'pending';

-- States: pending, generating, done, failed, published
```

### 4.2 New Table: `conversation_history`

```sql
CREATE TABLE IF NOT EXISTS conversation_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    role        TEXT NOT NULL,       -- 'user' | 'agent' | 'tool'
    content     TEXT NOT NULL,
    tool_name   TEXT,                 -- NULL for non-tool turns
    tool_args   TEXT,                 -- JSON string
    created_at  TEXT NOT NULL         -- ISO8601
);
```

### 4.3 New Table: `user_preferences`

```sql
CREATE TABLE IF NOT EXISTS user_preferences (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
```

### 4.4 Pool Queries

```sql
-- Pool status (counts by image_status)
SELECT image_status, COUNT(*) as cnt
FROM prompts
GROUP BY image_status;

-- Pop top-N pending prompts by quality score
SELECT p.*, CAST(p.quality_scores AS JSON) as scores
FROM prompts p
WHERE p.image_status = 'pending'
ORDER BY json_extract(p.quality_scores, '$.overall') DESC
LIMIT ?;

-- Retry failed → pending
UPDATE prompts
SET image_status = 'pending'
WHERE image_status = 'failed';

-- Mark done → published
UPDATE prompts
SET image_status = 'published'
WHERE image_status = 'done';
```

---

## 5. Agent System Prompt (Design)

The system prompt defines the agent's personality, capabilities, and tool-calling protocol.

```
你是 Sparki，一个管理 AI 视频/图像生成 Prompt 池的智能助手。

## 你的能力
你可以通过工具调用来执行以下操作：
- pool_status: 查看 Prompt 池的状态（各状态数量）
- crawl: 从 X.com 爬取新的 Prompt
- generate_images: 为池中的 Prompt 生成封面图
- retry_failed: 重试之前失败的图片生成
- publish: 发布网页到 GitHub Pages
- show_history: 查看历史运行记录

## 工具调用格式
当你需要执行操作时，用以下 JSON 格式回复：
{"tool": "tool_name", "args": {"arg1": "value1"}}

如果只是聊天或回答问题，直接回复文字即可。

## 规则
1. 执行操作前先检查池子状态（避免重复工作）
2. 生成图片前告知用户当前 pending 数量
3. 遇到错误时清楚说明原因和建议的下一步
4. 用简洁的中文回复，不要废话
5. 记住用户偏好（如偏好的生成数量、风格）
```

---

## 6. Agent Loop (Pseudocode)

```python
class SparkiAgent:
    def chat(self, user_message: str) -> str:
        # 1. Save user message to history
        save_turn(conn, role="user", content=user_message)

        # 2. Agent loop (may have tool call + follow-up)
        current_message = user_message
        max_iterations = 5  # prevent infinite loops

        for _ in range(max_iterations):
            # Build context
            context = self._build_context()

            # LLM call
            response = self.llm.complete(
                system=SYSTEM_PROMPT,
                prompt=f"{context}\n\n用户: {current_message}\n助手:",
            )

            # Parse
            parsed = self._parse_response(response)

            if isinstance(parsed, str):
                # Plain text reply — done
                save_turn(conn, role="agent", content=parsed)
                return parsed

            # Tool call
            tool_result = self._execute_tool(parsed)
            save_turn(conn, role="tool", content=tool_result,
                      tool_name=parsed["tool"], tool_args=json.dumps(parsed["args"]))

            # Feed result back to LLM for follow-up response
            current_message = f"[工具 {parsed['tool']} 执行结果]\n{tool_result}\n\n请用自然语言向用户报告结果。"

        return "操作步骤过多，请简化你的请求。"
```

---

## 7. Chat CLI Entry Point

```bash
# Interactive REPL
python -m src.agent.chat

# Single command
python -m src.agent.chat --msg "池子状态"
python -m src.agent.chat --msg "生成10张高分图"

# With specific model
python -m src.agent.chat --model gemini-3.5-flash
```

```python
# src/agent/chat.py
def main():
    agent = SparkiAgent(...)

    if args.msg:
        # Single-shot mode
        print(agent.chat(args.msg))
    else:
        # Interactive REPL
        print("Sparki Chat Agent v2.0")
        print("输入 /help 查看命令, /quit 退出")
        while True:
            user_input = input("\n你: ")
            if user_input == "/quit":
                break
            if user_input == "/help":
                print("可用命令: pool_status, crawl, generate_images, ...")
                continue
            response = agent.chat(user_input)
            print(f"\nSparki: {response}")
```

---

## 8. Image Worker — Rate-Limit-Safe Mode

The critical change from V1: **single-model, serial execution with mandatory delay**.

```python
class RateLimitSafeGenerator:
    """Generates images one at a time with enforced inter-request delay."""

    def __init__(self, model: str = "gemini-2.5-flash-image", min_interval_s: float = 15.0):
        self.model = model
        self.min_interval = min_interval_s
        self._last_request_time = 0.0

    def generate_batch(self, items: list[dict]) -> list[dict]:
        results = []
        for i, item in enumerate(items):
            # Enforce minimum interval
            elapsed = time.time() - self._last_request_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)

            result = self._generate_one(item)
            results.append(result)
            self._last_request_time = time.time()

            print(f"  [{i+1}/{len(items)}] {'OK' if not result['error'] else 'FAIL'}  {item['tweet_id']}")

        return results
```

Configuration in `configs/gemini.yaml`:
```yaml
gemini:
  image_worker:
    model: "gemini-2.5-flash-image"   # single model, no fallback
    min_interval_s: 15                 # minimum seconds between requests
    default_batch_size: 8
```

---

## 9. Operational Runbook (V2)

### 9.1 Starting the Chat Agent

```bash
# Interactive mode
python -m src.agent.chat

# Quick status check
python -m src.agent.chat --msg "池子状态"
```

### 9.2 Typical Workflow

```
你: 更新一下Prompt，然后看看有多少新的
Sparki: [crawl, extract, score] 新增 23 条到池子，当前 157 pending, 39 done

你: 挑 10 条最高分的生成图
Sparki: [generate_images batch=10] 10/10 成功，当前 49 done

你: 发布吧
Sparki: [publish] 已发布 49 条到 https://sparki-ai.github.io/veo-prompt-station
```

### 9.3 Checking Progress

```bash
# Via chat
python -m src.agent.chat --msg "最近做了什么"

# Via DB
python -c "
from src.memory.schema import _conn
conn = _conn()
rows = conn.execute(\"SELECT image_status, COUNT(*) FROM prompts GROUP BY image_status\").fetchall()
for r in rows: print(f'{r[0]}: {r[1]}')
"
```

### 9.4 Database Migration

```bash
# Run once to migrate V1 DB to V2 schema
python -m src.memory.schema  # init_db() auto-runs _migrate_prompts_image_status()
```

---

## 10. Key Design Decisions

| Decision | Rationale |
|---|---|
| Serial image gen, not concurrent | Vertex AI quota is ~5 RPM; serial with 15s delay = 4 RPM, safe margin |
| Single model for image gen | Multi-model fallback wastes quota on 429s across 3 models simultaneously |
| Tools return strings, not objects | Simpler LLM integration; string results feed back into conversation naturally |
| SQLite for conversation history | Same DB, no new infrastructure, sufficient for single-user agent |
| No LangChain/LangGraph in agent loop | The agent is a simple while loop; LangGraph adds complexity without benefit here |
| V1 pipeline kept as-is | Collection pipeline (crawl→extract→score) still works; just IMAGING phase is removed |
