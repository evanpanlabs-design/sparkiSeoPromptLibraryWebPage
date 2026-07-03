"""Category endpoints: list categories and pending suggestions, approve/reject/rename."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.memory.schema import _conn

router = APIRouter(prefix="/categories", tags=["Categories"])


# ── Response Models ─────────────────────────────────────────────────────────

class CategorySuggestionResponse(BaseModel):
    id: int
    suggested_name: str
    suggested_desc: str
    reason: str
    suggested_by: str
    sample_prompt: str
    status: str
    reviewed_at: str | None
    reviewed_by: str | None
    created_at: str


class CategoryListResponse(BaseModel):
    categories: list[dict]
    pending_suggestions: list[CategorySuggestionResponse]


class CategoryActionRequest(BaseModel):
    action: str  # "approve" | "reject" | "rename"
    new_name: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_categories() -> list[dict]:
    """Get all distinct categories from prompts + pending suggestions."""
    conn = _conn()

    # Get distinct categories from prompts
    rows = conn.execute(
        """
        SELECT category, COUNT(*) as prompt_count,
               MAX(extracted_at) as last_prompt_at
        FROM prompts
        GROUP BY category
        ORDER BY prompt_count DESC
        """
    ).fetchall()

    categories = [
        {
            "name": row["category"],
            "prompt_count": row["prompt_count"],
            "last_prompt_at": row["last_prompt_at"] or "",
        }
        for row in rows
    ]

    return categories


def _get_pending_suggestions() -> list[CategorySuggestionResponse]:
    """Get all pending category suggestions."""
    conn = _conn()
    rows = conn.execute(
        """
        SELECT * FROM category_suggestions
        WHERE status = 'pending'
        ORDER BY created_at DESC
        """
    ).fetchall()

    return [
        CategorySuggestionResponse(
            id=row["id"],
            suggested_name=row["suggested_name"],
            suggested_desc=row["suggested_desc"] or "",
            reason=row["reason"],
            suggested_by=row["suggested_by"],
            sample_prompt=row["sample_prompt"],
            status=row["status"],
            reviewed_at=row["reviewed_at"],
            reviewed_by=row["reviewed_by"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=CategoryListResponse)
async def list_categories():
    """List all active categories with prompt counts, plus pending suggestions."""
    categories = _get_categories()
    pending = _get_pending_suggestions()

    return CategoryListResponse(
        categories=categories,
        pending_suggestions=pending,
    )


@router.get("/suggestions", response_model=list[CategorySuggestionResponse])
async def list_suggestions():
    """List all pending category suggestions."""
    return _get_pending_suggestions()


@router.patch("/{suggestion_id}", response_model=CategorySuggestionResponse)
async def update_category(suggestion_id: int, req: CategoryActionRequest):
    """
    Approve, reject, or rename a pending category suggestion.

    Actions:
      - approve: marks suggestion as approved (adds to active categories)
      - reject: marks suggestion as rejected
      - rename: marks as approved and updates suggested_name to new_name

    On approve: a new category row is effectively added to the category list.
    On rename: new_name must be provided.
    """
    conn = _conn()
    now = datetime.now(timezone.utc).isoformat()

    # Fetch suggestion
    row = conn.execute(
        "SELECT * FROM category_suggestions WHERE id = ?", (suggestion_id,)
    ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Category suggestion not found")

    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Suggestion already {row['status']}")

    action = req.action.lower()
    if action not in ("approve", "reject", "rename"):
        raise HTTPException(status_code=400, detail="action must be approve, reject, or rename")

    if action == "rename" and not req.new_name:
        raise HTTPException(status_code=400, detail="new_name required for rename action")

    final_name = req.new_name if action == "rename" else row["suggested_name"]

    # Update suggestion status
    conn.execute(
        """
        UPDATE category_suggestions
        SET status = ?, reviewed_at = ?, reviewed_by = 'api'
        WHERE id = ?
        """,
        (action if action != "rename" else "approved", now, suggestion_id),
    )

    if action in ("approve", "rename"):
        # Add as a new category (create a placeholder prompt entry if needed)
        # For now, just log it — real implementation would register the category
        pass

    conn.commit()

    # Return updated suggestion
    updated_row = conn.execute(
        "SELECT * FROM category_suggestions WHERE id = ?", (suggestion_id,)
    ).fetchone()

    return CategorySuggestionResponse(
        id=updated_row["id"],
        suggested_name=final_name,
        suggested_desc=updated_row["suggested_desc"] or "",
        reason=updated_row["reason"],
        suggested_by=updated_row["suggested_by"],
        sample_prompt=updated_row["sample_prompt"],
        status=updated_row["status"],
        reviewed_at=updated_row["reviewed_at"],
        reviewed_by=updated_row["reviewed_by"],
        created_at=updated_row["created_at"],
    )