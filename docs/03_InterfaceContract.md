# Sparki Interface Contract

> **Version**: 1.0 | **Purpose**: Strict data contracts between LangGraph nodes — enables parallel development

---

## 1. Design Principles

1. **All inter-node data passes through `AgentState`** — no side-channel data
2. **Every field has an explicit type** — no `Optional` without reason, no bare `Any`
3. **Nodes only declare what they consume and produce** — internal logic is private
4. **Breaking a contract = CI failure** — schemas are the source of truth for type-checking
5. **Enums for all finite-state values** — no string comparison on phase names

---

## 2. Shared State: `AgentState`

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

@dataclass
class AgentState:
    # ── Identity ──────────────────────────────────────────────────────────────
    run_id: str                          # UUID for this pipeline run (set at startup)
    scrape_id: int                       # SQLite scrape_runs.id for this run
    config: "PipelineConfig"             # Merged from all YAML configs

    # ── Query Planning ─────────────────────────────────────────────────────────
    query_candidates: list["QueryCandidate"] = field(default_factory=list)
    active_query_index: int = 0          # Which query is currently being crawled

    # ── Pipeline Data (the main data tubes) ────────────────────────────────────
    # Raw tweets scraped this run (keyed by query for traceability)
    tweets_by_query: dict[str, list["Tweet"]] = field(default_factory=dict)
    all_tweet_ids: set[str] = field(default_factory=set)   # dedup set

    # Extracted prompts (one per qualifying tweet)
    extracted_prompts: list["ExtractedPrompt"] = field(default_factory=list)

    # Scored prompts (enriched with quality scores)
    scored_prompts: list["ScoredPrompt"] = field(default_factory=list)

    # Image generation results
    image_results: list["ImageResult"] = field(default_factory=list)

    # ── Memory/Feedback ────────────────────────────────────────────────────────
    query_metrics: dict[str, "QueryMetrics"] = field(default_factory=dict)
    author_metrics: dict[str, "AuthorMetrics"] = field(default_factory=dict)

    # ── Human-in-the-Loop ──────────────────────────────────────────────────────
    pending_category_suggestions: list["CategorySuggestion"] = field(default_factory=list)
    waiting_for_human: bool = False      # True → graph waits at router_node

    # ── Status ────────────────────────────────────────────────────────────────
    phase: "PipelinePhase" = PipelinePhase.INITIALIZING
    node_errors: list["PipelineError"] = field(default_factory=list)

    stats: "PipelineStats" = field(default_factory=lambda: PipelineStats())

    # ── Routing Hints (set by nodes, read by router_node) ─────────────────────
    router_decision: "RouterDecision" | None = None  # set by any node
    retry_count: int = 0                # incremented by error_recovery_node
```

---

## 3. Enumerations

```python
class PipelinePhase(Enum):
    INITIALIZING   = "initializing"
    QUERY_PLANNING = "query_planning"
    CRAWLING       = "crawling"
    EXTRACTING     = "extracting"
    SCORING        = "scoring"
    IMAGING        = "imaging"
    COMPOSING      = "composing"
    DONE           = "done"
    FAILED         = "failed"
    WAITING_HUMAN  = "waiting_human"   # paused at router_node


class RouterDecision(Enum):
    CONTINUE        = "continue"       # Proceed to next phase
    RETRY           = "retry"          # Retry current node (with backoff)
    SKIP            = "skip"           # Skip this item, continue
    WAIT_HUMAN      = "wait_human"     # Pause for human review
    EARLY_DONE      = "early_done"     # No more data, finish cleanly
    ERROR           = "error"          # Unrecoverable error


class NodeStatus(Enum):
    SUCCESS   = "success"
    RETRYING  = "retrying"
    FAILED    = "failed"
    SKIPPED   = "skipped"


class ImageGenStatus(Enum):
    PENDING    = "pending"
    GENERATING = "generating"
    COMPLETED  = "completed"
    FAILED     = "failed"
    SKIPPED    = "skipped"            # quality below threshold


class CategorySuggestionStatus(Enum):
    PENDING   = "pending"
    APPROVED  = "approved"
    REJECTED  = "rejected"


