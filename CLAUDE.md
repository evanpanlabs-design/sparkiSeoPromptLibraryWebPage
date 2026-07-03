# Sparki-Veo-Station — Project Source of Truth

> Sparki is an AI video generation + mixing Agent using Veo as the base model.
> Sparki-Veo-Station is Sparki's **content operations tool** — crawls Veo prompts from X.com, extracts them, generates cover images, and publishes them as Sparki's SEO landing page (`veo3-prompt-library` on GitHub Pages).

**Sparki-Veo-Station** has evolved through three major versions. The documents below are the **absolute source of truth** for each version:

| Current Version | Documents |
|---|---|
| **V1.0** (Pipeline MVP) | `docs/01_PRD.md`, `docs/02_DevGuide.md`, `docs/03_InterfaceContract.md` |
| **V2.0** (Async Pool) | `docs/01_PRD_V2.md`, `docs/02_DevGuide_V2.md`, `docs/03_InterfaceContract_V2.md` |
| **V3.2** (ReAct Agent + Two-Mode) | `docs/01_PRD_V3.md`, `docs/02_DevGuide_V3.md`, `docs/03_InterfaceContract_V3.md`, `docs/04_ParallelDevCommands_V3.md`, `docs/10_ProjectOverview.md`, `docs/11_ToolInterface.md` |

> **Active Development**: V3.2 — Two-Mode ReAct Agent (Agent mode + Pipeline mode). Phase skills fully decoupled. V1 pipeline preserved for data collection. V2 is superseded.

---

## V3.2 Architecture: Two-Mode ReAct Agent

V3.2 is a **conversational ReAct Agent** with two operating modes powered by LangGraph:

```
User ──▶ think_node (intent classification)
              │
              ├─ STATUS_QUERY / SEARCH / TASK_EXECUTION / CHITCHAT
              │      └── Agent 模式: single or multi-step, LLM picks tools freely
              │
              └─ MULTI_STEP + pipeline trigger
                     └── Pipeline 模式: auto-chains all phase skills

Pipeline chain:
  crawl_tweets → extract_prompts → score_prompts → generate_images → sync_images → build_html → publish
```

**Pipeline Trigger Keywords** (in `_keyword_intent()`): "全程" / "完整流程" / "一键" / "跑一遍" / "更新全部" / "全流程"

**Phase Skills** (V3.2, fully decoupled from V1 main.py): `crawl_tweets`, `extract_prompts`, `score_prompts`, `generate_images`, `sync_images`, `build_html`, `publish` + 6 utility skills = **12 core skills total**

**V1 main.py**: Deprecated for phase runs. Only `init-db` and `status` commands remain functional.

---

## Code Structure (V3)

```
src/
├── agent/                    # V3 ReAct Agent
│   ├── state.py              # AgentState dataclass (V3)
│   ├── graph.py              # build_react_graph() — LangGraph StateGraph
│   ├── chat.py               # CLI entry point
│   ├── chat_agent.py         # SparkiReActAgent high-level class
│   ├── nodes/                # LangGraph node implementations
│   │   ├── start_node.py     # Entry point, state init
│   │   ├── think_node.py     # Intent parsing + thought generation
│   │   ├── plan_node.py      # Task planning + action selection
│   │   ├── act_node.py       # Tool execution
│   │   ├── observe_node.py   # Result evaluation + loop control
│   │   ├── final_reply_node.py
│   │   └── error_node.py
│   ├── skills/               # Skill Registry (extensible tool system)
│   │   ├── registry.py       # SkillRegistry class
│   │   ├── base.py           # Skill, Parameter dataclasses
│   │   └── core_tools.py     # 12 core tool implementations (V3.2: phase skills decoupled)
│   ├── memory/               # Memory system
│   │   ├── short_term.py     # Session message helpers
│   │   ├── long_term.py      # SQLite CRUD
│   │   └── embedding.py      # Gemini embedding + cosine similarity
│   └── react/                # ReAct utilities
│       ├── parser.py         # Parse LLM output → structured
│       ├── prompt.py         # System prompts for each node
│       └── formatter.py       # ReAct format helpers
│
├── main.py                   # DEPRECATED: phase runs removed in V3.2 (init-db/status only)
├── crawler/                  # V1 (preserved)
├── worker/                  # V1 (preserved)
├── llm/                      # V1 (preserved)
├── image_gen/               # V1 + RateLimitSafeGenerator
├── memory/                   # V3 enhanced schema
│   └── schema.py             # DB migrations, V3 tables
├── api/                      # (future web UI)
└── types/
    ├── __init__.py
    ├── chat.py              # ToolName, PoolSummary (V2)
    └── react.py             # IntentType, ReActStep (V3)
```

