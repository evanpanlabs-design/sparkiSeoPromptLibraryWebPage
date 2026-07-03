# PRD V2: Sparki Chat Agent — Prompt Pool & Conversational Control

> **Version**: 2.0 | **Status**: Draft | **Predecessor**: [01_PRD.md](01_PRD.md) v1.0

---

## 1. Product Evolution

### 1.1 What We Learned from V1

| Observation | V2 Response |
|---|---|
| Image gen 429 rate limiting is permanent (~22% success at concurrency=3) | Decouple image gen into async, rate-limited worker |
| Synchronous pipeline couples fast ops (crawl/extract) to slow ops (image gen) | Split into **collection pipeline** + **image worker** + **chat agent** |
| CLI flags (`--from-cache`, `--phase 2`) require remembering arcane commands | Natural language chat: "从缓存提取，然后生成10张图" |
| No visibility into pool state without SQL queries | Agent tools: `pool_status`, `show_history` |
| Full pipeline run from cold-start takes hours and 80% of API calls are 429 waste | Small batch, steady drip: 5-10 images every 2 hours |

### 1.2 V2 Vision

Sparki evolves from a **batch pipeline** into a **persistent agent with a prompt pool**. You talk to it. It remembers context. It checks the environment. It executes tasks within rate limits. It reports back.

```
User: "池子里还有多少没生成图的？"
Sparki: "134 条 pending，上次 3 小时前跑了 8 张，6 张成功。要不要继续？"

User: "嗯，挑质量分最高的 10 张跑一下"
Sparki: "已提交 10 张到生成队列，预计 30 分钟内完成。完成后要我发布网页吗？"
```

---

## 2. Core Architecture Shift

### V1 (Synchronous Pipeline)
```
Crawl → Extract → Score → Image Gen → Publish
  (all in one blocking LangGraph run)
```

### V2 (Async Pool + Agent)
```
┌─────────────────────┐     ┌──────────────────────┐     ┌──────────────────┐
│  Collection Pipeline │────▶│    Prompt Pool (DB)   │────▶│  Image Worker    │
│  (fast, on-demand)   │     │  pending/generating/  │     │  (slow, steady)  │
│                       │     │  done/failed/published│     │  rate-limited    │
└─────────────────────┘     └──────────────────────┘     └──────────────────┘
                                      │                            │
                                      ▼                            ▼
                              ┌────────────────────────────────────────┐
                              │          Sparki Chat Agent              │
                              │  "池子状态?" / "跑10张" / "发布"          │
                              │  Tools: pool_status, crawl, extract,   │
                              │         score, gen_images, publish     │
                              └────────────────────────────────────────┘
```

---

## 3. Functional Specification

### F1 — Chat Agent (NEW)

The primary user interface. LLM-powered conversational agent with tool access.

| Capability | Description |
|---|---|
| Intent understanding | Parses natural language into tool calls or text replies |
| Multi-turn memory | Remembers conversation context within session + across sessions |
| Environment awareness | Checks pool state before acting: "已经有 50 张 done 了，还要继续吗？" |
| Task orchestration | Chains tools: crawl → extract → score → gen_images, reporting progress |
| Clarification | Asks follow-up questions when intent is ambiguous |

### F2 — Prompt Pool (REFACTORED)

All prompts live in a persistent pool with lifecycle states.

| State | Meaning |
|---|---|
| `pending` | Extracted and scored, waiting for image generation |
| `generating` | Currently being processed by image worker |
| `done` | Image generated successfully, ready to publish |
| `failed` | Image generation failed (rate limit, error), eligible for retry |
| `published` | Included in a published HTML release |

**Pool operations:**
- Insert: crawl + extract + score pipeline adds new prompts
- Query: `pool_status` tool returns counts by state
- Pop: `generate_images` tool pulls top-N pending by quality score
- Retry: `retry_failed` tool re-enqueues failed → pending

### F3 — Collection Pipeline (KEPT, simplified)

Same v1 pipeline but stops at scoring — no image gen inside the pipeline.

```
Query → Crawl → Extract → Score → Insert into Pool (status=pending)
```

Runs on-demand via `crawl` tool or scheduled weekly.

### F4 — Image Worker (NEW)

Independent, rate-limited background process for image generation.

| Property | Value |
|---|---|
| Trigger | Agent tool `generate_images(batch=N)` or cron schedule |
| Concurrency | 1 (serial, 15s inter-request delay to avoid 429) |
| Model | Single model, no fallback (avoids quota waste) |
| Retry | Failed → back to `pending` state in pool |
| Batch size | Configurable, default 8 |

**Design rationale:** Serial execution with long pauses is the only reliable mode under Vertex AI's low RPM quota. 10 images/hour × 24 hours = 240 images/day, which exceeds the weekly 100-image target.

### F5 — Publish (KEPT, simplified)

| Capability | Description |
|---|---|
| Build HTML | Reads all `status=done` prompts from pool, generates `outputs/veo3-prompt-library.html` |
| Push to GitHub Pages | Clones `sparki-ai/veo-prompt-station`, copies HTML + images, commits, pushes |
| Mark published | Updates `status=done` → `status=published` in pool |

### F6 — Memory (ENHANCED)

New tables alongside existing schema:

| Table | Purpose |
|---|---|
| `conversation_history` | Stores all chat turns (user, agent, tool call, tool result) |
| `user_preferences` | Key-value store for learned preferences |
| `prompts` (modified) | + `image_status TEXT DEFAULT 'pending'` column |

---

## 4. Tool Manifest

| Tool | Trigger Phrases | Side Effects |
|---|---|---|
| `pool_status` | "池子状态", "进度", "还有多少" | Read-only DB query |
| `crawl` | "爬一轮", "更新数据" | Apify crawl → extract → score → insert to pool |
| `generate_images` | "生成图", "跑图", "出图" | Pop N pending → serial gen → update status |
| `retry_failed` | "重试失败的", "失败的再跑" | Reset failed→pending, then generate_images |
| `publish` | "发布", "更新网页" | Build HTML → git push → mark published |
| `show_history` | "之前做了什么", "历史" | Query scrape_runs + conversation_history |

---

## 5. Success Metrics (V2)

| Metric | V1 Baseline | V2 Target |
|---|---|---|
| Image gen success rate | 22.5% | > 90% (serial with delays) |
| User actions to publish | 4 CLI commands | 1 chat message: "发布" |
| Time from crawl to publish | 1 day (manual intervention) | 1 hour (chat-driven) |
| Pool freshness | N/A | New prompts added weekly |
| Published images/week | 0 (broken pipeline) | 50-100 |

---

## 6. Out of Scope (V2)

- Web UI for chat (CLI REPL only for V2)
- Multi-user support
- Automatic weekly scheduling (manual trigger + optional cron)
- Vector-based semantic dedup
- TikTok / Instagram expansion

---

## 7. Milestones

| Phase | Deliverable | Files |
|---|---|---|
| **P1** | DB migration: `image_status` column + import existing data | `schema.py`, migration script |
| **P2** | 7 Tool functions implemented and testable | `src/agent/tools.py` |
| **P3** | Agent core loop + memory + system prompt | `src/agent/chat_agent.py` |
| **P4** | CLI chat entry point | `src/agent/chat.py` |
| **P5** | Integration test: full chat-driven workflow | manual testing + demo |
