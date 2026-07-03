# Sparki Developer Guide

> **Version**: 1.0 | **Audience**: Engineers building and extending Sparki

---

## 1. Project Structure

```
16_NewCrawler/
├── configs/                        # All YAML configuration — no code changes for ops tweaks
│   ├── queries.yaml               # Search queries + negative keywords
│   ├── engagement.yaml            # min_likes, min_followers, min_views
│   ├── crawler.yaml               # Scroll limits, timeouts, proxy, stale threshold
│   ├── llm.yaml                   # API base, model names, concurrency, timeouts
│   ├── gemini.yaml                # GCS bucket, image model preferences
│   └── quality.yaml               # Scoring weights, thresholds
│
├── src/                            # Source code (all new code goes here)
│   ├── __init__.py
│   ├── main.py                    # CLI entry point
│   │
│   ├── agent/                     # LangGraph agent definition
│   │   ├── __init__.py
│   │   ├── state.py               # AgentState dataclass (the shared state graph)
│   │   ├── nodes.py               # All node functions (query_planner, crawler, worker, etc.)
│   │   ├── graph.py               # LangGraph build_graph() definition
│   │   └── config.py              # Node-level config (retry policies, concurrency)
│   │
│   ├── crawler/                   # Playwright-based X crawler
│   │   ├── __init__.py
│   │   ├── browser.py             # Browser/context management, cookie auth
│   │   ├── search.py              # Search page navigation, tab switching
│   │   ├── scroll.py              # Scroll-and-extract loop, stale detection
│   │   ├── extraction.py          # DOM parsing: extract tweets, authors, metrics
│   │   └── enrichment.py          # Profile visits, tweet detail visits, enrichment
│   │
│   ├── worker/                    # Prompt extraction worker
│   │   ├── __init__.py
│   │   ├── extractor.py           # LLM call + post-extraction validation/repair
│   │   ├── classifier.py          # Category classification logic
│   │   ├── dedup.py               # Text similarity + embedding dedup
│   │   └── scorer.py              # Quality scoring across multiple dimensions
│   │
│   ├── memory/                    # SQLite-backed persistence layer
│   │   ├── __init__.py
│   │   ├── schema.py              # Full DDL, migrations
│   │   ├── queries.py             # Query table CRUD
│   │   ├── authors.py             # Author table CRUD
│   │   ├── prompts.py             # Prompt table CRUD
│   │   └── images.py              # Image table CRUD
│   │
│   ├── llm/                       # LLM integration (provider-agnostic)
│   │   ├── __init__.py
│   │   ├── client.py             # Generic OpenAI-compatible client (requests-based)
│   │   ├── prompts.py             # All system prompt templates
│   │   └── router.py              # Model routing (small/fast vs large/high-quality)
│   │
│   ├── image_gen/                 # Gemini image generation
│   │   ├── __init__.py
│   │   ├── client.py             # Vertex AI Gemini client, multi-model fallback
│   │   ├── style.py              # Category-based style system
│   │   └── gcs.py                # GCS upload helpers
│   │
│   ├── api/                       # REST API server (FastAPI)
│   │   ├── __init__.py
│   │   ├── main.py               # FastAPI app, routes
│   │   ├── agent_routes.py        # /agent/* endpoints
│   │   ├── prompt_routes.py       # /prompts/* endpoints
│   │   └── category_routes.py     # /categories/* endpoints
│   │
│   └── utils/                     # Shared utilities
│       ├── __init__.py
│       ├── logging.py             # Structured logging with correlation IDs
│       ├── config.py              # YAML config loader with env var overrides
│       └── metrics.py             # Cost estimation, yield rate calculators
│
├── scripts/                       # Legacy scripts from 11_X_Scrape (reference only)
│
├── tests/                         # Unit and integration tests
│   ├── unit/
│   │   ├── test_worker/
│   │   ├── test_memory/
│   │   └── test_scoring/
│   └── integration/
│       └── test_pipeline/
│
├── outputs/                       # Runtime output directory
│   ├── cookies.json              # X.com auth cookies
│   ├── results.json              # Raw scrape results
│   ├── veo3-prompt-library.html  # Generated HTML gallery
│   └── generated_images/         # Locally cached cover images
│
├── data/                          # SQLite database location
│   └── veo_prompts.db
│
├── docs/                          # Documentation
│   ├── 00_RawIdea.md
│   ├── 01_PRD.md                 # Product Requirements Document
│   └── 02_DevGuide.md            # This file
│
├── .env                           # API keys and secrets (git-ignored)
├── .env.example                   # Template for .env
├── requirements.txt
├── pyproject.toml
└── CLAUDE.md                      # Project-specific instructions
```

