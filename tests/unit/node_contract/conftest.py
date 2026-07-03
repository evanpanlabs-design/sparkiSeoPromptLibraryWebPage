"""
Shared fixtures for node contract tests.

Each fixture builds a minimal AgentState that satisfies the type signatures
in src/agent/state.py / docs/03_InterfaceContract.md.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from src.agent.state import (
    AgentState,
    PipelinePhase,
    PipelineConfig,
    PipelineStats,
    QueryCandidate,
    Tweet,
    AuthorRef,
    ExtractedPrompt,
    ScoredPrompt,
    ImageResult,
    ImageGenStatus,
    QualityScores,
    QueryMetrics,
    AuthorMetrics,
    CategorySuggestion,
    CategorySuggestionStatus,
    PipelineError,
    RouterDecision,
    PipelineConfig,
    QueriesConfig,
    ExpansionConfig,
    EngagementConfig,
    CrawlerConfig,
    LLMConfig,
    GeminiConfig,
    QualityConfig,
    QualityWeights,
    QualityThresholds,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Minimal Config Fixture ────────────────────────────────────────────────────

@pytest.fixture
def minimal_config() -> PipelineConfig:
    return PipelineConfig(
        queries=QueriesConfig(
            seed_queries=["veo prompt", "Veo 3 prompt"],
            negative_keywords=["ChatGPT", "Sora", "Kling"],
            expansion=ExpansionConfig(
                top_n_queries=5,
                new_query_count=8,
                min_yield_threshold=0.01,
            ),
        ),
        engagement=EngagementConfig(
            min_likes=50,
            min_followers=1000,
            min_views=1000,
            max_tweets_per_query=200,
        ),
        crawler=CrawlerConfig(
            max_scrolls=20,
            stale_threshold=3,
            delay_ms_min=100,
            delay_ms_max=500,
            page_goto_timeout_ms=60000,
            selector_wait_ms=15000,
            scroll_wait_ms=5000,
            proxy_enabled=True,
            proxy_server="http://127.0.0.1:7897",
            cookie_age_days=7,
            max_search_contexts=3,
            max_enrichment_tasks=5,
        ),
        llm=LLMConfig(
            api_base="https://api.minimaxi.com/v1",
            api_key_env="OPENAI_API_KEY",
            default_model="MiniMax-M2.7",
            extraction_timeout=60,
            scoring_timeout=45,
            query_expansion_timeout=30,
            extraction_concurrency=15,
            scoring_concurrency=10,
            query_expansion_concurrency=1,
        ),
        gemini=GeminiConfig(
            project="sparki-op",
            location="global",
            gcs_bucket="sparki-op-test",
            image_models=[
                "gemini-3-pro-image-preview",
                "gemini-3.1-flash-image-preview",
                "gemini-2.5-flash-image",
            ],
            generation_concurrency=3,
            max_retries_per_model=3,
            retry_delay_base=5,
            style_keywords={
                "cinematic": ["film grain", "anamorphic"],
                "video-generation": ["motion blur", "dynamic pose"],
                "other": ["high quality"],
            },
        ),
        quality=QualityConfig(
            weights=QualityWeights(
                specificity=0.25,
                visual_detail=0.30,
                novelty=0.20,
                generatable=0.25,
            ),
            thresholds=QualityThresholds(
                min_overall=0.40,
                good_overall=0.60,
                min_specificity=0.30,
                min_visual_detail=0.20,
            ),
        ),
    )


# ─── AgentState Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def empty_state(minimal_config: PipelineConfig) -> AgentState:
    """Minimal AgentState at INITIALIZING phase with only config set."""
    return AgentState(
        run_id=str(uuid.uuid4()),
        scrape_id=1,
        config=minimal_config,
        phase=PipelinePhase.INITIALIZING,
        stats=PipelineStats(phase_started_at=_utc_now()),
    )


@pytest.fixture
def state_with_queries(
    minimal_config: PipelineConfig,
) -> AgentState:
    """AgentState after query_planner_node has run."""
    qs = [
        QueryCandidate(text="veo prompt", source="seed", scroll_budget=20, priority=1.0),
        QueryCandidate(text="Veo 3 prompt", source="expansion", scroll_budget=15, priority=0.8),
    ]
    state = AgentState(
        run_id=str(uuid.uuid4()),
        scrape_id=1,
        config=minimal_config,
        query_candidates=qs,
        phase=PipelinePhase.CRAWLING,
        stats=PipelineStats(phase_started_at=_utc_now()),
    )
    return state


@pytest.fixture
def sample_author() -> AuthorRef:
    return AuthorRef(
        name="Test Creator",
        screen_name="testcreator",
        profile_url="/testcreator",
        followers_count=5000,
        is_blue_verified=True,
    )


@pytest.fixture
def sample_tweet(sample_author: AuthorRef) -> Tweet:
    return Tweet(
        tweet_id="1234567890",
        url="https://x.com/testcreator/status/1234567890",
        text="Created with Veo 3. Prompt: Ultra-realistic cinematic video, 4K, 24fps, "
             "psychological horror style, foggy forest, abandoned cabin, single torch light",
        short_text="Created with Veo 3. Prompt: Ultra-realistic cinematic video...",
        author=sample_author,
        created_at="2026-05-18T10:00:00Z",
        favorite_count=150,
        retweet_count=23,
        reply_count=5,
        view_count=15000,
        source_query="veo prompt",
        scraped_at=_utc_now(),
        author_enriched=True,
        detail_enriched=True,
    )


@pytest.fixture
def sample_extracted_prompt(sample_author: AuthorRef) -> ExtractedPrompt:
    return ExtractedPrompt(
        tweet_id="1234567890",
        url="https://x.com/testcreator/status/1234567890",
        category="video-generation",
        title="Psychological horror forest cabin",
        prompt_text="Ultra-realistic cinematic video, 4K, 24fps, psychological horror style, "
                    "foggy forest, abandoned cabin, single torch light",
        notes="Explicit Veo prompt with scene description and technical parameters.",
        author=sample_author,
        likes_count=150,
        retweet_count=23,
        reply_count=5,
        view_count=15000,
        extracted_at=_utc_now(),
        needs_image=True,
        image_status=ImageGenStatus.PENDING,
    )


@pytest.fixture
def sample_quality_scores() -> QualityScores:
    return QualityScores(
        specificity=0.75,
        visual_detail=0.80,
        novelty=0.60,
        generatable=0.85,
        overall=0.76,
    )


@pytest.fixture
def sample_scored_prompt(
    sample_extracted_prompt: ExtractedPrompt,
    sample_quality_scores: QualityScores,
) -> ScoredPrompt:
    p = sample_extracted_prompt
    p.quality_scores = sample_quality_scores
    return p


@pytest.fixture
def sample_image_result() -> ImageResult:
    return ImageResult(
        prompt_id=1,
        tweet_id="1234567890",
        status=ImageGenStatus.COMPLETED,
        model_used="gemini-3-pro-image-preview",
        gcs_url="gs://sparki-op-test/prompts/video-generation/2026-05/1/1.png",
        local_path=None,
        error_message=None,
        generated_at=_utc_now(),
        category_path="prompts/video-generation/2026-05/1/1.png",
    )


@pytest.fixture
def sample_query_metrics() -> dict[str, QueryMetrics]:
    return {
        "veo prompt": QueryMetrics(
            query_text="veo prompt",
            scrape_run_id=1,
            tweets_raw=120,
            tweets_filtered=45,
            prompts_extracted=12,
            qualified_prompts=8,
            qualified_rate=0.178,
            prompt_yield_rate=0.267,
            run_count=1,
            last_run_at=_utc_now(),
            scroll_budget_hint=20,
            is_active=True,
        ),
    }


@pytest.fixture
def sample_author_metrics() -> dict[str, AuthorMetrics]:
    return {
        "testcreator": AuthorMetrics(
            screen_name="testcreator",
            display_name="Test Creator",
            profile_url="/testcreator",
            followers_count=5000,
            total_prompts=5,
            qualified_prompts=4,
            high_value_ratio=0.80,
            last_active_at=_utc_now(),
            last_crawled_at=_utc_now(),
            is_high_value=True,
        ),
    }


# ─── Contract Validation Helpers ──────────────────────────────────────────────

def assert_field_presence(obj: Any, expected_fields: list[str]) -> None:
    """Fail if obj is missing any expected field or has extra unexpected fields."""
    actual = set(obj.__dict__.keys())
    missing = set(expected_fields) - actual
    extra = actual - set(expected_fields)
    assert not missing, f"Missing fields: {missing}"
    assert not extra, f"Unexpected fields: {extra}"


def assert_phase_advanced(old_phase: PipelinePhase, new_phase: PipelinePhase) -> None:
    """Assert phase transitioned forward (not stuck or went backwards)."""
    phase_order = list(PipelinePhase)
    assert phase_order.index(new_phase) >= phase_order.index(old_phase), (
        f"Phase regressed: {old_phase} -> {new_phase}"
    )