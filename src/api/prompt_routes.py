"""Prompt endpoints: list, detail, image regeneration."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.memory import PromptRepository
from src.memory.schema import _conn

router = APIRouter(prefix="/prompts", tags=["Prompts"])
_prompt_repo = PromptRepository()


# ── Response Models ─────────────────────────────────────────────────────────

class PromptResponse(BaseModel):
    id: int
    title: str
    prompt_text: str
    category: str
    quality_score: float
    author: str
    likes_count: int
    retweet_count: int
    image_gcs_url: Optional[str]

    class Config:
        from_attributes = True


class PromptDetailResponse(BaseModel):
    id: int
    tweet_id: str
    url: str
    title: str
    prompt_text: str
    notes: str
    category: str
    quality_scores: Optional[dict]
    author: str
    author_screen_name: str
    likes_count: int
    retweet_count: int
    reply_count: int
    view_count: int
    extracted_at: str
    image_gcs_url: Optional[str]
    image_generated_at: Optional[str]
    needs_image: bool

    class Config:
        from_attributes = True


class PromptListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    prompts: list[dict]


class ImageRegenerateResponse(BaseModel):
    prompt_id: int
    new_image_url: Optional[str]
    model_used: Optional[str]


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=PromptListResponse)
async def list_prompts(
    category: Optional[str] = Query(None, description="Filter by category"),
    min_score: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum overall quality score"),
    since: Optional[str] = Query(None, description="Created after ISO8601 date"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """List prompts with optional filters: category, min_score, since, limit, offset."""
    conn = _conn()

    sql = """
        SELECT p.*, a.screen_name, a.display_name
        FROM prompts p
        LEFT JOIN authors a ON p.author_id = a.id
        WHERE 1=1
    """
    params = []

    if category:
        sql += " AND p.category = ?"
        params.append(category)

    if min_score is not None:
        sql += " AND CAST(p.quality_scores AS REAL) >= ?"
        params.append(min_score)

    if since:
        sql += " AND p.extracted_at >= ?"
        params.append(since)

    # Count total
    count_sql = sql.replace("SELECT p.*, a.screen_name, a.display_name", "SELECT COUNT(*)")
    total = conn.execute(count_sql, params).fetchone()[0]

    # Apply pagination
    sql += " ORDER BY p.id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(sql, params).fetchall()

    prompts = []
    for row in rows:
        quality_score = 0.0
        if row["quality_scores"]:
            try:
                import json
                scores = json.loads(row["quality_scores"])
                quality_score = scores.get("overall", 0.0)
            except Exception:
                pass

        prompts.append({
            "id": row["id"],
            "title": row["title"],
            "prompt_text": row["prompt_text"],
            "category": row["category"],
            "quality_score": quality_score,
            "author": row["display_name"] or row["screen_name"] or "",
            "author_screen_name": row["screen_name"] or "",
            "likes_count": row["likes_count"],
            "retweet_count": row["retweet_count"],
            "reply_count": row["reply_count"],
            "view_count": row["view_count"],
            "url": row["url"],
            "extracted_at": row["extracted_at"],
            "image_gcs_url": row["image_gcs_url"],
            "needs_image": bool(row["needs_image"]),
        })

    return PromptListResponse(total=total, limit=limit, offset=offset, prompts=prompts)


@router.get("/{prompt_id}", response_model=PromptDetailResponse)
async def get_prompt(prompt_id: int):
    """Get full prompt detail including quality score breakdown."""
    prompt = _prompt_repo.get_by_id(prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Prompt not found")

    quality_scores = None
    if prompt.quality_scores:
        quality_scores = {
            "specificity": prompt.quality_scores.specificity,
            "visual_detail": prompt.quality_scores.visual_detail,
            "novelty": prompt.quality_scores.novelty,
            "generatable": prompt.quality_scores.generatable,
            "overall": prompt.quality_scores.overall,
        }

    return PromptDetailResponse(
        id=prompt.id,
        tweet_id=prompt.tweet_id,
        url=prompt.url,
        title=prompt.title,
        prompt_text=prompt.prompt_text,
        notes=prompt.notes,
        category=prompt.category,
        quality_scores=quality_scores,
        author=prompt.author_display_name or prompt.author_screen_name,
        author_screen_name=prompt.author_screen_name,
        likes_count=prompt.likes_count,
        retweet_count=prompt.retweet_count,
        reply_count=prompt.reply_count,
        view_count=prompt.view_count,
        extracted_at=prompt.extracted_at,
        image_gcs_url=prompt.image_gcs_url,
        image_generated_at=prompt.image_generated_at,
        needs_image=prompt.needs_image,
    )


# ── Image Regenerate ─────────────────────────────────────────────────────────
# Mounted at /images/regenerate/{prompt_id} per DevGuide §5.2

images_router = APIRouter(prefix="/images", tags=["Images"])


@images_router.post("/regenerate/{prompt_id}", response_model=ImageRegenerateResponse)
async def regenerate_image(prompt_id: int):
    """Re-generate cover image for a prompt, bypassing existing image."""
    prompt = _prompt_repo.get_by_id(prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Prompt not found")

    # TODO: Integrate with image_gen module for actual regeneration
    # For now, simulate the response structure
    new_image_url = f"gs://sparki-op-test/prompts/{prompt.category}/{prompt.id}_regenerated.jpg"
    model_used = "gemini-3-pro-image-preview"

    # Clear existing image and update status
    conn = _conn()
    conn.execute(
        """
        UPDATE prompts SET image_gcs_url = NULL, image_generated_at = NULL
        WHERE id = ?
        """,
        (prompt_id,),
    )
    conn.commit()

    # Insert/Update images table
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT id FROM images WHERE prompt_id = ?", (prompt_id,)
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE images SET status = 'pending', generated_url = NULL, error_message = NULL
            WHERE prompt_id = ?
            """,
            (prompt_id,),
        )
    else:
        conn.execute(
            "INSERT INTO images (prompt_id, status, generated_at) VALUES (?, 'pending', ?)",
            (prompt_id, now),
        )
    conn.commit()

    return ImageRegenerateResponse(
        prompt_id=prompt_id,
        new_image_url=new_image_url,
        model_used=model_used,
    )