---

## 2. Architecture

### 2.1 System Diagram

```
                          ┌─────────────────────────────────────────────────────────┐
                          │                    LangGraph Agent                       │
                          │                                                          │
                          │  ┌─────────────┐   ┌─────────────┐   ┌──────────────┐  │
                          │  │ Query       │──▶│  Crawler     │──▶│   Worker      │  │
                          │  │ Planner     │   │  Node        │   │   Node        │  │
                          │  │ Node        │   │ (Playwright) │   │ (LLM Extract) │  │
                          │  └──────┬──────┘   └─────────────┘   └──────┬───────┘  │
                          │         │                                      │          │
                          │         │          ┌─────────────┐             │          │
                          │         └─────────▶│  Router     │◀────────────┘          │
                          │                    │  Node       │                        │
                          │                    └──────┬──────┘                        │
                          │                           │                                │
                          │         ┌────────────────┼────────────────┐              │
                          │         ▼                ▼                ▼              │
                          │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
                          │  │  Quality    │  │ Image Gen   │  │ Feedback    │       │
                          │  │  Scorer     │  │ Node        │  │ Node        │       │
                          │  │  Node       │  │ (Gemini)    │  │             │       │
                          │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘       │
                          │         │               │                │               │
                          │         │               ▼                │               │
                          │         │         ┌─────────────┐        │               │
                          │         │         │ Output      │        │               │
                          │         │         │ Composer    │        │               │
                          │         │         │ (HTML/JSON) │        │               │
                          │         │         └─────────────┘        │               │
                          │         │                               ▼               │
                          │         │                    ┌─────────────────┐        │
                          │         │                    │    Memory       │        │
                          │         │                    │    Layer        │        │
                          │         │                    │  (SQLite)       │        │
                          │         │                    └────────┬────────┘        │
                          │         │                             │                 │
                          └─────────┼─────────────────────────────┘                 │
                                    │                                               │
                                    ▼                                               │
                          ┌─────────────────┐                                        │
                          │   REST API      │                                        │
                          │   (FastAPI)     │                                        │
                          │   :8000         │                                        │
                          └─────────────────┘                                        │
                                                                                    │
                          ┌─────────────────────────────────────────────────────────┐
                          │                  External Services                      │
                          │  X.com (Playwright) │ MiniMax LLM API │ Vertex AI Gemini │
                          │  gs://sparki-op-test                                     │
                          └─────────────────────────────────────────────────────────┘
```

### 2.2 Data Flow (Single Pipeline Run)

```
queries.yaml ──▶ Query Planner Node
                        │
                        ▼ (ranked query list)
               Crawler Node (Playwright)
                        │
                        ▼ (enriched tweets)
               Worker Node (LLM extraction)
                        │
                        ▼ (prompts, category suggestions)
               ┌───────┴───────┐
               ▼               ▼
        [good prompts]    [needs human approval]
                                 │
                                 ▼ (HITL)
                          Category approved
                                 │
                                 ▼
               Quality Scorer Node
                        │
                        ▼ (scored prompts)
               Image Gen Node (Gemini)
                        │
                        ▼ (image URLs in DB)
               Feedback Node (update metrics)
                        │
                        ▼ (persisted to SQLite)
               Output Composer (HTML/JSON)
```

---

## 3. Module Specifications

### 3.1 Agent (`src/agent/`)

#### `state.py` — AgentState

```python
@dataclass
class AgentState:
    scrape_id: int
    run_id: str                          # UUID for this pipeline run
    config: AgentConfig                  # Merged from all YAML configs

    # Query planning
    queries: list[QueryCandidate]         # Generated search queries
    active_query_idx: int                 # Current query being processed

    # Pipeline data
    tweets: list[Tweet]                  # All scraped tweets this run
    prompts: list[ExtractedPrompt]        # All extracted prompts
    scored_prompts: list[ScoredPrompt]    # With quality scores
    generated_images: list[ImageResult]   # With GCS URLs

    # Memory/feedback
    query_metrics: dict[str, QueryMetrics] # Per-query yield data
    author_metrics: dict[str, AuthorMetrics]

    # Category management
    pending_category_approvals: list[CategorySuggestion]

    # Status
    phase: PipelinePhase                  # INITIALIZING / QUERY_PLANNING / CRAWLING /
                                          #   EXTRACTING / SCORING / IMAGING / COMPOSING / DONE
    errors: list[PipelineError]
    stats: PipelineStats                 # Timings, counts, cost estimates
```

#### `graph.py` — LangGraph Definition

