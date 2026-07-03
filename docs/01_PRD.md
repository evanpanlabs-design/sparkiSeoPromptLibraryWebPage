# PRD: Sparki — Autonomous Prompt Crawling & Analysis Agent

> **Version**: 1.0 | **Target**: Video Generation Prompt Discovery System

---

## 1. Product Overview

### 1.1 Vision

Sparki is an autonomous agent that continuously discovers, extracts, and curates high-quality AI video/image generation prompts from X.com (Twitter). It mimics a skilled human researcher: formulating search strategies, filtering noise, extracting actionable prompts, scoring quality, generating cover imagery, and — critically — learning from each iteration to improve future searches. The system runs as a self-optimizing loop powered by LangGraph.

### 1.2 Product Type

**Autonomous Multi-Agent System** (LangGraph-powered, event-driven pipeline)

### 1.3 Core Value Proposition

| Stakeholder | Value |
|---|---|
| Prompt Engineers | Discover trending prompt patterns and techniques |
| Content Creators | Curated, production-ready prompts with cover images |
| AI Researchers | Data on what prompt structures succeed in the wild |
| Sparki Platform | Evergreen prompt library powering the Sparki frontend |

### 1.4 Success Metrics

- **Coverage**: Prompts from Top-N trending creators in AI video space
- **Quality**: % of extracted prompts that are actually usable (target: > 70%)
- **Deduplication**: < 5% duplicate rate across the prompt library
- **Autonomy**: Human intervention required only for novel category approval
- **Freshness**: New prompts discovered within 24h of trending

---

## 2. Functional Specification

### 2.1 Core Features

#### F1 — Query Planner (Stateful Strategy Agent)

The Query Planner is the "brain" that decides what to search. It is **not** a static keyword list.

| Capability | Description |
|---|---|
| Seed queries | Starts from `configs/queries.yaml` (Veo 3, Veo 3.1 prompt, etc.) |
| LLM-driven expansion | Analyzes top-performing queries from Memory and generates 5–10 new candidates |
| Trend-aware | Incorporates trending model names, competitor comparisons, and prompting technique terms |
| Diversity enforcement | Ensures query mix covers: model names, styles, techniques, use-cases |
| Budget allocation | Decides how many scrolls/query to spend based on historical yield |

**Outputs**: Ranked list of queries with planned scroll budget.

#### F2 — Crawler Agent (Playwright-based X Scraper)

Reuses the battle-tested `x_scraper_pw.py` pattern as the **lowest layer**, wrapped as an async LangGraph node.

| Capability | Description |
|---|---|
| Multi-query orchestration | Runs multiple search queries, each as an independent async task |
| Dynamic scroll | Scrolls until stale (3 consecutive empty scrolls), configurable max |
| Cookie auth persistence | Loads/saves cookies from `outputs/cookies.json` |
| Two-round filtering | Round 1: likes ≥ threshold; Round 2: followers + views + keyword match |
| Author enrichment | Visits author profile → fetches `followers_count`; visits tweet detail → fetches `view_count` |
| Anti-ban measures | Random delays (100–1000ms), User-Agent spoofing, proxy support |
| Parallel execution | Uses `asyncio` + `playwright.async_api` for concurrent query execution |

**Outputs**: List of enriched tweet objects → written to SQLite `tweets` table.

#### F3 — Worker Agent (Prompt Extraction)

Each tweet is processed by a Worker that calls an LLM to classify and extract.

| Capability | Description |
|---|---|
| Classification | Is it a prompt? If yes → which category? |
| Extraction | Pull out `prompt_text`, `title`, `notes` |
| Validation & repair | Detects JSON key-name extraction errors and placeholder text; re-extracts with specialized prompts |
| Structured prompt detection | Finds JSON/YAML/shot-list format prompts in tweet text |
| "Prompt:" marker extraction | Extracts everything after `Prompt:` or `Prompt:-` |
| Author data attachment | Copies `author_name`, `author_screen`, `followers_count`, engagement metrics |
| Human-in-the-loop categories | If LLM suggests a new category → pause for human approval via `category_suggestions` table |

