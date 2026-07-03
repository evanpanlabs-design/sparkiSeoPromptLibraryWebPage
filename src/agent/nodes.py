"""Pipeline node implementations.

This module contains all node functions as defined in docs/03_InterfaceContract.md §5.
Each node function follows the signature: def node_name(state: AgentState) -> AgentState

Nodes communicate only through AgentState fields documented in §5.
Error handling: all exceptions caught and converted to PipelineError in state.node_errors.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Optional

from src.agent.state import AgentState
from src.types.prompt import ExtractedPrompt, QualityScores
from src.types.tweet import Tweet, AuthorRef
from src.types.query import QueryCandidate, QueryMetrics
from src.types.category import CategorySuggestion, CategorySuggestionStatus
from src.types.image import ImageResult, ImageGenStatus
from src.types.pipeline import PipelinePhase, RouterDecision, PipelineError
from src.exceptions import LLMError, LLMParseError, ScoringError


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── LLM Client Stub (for development/testing) ─────────────────────────────────
# Real implementation in src.llm.client

class _StubLLMClient:
    """Stub LLM client used when the real client is unavailable."""

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> str:
        """Return a 'not a prompt' classification."""
        return '{"is_prompt": false, "category": null, "title": null, "prompt_text": null, "notes": "stub LLM"}'


def _get_llm_client(config: Any | None = None) -> Any:
    """Create LLM client based on config.llm.provider.

    Args:
        config: Optional LLMConfig from state.config.llm. If None, reads env vars.
    """
    import os

    provider = getattr(config, "provider", "minimax") if config else "minimax"

    try:
        if provider == "gemini":
            from src.llm.gemini_client import GeminiClient
            gemini_project = getattr(config, "gemini_project", "sparki-op") if config else "sparki-op"
            gemini_location = getattr(config, "gemini_location", "global") if config else "global"
            gemini_model = getattr(config, "gemini_default_model", "gemini-3.5-flash") if config else "gemini-3.5-flash"
            return GeminiClient(
                project=gemini_project,
                location=gemini_location,
                default_model=gemini_model,
            )

        # MiniMax / OpenAI-compatible
        from src.llm.client import LLMClient
        api_base = os.environ.get(
            "OPENAI_API_BASE",
            getattr(config, "api_base", "https://api.minimaxi.com/v1") if config else "https://api.minimaxi.com/v1",
        )
        api_key = os.environ.get("OPENAI_API_KEY", "")
        default_model = getattr(config, "default_model", "MiniMax-M2.7") if config else "MiniMax-M2.7"
        if api_key:
            return LLMClient(api_base=api_base, api_key=api_key, default_model=default_model)
    except Exception:
        pass
    return _StubLLMClient()


def _pre_filter_tweets(tweets: list) -> list:
    """Cheap pre-filter to remove tweets unlikely to contain real prompts.

    Saves LLM cost by skipping:
      - Very short tweets (< 80 chars) — real prompts are detailed
      - Complaint/discussion tweets with negative sentiment markers
      - Tweets without any visual-generation keywords
    """
    VISUAL_KEYWORDS = {
        "camera", "lighting", "shot", "scene", "cinematic",
        "film", "lens", "angle", "composition", "motion",
        "slow", "macro", "aerial", "drone", "portrait",
        "render", "generate", "8k", "4k", "photorealistic",
        "depth of field", "golden hour", "studio", "style",
        "prompt:", "prompt：",
    }

    NEGATIVE_MARKERS = {
        "burn through", "its ass", "trash", "garbage",
        "waste", "fuck", "shit", "sucks", "terrible",
    }

    result = []
    for t in tweets:
        text = t.text if hasattr(t, 'text') else t.get('text', '')
        if not text:
            continue

        text_lower = text.lower()

        # Length check
        if len(text) < 80:
            continue

        # Skip complaint tweets
        if any(m in text_lower for m in NEGATIVE_MARKERS):
            continue

        # Must contain at least one visual keyword
        if not any(kw in text_lower for kw in VISUAL_KEYWORDS):
            continue

        result.append(t)
    return result


CRAWL_CACHE_PATH = "outputs/last_crawl.json"


def _save_crawl_cache(tweets_by_query: dict) -> None:
    """Save crawled tweets to JSON so --from-cache can skip re-crawling."""
    import json
    from dataclasses import asdict

    serializable: dict[str, list[dict]] = {}
    for query, tweets in tweets_by_query.items():
        serializable[query] = []
        for t in tweets:
            d = {
                "tweet_id": t.tweet_id,
                "url": t.url,
                "text": t.text,
                "short_text": t.short_text,
                "author": {
                    "name": t.author.name,
                    "screen_name": t.author.screen_name,
                    "profile_url": t.author.profile_url,
                    "followers_count": t.author.followers_count,
                },
                "created_at": t.created_at,
                "favorite_count": t.favorite_count,
                "retweet_count": t.retweet_count,
                "reply_count": t.reply_count,
                "view_count": t.view_count,
                "source_query": t.source_query,
                "scraped_at": t.scraped_at,
                "author_enriched": t.author_enriched,
                "detail_enriched": t.detail_enriched,
            }
            serializable[query].append(d)

    import os
    os.makedirs("outputs", exist_ok=True)
    with open(CRAWL_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    print(f"  [cache] Saved {sum(len(v) for v in serializable.values())} tweets to {CRAWL_CACHE_PATH}")


def _load_crawl_cache() -> dict[str, list] | None:
    """Load cached tweets if available. Returns None if no cache."""
    import json
    import os

    if not os.path.exists(CRAWL_CACHE_PATH):
        return None

    with open(CRAWL_CACHE_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    from src.types.tweet import Tweet, AuthorRef

    result: dict[str, list] = {}
    for query, tweet_dicts in raw.items():
        tweets = []
        for d in tweet_dicts:
            author = AuthorRef(
                name=d["author"]["name"],
                screen_name=d["author"]["screen_name"],
                profile_url=d["author"]["profile_url"],
                followers_count=d["author"].get("followers_count", 0),
            )
            tweets.append(Tweet(
                tweet_id=d["tweet_id"],
                url=d["url"],
                text=d["text"],
                short_text=d.get("short_text", ""),
                author=author,
                created_at=d.get("created_at", ""),
                favorite_count=d.get("favorite_count", 0),
                retweet_count=d.get("retweet_count", 0),
                reply_count=d.get("reply_count", 0),
                view_count=d.get("view_count", 0),
                source_query=d.get("source_query", query),
                scraped_at=d.get("scraped_at", ""),
                author_enriched=d.get("author_enriched", False),
                detail_enriched=d.get("detail_enriched", False),
            ))
        result[query] = tweets
    return result


# ─── Node Implementations ───────────────────────────────────────────────────────

def worker_node(state: AgentState) -> AgentState:
    """
    CONTRACT (§5.5):
      INPUT:  state.tweets_by_query, state.config.llm, state.config.crawler (negative_keywords)
      OUTPUT: state.extracted_prompts (list[ExtractedPrompt]),
              state.pending_category_suggestions,
              state.stats.prompts_extracted,
              state.phase = SCORING (or WAITING_HUMAN if pending suggestions)
              + if pending_category_suggestions non-empty:
                  state.waiting_for_human = True
                  state.router_decision = RouterDecision.WAIT_HUMAN
      BLOCKS: quality_scorer_node
      PARALLEL: LLM calls concurrent (extraction_concurrency)

    Error handling: LLM errors are collected in state.node_errors (not raised).
    """
    print(f"[worker_node] ENTER — phase={state.phase}, tweets_by_query entries={len(state.tweets_by_query)}")
    try:
        from src.worker.extractor import PromptExtractor, build_extracted_prompt

        llm_client = _get_llm_client(state.config.llm)
        concurrency = state.config.llm.extraction_concurrency

        # Collect all tweets from all queries
        all_tweets = []
        for query, tweets in state.tweets_by_query.items():
            all_tweets.extend(tweets)

        # Pre-filter: skip tweets unlikely to contain real prompts
        pre_filtered = _pre_filter_tweets(all_tweets)
        print(f"  Pre-filter: {len(all_tweets)} -> {len(pre_filtered)} tweets")
        all_tweets = pre_filtered

        if not all_tweets:
            state.router_decision = RouterDecision.CONTINUE
            return state

        # Get known categories (would come from DB/memory in real impl)
        known_categories = _get_known_categories()

        # Run extraction
        extractor = PromptExtractor(
            llm_client=llm_client,
            categories=list(known_categories),
            default_model=state.config.llm.default_model,
        )

        results = extractor.extract_batch(all_tweets, concurrency=concurrency)

        # Build ExtractedPrompts and collect category suggestions
        extracted: list[ExtractedPrompt] = []
        suggestions: list[CategorySuggestion] = []

        for tweet, result in zip(all_tweets, results):
            if result.is_prompt:
                prompt, new_suggestions = build_extracted_prompt(tweet, result, known_categories)
                extracted.append(prompt)
                suggestions.extend(new_suggestions)

        state.extracted_prompts = extracted
        state.pending_category_suggestions = suggestions
        state.stats.prompts_extracted = len(extracted)

        if suggestions:
            state.waiting_for_human = True
            state.router_decision = RouterDecision.WAIT_HUMAN
        else:
            state.router_decision = RouterDecision.CONTINUE

    except Exception as e:
        error = PipelineError(
            phase=state.phase,
            node="worker_node",
            error_type=type(e).__name__,
            error_message=str(e),
            timestamp=_utc_now(),
        )
        state.node_errors.append(error)
        state.router_decision = RouterDecision.CONTINUE

    print(f"[worker_node] EXIT — phase={state.phase}, extracted_prompts={len(state.extracted_prompts)}")
    return state


def quality_scorer_node(state: AgentState) -> AgentState:
    print(f"[quality_scorer_node] ENTER — phase={state.phase}, extracted_prompts={len(state.extracted_prompts)}")
    """
    CONTRACT (§5.7):
      INPUT:  state.extracted_prompts, state.config.quality, state.config.llm
      OUTPUT: state.scored_prompts (same list reference, quality_scores populated in-place),
              state.extracted_prompts[i].needs_image = scores.should_generate_image(),
              state.stats.prompts_scored,
              state.phase = IMAGING
      BLOCKS: image_gen_node
      PARALLEL: LLM scoring calls concurrent (scoring_concurrency)

    Scoring is done in-place — quality_scores field is populated on each ExtractedPrompt.
    Every prompt gets scored (no skipping).
    needs_image = False ONLY when overall < quality.thresholds.min_overall.
    """
    try:
        from src.worker.scorer import QualityScorer

        if not state.extracted_prompts:
            state.scored_prompts = []
            state.stats.prompts_scored = 0
            state.phase = PipelinePhase.IMAGING
            return state

        llm_client = _get_llm_client(state.config.llm)
        scorer = QualityScorer(
            llm_client=llm_client,
            quality_config=state.config.quality,
            default_model=state.config.llm.default_model,
        )
        concurrency = state.config.llm.scoring_concurrency

        # Score all prompts concurrently
        def score_one(prompt: ExtractedPrompt) -> ExtractedPrompt:
            prompt.quality_scores = scorer.score(prompt)
            prompt.needs_image = scorer.should_generate_image(prompt.quality_scores)
            return prompt

        scored = []
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            futures = {ex.submit(score_one, p): p for p in state.extracted_prompts}
            for fut in as_completed(futures):
                try:
                    scored.append(fut.result())
                except Exception:
                    # Fallback: mark with zero scores
                    p = futures[fut]
                    p.quality_scores = QualityScores(
                        specificity=0.0, visual_detail=0.0,
                        novelty=0.0, generatable=0.0, overall=0.0,
                    )
                    p.needs_image = False
                    scored.append(p)

        state.scored_prompts = state.extracted_prompts  # Same list reference
        state.stats.prompts_scored = len(scored)
        state.phase = PipelinePhase.IMAGING

    except Exception as e:
        error = PipelineError(
            phase=state.phase,
            node="quality_scorer_node",
            error_type=type(e).__name__,
            error_message=str(e),
            timestamp=_utc_now(),
        )
        state.node_errors.append(error)
        # Fallback: mark all as not needing images
        for p in state.extracted_prompts:
            p.quality_scores = QualityScores(
                specificity=0.0, visual_detail=0.0,
                novelty=0.0, generatable=0.0, overall=0.0,
            )
            p.needs_image = False
        state.scored_prompts = state.extracted_prompts
        state.stats.prompts_scored = len(state.extracted_prompts)
        state.phase = PipelinePhase.IMAGING

    return state


def initialize_node(state: AgentState) -> AgentState:
    """
    CONTRACT (§5.2):
      INPUT:  state.config loaded from YAML files
      OUTPUT: state.run_id (uuid), state.scrape_id (from DB insert),
              state.phase = QUERY_PLANNING
      SIDE EFFECTS:
        - Inserts row into scrape_runs table
        - Loads existing query_metrics from DB into state.query_metrics
        - Loads existing author_metrics from DB into state.author_metrics
    """
    import uuid as uuid_lib

    if not state.run_id:
        state.run_id = str(uuid_lib.uuid4())

    try:
        from src.memory.schema import insert_scrape_run, load_query_metrics, load_author_metrics

        # Insert new scrape_runs row
        state.scrape_id = insert_scrape_run(
            run_id=state.run_id,
            queries=[qc.text for qc in state.query_candidates] if state.query_candidates else [],
            phase=state.phase.value,
        )

        # Load historical metrics from DB
        state.query_metrics = load_query_metrics()
        state.author_metrics = load_author_metrics()

    except Exception as e:
        # If DB is not available, continue with empty metrics
        from src.types.query import QueryMetrics
        from src.types.author import AuthorMetrics

        if not state.query_metrics:
            state.query_metrics = {}
        if not state.author_metrics:
            state.author_metrics = {}

        # Still set a scrape_id (it will be None/invalid but allows continuation)
        if state.scrape_id == 0:
            state.scrape_id = 1  # Placeholder

    state.phase = PipelinePhase.QUERY_PLANNING
    state.stats.phase_started_at = _utc_now()

    return state


def _get_known_categories() -> set[str]:
    """Get known category names from DB. Returns default set for stub."""
    try:
        from src.memory.categories import get_categories
        cats = get_categories()
        return {c["name"] for c in cats}
    except Exception:
        return {"video-generation", "cinematic", "product-photography",
                "character-design", "image-generation", "other"}


def query_planner_node(state: AgentState) -> AgentState:
    """
    CONTRACT (§5.3):
      INPUT:  state.config.queries, state.query_metrics (historical)
      OUTPUT: state.query_candidates: list[QueryCandidate]
                - Seed queries from queries.yaml (source="seed")
                - LLM-expanded queries from top-performing historical queries (source="expansion")
                - Sorted by priority descending
              state.phase = CRAWLING
    """
    candidates: list[QueryCandidate] = []
    cfg = state.config.queries
    expansion_cfg = cfg.expansion

    # Seed queries from config
    for query_text in cfg.seed_queries:
        candidate = QueryCandidate(
            text=query_text,
            source="seed",
            scroll_budget=20,
            priority=1.0,
            negative_keywords=cfg.negative_keywords,
        )
        candidates.append(candidate)

    # LLM-expanded queries from top-performing historical queries
    if state.query_metrics:
        sorted_metrics = sorted(
            state.query_metrics.items(),
            key=lambda x: x[1].qualified_rate if x[1].qualified_rate else 0.0,
            reverse=True,
        )[:expansion_cfg.top_n_queries]

        for query_text, metrics in sorted_metrics:
            if metrics.qualified_rate >= expansion_cfg.min_yield_threshold:
                candidate = QueryCandidate(
                    text=query_text,
                    source="expansion",
                    scroll_budget=metrics.scroll_budget_hint,
                    priority=0.8,
                    negative_keywords=cfg.negative_keywords,
                )
                candidates.append(candidate)

    # Sort by priority descending
    candidates.sort(key=lambda x: x.priority, reverse=True)

    state.query_candidates = candidates
    state.phase = PipelinePhase.CRAWLING
    state.stats.phase_started_at = _utc_now()

    return state

def crawler_node(state: AgentState) -> AgentState:
    """
    CONTRACT (§5.4):
      INPUT:  state.query_candidates (ordered by priority),
              state.config.crawler, state.config.engagement
      OUTPUT: state.tweets_by_query: dict[str, list[Tweet]]
                - Key = query text, Value = list of enriched Tweet objects
                - Deduplication: tweet_id checked against all_tweet_ids before appending
              state.all_tweet_ids: merged set of all tweet_ids seen
              state.query_metrics[query].tweets_raw/filtered updated
              state.phase = PipelinePhase.EXTRACTING
      BLOCKS: worker_node

    All tweets pass engagement filters (min_likes, min_followers, min_views).
    Tweet.author is ALWAYS populated after enrichment.
    For each query, at least an empty list is written to tweets_by_query.
    """
    # If --from-cache, load saved tweets and skip crawling
    if state.from_cache:
        cached = _load_crawl_cache()
        if cached:
            all_tweet_ids: set[str] = set()
            for tweets in cached.values():
                for t in tweets:
                    all_tweet_ids.add(t.tweet_id)
            state.tweets_by_query = cached
            state.all_tweet_ids = all_tweet_ids
            state.stats.tweets_collected = sum(len(v) for v in cached.values())
            state.stats.tweets_deduped = len(all_tweet_ids)
            state.phase = PipelinePhase.EXTRACTING
            print(f"[crawler_node] Loaded {state.stats.tweets_collected} tweets from cache, skipping crawl")
            return state
        else:
            print("[crawler_node] --from-cache set but no cache found, crawling normally")

    try:
        import asyncio
        from pathlib import Path

        from src.crawler import BrowserManager, scroll_and_extract, enrich_tweet
        from src.types.tweet import Tweet, AuthorRef
        from src.types.query import QueryMetrics

        cfg = state.config.crawler
        eng = state.config.engagement
        cookies_path = Path("outputs/cookies.json")

        def _run_crawl_for_query(qc) -> tuple[str, list[Tweet], int, int, str | None]:
            """Sync wrapper that runs the async crawl for one query."""
            return asyncio.run(_crawl_query(
                query=qc.text,
                scroll_budget=qc.scroll_budget,
                max_scrolls=cfg.max_scrolls,
                stale_threshold=cfg.stale_threshold,
                delay_ms=(cfg.delay_ms_min, cfg.delay_ms_max),
                page_goto_timeout_ms=cfg.page_goto_timeout_ms,
                selector_wait_ms=cfg.selector_wait_ms,
                scroll_wait_ms=cfg.scroll_wait_ms,
                proxy=cfg.proxy_server if cfg.proxy_enabled else None,
                cookies_path=cookies_path,
                min_likes=eng.min_likes,
                min_followers=eng.min_followers,
                min_views=eng.min_views,
                headed=state.headed,
                crawler_type=cfg.type,
                apify_actor_id=cfg.apify_actor_id,
                apify_api_token=os.environ.get(cfg.apify_api_token_env, ""),
                apify_timeout_ms=cfg.apify_timeout_ms,
                apify_max_retries=cfg.apify_max_retries,
                apify_max_cost_usd=cfg.apify_max_cost_usd,
            ))

        tweets_by_query: dict[str, list[Tweet]] = {}
        all_tweet_ids: set[str] = set()
        query_metrics: dict[str, QueryMetrics] = dict(state.query_metrics)

        for qc in state.query_candidates:
            query_key = qc.text
            print(f"\nCrawling query: '{query_key}'")

            try:
                raw_tweets, filtered_count, error_msg = _run_crawl_for_query(qc)
                if error_msg:
                    print(f"  ERROR: {error_msg}")
            except Exception as e:
                error_msg = str(e)
                raw_tweets = []
                filtered_count = 0
                print(f"  EXCEPTION: {error_msg}")

            qualified_tweets: list[Tweet] = []
            for t_dict in raw_tweets:
                tid = t_dict["tweet_id"]
                if tid not in all_tweet_ids:
                    all_tweet_ids.add(tid)
                    author_dict = t_dict["author"]
                    author = AuthorRef(
                        name=author_dict.get("name", ""),
                        screen_name=author_dict.get("screen_name", ""),
                        profile_url=author_dict.get("profile_url", ""),
                        followers_count=author_dict.get("followers_count", 0),
                    )
                    tweet = Tweet(
                        tweet_id=tid,
                        url=t_dict["url"],
                        text=t_dict["text"],
                        short_text=t_dict["short_text"],
                        author=author,
                        created_at=t_dict.get("created_at"),
                        favorite_count=t_dict.get("favorite_count", 0),
                        retweet_count=t_dict.get("retweet_count", 0),
                        reply_count=t_dict.get("reply_count", 0),
                        view_count=t_dict.get("view_count", 0),
                        source_query=query_key,
                        scraped_at=t_dict.get("scraped_at", ""),
                        author_enriched=t_dict.get("author_enriched", False),
                        detail_enriched=t_dict.get("detail_enriched", False),
                    )
                    qualified_tweets.append(tweet)

            tweets_by_query[query_key] = qualified_tweets

            if query_key in query_metrics:
                qm = query_metrics[query_key]
                qm.tweets_raw = len(raw_tweets) + (qm.tweets_raw - qm.tweets_filtered)
                qm.tweets_filtered = len(qualified_tweets)
            else:
                qm = QueryMetrics(
                    query_text=query_key,
                    scrape_run_id=state.scrape_id,
                    tweets_raw=len(raw_tweets),
                    tweets_filtered=len(qualified_tweets),
                )
            query_metrics[query_key] = qm
            print(f"  → {len(raw_tweets)} raw, {len(qualified_tweets)} qualified for '{query_key}'")

            # Delay between queries to avoid X.com rate limiting
            if qc != state.query_candidates[-1]:
                delay = random.uniform(5, 10)
                print(f"  Waiting {delay:.1f}s before next query...")
                time.sleep(delay)

        state.tweets_by_query = tweets_by_query
        state.all_tweet_ids = all_tweet_ids
        state.query_metrics = query_metrics
        state.stats.tweets_collected = sum(len(v) for v in tweets_by_query.values())
        state.stats.tweets_deduped = len(all_tweet_ids)
        state.phase = PipelinePhase.EXTRACTING

        # Persist crawled tweets so --from-cache can skip re-crawling
        _save_crawl_cache(tweets_by_query)

    except Exception as e:
        error = PipelineError(
            phase=state.phase,
            node="crawler_node",
            error_type=type(e).__name__,
            error_message=str(e),
            timestamp=_utc_now(),
        )
        state.node_errors.append(error)
        for qc in state.query_candidates:
            if qc.text not in state.tweets_by_query:
                state.tweets_by_query[qc.text] = []
        state.phase = PipelinePhase.EXTRACTING

    return state


async def _crawl_query(
    query: str,
    scroll_budget: int,
    max_scrolls: int,
    stale_threshold: int,
    delay_ms: tuple[int, int],
    page_goto_timeout_ms: int,
    selector_wait_ms: int,
    scroll_wait_ms: int,
    proxy: str | None,
    cookies_path: Path,
    min_likes: int,
    min_followers: int,
    min_views: int,
    headed: bool = False,
    crawler_type: str = "browser",
    apify_actor_id: str = "nfp1fpt5gUlBwPcor",
    apify_api_token: str = "",
    apify_timeout_ms: int = 120_000,
    apify_max_retries: int = 2,
    apify_max_cost_usd: float = 1.0,
) -> tuple[list[dict], int, str | None]:
    """Async inner crawl for one query. Returns (raw_tweets, filtered_count, error_msg).

    When crawler_type == "apify", delegates to ApifyCrawler instead of Playwright.
    """
    import os
    error_msg = None
    try:
        if crawler_type == "apify":
            from src.crawler.apify import ApifyCrawler
            token = apify_api_token or os.environ.get("APIFY_API_TOKEN", "")
            crawler = ApifyCrawler(
                actor_id=apify_actor_id,
                api_token=token,
                timeout_ms=apify_timeout_ms,
                max_retries=apify_max_retries,
            )
            tweets = await crawler.crawl(query, max_cost_usd=apify_max_cost_usd)
            return tweets, len(tweets), None

        # --- Playwright / BrowserManager path ---
        from src.crawler import BrowserManager, scroll_and_extract, enrich_tweet  # imported here because _crawl_query is module-level
        async with BrowserManager(
            cookies_path=cookies_path,
            proxy=proxy,
            headless=not headed,
        ) as browser_mgr:
            context = await browser_mgr.new_context()

            if not await browser_mgr.verify_session(context):
                return [], 0, "Session verification failed — cookies may be invalid"

            page = await context.new_page()
            tabs = ["Top", "Latest"]
            search_loaded = False

            for tab in tabs:
                search_url = f"https://x.com/search?q={query}&src=typed_query"
                print(f"  Navigating to search ({tab} tab)...")
                try:
                    await page.goto(search_url, timeout=page_goto_timeout_ms)
                    # Wait for tweet elements to appear in DOM (poll until found or timeout)
                    deadline = asyncio.get_event_loop().time() + (selector_wait_ms / 1000.0)
                    while asyncio.get_event_loop().time() < deadline:
                        tweets = await page.query_selector_all('[data-testid="tweet"]')
                        if tweets:
                            print(f"  {tab} tab loaded — {len(tweets)} tweets visible.")
                            search_loaded = True
                            break
                        await page.wait_for_timeout(0.5)
                    if search_loaded:
                        break
                except Exception as e:
                    print(f"  {tab} tab failed: {e}")
                    try:
                        other = "Latest" if tab == "Top" else "Top"
                        await page.locator(f"span:has-text('{other}')").first.click()
                        # Poll for tweets instead of blocking wait
                        deadline = asyncio.get_event_loop().time() + (selector_wait_ms / 1000.0)
                        while asyncio.get_event_loop().time() < deadline:
                            tweets = await page.query_selector_all('[data-testid="tweet"]')
                            if tweets:
                                print(f"  Switched to {other} tab — {len(tweets)} tweets visible.")
                                search_loaded = True
                                break
                            await page.wait_for_timeout(0.5)
                    except Exception:
                        continue

            if not search_loaded:
                return [], 0, "Could not load search page (tried Top and Latest)"

            print(f"  Scrolling and extracting (up to {scroll_budget} scrolls, auto-stop on stale)...")
            all_tweets = await scroll_and_extract(
                page,
                max_scrolls=scroll_budget,
                stale_threshold=stale_threshold,
                delay_ms=delay_ms,
            )
            print(f"  Total extracted (after dedup): {len(all_tweets)}")

            if not all_tweets:
                return [], 0, None

            print(f"  Round-1 filter: likes >= {min_likes}")
            r1 = [t for t in all_tweets if t["favorite_count"] >= min_likes]
            print(f"  Passed round-1: {len(r1)}")

            if not r1:
                return [], 0, None

            print(f"  Enriching {len(r1)} tweets...")
            keywords = query.split()
            final_tweets = []

            for i, t in enumerate(r1):
                screen = t["author_screen"]
                print(f"    [{i+1}/{len(r1)}] @{screen} ({t['tweet_id']})...", end=" ", flush=True)

                enriched = await enrich_tweet(
                    context,
                    t,
                    min_followers=min_followers,
                    min_views=min_views,
                    delay_ms=delay_ms,
                )

                if enriched is None:
                    continue

                from src.crawler.extraction import TweetExtractor
                if not TweetExtractor.text_matches_all_keywords(enriched["text"], keywords):
                    print("FILTERED (keywords)")
                    continue

                final_tweets.append(enriched)

            return final_tweets, len(final_tweets), None

    except Exception as e:
        return [], 0, str(e)

def router_node(state: AgentState) -> AgentState:
    """
    CONTRACT (§5.6):
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

      NOTE: This is the ONLY node that writes to state.phase
            WAITING_HUMAN phase requires external handler to call graph
            again with router_decision=CONTINUE after human resolves suggestions.
    """
    print(f"[router_node] ENTER — phase={state.phase}, router_decision={state.router_decision}, pending_sugs={len(state.pending_category_suggestions)}")
    decision = state.router_decision

    if decision is None:
        # Default to CONTINUE if no explicit decision
        decision = RouterDecision.CONTINUE

    if decision == RouterDecision.WAIT_HUMAN:
        state.phase = PipelinePhase.WAITING_HUMAN
        state.waiting_for_human = True
    elif decision == RouterDecision.CONTINUE:
        # Continue to next phase based on current phase
        current = state.phase
        if current == PipelinePhase.INITIALIZING:
            state.phase = PipelinePhase.QUERY_PLANNING
        elif current == PipelinePhase.QUERY_PLANNING:
            state.phase = PipelinePhase.CRAWLING
        elif current == PipelinePhase.CRAWLING:
            state.phase = PipelinePhase.EXTRACTING
        elif current == PipelinePhase.EXTRACTING:
            state.phase = PipelinePhase.SCORING
        elif current == PipelinePhase.WAITING_HUMAN:
            state.phase = PipelinePhase.SCORING  # Human resolved, continue
        elif current == PipelinePhase.SCORING:
            state.phase = PipelinePhase.IMAGING
        elif current == PipelinePhase.IMAGING:
            state.phase = PipelinePhase.COMPOSING
        # For COMPOSING, keep it - output_composer and feedback handle the flow
    elif decision == RouterDecision.EARLY_DONE:
        state.phase = PipelinePhase.DONE
    elif decision == RouterDecision.ERROR:
        state.phase = PipelinePhase.FAILED
    elif decision == RouterDecision.RETRY:
        # Stay in current phase for retry (handled by error_recovery_node)
        pass
    elif decision == RouterDecision.SKIP:
        # Skip current item, continue to next phase
        pass

    # Consume the decision after handling
    state.router_decision = None
    state.stats.phase_started_at = _utc_now()
    print(f"[router_node] EXIT — phase={state.phase}, will route to next node")

    return state

def image_gen_node(state: AgentState) -> AgentState:
    print(f"[image_gen_node] ENTER — phase={state.phase}, scored_prompts={len(state.scored_prompts)}")
    """Generate cover images for qualified prompts via Gemini with multi-model fallback.

    CONTRACT (§5.8):
      INPUT:  state.scored_prompts where ExtractedPrompt.needs_image == True
      OUTPUT: state.image_results: list[ImageResult]
              state.stats.images_generated, state.stats.images_failed updated
              state.phase = PipelinePhase.COMPOSING
      PARALLEL: Gemini calls concurrent (config.gemini.generation_concurrency)
      CONTRACT: multi-model fallback tries all models; failures never raise, only status FAILED
    """
    from src.image_gen.client import GeminiImageClient

    gemini_cfg = state.config.gemini

    try:
        client = GeminiImageClient(
            project=gemini_cfg.project,
            location=gemini_cfg.location,
            gcs_bucket=gemini_cfg.gcs_bucket,
            max_retries_per_model=gemini_cfg.max_retries_per_model,
            retry_delay_base=gemini_cfg.retry_delay_base,
            models=gemini_cfg.image_models,
        )
    except Exception as e:
        # If client init fails, mark all as failed and move on
        for p in state.scored_prompts:
            if getattr(p, "needs_image", True):
                p.image_status = ImageGenStatus.FAILED
        state.stats.images_failed = sum(
            1 for p in state.scored_prompts if getattr(p, "needs_image", True)
        )
        state.phase = PipelinePhase.COMPOSING
        return state

    items_to_generate = [
        {
            "tweet_id": p.tweet_id,
            "prompt_text": p.prompt_text,
            "category": p.category,
            "title": p.title,
        }
        for p in state.scored_prompts
        if getattr(p, "needs_image", True)
    ]

    needs_image_false = [
        p for p in state.scored_prompts if not getattr(p, "needs_image", True)
    ]
    for p in needs_image_false:
        p.image_status = ImageGenStatus.SKIPPED

    if not items_to_generate:
        state.phase = PipelinePhase.COMPOSING
        return state

    concurrency = gemini_cfg.generation_concurrency

    try:
        batch_results = client.generate_batch(items_to_generate, concurrency=concurrency)
    except Exception as e:
        # All failed — propagate as error but don't raise
        for item in items_to_generate:
            state.image_results.append(ImageResult(
                prompt_id=0,
                tweet_id=item["tweet_id"],
                status=ImageGenStatus.FAILED,
                model_used=None,
                gcs_url=None,
                error_message=str(e),
                generated_at=_utc_now(),
                category_path=None,
            ))
        state.stats.images_failed = len(items_to_generate)
        state.phase = PipelinePhase.COMPOSING
        return state

    now_str = _utc_now()
    generated = 0
    failed = 0

    for result in batch_results:
        tweet_id = result["tweet_id"]
        error = result.get("error")

        if error is None:
            status = ImageGenStatus.COMPLETED
            generated += 1
        else:
            status = ImageGenStatus.FAILED
            failed += 1

        image_result = ImageResult(
            prompt_id=0,
            tweet_id=tweet_id,
            status=status,
            model_used=result.get("model_used"),
            gcs_url=result.get("gcs_url"),
            local_path=None,
            error_message=error,
            generated_at=now_str,
            category_path=None,
        )
        state.image_results.append(image_result)

        # Map result back to scored_prompts via tweet_id
        for p in state.scored_prompts:
            if p.tweet_id == tweet_id:
                p.image_status = status
                p.image_gcs_url = result.get("gcs_url")
                break

    state.stats.images_generated += generated
    state.stats.images_failed += failed
    state.phase = PipelinePhase.COMPOSING
    return state

def feedback_node(state: AgentState) -> AgentState:
    """
    CONTRACT (§5.9):
      INPUT:  state.tweets_by_query, state.scored_prompts,
              state.image_results, state.query_metrics, state.author_metrics
      OUTPUT: For each query in tweets_by_query:
                - Update query_metrics in DB: tweets_raw, tweets_filtered, prompts_extracted, qualified
                - Recalculate qualified_rate, prompt_yield_rate
                - Set scroll_budget_hint
              For each author in scored_prompts:
                - Update author_metrics in DB: total_prompts, qualified_prompts
                - Recalculate high_value_ratio
              state.stats.total_cost_usd (llm + image gen estimates)
              state.phase = DONE

      NOTE: scroll_budget_hint: 5 if qualified_rate < 0.05, 30 if qualified_rate > 0.25, else 20
    """
    from src.types.author import AuthorMetrics

    # Update query_metrics with final stats
    for query_text, metrics in state.query_metrics.items():
        tweets_filtered = metrics.tweets_filtered
        if tweets_filtered > 0:
            metrics.qualified_rate = metrics.qualified_prompts / tweets_filtered
            metrics.prompt_yield_rate = metrics.prompts_extracted / tweets_filtered
        else:
            metrics.qualified_rate = 0.0
            metrics.prompt_yield_rate = 0.0

        # Set scroll_budget_hint based on qualified_rate
        if metrics.qualified_rate < 0.05:
            metrics.scroll_budget_hint = 5
        elif metrics.qualified_rate > 0.25:
            metrics.scroll_budget_hint = 30
        else:
            metrics.scroll_budget_hint = 20

        metrics.last_run_at = _utc_now()
        metrics.run_count += 1

    # Update author_metrics
    author_counts: dict[str, dict] = {}
    for prompt in state.scored_prompts:
        if not prompt.author:
            continue
        screen_name = prompt.author.screen_name
        if screen_name not in author_counts:
            author_counts[screen_name] = {"total": 0, "qualified": 0}
        author_counts[screen_name]["total"] += 1
        if prompt.quality_scores and prompt.quality_scores.overall >= state.config.quality.thresholds.min_overall:
            author_counts[screen_name]["qualified"] += 1

    for screen_name, counts in author_counts.items():
        if screen_name not in state.author_metrics:
            state.author_metrics[screen_name] = AuthorMetrics(
                screen_name=screen_name,
                display_name="",
                profile_url=f"https://x.com/{screen_name}",
            )
        am = state.author_metrics[screen_name]
        am.total_prompts = counts["total"]
        am.qualified_prompts = counts["qualified"]
        if am.total_prompts > 0:
            am.high_value_ratio = am.qualified_prompts / am.total_prompts
        am.is_high_value = am.high_value_ratio > 0.5 and am.total_prompts >= 3
        am.last_active_at = _utc_now()

    # Try to persist to DB
    try:
        from src.memory.schema import update_query_metrics, update_author_metrics
        for query_text, metrics in state.query_metrics.items():
            update_query_metrics(metrics)
        for screen_name, metrics in state.author_metrics.items():
            update_author_metrics(metrics)
    except Exception:
        pass  # Continue even if DB write fails

    # Estimate costs (placeholder values)
    state.stats.estimated_llm_cost_usd = (
        state.stats.prompts_extracted * 0.01 +
        state.stats.prompts_scored * 0.005 +
        state.stats.tweets_collected * 0.001
    )
    state.stats.estimated_image_gen_cost_usd = (
        state.stats.images_generated * 0.05 +
        state.stats.images_failed * 0.01
    )

    state.phase = PipelinePhase.DONE
    state.stats.phase_started_at = _utc_now()

    return state

def output_composer_node(state: AgentState) -> AgentState:
    """
    CONTRACT (§5.10):
      INPUT:  state.scored_prompts (with quality_scores and image_gcs_url populated)
      OUTPUT: Writes files:
                - outputs/veo3-prompt-library.html (gallery, card grid)
                - outputs/prompts.json (full prompt objects)
                - Optionally: uploads HTML to GCS for CDN
              Returns state with phase = COMPOSING (feedback_node runs after)

      NOTE: HTML includes ALL scored_prompts regardless of image generation status.
            Prompts without images show a placeholder card.
            HTML template uses category-based color coding.
    """
    import os
    import json

    os.makedirs("outputs", exist_ok=True)

    prompts = state.scored_prompts

    # Build HTML gallery
    html_parts = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='UTF-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>",
        "<title>Veo 3 Prompt Library</title>",
        "<style>",
        "body { font-family: system-ui, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; }",
        "h1 { text-align: center; }",
        ".grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; }",
        ".card { border: 1px solid #ddd; border-radius: 8px; padding: 16px; background: #fff; }",
        ".card.video-generation { border-left: 4px solid #e63946; }",
        ".card.cinematic { border-left: 4px solid #457b9d; }",
        ".card.product-photography { border-left: 4px solid #2a9d8f; }",
        ".card.character-design { border-left: 4px solid #9b5de5; }",
        ".card.image-generation { border-left: 4px solid #f4a261; }",
        ".card.other { border-left: 4px solid #aaa; }",
        ".title { font-weight: bold; font-size: 16px; margin-bottom: 8px; }",
        ".category { display: inline-block; padding: 2px 8px; border-radius: 4px; background: #eee; font-size: 12px; margin-bottom: 8px; }",
        ".prompt-text { background: #f8f8f8; padding: 12px; border-radius: 4px; font-size: 14px; white-space: pre-wrap; margin-bottom: 12px; }",
        ".image-placeholder { width: 100%; height: 200px; background: #eee; border-radius: 4px; display: flex; align-items: center; justify-content: center; color: #888; }",
        ".image-placeholder img { max-width: 100%; max-height: 200px; object-fit: cover; border-radius: 4px; }",
        ".meta { font-size: 12px; color: #666; }",
        ".score { font-size: 12px; color: #333; margin-top: 8px; }",
        "</style>",
        "</head>",
        "<body>",
        "<h1>Veo 3 Prompt Library</h1>",
        f"<p>Total prompts: {len(prompts)}</p>",
        "<div class='grid'>",
    ]

    for prompt in prompts:
        category_class = prompt.category.replace("_", "-") if prompt.category else "other"
        title = prompt.title if prompt.title else "Untitled"
        cat = prompt.category if prompt.category else "other"
        prompt_text = prompt.prompt_text[:500] + ("..." if len(prompt.prompt_text) > 500 else "")
        author_handle = f"@{prompt.author.screen_name}" if prompt.author else ""
        score = f"{prompt.quality_scores.overall:.2f}" if prompt.quality_scores else "N/A"

        # Image placeholder or actual image
        gcs_url = getattr(prompt, "image_gcs_url", None) or getattr(prompt, "gcs_url", None)
        if gcs_url:
            image_html = f"<img src='{gcs_url}' alt='Generated image' />"
        else:
            image_html = "<div class='image-placeholder'>No image generated</div>"

        html_parts.append(f"<div class='card {category_class}'>")
        html_parts.append(f"<div class='title'>{title}</div>")
        html_parts.append(f"<div class='category'>{cat}</div>")
        html_parts.append(f"<div class='prompt-text'>{prompt_text}</div>")
        html_parts.append(image_html)
        html_parts.append(f"<div class='meta'>Author: {author_handle}</div>")
        html_parts.append(f"<div class='score'>Quality: {score}</div>")
        html_parts.append("</div>")

    html_parts.extend(["</div>", "</body>", "</html>"])

    html_content = "\n".join(html_parts)
    html_path = os.path.join("outputs", "veo3-prompt-library.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    # Build JSON export
    prompts_json = []
    for prompt in prompts:
        gcs_url = getattr(prompt, "image_gcs_url", None) or getattr(prompt, "gcs_url", None)
        prompt_dict = {
            "tweet_id": prompt.tweet_id,
            "url": prompt.url,
            "category": prompt.category,
            "title": prompt.title,
            "prompt_text": prompt.prompt_text,
            "notes": prompt.notes,
            "author": {
                "name": prompt.author.name if prompt.author else "",
                "screen_name": prompt.author.screen_name if prompt.author else "",
                "profile_url": prompt.author.profile_url if prompt.author else "",
                "followers_count": prompt.author.followers_count if prompt.author else 0,
            },
            "likes_count": prompt.likes_count,
            "retweet_count": prompt.retweet_count,
            "reply_count": prompt.reply_count,
            "view_count": prompt.view_count,
            "quality_scores": {
                "specificity": prompt.quality_scores.specificity if prompt.quality_scores else None,
                "visual_detail": prompt.quality_scores.visual_detail if prompt.quality_scores else None,
                "novelty": prompt.quality_scores.novelty if prompt.quality_scores else None,
                "generatable": prompt.quality_scores.generatable if prompt.quality_scores else None,
                "overall": prompt.quality_scores.overall if prompt.quality_scores else None,
            } if prompt.quality_scores else None,
            "image_gcs_url": gcs_url,
            "extracted_at": prompt.extracted_at,
            "needs_image": prompt.needs_image,
            "image_status": prompt.image_status.value if hasattr(prompt.image_status, "value") else str(prompt.image_status),
        }
        prompts_json.append(prompt_dict)

    json_path = os.path.join("outputs", "prompts.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(prompts_json, f, indent=2, ensure_ascii=False)

    state.stats.phase_started_at = _utc_now()

    return state

def error_recovery_node(state: AgentState) -> AgentState:
    raise NotImplementedError("error_recovery_node not yet implemented")