class ImageModel(Enum):
    GEMINI_3_PRO_IMAGE_PREVIEW    = "gemini-3-pro-image-preview"
    GEMINI_3_1_FLASH_IMAGE_PREVIEW = "gemini-3.1-flash-image-preview"
    GEMINI_2_5_FLASH_IMAGE         = "gemini-2.5-flash-image"
```

---

## 4. Data Object Schemas

### 4.1 `QueryCandidate`

Produced by: `query_planner_node`
Consumed by: `crawler_node`

```python
@dataclass
class QueryCandidate:
    text: str                           # The search keyword/string
    source: str                         # "seed" | "expansion" | "author_followup"
    scroll_budget: int = 20             # How many scroll cycles to run
    priority: float = 1.0               # 0.0–1.0, higher = more important
    negative_keywords: list[str] = field(default_factory=list)  # from engagement.yaml

    # Populated after crawl
    tweets_raw: int = 0
    tweets_filtered: int = 0
    error_message: str | None = None
```

### 4.2 `Tweet`

Produced by: `crawler_node` (enrichment step)
Consumed by: `worker_node`

```python
@dataclass
class Tweet:
    tweet_id: str                       # X.com status ID (e.g. "1234567890")
    url: str                             # Full https://x.com/user/status/{id}
    text: str                            # Full tweet text (after enrichment visit)
    short_text: str                      # Truncated text from search card (pre-enrichment)

    author: "AuthorRef"                 # Always non-null after enrichment

    created_at: str | None              # ISO8601 datetime
    favorite_count: int = 0             # Likes
    retweet_count: int = 0
    reply_count: int = 0
    view_count: int = 0                  # 0 if unavailable

    source_query: str = ""               # Which search query found this tweet
    scraped_at: str = ""                 # ISO8601, set at scrape time

    # Enrichment status flags
    author_enriched: bool = False        # Profile page visited, followers fetched
    detail_enriched: bool = False        # Tweet detail page visited, views fetched

    def dedup_key(self) -> str:
        return self.tweet_id


@dataclass
class AuthorRef:
    name: str                           # Display name
    screen_name: str                    # Handle (without @)
    profile_url: str                    # /{screen_name}
    followers_count: int = 0
    is_blue_verified: bool = False
```

### 4.3 `ExtractedPrompt`

Produced by: `worker_node`
Consumed by: `quality_scorer_node`

```python
@dataclass
class ExtractedPrompt:
    tweet_id: str                       # Foreign key to source Tweet
    url: str                            # https://x.com/user/status/{id}

    category: str                       # e.g. "video-generation", "cinematic"
    title: str                          # Short descriptive title (≤ 60 chars)
    prompt_text: str                    # The actual prompt content
    notes: str = ""                     # LLM explanation of why this qualifies

    author: "AuthorRef"

    # Engagement from tweet
    likes_count: int = 0
    retweet_count: int = 0
    reply_count: int = 0
    view_count: int = 0

    extracted_at: str = ""              # ISO8601, set by worker_node

    # Quality — populated by quality_scorer_node
    quality_scores: "QualityScores | None" = None

    # Image generation control
    needs_image: bool = True             # Set False for low-quality or duplicate
    image_status: ImageGenStatus = ImageGenStatus.PENDING

    # For structured prompts (JSON/shot-list/"Prompt:" marker)
    is_structured: bool = False          # True if extracted from structured format
    structured_format: str | None = None # "json" | "shot_list" | "prompt_marker"

    # Validation flags (set during extraction)
    is_recheck: bool = False             # True = second-pass LLM call was needed
    repair_attempted: bool = False       # True = validation/repair was triggered
```

### 4.4 `QualityScores`

Produced by: `quality_scorer_node`
Stored in: `ExtractedPrompt.quality_scores`

```python
@dataclass
class QualityScores:
    # All scores: 0.0 (worst) – 1.0 (best)
    specificity: float = 0.0            # Detail level of visual description
    visual_detail: float = 0.0           # Camera, lighting, composition terms
    novelty: float = 0.0                 # Uniqueness/rarity of structure
    generatable: float = 0.0             # Can this directly drive generation?

    # Computed
    overall: float = 0.0                 # Weighted average (weights in quality.yaml)

    def is_qualified(self, threshold: float = 0.40) -> bool:
        return self.overall >= threshold

    def should_generate_image(self, threshold: float = 0.40) -> bool:
        return self.overall >= threshold