**Outputs**: Extracted prompt records → written to SQLite `prompts` table.

#### F4 — Prompt Quality Scorer

After extraction, each prompt is scored across multiple dimensions.

| Metric | Description | Score Range |
|---|---|---|
| `specificity` | How detailed is the visual description? | 0.0–1.0 |
| `visual_detail` | Camera, lighting, composition terms present? | 0.0–1.0 |
| `novelty` | Unique/rare prompt structure or common? | 0.0–1.0 |
| `generatable` | Can this be directly used for generation? | 0.0–1.0 |
| `overall` | Weighted average | 0.0–1.0 |

Scores are written back to the `prompts` table (`quality_score` JSON column).

#### F5 — Memory / Retrieval Layer

The **long-term memory** of the agent, implemented in SQLite (upgradeable to PostgreSQL/Pinecone).

| Table | Purpose |
|---|---|
| `queries` | Historical query text, run timestamps, yield rates (prompts per tweet) |
| `authors` | Author screen name, profile URL, follower counts, `high_value_ratio`, last_active |
| `prompts` | Full prompt text, source tweet URL, category, quality scores, embedding vector, timestamps |
| `images` | Generated cover image GCS URL, model used, generation status |
| `scrape_runs` | Each agent run: timestamp, queries run, inputs/outputs, funnel rates |

**Vector search** (future): `prompt_text` embedding stored for similarity-based deduplication.

#### F6 — Cover Image Generator

| Capability | Description |
|---|---|
| Multi-model fallback | Tries `gemini-3-pro-image-preview` → `gemini-3.1-flash-image-preview` → `gemini-2.5-flash-image` |
| Style system | Category-specific style keywords (cinematic: film grain, anamorphic; product-photography: studio lighting, white background) |
| GCS upload | Uploads to `gs://sparki-op-test/prompts/{category}/{YYYY-MM}/{scrape_id}/{prompt_id}.png` |
| Local fallback | If GCS fails, saves to `outputs/generated_images/` |
| Batch async | Runs up to 3 concurrent generations |

**Outputs**: Image GCS URL → written to `prompts.image_gcs_url`.

#### F7 — Feedback & Strategy Optimizer

The **self-improvement loop** that closes the agent cycle.

| Capability | Description |
|---|---|
| Yield analysis | Per-query: raw tweets → filtered → prompts extracted → high-quality |
| Query performance tracking | Stores `prompts_yield_rate` (prompts / tweets) and `qualified_rate` (high-quality / total) per query |
| Strategy update | High-yield queries get more scroll budget; low-yield queries pruned or rephrased |
| Author follow-up | High-value authors (high `high_value_ratio`) are tracked for follow-up crawls |
| Memory persistence | All metrics persisted to SQLite; loaded at startup for warm start |

#### F8 — Output Composer

| Format | Description |
|---|---|
| HTML gallery | `outputs/veo3-prompt-library.html` — card grid with cover image, prompt text, author, metrics |
| JSON export | `outputs/prompts.json` — full prompt objects with quality scores |
| GCS-hosted HTML | Uploads to GCS, returns `gs://` URL for CDN serving |

---

### 2.2 User Interactions & Flows

#### Flow 1 — Continuous Agent Loop (Fully Autonomous)
```
Query Planner → Crawler Agent → Worker Agent → Quality Scorer
      ↑                                                    ↓
      └──────── Feedback & Strategy Optimizer ←────────────┘
```

#### Flow 2 — Human-in-the-Loop for Novel Categories
```
Worker Agent detects unknown category → writes to category_suggestions table
→ pauses pipeline → alerts operator
→ operator approves/rejects/renames → pipeline resumes with updated categories
```

#### Flow 3 — Cold Start
```
System boots → loads queries from configs/queries.yaml → loads Memory from SQLite
→ checks X cookie freshness → if stale → requires re-auth
→ runs full pipeline
```

---

### 2.3 Data Flows

