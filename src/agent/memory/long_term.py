"""Long-term memory — SQLite CRUD for cross-session persistence."""

import json
from datetime import datetime, timezone
from typing import Any

from src.types.react import PoolSummary


def save_preference(conn, key: str, value: str) -> None:
    """Upsert a user preference."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO user_preferences (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, value, now),
    )
    conn.commit()


def get_preference(conn, key: str) -> str | None:
    """Get a user preference value, or None if not set."""
    row = conn.execute(
        "SELECT value FROM user_preferences WHERE key = ?",
        (key,),
    ).fetchone()
    return row["value"] if row else None


def get_pool_summary(conn) -> PoolSummary:
    """Return current pool counts by status."""
    row = conn.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE image_status = 'pending')    AS pending,
            COUNT(*) FILTER (WHERE image_status = 'generating') AS generating,
            COUNT(*) FILTER (WHERE image_status = 'done')       AS done,
            COUNT(*) FILTER (WHERE image_status = 'failed')     AS failed,
            COUNT(*) FILTER (WHERE image_status = 'published')  AS published,
            COUNT(*)                                            AS total
        FROM prompts
        """
    ).fetchone()

    return PoolSummary(
        pending=row["pending"],
        generating=row["generating"],
        done=row["done"],
        failed=row["failed"],
        published=row["published"],
        total=row["total"],
        last_updated=datetime.now(timezone.utc).isoformat(),
    )


def save_task_history(conn, description: str, steps: list[dict], result: str | None) -> None:
    """Archive a completed ReAct task."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO task_history (description, steps_json, result_summary, created_at, completed_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (description, json.dumps(steps, ensure_ascii=False), result, now, now),
    )
    conn.commit()


def load_task_history(conn, limit: int = 10) -> list[dict]:
    """Load the most recent N archived tasks."""
    rows = conn.execute(
        """
        SELECT id, description, steps_json, result_summary, created_at, completed_at
        FROM task_history
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "description": row["description"],
            "steps": json.loads(row["steps_json"]),
            "result_summary": row["result_summary"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
        }
        for row in rows
    ]


def search_prompts_by_embedding(conn, query_vec: list[float], top_k: int = 5) -> list[dict]:
    """Find prompts by embedding similarity (cosine). Requires query_vec as list[float]."""
    from src.agent.memory.embedding import cosine_similarity

    rows = conn.execute(
        """
        SELECT pe.prompt_id, pe.embedding, p.title, p.prompt_text, p.quality_scores, p.image_status
        FROM prompt_embeddings pe
        JOIN prompts p ON p.id = pe.prompt_id
        """
    ).fetchall()

    scored = []
    for row in rows:
        stored_vec = json.loads(row["embedding"])
        sim = cosine_similarity(query_vec, stored_vec)
        scored.append({
            "prompt_id": row["prompt_id"],
            "title": row["title"],
            "prompt_text": row["prompt_text"],
            "quality_scores": row["quality_scores"],
            "image_status": row["image_status"],
            "similarity": sim,
        })

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:top_k]