```

### 4.5 `ScoredPrompt`

Alias / view of `ExtractedPrompt` after `quality_scorer_node` populates `quality_scores`.
No new fields — the presence of non-null `quality_scores` marks a prompt as "scored".

```python
# Type alias for clarity in code
ScoredPrompt = ExtractedPrompt  # same class, semantic role differs
```

### 4.6 `ImageResult`

Produced by: `image_gen_node`
Stored in: `AgentState.image_results` and written to DB

```python
@dataclass
class ImageResult:
    prompt_id: int                      # SQLite prompts.id (after insert)
    tweet_id: str                       # Foreign key

    status: ImageGenStatus
    model_used: str | None = None       # Which Gemini model succeeded
    gcs_url: str | None = None          # gs://sparki-op-test/prompts/...
    local_path: str | None = None        # Local fallback if GCS disabled
    error_message: str | None = None

    generated_at: str = ""               # ISO8601
    category_path: str | None = None     # GCS blob path (prompts/{cat}/{yyyy-mm}/...)
```

### 4.7 `QueryMetrics`

Produced by: `feedback_node`
Stored in: Memory layer; input to next run's `query_planner_node`

```python
@dataclass
class QueryMetrics:
    query_text: str
    scrape_run_id: int

    # Funnel counts
    tweets_raw: int = 0
    tweets_filtered: int = 0             # After Round-1 (likes) + Round-2 (followers/views)
    prompts_extracted: int = 0
    qualified_prompts: int = 0           # quality_score >= min_overall threshold

    # Rates
    qualified_rate: float = 0.0          # qualified_prompts / tweets_filtered
    prompt_yield_rate: float = 0.0       # prompts_extracted / tweets_filtered

    # History
    run_count: int = 1
    last_run_at: str = ""                # ISO8601

    # Planner hints (set by feedback_node)
    scroll_budget_hint: int = 20         # Recommended scroll_budget for next run
    is_active: bool = True               # False → prune from future runs
```

### 4.8 `AuthorMetrics`

Produced by: `feedback_node`
Stored in: Memory layer; used by Author Follow-up feature

```python
@dataclass
class AuthorMetrics:
    screen_name: str
    display_name: str
    profile_url: str

    followers_count: int = 0

    # Prompt history
    total_prompts: int = 0
    qualified_prompts: int = 0
    high_value_ratio: float = 0.0         # qualified_prompts / total_prompts

    last_active_at: str = ""             # ISO8601 of most recent prompt tweet
    last_crawled_at: str = ""            # ISO8601 of last crawl that included this author

    is_high_value: bool = False          # True if high_value_ratio > 0.5 and total >= 3
```

### 4.9 `CategorySuggestion`

Produced by: `worker_node`
Resolved by: human operator → `category_routes.py` or CLI

```python
@dataclass
class CategorySuggestion:
    id: int | None                      # SQLite category_suggestions.id (after insert)
    suggested_name: str
    suggested_desc: str = ""
    reason: str                         # Why LLM thinks this is a new category
    suggested_by: str                   # "MiniMax-M2.7" or "human"
    sample_prompt_text: str             # The triggering prompt text (first 200 chars)

    status: CategorySuggestionStatus = CategorySuggestionStatus.PENDING
    reviewed_at: str | None = None
    reviewed_by: str | None = None

    created_at: str = ""               # ISO8601
```

### 4.10 `PipelineStats`

Maintained by: all nodes (increment counters)

```python
@dataclass
class PipelineStats:
    phase_started_at: str = ""          # ISO8601 of current phase start
    phase_elapsed_seconds: float = 0.0

    # Counts (cumulative)
    tweets_collected: int = 0
    tweets_deduped: int = 0
    prompts_extracted: int = 0
    prompts_scored: int = 0
    images_generated: int = 0
    images_failed: int = 0
    categories_pending: int = 0

    # Cost estimation (USD)
    estimated_llm_cost_usd: float = 0.0
    estimated_image_gen_cost_usd: float = 0.0

    # Phase-level counts (reset per phase)
    phase_tweets_processed: int = 0
    phase_items_succeeded: int = 0
    phase_items_failed: int = 0

    def current_phase_duration(self) -> float:
        ...