```python
def build_graph() -> StateGraph:
    """
    Returns the compiled LangGraph StateGraph.

    Edges:
      INITIALIZING  ──▶ QUERY_PLANNING
      QUERY_PLANNING ──▶ CRAWLING
      CRAWLING      ──▶ EXTRACTING
      EXTRACTING    ──▶ SCORING
      SCORING       ──▶ IMAGING
      IMAGING       ──▶ COMPOSING
      COMPOSING     ──▶ DONE

    Conditional edges from CRAWLING / EXTRACTING:
      on error   → ERROR_RECOVERY
      on empty   → early_done
      on HITL    → wait_for_human

    Error recovery retries up to 3× with exponential backoff,
      then escalates to ERROR state.
    """
```

#### `nodes.py` — Node Functions

| Node Function | Signature | Description |
|---|---|---|
| `query_planner_node` | `(state) → AgentState` | Loads seed queries from config, calls LLM expansion, returns ranked list |
| `crawler_node` | `(state) → AgentState` | Orchestrates async Playwright for all queries, writes tweets to DB |
| `worker_node` | `(state) → AgentState` | Concurrent LLM extraction for each tweet, writes prompts to DB |
| `router_node` | `(state) → str` | Conditional routing: `retry` / `skip` / `human_review` / `continue` |
| `quality_scorer_node` | `(state) → AgentState` | Scores all prompts, skips low-quality image gen |
| `image_gen_node` | `(state) → AgentState` | Gemini image gen for qualified prompts, uploads to GCS |
| `feedback_node` | `(state) → AgentState` | Updates `query_metrics`, `author_metrics` in Memory |
| `output_composer_node` | `(state) → AgentState` | Generates HTML gallery + JSON export |
| `error_recovery_node` | `(state) → AgentState` | Retries failed items, logs errors |

### 3.2 Crawler (`src/crawler/`)

#### `browser.py` — BrowserManager

```python
class BrowserManager:
    def __init__(
        self,
        cookies_path: Path,
        proxy: str | None = None,
        headless: bool = True,
    ):
        """Initialize Playwright browser with cookie auth."""

    async def new_context(self) -> BrowserContext:
        """Return a new isolated browser context."""

    async def close(self):
        """Clean up all contexts and browser."""

    @staticmethod
    def load_cookies(cookies_path: Path) -> list[dict]:
        """Load cookies from JSON, adapt to Playwright format.

        Cookie format requirements (Playwright 1.58+):
          - __Host- cookies: domain='x.com', secure=True, sameSite='Strict'
          - __Secure- cookies: domain='.x.com', secure=True, sameSite='Strict'
          - All other cookies: domain='.x.com', secure=True, sameSite='Strict'
        """

    async def verify_session(self, context: BrowserContext) -> bool:
        """Check if cookies are still valid by navigating to x.com home."""
```

#### `browser_auth.py` — X.com Login

```bash
# Interactive (opens browser, you log in manually)
python -m src.crawler.browser_auth

# With credentials (for CI/automation)
python -m src.crawler.browser_auth --username USER --password PASS

# Verify existing cookies
python -m src.crawler.browser_auth --verify
```

#### `extraction.py` — TweetExtractor

```python
class TweetExtractor:
    @staticmethod
    def extract_search_tweets(page: Page) -> list[dict]:
        """
        Parse all [data-testid='tweet'] elements currently in DOM.
        Returns list of tweet dicts with:
          tweet_id, url, profile_url, author_name, author_screen,
          short_text, created_at, favorite_count, retweet_count,
          reply_count, view_count
        """

    @staticmethod
    def parse_metric(text: str) -> int:
        """Parse '1.29K', '3.5M' → int."""

    @staticmethod
    def text_matches_all_keywords(text: str, keywords: list[str]) -> bool:
        """Case-insensitive all-keywords match."""
```

#### `scroll.py` — ScrollAndExtract

```python
async def scroll_and_extract(
    page: Page,
    max_scrolls: int = 20,
    stale_threshold: int = 3,
    delay_ms: tuple[int, int] = (100, 500),
) -> list[dict]:
    """
    Async scroll-to-bottom loop.
    Stops when no new tweets appear for `stale_threshold` consecutive scrolls.
    Returns deduplicated list of all extracted tweets.
    """
```

### 3.3 Worker (`src/worker/`)

#### `extractor.py` — PromptExtractor