```
[Config: queries.yaml]
       ↓
[Query Planner] → generates ranked query list
       ↓
[Crawler Agent] → Playwright scrolls X.com search → raw tweets
       ↓ (writes to tweets table)
[Worker Agent] → LLM extraction → prompts
       ↓ (writes to prompts table)
[Quality Scorer] → scores each prompt
       ↓ (updates prompts table)
[Cover Image Generator] → Gemini image gen → GCS URL
       ↓ (updates prompts table)
[Output Composer] → HTML gallery
       ↓
[Feedback & Strategy Optimizer] → updates query/author metrics
       ↓
[Memory Layer] → SQLite persists everything
       ↓
→ next loop iteration
```

---

### 2.4 Edge Cases

| Scenario | Handling |
|---|---|
| X cookie expired (> 7 days) | Block pipeline, prompt for re-auth via `browser_auth.py` |
| LLM returns malformed JSON | Fall back to null, log warning, skip tweet |
| Prompt text extracted as JSON key name | Specialized re-extraction with `reextract_structured_prompt` |
| Prompt text is a placeholder ("...", "[full prompt]") | Re-extraction via `reextract_structured_prompt` → then `recheck_tweet` |
| X rate limit hit | Catch `TooManyRequests`, wait 15 min, retry once |
| Gemini image gen rate limited | Multi-model fallback with exponential backoff per model |
| Zero new tweets for a query | Log 0 yield, reduce future scroll budget for that query |
| Author has 0 followers | Filter out — likely spam/bot |
| Concurrent playwright contexts exhaust memory | Cap at 3 concurrent search contexts; queue excess |

---

## 3. Technical Architecture

### 3.1 Agent Framework

**LangGraph** with the following node types:

| Node Type | Description |
|---|---|
| `query_planner_node` | Stateless: generates query list from Memory + seed config |
| `crawler_node` | Stateful: manages Playwright lifecycle, scroll loops |
| `worker_node` | Stateless: LLM calls for prompt extraction |
| `quality_scorer_node` | Stateless: scoring heuristics |
| `image_gen_node` | Stateless: Gemini calls |
| `feedback_node` | Stateful: writes back to Memory |
| `router_node` | Conditional: decides next step (retry / skip / escalate) |

### 3.2 Concurrency Model

- **Async/await** throughout using `asyncio`
- **ThreadPoolExecutor** for CPU-bound LLM calls (non-blocking)
- **Semaphore** to cap concurrent Playwright contexts (max 3)
- **Producer/Consumer** pattern: Crawler produces tweets → Worker consumes

### 3.3 Database Schema