```

### 4.11 `PipelineError`

Produced by: any node; collected in `AgentState.node_errors`

```python
@dataclass
class PipelineError:
    phase: PipelinePhase                # Phase during which error occurred
    node: str                           # Node function name (e.g. "crawler_node")
    error_type: str                     # "CrawlError" | "LLMError" | "ImageGenError" | etc.
    error_message: str
    item_id: str | None = None          # tweet_id, prompt_id, etc. if applicable
    timestamp: str = ""                 # ISO8601

    def is_retryable(self) -> bool:
        return self.error_type in {
            "TooManyRequestsError",
            "RateLimitError",
            "TimeoutError",
            "TemporaryGCSError",
        }
```

### 4.12 `PipelineConfig`

Merged from all `configs/*.yaml` files at startup.

```python
@dataclass
class PipelineConfig:
    queries: "QueriesConfig"
    engagement: "EngagementConfig"
    crawler: "CrawlerConfig"
    llm: "LLMConfig"
    gemini: "GeminiConfig"
    quality: "QualityConfig"


@dataclass
class QueriesConfig:
    seed_queries: list[str]
    negative_keywords: list[str]
    expansion: "ExpansionConfig"


@dataclass
class ExpansionConfig:
    top_n_queries: int = 5
    new_query_count: int = 8
    min_yield_threshold: float = 0.01


@dataclass
class EngagementConfig:
    min_likes: int = 50
    min_followers: int = 1000
    min_views: int = 1000
    max_tweets_per_query: int = 200


@dataclass
class CrawlerConfig:
    max_scrolls: int = 20
    stale_threshold: int = 3
    delay_ms_min: int = 100
    delay_ms_max: int = 500
    page_goto_timeout_ms: int = 60000
    selector_wait_ms: int = 15000
    scroll_wait_ms: int = 5000
    proxy_enabled: bool = True
    proxy_server: str = "http://127.0.0.1:7897"
    cookie_age_days: int = 7
    max_search_contexts: int = 3
    max_enrichment_tasks: int = 5


@dataclass
class LLMConfig:
    api_base: str = "https://api.minimaxi.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    default_model: str = "MiniMax-M2.7"
    extraction_timeout: int = 60
    scoring_timeout: int = 45
    query_expansion_timeout: int = 30
    extraction_concurrency: int = 15
    scoring_concurrency: int = 10
    query_expansion_concurrency: int = 1


@dataclass
class GeminiConfig:
    project: str = "sparki-op"
    location: str = "global"
    gcs_bucket: str = "sparki-op-test"
    image_models: list[str] = field(default_factory=lambda: [
        "gemini-3-pro-image-preview",
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-image",
    ])
    generation_concurrency: int = 3
    max_retries_per_model: int = 3
    retry_delay_base: int = 5
    style_keywords: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class QualityConfig:
    weights: "QualityWeights"
    thresholds: "QualityThresholds"


@dataclass
class QualityWeights:
    specificity: float = 0.25
    visual_detail: float = 0.30
    novelty: float = 0.20
    generatable: float = 0.25


@dataclass
class QualityThresholds:
    min_overall: float = 0.40
    good_overall: float = 0.60
    min_specificity: float = 0.30
    min_visual_detail: float = 0.20
```

---

## 5. Node Input/Output Contracts

### 5.1 Node Function Signature Convention

All node functions follow this signature:

```python
def node_name(state: AgentState) -> AgentState:
    """
    CONTRACT:
      INPUT:  reads AgentState fields as documented
      OUTPUT: returns AgentState with updated fields as documented
      THROWS: PipelineError (caught and collected by error_recovery_node)
              Never let exceptions propagate out of the node.
    """
    ...
    return state
```

### 5.2 `initialize_node`

**Trigger:** First node called when `phase == INITIALIZING`

| Reads | Writes |
|---|---|
| `config` | `run_id`, `scrape_id`, `phase` |
| | `stats` (phase_started_at) |

```python
def initialize_node(state: AgentState) -> AgentState:
    """
    INPUT:  state.config loaded from YAML files
    OUTPUT: state.run_id (uuid), state.scrape_id (from DB insert),
            state.phase = QUERY_PLANNING
    SIDE EFFECTS:
      - Inserts row into scrape_runs table
      - Loads existing query_metrics from DB into state.query_metrics
      - Loads existing author_metrics from DB into state.author_metrics
    """
```

### 5.3 `query_planner_node`

**Trigger:** `phase == QUERY_PLANNING`

| Reads | Writes |
|---|---|
| `config.queries` | `query_candidates` |
| `query_metrics` | `phase` → CRAWLING |
| `config.engagement` (for negative_keywords) | |

```python
def query_planner_node(state: AgentState) -> AgentState:
    """
    INPUT:  state.config.queries, state.query_metrics (historical)
    OUTPUT: state.query_candidates: list[QueryCandidate]
              - Seed queries from queries.yaml (source="seed")
              - LLM-expanded queries from top-performing historical queries (source="expansion")
              - Sorted by priority descending
            state.phase = PipelinePhase.CRAWLING
    CONTRACT:
      - query_candidates is never empty (at minimum returns seed queries)
      - Each QueryCandidate.negative_keywords is loaded from engagement config
    """
```

### 5.4 `crawler_node`

**Trigger:** `phase == CRAWLING`

| Reads | Writes |
|---|---|
| `query_candidates` | `tweets_by_query` (appends per query) |
| `all_tweet_ids` | `all_tweet_ids` (merged) |
| `config.crawler` | `stats.tweets_collected`, `stats.tweets_deduped` |
| `config.engagement` | `query_metrics[query].tweets_raw/filtered` |
| | `phase` → EXTRACTING |

```python
def crawler_node(state: AgentState) -> AgentState:
    """
    INPUT:  state.query_candidates (ordered by priority)
            state.config.crawler, state.config.engagement
    OUTPUT: state.tweets_by_query: dict[str, list[Tweet]]
              - Key = query text, Value = list of enriched Tweet objects
              - Deduplication: tweet_id checked against all_tweet_ids before appending
            state.all_tweet_ids: merged set of all tweet_ids seen
            state.query_metrics[query].tweets_raw/filtered updated
            state.phase = PipelinePhase.EXTRACTING

    CONTRACT:
      - For each query, at least an empty list is written to tweets_by_query
        (even if crawl failed — error_message on QueryCandidate is set instead)
      - Tweet.author is ALWAYS populated (author_enriched=True) after this node
      - All tweets in tweets_by_query pass engagement filters (min_likes etc.)
      - tweets_by_query is append-only (never overwrite a query's results)
    """
```

### 5.5 `worker_node`

**Trigger:** `phase == EXTRACTING`

| Reads | Writes |
|---|---|
| `tweets_by_query` | `extracted_prompts` (extends) |
| `config.llm` | `pending_category_suggestions` (extends) |
| `config.crawler` (negative_keywords) | `stats.prompts_extracted` |
| | `phase` → SCORING |

```python
def worker_node(state: AgentState) -> AgentState:
    """
    INPUT:  state.tweets_by_query (all tweets from all queries)
    OUTPUT: state.extracted_prompts: list[ExtractedPrompt]
              - Only tweets where LLM classified is_prompt=True
              - Structured prompts (JSON/shot-list/"Prompt:" marker) have is_structured=True
            state.pending_category_suggestions: list[CategorySuggestion]
              - Only for NEW categories not in existing categories list
            state.stats.prompts_extracted (count)
            state.phase = PipelinePhase.SCORING

    CONTRACT:
      - If pending_category_suggestions is non-empty:
          state.waiting_for_human = True
          state.router_decision = RouterDecision.WAIT_HUMAN
          (pipeline will pause at router_node until human resolves suggestions)
      - All ExtractedPrompt fields are non-null except notes (can be "")
      - extracted_at is set to current UTC ISO8601 for each prompt
      - author.followers_count >= engagement.min_followers for all prompts
    """
```

### 5.6 `router_node`

**Trigger:** Called after any node that may need routing decision; also called after `initialize_node`

| Reads | Writes |
|---|---|
| `router_decision` (from previous node) | `phase` (may change) |
| `waiting_for_human` | `router_decision` (resets to None) |
| `pending_category_suggestions` | |
| `node_errors` | |

```python
def router_node(state: AgentState) -> AgentState:
    """
    INPUT:  state.router_decision (set by prior node)
            state.waiting_for_human
            state.pending_category_suggestions
            state.node_errors
            state.retry_count
    OUTPUT: state.phase updated to next phase based on decision:
              WAIT_HUMAN   → WAITING_HUMAN (graph suspends)
              CONTINUE     → next phase in sequence
              EARLY_DONE   → DONE
              ERROR        → FAILED
              RETRY        → re-run current phase node
            state.router_decision = None (consumed)

    CONTRACT:
      - This is the ONLY node that writes to state.phase
      - WAITING_HUMAN phase requires external handler to call the graph
        again with router_decision=CONTINUE after human resolves suggestions
    """
```

### 5.7 `quality_scorer_node`

**Trigger:** `phase == SCORING`

| Reads | Writes |
|---|---|
| `extracted_prompts` | `scored_prompts` (same objects, scores populated) |
| `config.quality` | `ExtractedPrompt.quality_scores` (in-place) |
| `config.llm` | `stats.prompts_scored` |
| | `phase` → IMAGING |

```python
def quality_scorer_node(state: AgentState) -> AgentState:
    """
    INPUT:  state.extracted_prompts (all ExtractedPrompt objects)
    OUTPUT: state.scored_prompts: list[ScoredPrompt]
              - Same list reference; quality_scores field is now populated
            state.extracted_prompts[i].quality_scores = QualityScores (in-place)
            state.extracted_prompts[i].needs_image = scores.should_generate_image()
            state.stats.prompts_scored (count)
            state.phase = PipelinePhase.IMAGING

    CONTRACT:
      - Every prompt in extracted_prompts gets scored (no skipping)
      - needs_image = False ONLY when overall < quality.thresholds.min_overall
      - Scoring is done in concurrent batches (config.llm.scoring_concurrency)
    """
```

### 5.8 `image_gen_node`

**Trigger:** `phase == IMAGING`

| Reads | Writes |
|---|---|
| `scored_prompts` (where needs_image=True) | `image_results` (extends) |
| `config.gemini` | `stats.images_generated`, `stats.images_failed` |
| `config.quality` | `ExtractedPrompt.image_gcs_url` (written to DB) |
| | `phase` → COMPOSING |

```python
def image_gen_node(state: AgentState) -> AgentState:
    """
    INPUT:  state.scored_prompts where ExtractedPrompt.needs_image == True
    OUTPUT: state.image_results: list[ImageResult]
              - One ImageResult per prompt where generation was attempted
            For each prompt where image gen succeeded:
              - ExtractedPrompt.image_gcs_url updated in DB
              - ExtractedPrompt.image_status = ImageGenStatus.COMPLETED
            For each prompt where image gen failed:
              - ExtractedPrompt.image_status = ImageGenStatus.FAILED
              - ImageResult.error_message set
            Prompts with needs_image=False → ImageGenStatus.SKIPPED (no ImageResult)
            state.stats.images_generated, state.stats.images_failed updated
            state.phase = PipelinePhase.COMPOSING

    CONTRACT:
      - Prompts are processed in concurrent batches (max config.gemini.generation_concurrency)
      - Multi-model fallback: tries models in IMAGE_MODELS order
      - If all models exhausted → ImageGenStatus.FAILED, never raises exception
    """
```

### 5.9 `feedback_node`

**Trigger:** `phase == COMPOSING` (after Output Composer)

| Reads | Writes |
|---|---|
| `tweets_by_query` | `query_metrics` (updated in DB + state) |
| `scored_prompts` | `author_metrics` (updated in DB + state) |
| `image_results` | `stats.total_cost_usd` |
| `query_metrics` (current) | `phase` → DONE |

```python
def feedback_node(state: AgentState) -> AgentState:
    """
    INPUT:  state.tweets_by_query, state.scored_prompts,
            state.image_results, state.query_metrics, state.author_metrics
    OUTPUT: For each query in tweets_by_query:
              - Update query_metrics in DB: tweets_raw, tweets_filtered, prompts_extracted, qualified
              - Recalculate qualified_rate, prompt_yield_rate
              - Set scroll_budget_hint (reduce if low yield, increase if high yield)
            For each author in scored_prompts:
              - Update author_metrics in DB: total_prompts, qualified_prompts
              - Recalculate high_value_ratio
            state.stats.total_cost_usd (llm + image gen estimates)
            state.phase = PipelinePhase.DONE

    CONTRACT:
      - All metrics written to DB before phase transitions to DONE
      - scroll_budget_hint: 5 if qualified_rate < 0.05, 30 if qualified_rate > 0.25, else 20
    """
```

### 5.10 `output_composer_node`

**Trigger:** Called within `COMPOSING` phase (before `feedback_node`)

| Reads | Writes |
|---|---|
| `scored_prompts` | HTML file to `outputs/` |
| `image_results` | JSON export to `outputs/` |
| `query_metrics` | |
| `author_metrics` | |

```python
def output_composer_node(state: AgentState) -> AgentState:
    """
    INPUT:  state.scored_prompts (with quality_scores and image_gcs_url populated)
    OUTPUT: Writes files:
              - outputs/veo3-prompt-library.html (gallery, card grid)
              - outputs/prompts.json (full prompt objects)
              - Optionally: uploads HTML to GCS for CDN
            Returns state with phase = COMPOSING (feedback_node runs after)

    CONTRACT:
      - HTML includes ALL scored_prompts regardless of image generation status
      - Prompts without images show a placeholder card
      - HTML template uses category-based color coding
    """
```

---

## 6. Exception Taxonomy

All exceptions raised inside nodes are caught and converted to `PipelineError`.

| Exception Class | Thrown By | Is Retryable |
|---|---|---|
| `CrawlError` | crawler_node | No |
| `TooManyRequestsError(CrawlError)` | crawler_node | Yes (15min wait) |
| `EnrichmentError(CrawlError)` | crawler_node.enrichment | No |
| `LLMError` | worker_node | Yes (2 retries) |
| `LLMParseError(LLMError)` | worker_node | No |
| `ScoringError` | quality_scorer_node | Yes (2 retries) |
| `ImageGenError` | image_gen_node | No (multi-model fallback handles) |
| `RateLimitError(ImageGenError)` | image_gen_node | Yes (model-level retry) |
| `GCSError` | image_gen_node | No |
| `DeduplicationError` | worker_node | No |
| `ConfigError` | initialize_node | No (fatal — pipeline fails) |
| `DBError` | any memory node | No |

```python
class CrawlError(Exception): ...
class TooManyRequestsError(CrawlError): ...
class EnrichmentError(CrawlError): ...
class LLMError(Exception): ...
class LLMParseError(LLMError): ...
class ScoringError(Exception): ...
class ImageGenError(Exception): ...
class RateLimitError(ImageGenError): ...
class GCSError(Exception): ...
class DeduplicationError(Exception): ...
class ConfigError(Exception): ...
class DBError(Exception): ...
```

---

## 7. Node Dependency & Parallelism Map

```
┌──────────────────────────────────────────────────────────────────┐
│                        INITIALIZING                               │
│                    (initialize_node)                              │
└──────────────────────────┬───────────────────────────────────────┘
                           │ phase=QUERY_PLANNING
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                     QUERY_PLANNING                                │
│  query_planner_node ─────────────────────────────────────────────│
│  REQUIRES: seed queries from configs + historical query_metrics  │
│  BLOCKS:   nothing                                               │
└──────────────────────────┬───────────────────────────────────────┘
                           │ phase=CRAWLING
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                       CRAWLING                                    │
│  crawler_node ────────────────────────────────────────────────────│
│  REQUIRES: query_candidates                                       │
│  BLOCKS:   all subsequent phases                                  │
│  NOTE:     queries can run in parallel up to max_search_contexts │
│            but are orchestrated inside one node for state safety  │
└──────────────────────────┬───────────────────────────────────────┘
                           │ phase=EXTRACTING
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                       EXTRACTING                                 │
│  worker_node ────────────────────────────────────────────────────│
│  REQUIRES: tweets_by_query (all tweets from all queries)           │
│  BLOCKS:   quality_scorer_node                                    │
│  PARALLEL: LLM calls are concurrent (extraction_concurrency=15)  │
│  NOTE:     if pending_category_suggestions non-empty              │
│            → router sets WAITING_HUMAN (pipeline pauses here)     │
└──────────────────────────┬───────────────────────────────────────┘
                           │ phase=SCORING
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                       SCORING                                    │
│  quality_scorer_node ────────────────────────────────────────────│
│  REQUIRES: extracted_prompts                                      │
│  BLOCKS:   image_gen_node                                         │
│  PARALLEL: LLM scoring calls concurrent (scoring_concurrency=10)│
└──────────────────────────┬───────────────────────────────────────┘
                           │ phase=IMAGING
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                       IMAGING                                    │
│  image_gen_node ─────────────────────────────────────────────────│
│  REQUIRES: scored_prompts where needs_image=True                  │
│  BLOCKS:   output_composer_node                                  │
│  PARALLEL: Gemini calls concurrent (generation_concurrency=3)     │
│  NOTE:     failures do not block; failed items tracked in stats   │
└──────────────────────────┬───────────────────────────────────────┘
                           │ phase=COMPOSING
                           ▼
┌────────────────────┬─────────────────────┬────────────────────────┐
│  output_composer   │    feedback_node   │   (can run sequentially │
│  (HTML/JSON output) │ (update metrics)   │    composer then feedback)│
└────────────────────┴─────────────────────┴────────────────────────┘
                           │
                           ▼ phase=DONE
```

**Fully parallelizable pairs:**
- `output_composer_node` and `feedback_node` run sequentially within COMPOSING
- No cross-node parallelism within a single run (LangGraph handles this)
- Multiple `crawler_node` query tasks use async I/O within the node (not separate nodes)

---

## 8. Type Aliases for Call-site Clarity

```python
# Re-export the main types for cleaner function signatures across modules
from src.agent.state import (
    AgentState,
    QueryCandidate,
    Tweet,
    AuthorRef,
    ExtractedPrompt,
    ScoredPrompt,      # = ExtractedPrompt (semantic alias)
    QualityScores,
    ImageResult,
    QueryMetrics,
    AuthorMetrics,
    CategorySuggestion,
    PipelineStats,
    PipelineError,
    PipelineConfig,
    PipelinePhase,
    RouterDecision,
    NodeStatus,
    ImageGenStatus,
    CategorySuggestionStatus,
)
```

---

## 9. Strict Rules for Contract Compliance

### 9.1 No Type Widening

If a node writes to a field, subsequent nodes can rely on the exact type.
Do NOT change `int` fields to `Optional[int]` unless the semantic genuinely allows absence.

### 9.2 No Field Removal

Once a field is in a contract, it stays with at least a default value.
If truly unused, deprecate with `@property` or a `_deprecated_*` marker.

### 9.3 Node Isolation

A node MUST NOT read fields it doesn't declare in its INPUT contract.
This ensures nodes can be developed and tested in isolation.

### 9.4 State Mutation Only in-place

Nodes return a modified copy or mutate the input state.
No node creates a "partial state" and passes it through a global.
The LangGraph checkpointing mechanism handles state versioning.

### 9.5 Error Collection, Not Propagation

Nodes log errors to `state.node_errors` and return `state` with `node_errors` appended.
The `router_node` decides whether to retry or fail.
Only `ConfigError` (missing/invalid config) is allowed to propagate as a fatal exception.

---

## 10. File Locations

```
16_NewCrawler/
├── src/
│   ├── agent/
│   │   ├── state.py      # AgentState, all dataclasses, enums, type aliases
│   │   ├── nodes.py      # All node function implementations
│   │   ├── graph.py      # build_graph() definition
│   │   └── config.py     # NodeConfig, retry policies, concurrency settings
│   │
│   ├── types/            # Shared Pydantic/dataclass definitions (strict schemas)
│   │   ├── __init__.py
│   │   ├── tweet.py      # Tweet, AuthorRef
│   │   ├── prompt.py     # ExtractedPrompt, QualityScores, ScoredPrompt
│   │   ├── image.py      # ImageResult, ImageGenStatus
│   │   ├── query.py      # QueryCandidate, QueryMetrics
│   │   ├── author.py     # AuthorMetrics
│   │   ├── category.py   # CategorySuggestion
│   │   ├── pipeline.py   # PipelineStats, PipelineError, PipelinePhase, RouterDecision
│   │   └── config.py     # PipelineConfig, QueriesConfig, EngagementConfig, etc.
│   │
│   └── exceptions.py     # All exception class definitions (Section 6)
```