---

## V3 Development Workflow

**Parallel development (up to 5 instances simultaneously):**

1. Read `docs/04_ParallelDevCommands_V3.md` for your assigned Code instance
2. Implement independently using `docs/03_InterfaceContract_V3.md` as contract reference
3. Run verification commands per Code instance
4. After all instances complete → Code-6 (integration) → Code-7 (tests)

**Key principles:**
- ReAct nodes communicate **only** through `AgentState` fields
- All tools are `Skill` objects registered in `SkillRegistry` — no hardcoded tool names
- LLM calls are isolated to `think_node`, `plan_node`, `observe_node`
- Memory is explicit: short-term = `state.messages`, long-term = SQLite

---

## Configuration (V3)

| File | Purpose |
|---|---|
| `configs/queries.yaml` | Search queries + negative keywords |
| `configs/engagement.yaml` | min_likes, min_followers, min_views |
| `configs/crawler.yaml` | Scroll limits, timeouts, proxy |
| `configs/llm.yaml` | LLM API, model, concurrency, `gemini.default_model` |
| `configs/gemini.yaml` | GCS bucket, image models, `image_worker` settings |
| `configs/quality.yaml` | Scoring weights and thresholds |
| `configs/agent.yaml` | **NEW** V3 Agent config: model, max_steps, embedding model |

---

## Node Function Convention

All LangGraph node functions:
```python
def node_name(state: AgentState) -> AgentState:
    """Reads documented fields, writes documented fields, returns state."""
```

**No exceptions propagate** — errors are caught at graph boundary, routed to `error_node`.

---

## V1 Pipeline (Deprecated)

V1 `main.py` is deprecated for phase runs. Phase execution now happens via V3 Agent's phase skills (`crawl_tweets`, `extract_prompts`, `score_prompts`).

Only these commands remain functional:
- `python -m src.main init-db` — initialize database
- `python -m src.main status` — show scrape run status

```
V3.2 Agent mode:    user → pool_status / search / generate / publish (individual tools)
V3.2 Pipeline mode:  user → crawl_tweets → extract_prompts → score_prompts → generate_images → sync_images → build_html → publish (auto-chain)
```

---

## Output & Publish

| Component | Location |
|---|---|
| HTML template | `outputs/templates/veo3-prompt-library.html` |
| Built HTML | `outputs/index.html` |
| Cover images | GCS: `gs://sparki-op-test/prompts/{cat}/{yyyy-mm}/{tweet_id}.png` |
| GitHub Pages | `https://github.com/sparki-ai/veo-prompt-station` (branch: `gh-pages`) |

---

## Key Conventions

- **ReAct format**: `thought` → `action` → `observation` per step (explicit, not implicit)
- **Tool calling**: LLM outputs `{"tool": "...", "args": {...}}` JSON (Anthropic function calling style, not ReAct)
- **Skill Registry**: All tools registered at startup, dynamically available to LLM via `get_tool_schemas()`
- **Embedding search**: Gemini `gemini-embedding-exp-03-07`, stored as JSON BLOB in SQLite
- **Rate-limit-safe image gen**: Serial mode, 2s interval, `gemini-2.5-flash-image` only

---

## Incremental Processing

**ReAct Agent**: Stateless per conversation — each `run()` call is a fresh ReAct loop. Session history via LangGraph `MemorySaver` checkpointer.

**V1 Pipeline**: Restart-safe with `--phase N --scrape-id X`

**Prompt Pool**: `INSERT OR IGNORE` for duplicates, state machine transitions enforced in DB.