```python
class PromptExtractor:
    def __init__(
        self,
        llm_client: LLMClient,
        categories: list[Category],
    ):
        """Initialize with LLM client and active category list."""

    def extract(self, tweet: Tweet) -> ExtractionResult:
        """
        Single-tweet extraction.
        Returns ExtractionResult(is_prompt, category, title, prompt_text, notes).
        Handles:
          - First-pass LLM classification
          - Recheck for tweets with prompt indicators
          - Validation & repair for JSON-key extraction errors
          - Structured prompt extraction (JSON/shot-list/"Prompt:" markers)
        """

    def extract_batch(
        self,
        tweets: list[Tweet],
        concurrency: int = 15,
    ) -> list[ExtractionResult]:
        """Concurrent extraction with ThreadPoolExecutor + as_completed."""
```

#### `scorer.py` — QualityScorer

```python
@dataclass
class QualityScores:
    specificity: float   # 0.0–1.0
    visual_detail: float
    novelty: float
    generatable: float
    overall: float

class QualityScorer:
    def score(self, prompt: ExtractedPrompt) -> QualityScores:
        """
        Score a prompt across 4 dimensions using LLM analysis.
        Returns QualityScores dataclass.
        """

    def should_generate_image(self, scores: QualityScores) -> bool:
        """Return True if overall score >= quality.yaml thresholds."""
```

#### `dedup.py` — PromptDeduplicator

```python
class PromptDeduplicator:
    def is_duplicate(self, new_prompt: str, threshold: float = 0.85) -> bool:
        """
        Check if prompt is a near-duplicate of an existing prompt in DB.
        Uses text similarity (Jaccard on trigrams) as fast path,
        then embedding cosine similarity if available (future: Pinecone).
        """

    def add_to_corpus(self, prompt_id: int, text: str):
        """Add a prompt to the dedup corpus (in-memory + persisted to DB)."""
```

### 3.4 Memory (`src/memory/`)

#### `schema.py` — Database Schema

```sql
CREATE TABLE IF NOT EXISTS scrape_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL UNIQUE,
    started_at   TEXT NOT NULL,
    completed_at TEXT,
    queries      TEXT NOT NULL,          -- JSON array
    phase        TEXT NOT NULL,
    total_tweets INTEGER DEFAULT 0,
    total_prompts INTEGER DEFAULT 0,
    total_images INTEGER DEFAULT 0,
    total_cost_usd REAL DEFAULT 0,
    status       TEXT DEFAULT 'running'  -- running / completed / failed
);

CREATE TABLE IF NOT EXISTS queries (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    scrape_run_id    INTEGER REFERENCES scrape_runs(id),
    text             TEXT NOT NULL,
    scroll_budget    INTEGER DEFAULT 20,
    tweets_raw       INTEGER DEFAULT 0,
    tweets_filtered  INTEGER DEFAULT 0,
    prompts_extracted INTEGER DEFAULT 0,
    qualified        INTEGER DEFAULT 0,
    qualified_rate   REAL DEFAULT 0,      -- qualified / tweets_filtered
    prompt_yield_rate REAL DEFAULT 0,     -- prompts_extracted / tweets_filtered
    last_run_at      TEXT
);

CREATE TABLE IF NOT EXISTS authors (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    screen_name      TEXT NOT NULL UNIQUE,
    display_name     TEXT,
    profile_url      TEXT,
    followers_count  INTEGER DEFAULT 0,
    total_prompts    INTEGER DEFAULT 0,
    qualified_prompts INTEGER DEFAULT 0,
    high_value_ratio REAL DEFAULT 0,     -- qualified_prompts / total_prompts
    last_active_at   TEXT,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    tweet_id         TEXT NOT NULL UNIQUE,
    scrape_run_id    INTEGER REFERENCES scrape_runs(id),
    url              TEXT NOT NULL,
    category         TEXT NOT NULL,
    title            TEXT NOT NULL,
    prompt_text      TEXT NOT NULL,
    notes            TEXT,
    author_id        INTEGER REFERENCES authors(id),
    likes_count      INTEGER DEFAULT 0,
    retweet_count    INTEGER DEFAULT 0,
    reply_count      INTEGER DEFAULT 0,
    view_count       INTEGER DEFAULT 0,
    quality_scores   TEXT,                -- JSON: {specificity, visual_detail, novelty, generatable, overall}
    extracted_at     TEXT NOT NULL,
    image_gcs_url    TEXT,
    image_generated_at TEXT,
    category_path    TEXT,
    embedding_vector  BLOB,               -- Future: for semantic dedup
    needs_image      INTEGER DEFAULT 1,
    FOREIGN KEY (scrape_run_id) REFERENCES scrape_runs(id)
);

CREATE TABLE IF NOT EXISTS images (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id        INTEGER NOT NULL REFERENCES prompts(id),
    generated_url    TEXT,
    model_used       TEXT,
    status           TEXT DEFAULT 'pending',  -- pending / generating / completed / failed
    error_message    TEXT,
    generated_at     TEXT
);

CREATE TABLE IF NOT EXISTS category_suggestions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    suggested_name  TEXT NOT NULL,
    suggested_desc  TEXT,
    reason          TEXT NOT NULL,
    suggested_by    TEXT NOT NULL,
    sample_prompt   TEXT NOT NULL,
    status          TEXT DEFAULT 'pending',   -- pending / approved / rejected
    reviewed_at     TEXT,
    reviewed_by     TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prompts_category ON prompts(category);
CREATE INDEX IF NOT EXISTS idx_prompts_quality ON prompts(quality_scores);
CREATE INDEX IF NOT EXISTS idx_authors_hvr ON authors(high_value_ratio DESC);
CREATE INDEX IF NOT EXISTS idx_queries_yield ON queries(prompt_yield_rate DESC);
```

