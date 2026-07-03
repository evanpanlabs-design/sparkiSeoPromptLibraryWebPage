"""Query and author endpoints: list queries with metrics, list high-value authors."""

from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Optional

from src.memory.queries import QueryRepository
from src.memory.authors import AuthorRepository

router = APIRouter(prefix="/queries", tags=["Queries"])
_queries_repo = QueryRepository()
_authors_repo = AuthorRepository()


# ── Response Models ─────────────────────────────────────────────────────────

class QueryResponse(BaseModel):
    text: str
    last_run_at: str
    tweets_raw: int
    tweets_filtered: int
    prompts_extracted: int
    qualified: int
    qualified_rate: float
    prompt_yield_rate: float


class QueriesListResponse(BaseModel):
    queries: list[dict]


class AuthorResponse(BaseModel):
    screen_name: str
    display_name: str
    profile_url: str
    followers_count: int
    total_prompts: int
    qualified_prompts: int
    high_value_ratio: float
    last_active_at: str
    is_high_value: bool


class AuthorsListResponse(BaseModel):
    authors: list[dict]


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=QueriesListResponse)
async def list_queries():
    """
    List all queries with performance metrics.
    Returns the same shape as DevGuide §5.4.
    """
    all_metrics = _queries_repo.get_all()

    return QueriesListResponse(
        queries=[
            {
                "text": m.query_text,
                "last_run_at": m.last_run_at,
                "tweets_raw": m.tweets_raw,
                "tweets_filtered": m.tweets_filtered,
                "prompts_extracted": m.prompts_extracted,
                "qualified": m.qualified_prompts,
                "qualified_rate": m.qualified_rate,
                "prompt_yield_rate": m.prompt_yield_rate,
            }
            for m in all_metrics
        ]
    )


@router.get("/top", response_model=QueriesListResponse)
async def top_queries(top_n: int = Query(5, ge=1, le=50)):
    """Get top performing queries by prompt_yield_rate."""
    top = _queries_repo.get_top_performing(top_n=top_n)

    return QueriesListResponse(
        queries=[
            {
                "text": m.query_text,
                "last_run_at": m.last_run_at,
                "tweets_raw": m.tweets_raw,
                "tweets_filtered": m.tweets_filtered,
                "prompts_extracted": m.prompts_extracted,
                "qualified": m.qualified_prompts,
                "qualified_rate": m.qualified_rate,
                "prompt_yield_rate": m.prompt_yield_rate,
            }
            for m in top
        ]
    )


# ── /authors endpoint ────────────────────────────────────────────────────────

authors_router = APIRouter(prefix="/authors", tags=["Authors"])


@authors_router.get("", response_model=AuthorsListResponse)
async def list_authors(
    min_prompts: Optional[int] = Query(None, ge=1, description="Minimum total prompts"),
    high_value_only: bool = Query(False, description="Only return high-value authors"),
):
    """
    List authors with prompt metrics.
    Supports filtering by minimum prompt count and high-value flag.
    """
    if high_value_only:
        authors = _authors_repo.get_high_value(top_n=50)
    else:
        from src.memory.schema import _conn
        conn = _conn()
        sql = "SELECT * FROM authors"
        params = []
        if min_prompts:
            sql += " WHERE total_prompts >= ?"
            params.append(min_prompts)
        sql += " ORDER BY total_prompts DESC LIMIT 100"
        rows = conn.execute(sql, params).fetchall()
        from src.types.author import AuthorMetrics
        authors = [_authors_repo._row_to_metrics(row) for row in rows]

    return AuthorsListResponse(
        authors=[
            {
                "screen_name": a.screen_name,
                "display_name": a.display_name,
                "profile_url": a.profile_url,
                "followers_count": a.followers_count,
                "total_prompts": a.total_prompts,
                "qualified_prompts": a.qualified_prompts,
                "high_value_ratio": a.high_value_ratio,
                "last_active_at": a.last_active_at,
                "is_high_value": a.is_high_value,
            }
            for a in authors
        ]
    )


@authors_router.get("/high-value", response_model=AuthorsListResponse)
async def list_high_value_authors(top_n: int = Query(20, ge=1, le=100)):
    """List authors with high_value_ratio > 0.5 and total_prompts >= 3."""
    authors = _authors_repo.get_high_value(top_n=top_n)

    return AuthorsListResponse(
        authors=[
            {
                "screen_name": a.screen_name,
                "display_name": a.display_name,
                "profile_url": a.profile_url,
                "followers_count": a.followers_count,
                "total_prompts": a.total_prompts,
                "qualified_prompts": a.qualified_prompts,
                "high_value_ratio": a.high_value_ratio,
                "last_active_at": a.last_active_at,
                "is_high_value": a.is_high_value,
            }
            for a in authors
        ]
    )