See [DevGuide §3.2 Database Schema](#32-database-schema) for full DDL.

### 3.4 Model Integration

| Task | Model | SDK |
|---|---|---|
| Prompt extraction | MiniMax LLM (OpenAI-compatible API) | `requests` |
| Quality scoring | MiniMax LLM | `requests` |
| Query expansion | MiniMax LLM | `requests` |
| Cover image generation | Gemini 3 Pro / 3.1 Flash / 2.5 Flash (Vertex AI) | `google.genai` |
| Embedding (future) | Vertex AI text embeddings | `google.genai` |

### 3.5 API Design

| Endpoint | Method | Description |
|---|---|---|
| `POST /agent/run` | POST | Trigger a full agent pipeline run |
| `GET /agent/status` | GET | Current pipeline status, progress |
| `POST /agent/stop` | POST | Gracefully halt running pipeline |
| `GET /prompts` | GET | Query prompts with filters (category, min_score, date) |
| `GET /prompts/{id}` | GET | Single prompt with full details |
| `GET /queries` | GET | Historical query performance data |
| `POST /categories/suggest` | POST | Submit a new category suggestion |
| `PATCH /categories/{id}` | PATCH | Approve/reject/rename a category suggestion |
| `GET /authors` | GET | List high-value authors |
| `POST /images/regenerate/{prompt_id}` | POST | Trigger cover image regeneration |

### 3.6 Configuration Management

All configuration via `configs/` YAML files — **no code changes** for operational tweaks.

| File | Purpose |
|---|---|
| `configs/queries.yaml` | Seed queries + negative keywords |
| `configs/engagement.yaml` | min_likes, min_followers, min_views thresholds |
| `configs/crawler.yaml` | scroll limits, stale threshold, timeouts, proxy |
| `configs/llm.yaml` | API base, model names, concurrency, timeouts |
| `configs/gemini.yaml` | GCS bucket, image model preferences |
| `configs/quality.yaml` | Scoring weights and thresholds |

---

## 4. Non-Functional Requirements

### 4.1 Performance
- Process ≥ 500 tweets per query run
- LLM extraction: ≤ 2s per tweet (with concurrency=15)
- Image generation: ≤ 30s per image (with concurrency=3)
- Full pipeline: ≤ 45 min for 10 queries × 20 scrolls

### 4.2 Reliability
- Pipeline must be **restartable** at any phase without data loss
- All intermediate state persisted to SQLite
- Failed LLM calls: max 2 retries with exponential backoff

### 4.3 Cost Control
- Cost estimation before each Gemini image gen call
- Low-quality prompts (overall score < 0.4) skip image generation
- Image gen only for prompts with `needs_image = true`

### 4.4 Observability
- Structured JSON logging with correlation IDs (`scrape_id`, `tweet_id`, `prompt_id`)
- Log levels: DEBUG (scroll details), INFO (phase transitions), WARNING (filters), ERROR (failures)
- Summary stats printed after each phase: throughput, yield rates, cost estimates

### 4.5 Security
- API keys loaded from `.env` only — never in code or config files
- X cookies stored locally, encrypted at rest (future: use OS keychain)
- GCS bucket is project-internal, not public

---

## 5. Extensibility

### 5.1 Trend Discovery Agent
Analyzes trending topics via `client.get_trends()` and automatically proposes new query additions.

### 5.2 Author Follow-up Agent
Periodically re-crawls high-value authors (top 20 by `high_value_ratio`) for new prompt posts.

### 5.3 Multi-Platform Expansion
- **TikTok**: `tiktok-scroll` skill for TikTok prompt discovery
- **Instagram**: `sparki-seo-blog-creator` for Instagram Reels/carousel analysis
- **Reddit**: Subreddit monitoring (`r/ChatPromptEngineering`, `r/Veo`, etc.)

### 5.4 Vector Deduplication
When prompt volume grows, add Pinecone/Vertex AI embeddings for semantic dedup (beyond text-match dedup).

---

## 6. Out of Scope

- Direct posting/sharing to social media
- Prompt execution / actual video generation (Sparki is a discovery tool, not an executor)
- User authentication / multi-tenant access control (internal tool)
- Real-time streaming of results (batch pipeline is acceptable)

---

## 7. Milestones

| Week | Deliverable |
|---|---|
| **W1** | LangGraph pipeline skeleton, Crawler node (Playwright async), SQLite schema |
| **W2** | Worker node (LLM extraction), Validation & repair logic, Category HITL |
| **W3** | Memory layer (full CRUD), Feedback node (yield tracking), Query Planner |
| **W4** | Quality Scorer node, Cover Image Generator node |
| **W5** | Full loop integration, Output Composer (HTML gallery), Quality thresholds |
| **W6** | Anti-ban hardening, cost estimation, observability logging |
| **W7** | API server, incremental run detection, retry resilience |
| **W8** | Trend Discovery Agent, Author Follow-up Agent, multi-platform stubs |

---

## 8. Glossary

| Term | Definition |
|---|---|
| **Sparki** | The system name — a smart, autonomous prompt-crawling spider |
| **Veo** | Google's AI video generation model (Veo 3, Veo 3.1) |
| **Prompt** | A text description used to guide AI generation of video/images |
| **Yield rate** | Number of usable prompts extracted per 100 tweets scraped |
| **HITL** | Human-in-the-Loop — system pauses for human approval |
| **Qualified prompt** | A prompt with quality score ≥ 0.6 |
| **Memory layer** | SQLite-backed persistent storage for queries, authors, prompts |