#### `queries.py` — QueryRepository

```python
class QueryRepository:
    def create(self, run_id: int, query_text: str, scroll_budget: int = 20) -> int: ...
    def update_yield(self, query_id: int, tweets_raw, tweets_filtered,
                     prompts_extracted, qualified) -> None: ...
    def get_top_performing(self, run_id: int | None = None, top_n: int = 5
                          ) -> list[dict]: ...
    def get_all(self) -> list[Query]: ...
```

#### `authors.py` — AuthorRepository

```python
class AuthorRepository:
    def upsert(self, screen_name: str, display_name: str, profile_url: str,
               followers_count: int) -> int: ...
    def record_prompt(self, author_id: int, qualified: bool) -> None: ...
    def get_high_value(self, top_n: int = 20) -> list[Author]: ...
    def get_or_create(self, screen_name: str) -> Author: ...
```

#### `prompts.py` — PromptRepository

```python
class PromptRepository:
    def insert(self, prompt: PromptRecord) -> int: ...
    def update_quality(self, prompt_id: int, scores: QualityScores) -> None: ...
    def update_image_url(self, prompt_id: int, gcs_url: str,
                         category_path: str = None) -> None: ...
    def get_without_images(self, scrape_run_id: int | None = None,
                           limit: int = None) -> list[Prompt]: ...
    def get_by_category(self, category: str, limit: int = 100) -> list[Prompt]: ...
    def search(self, query: str, min_score: float = 0,
               category: str = None) -> list[Prompt]: ...
```

### 3.5 LLM (`src/llm/`)

#### `client.py` — LLMClient

```python
class LLMClient:
    def __init__(
        self,
        api_base: str,
        api_key: str,
        default_model: str,
        timeout: int = 60,
    ):
        """OpenAI-compatible REST client using requests."""

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> str:
        """
        Send a completion request.
        Returns raw response text (caller parses JSON).
        """

    def complete_json[T: Any](
        self,
        prompt: str,
        system: str | None,
        pydantic_model: type[T],
        model: str | None = None,
    ) -> T:
        """
        Send a completion request and parse response into a Pydantic model.
        Handles JSON extraction from response text.
        Raises LLMError on parse failure.
        """
```

#### `router.py` — ModelRouter

```python
class ModelRouter:
    """
    Decides which model to use based on task type and API key load.
    Configuration via llm.yaml:

    routes:
      fast_cheap:
        model: MiniMax-M2.7
        use_for: [classification, dedup_check]
        max_tokens: 200
      high_quality:
        model: MiniMax-M2.7
        use_for: [extraction, quality_scoring]
        max_tokens: 500
      image_prompt:
        model: MiniMax-M2.7
        use_for: [cover_image_prompt_enhancement]
        max_tokens: 300
    """

    def route(self, task: str, **kwargs) -> LLMResponse: ...
```

### 3.6 Image Gen (`src/image_gen/`)

#### `client.py` — GeminiImageClient

```python
class GeminiImageClient:
    MODELS = [
        "gemini-3-pro-image-preview",
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-image",
    ]

    def generate(
        self,
        prompt: str,
        category: str,
        title: str,
    ) -> ImageResult:
        """
        Generate a cover image with multi-model fallback.
        Tries each model in order; on 429/RESOURCE_EXHAUSTED, waits and retries
        up to 3× before trying the next model.
        Uploads to GCS on success.
        Returns ImageResult(prompt_id, gcs_url, model_used).
        """

    def generate_batch(
        self,
        prompts: list[Prompt],
        concurrency: int = 3,
    ) -> list[ImageResult]:
        """Concurrent generation with semaphore-capped ThreadPoolExecutor."""
```

