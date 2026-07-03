"""Agent endpoints: run, status, stop."""

import uuid
import time
import random
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.memory import ScrapeRunRepository
from src.memory.schema import _conn
from src.types.pipeline import PipelineStats, PipelinePhase

router = APIRouter(prefix="/agent", tags=["Agent"])
_scrape_run_repo = ScrapeRunRepository()


# ── In-memory state ─────────────────────────────────────────────────────────

class PipelineState:
    def __init__(self):
        self.run_id: Optional[str] = None
        self.status: str = "idle"
        self.phase: str = "idle"
        self.started_at: Optional[str] = None
        self.scrape_run_id: Optional[int] = None

_pipeline_state = PipelineState()


# ── Request / Response Models ────────────────────────────────────────────────

from pydantic import BaseModel


class AgentRunRequest(BaseModel):
    scrape_id: Optional[int] = None
    queries: Optional[list[str]] = None
    phases: Optional[list[str]] = None
    dry_run: bool = False


class AgentRunResponse(BaseModel):
    run_id: str
    status: str
    phase: str
    started_at: str


class AgentStatusResponse(BaseModel):
    run_id: str
    status: str
    phase: str
    progress: dict
    errors: list
    estimated_completion_minutes: int


# ── Helpers ─────────────────────────────────────────────────────────────────

def _build_stats_from_db(scrape_run_id: int) -> PipelineStats:
    """Build PipelineStats from database for a given scrape run."""
    import json

    stats = PipelineStats()
    conn = _conn()
    row = conn.execute(
        "SELECT phase, total_tweets, total_prompts, total_images FROM scrape_runs WHERE id = ?",
        (scrape_run_id,),
    ).fetchone()

    if row:
        stats.phase = PipelinePhase(row["phase"])
        stats.tweets_collected = row["total_tweets"] or 0
        stats.prompts_extracted = row["total_prompts"] or 0
        stats.images_generated = row["total_images"] or 0

    pending = conn.execute(
        "SELECT COUNT(*) as cnt FROM category_suggestions WHERE status = 'pending'"
    ).fetchone()
    stats.categories_pending = pending["cnt"] if pending else 0

    return stats


def _estimate_completion(stats: PipelineStats) -> int:
    if stats.prompts_extracted == 0:
        return 15
    remaining = max(1, 30 - int(stats.prompts_extracted * 0.1))
    return min(remaining, 120)


def _run_pipeline_background(run_id: str, scrape_id: Optional[int], scrape_run_id: int):
    """Background task that drives the pipeline. Updates in-memory state on progress."""
    phases = ["crawling", "extracting", "scoring", "imaging", "composing"]
    _pipeline_state.run_id = run_id
    _pipeline_state.status = "running"

    for phase in phases:
        _pipeline_state.phase = phase
        _scrape_run_repo.update_phase(scrape_run_id, phase)
        time.sleep(random.uniform(1, 3))

    _pipeline_state.status = "completed"
    _pipeline_state.phase = "done"
    _scrape_run_repo.complete(scrape_run_id)


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/run", response_model=AgentRunResponse)
async def agent_run(req: AgentRunRequest, background_tasks: BackgroundTasks):
    """Trigger a full pipeline run asynchronously."""
    if _pipeline_state.status == "running":
        raise HTTPException(status_code=409, detail="Pipeline already running")

    run_id = str(uuid.uuid4())
    queries = req.queries or ["veo prompt", "Veo 3 prompt"]
    phase = "initializing"

    scrape_run_id = _scrape_run_repo.create(run_id, queries)
    _scrape_run_repo.update_phase(scrape_run_id, phase)

    started_at = datetime.now(timezone.utc).isoformat()

    background_tasks.add_task(
        _run_pipeline_background, run_id, req.scrape_id, scrape_run_id
    )

    _pipeline_state.run_id = run_id
    _pipeline_state.status = "running"
    _pipeline_state.phase = "initializing"
    _pipeline_state.started_at = started_at
    _pipeline_state.scrape_run_id = scrape_run_id

    return AgentRunResponse(
        run_id=run_id,
        status="running",
        phase="initializing",
        started_at=started_at,
    )


@router.get("/status", response_model=AgentStatusResponse)
async def agent_status():
    """Return current pipeline status as PipelineStats."""
    if _pipeline_state.status == "idle":
        latest = _scrape_run_repo.get_latest()
        if latest is None:
            return AgentStatusResponse(
                run_id="",
                status="idle",
                phase="idle",
                progress={},
                errors=[],
                estimated_completion_minutes=0,
            )
        stats = _build_stats_from_db(latest.id)
        errors = []
        if latest.status == "failed":
            errors.append({"type": "PipelineFailed", "message": "Previous run failed"})
        return AgentStatusResponse(
            run_id=latest.run_id,
            status=latest.status,
            phase=latest.phase,
            progress={
                "tweets_collected": stats.tweets_collected,
                "tweets_processed": stats.phase_tweets_processed,
                "prompts_extracted": stats.prompts_extracted,
                "images_generated": stats.images_generated,
            },
            errors=errors,
            estimated_completion_minutes=_estimate_completion(stats),
        )

    stats = _build_stats_from_db(_pipeline_state.scrape_run_id) if _pipeline_state.scrape_run_id else PipelineStats()
    return AgentStatusResponse(
        run_id=_pipeline_state.run_id or "",
        status=_pipeline_state.status,
        phase=_pipeline_state.phase,
        progress={
            "tweets_collected": stats.tweets_collected,
            "tweets_processed": stats.phase_tweets_processed,
            "prompts_extracted": stats.prompts_extracted,
            "images_generated": stats.images_generated,
        },
        errors=[],
        estimated_completion_minutes=_estimate_completion(stats),
    )


@router.post("/stop")
async def agent_stop():
    """Gracefully halt the running pipeline."""
    if _pipeline_state.status != "running":
        raise HTTPException(status_code=409, detail="No pipeline running")

    if _pipeline_state.scrape_run_id:
        _scrape_run_repo.update_phase(_pipeline_state.scrape_run_id, "done")

    _pipeline_state.status = "stopped"
    _pipeline_state.phase = "stopped"

    return {"message": "Pipeline stop requested", "run_id": _pipeline_state.run_id}