---

## 4. Configuration Reference

### 4.1 `configs/queries.yaml`

```yaml
queries:
  - "veo prompt"
  - "Veo 3 prompt"
  - "Gemini Veo prompt"
  - "Google Veo 3"
  - "Veo 3.1 prompt"

negative_keywords:
  - "ChatGPT"
  - "Doubao"
  - "Seedance"
  - "Kling"
  - "Sora"
  - "Runway"
  - "Pika"
  - "Luma Dream"
  - "Hailuo AI"

expansion:
  top_n_queries: 5          # How many top queries to feed to LLM for expansion
  new_query_count: 8        # How many new queries to generate per run
  min_yield_threshold: 0.01 # Only expand from queries with ≥ 1% yield rate
```

### 4.2 `configs/engagement.yaml`

```yaml
engagement:
  min_likes: 50
  min_followers: 1000
  min_views: 1000
  max_tweets_per_query: 200  # Cap tweets collected per query this run
```

### 4.3 `configs/crawler.yaml`

```yaml
crawler:
  scroll:
    max_scrolls: 20
    stale_threshold: 3       # Stop after N consecutive scrolls with no new tweets
    delay_ms: [100, 500]    # Random delay range between scrolls

  timeouts:
    page_goto: 60000         # ms
    selector_wait: 15000     # ms
    scroll_wait: 5000        # ms

  proxy:
    enabled: true
    server: "http://127.0.0.1:7897"

  cookie_age_days: 7         # Re-auth if cookies older than this

  concurrency:
    max_search_contexts: 3   # Max concurrent Playwright contexts for search
    max_enrichment_tasks: 5 # Max concurrent author/tweet enrichment tasks
```

### 4.4 `configs/llm.yaml`

```yaml
llm:
  api_base: "https://api.minimaxi.com/v1"
  api_key_env: "OPENAI_API_KEY"
  default_model: "MiniMax-M2.7"

  timeouts:
    extraction: 60           # seconds per LLM call
    scoring: 45
    query_expansion: 30

  concurrency:
    extraction: 15
    scoring: 10
    query_expansion: 1      # Sequential

  routes:
    fast_cheap:
      model: "MiniMax-M2.7"
      max_tokens: 200
      temperature: 0.0
    high_quality:
      model: "MiniMax-M2.7"
      max_tokens: 500
      temperature: 0.0
```

### 4.5 `configs/gemini.yaml`

```yaml
gemini:
  project: "sparki-op"
  location: "global"
  gcs_bucket: "sparki-op-test"

  image_models:
    - "gemini-3-pro-image-preview"
    - "gemini-3.1-flash-image-preview"
    - "gemini-2.5-flash-image"

  generation:
    concurrency: 3
    max_retries_per_model: 3
    retry_delay_base: 5      # seconds, exponential backoff multiplier

  style:
    cinematic:
      - "film grain"
      - "anamorphic"
      - "shallow depth of field"
      - "f-stop"
      - "35mm"
      - "kodak portra 400"
    character-design:
      - "character sheet"
      - "turnaround"
      - "expression sheet"
      - "animation ready"
    product-photography:
      - "product shot"
      - "studio lighting"
      - "white background"
      - "high-key lighting"
    video-generation:
      - "motion blur"
      - "dynamic pose"
      - "cinematic frame"
    image-generation:
      - "detailed illustration"
      - "digital art"
      - "8k resolution"
    other:
      - "high quality"
      - "vibrant colors"
      - "professional composition"
```

### 4.6 `configs/quality.yaml`

```yaml
quality:
  weights:
    specificity: 0.25
    visual_detail: 0.30
    novelty: 0.20
    generatable: 0.25

  thresholds:
    min_overall: 0.40         # Below this → skip image generation
    good_overall: 0.60       # Above this → auto-approve without review
    min_specificity: 0.30    # Per-dimension minimums
    min_visual_detail: 0.20
```

---

## 5. API Reference

### 5.1 Agent Endpoints

#### `POST /agent/run`
Trigger a full pipeline run.

**Request body:**
```json
{
  "scrape_id": 1,
  "queries": ["veo prompt", "Veo 3.1 prompt"],  // optional: override queries.yaml
  "phases": ["crawl", "extract", "score", "image", "compose"],
  "dry_run": false
}
```

**Response:**
```json
{
  "run_id": "uuid",
  "status": "running",
  "phase": "crawling",
  "started_at": "2026-05-19T10:00:00Z"
}
```

#### `GET /agent/status`
Get current pipeline status.

**Response:**
```json
{
  "run_id": "uuid",
  "status": "running",
  "phase": "extracting",
  "progress": {
    "tweets_collected": 342,
    "tweets_processed": 298,
    "prompts_extracted": 87,
    "images_generated": 45
  },
  "errors": [],
  "estimated_completion_minutes": 12
}
```

#### `POST /agent/stop`
Gracefully halt the running pipeline.

### 5.2 Prompt Endpoints

#### `GET /prompts`
List prompts with filters.

| Query Param | Type | Description |
|---|---|---|
| `category` | str | Filter by category |
| `min_score` | float | Minimum overall quality score |
| `since` | date | Created after |
| `limit` | int | Max results (default 50, max 200) |
| `offset` | int | Pagination offset |

**Response:**
```json
{
  "total": 342,
  "limit": 50,
  "offset": 0,
  "prompts": [
    {
      "id": 1,
      "title": "Cinematic mountain product shot",
      "prompt_text": "Ultra-realistic product photograph...",
      "category": "product-photography",
      "quality_score": 0.78,
      "author": "@creator",
      "likes_count": 234,
      "image_gcs_url": "gs://sparki-op-test/..."
    }
  ]
}
```

#### `GET /prompts/{id}`

**Response:** Full prompt object including `quality_scores` breakdown, engagement metrics, image URL.

#### `POST /images/regenerate/{prompt_id}`
Re-generate cover image for a prompt (bypasses existing image).

**Response:**
```json
{
  "prompt_id": 1,
  "new_image_url": "gs://sparki-op-test/prompts/...",
  "model_used": "gemini-3-pro-image-preview"
}
```

### 5.3 Category Endpoints

#### `GET /categories`
List all active categories.

#### `PATCH /categories/{suggestion_id}`
Approve, reject, or rename a pending category suggestion.

**Request:**
```json
{
  "action": "approve",
  "new_name": "fashion-photography"
}
```

### 5.4 Query Endpoints

#### `GET /queries`
List queries with performance metrics.

**Response:**
```json
{
  "queries": [
    {
      "text": "veo prompt",
      "last_run_at": "2026-05-19T10:00:00Z",
      "tweets_raw": 120,
      "tweets_filtered": 45,
      "prompts_extracted": 12,
      "qualified": 8,
      "qualified_rate": 0.178,
      "prompt_yield_rate": 0.267
    }
  ]
}
```

---

## 6. Key Design Patterns

### 6.1 Producer / Consumer (Crawler → Worker)

The Crawler node produces enriched tweets and writes them to the SQLite `tweets` table immediately (not held in memory). The Worker node reads from the same table in batches. This means:
- If the process crashes mid-crawl, tweets are already persisted
- Worker can process at its own pace independent of crawl speed

```python
# Crawler writes immediately after each query
for tweet_batch in chunked(all_tweets, size=50):
    insert_tweets(scrape_id, tweet_batch, source_query=q)

# Worker reads incrementally
for batch in iter_batches(get_tweets_without_prompts(limit=100)):
    process_batch(batch)
```

### 6.2 Incremental Processing

Every phase is **incremental** — it skips already-processed records using `INSERT OR IGNORE` or `WHERE id NOT IN (SELECT ...)`. This makes the pipeline restart-safe at any point.

```python
# Example: extract only tweets without prompts
tweets = get_tweets_without_prompts()

# Example: generate images only for prompts without images
prompts = get_prompts_without_images(scrape_id=scrape_id, limit=50)
```

### 6.3 Structured Logging with Correlation IDs

Every log entry includes `scrape_id` and `run_id` (and `tweet_id`/`prompt_id` when available) for traceability.

```python
logger = get_logger("worker")
logger.info("prompt_extracted",
    extra={"run_id": state.run_id, "prompt_id": prompt.id, "category": "cinematic"})
```

### 6.4 Error Recovery with Exponential Backoff

```python
@retry(
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def call_with_backoff():
    await gemini_generate_image(...)
```

### 6.5 Multi-Model Fallback for Image Generation

```python
for model_name in IMAGE_MODELS:
    for attempt in range(3):
        try:
            return await generate(model_name, prompt)
        except RateLimitError:
            await asyncio.sleep((attempt + 1) * retry_delay_base)
        except OtherError:
            break  # Try next model
```

---

## 7. Development Guide

### 7.1 Setup

```bash
# 1. Clone and enter directory
cd e:/2027_GET_A_JOB/Get_An_AI_Job/视界Sparki/16_NewCrawler

# 2. Create virtual environment
python -m venv .venv
source .venv/Scripts/activate  # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your API keys:
#   OPENAI_API_KEY=sk-...
#   OPENAI_API_BASE=https://api.minimaxi.com/v1
#   GOOGLE_CLOUD_PROJECT=sparki-op

# 5. Initialize database
python -m src.memory.schema  # or via: sparki init-db

# 6. Authenticate with X.com
python -m src.crawler.browser_auth

# 7. Verify cookies are valid
python -m src.crawler.browser_auth --verify

# 8. Run a test pipeline (dry run first)
python -m src.main run --all --dry-run
```

### 7.2 Adding a New Node

1. Define the node function in `src/agent/nodes.py`:
   ```python
   def my_new_node(state: AgentState) -> AgentState:
       state.my_new_data = process(state.existing_data)
       return state
   ```

2. Add the edge in `src/agent/graph.py`:
   ```python
   graph.add_node("my_new_node", my_new_node)
   graph.add_edge("previous_node", "my_new_node")
   ```

3. Add node config in `src/agent/config.py`:
   ```python
   my_new_node_config = NodeConfig(
       max_retries=3,
       retry_delay=5,
   )
   ```

### 7.3 Adding a New Category

1. Add to `src/memory/categories.py`:
   ```python
   DEFAULT_CATEGORIES = [
       ...
       ("fashion-photography", "Prompt for fashion and clothing photography"),
   ]
   ```

2. Run migration:
   ```bash
   python -c "from src.memory.schema import init_db; init_db()"
   ```

3. Update style keywords in `configs/gemini.yaml` under `style.fashion-photography`.

### 7.4 Adding a New Platform (TikTok, Instagram)

1. Create a new crawler module: `src/crawler/tiktok.py`
2. Implement the same interface as `src/crawler/playwright.py`:
   - `scrape_search(query, config) -> list[Tweet]`
3. Add a platform enum to `src/agent/state.py`
4. Add a conditional branch in `crawler_node` to dispatch to the correct crawler

### 7.5 Testing

```bash
# Run all unit tests
pytest tests/unit/ -v

# Run specific test file
pytest tests/unit/test_worker/test_extractor.py -v

# Run integration test (requires X cookies + API keys)
pytest tests/integration/test_pipeline.py -v

# Run with coverage
pytest --cov=src --cov-report=html tests/

# Dry-run specific phase
python -m src.main --phase 2 --dry-run
```

### 7.6 Database Migrations

Migrations are handled via `_migrate_*` functions in `src/memory/schema.py`, called on `init_db()`. Each migration uses `ALTER TABLE ... ADD COLUMN` to add new columns to existing tables (SQLite-compatible).

For schema changes that require data transformation:
1. Create a new `_migrate_<description>` function
2. Call it from `init_db()`
3. Log migration in a `schema_migrations` tracking table

---

## 8. Operational Runbook

### 8.1 Starting a Full Pipeline Run

```bash
# All phases
python -m src.main run --all

# Specific scrape ID, all phases
python -m src.main run --scrape-id 5 --all

# Single phase (incremental)
python -m src.main run --phase 2 --scrape-id 5
```

### 8.2 Checking Status

```bash
# Via CLI
python -m src.main status

# Via API
curl http://localhost:8000/agent/status
```

### 8.3 Handling Category Suggestions

```bash
# List pending suggestions
python -c "
from src.memory import init_db, get_pending_suggestions
init_db()
for s in get_pending_suggestions():
    print(f'[{s[\"id\"]}] {s[\"suggested_name\"]}: {s[\"reason\"][:80]}')
"

# Approve
python -c "from src.memory import approve_suggestion; approve_suggestion(suggestion_id)"

# Reject
python -c "from src.memory import reject_suggestion; reject_suggestion(suggestion_id)"
```

### 8.4 Restarting After Failure

```bash
# The pipeline is restart-safe — just re-run from the last failed phase
python -m src.main run --phase 2  # resumes from where it left off

# If Phase 1 fails, fix the issue and re-run
python -m src.main run --phase 1

# Full reset (delete a specific scrape run and re-run)
# Only do this if you want to re-collect all tweets for that scrape
```

### 8.5 Monitoring Logs

```bash
# Real-time tail
python -m src.main run --all 2>&1 | grep -E "(ERROR|WARN|Phase|Prompts|Images)"

# Or use the structured log output
python -m src.main run --all --log-format json | jq '.phase, .stats'
```

---

## 9. Dependencies

```
playwright>=1.40.0
asyncio
langgraph
sqlite3 (stdlib)
requests
pydantic>=2.0
pyyaml
python-dotenv
google-genai>=0.8.0
google-cloud-storage
pillow
structlog
pytest (dev)
pytest-asyncio (dev)
pytest-cov (dev)
```