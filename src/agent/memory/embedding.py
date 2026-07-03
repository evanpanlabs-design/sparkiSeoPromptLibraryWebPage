"""Embedding utilities — Gemini embeddings API + cosine similarity search."""

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

# Lazy-init client to avoid circular import with src.llm.gemini_client
_embed_client: Optional[Any] = None

EMBEDDING_MODEL = "gemini-embedding-2"


def _load_gemini_config() -> dict:
    """Load Gemini project/location from configs/llm.yaml."""
    import yaml
    cfg_path = Path(__file__).resolve().parent.parent.parent.parent / "configs" / "llm.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    gemini_cfg = cfg.get("llm", {}).get("gemini", {})
    return {
        "project": gemini_cfg.get("project", "sparki-op"),
        "location": gemini_cfg.get("location", "global"),
    }


def _get_embed_client():
    global _embed_client
    if _embed_client is None:
        from google import genai as _genai
        cfg = _load_gemini_config()
        _embed_client = _genai.Client(vertexai=True, project=cfg["project"], location=cfg["location"])
    return _embed_client


def embed_text(text: str) -> list[float]:
    """Generate an embedding vector for the given text via Gemini embeddings API."""
    from google.genai.types import EmbedContentConfig

    client = _get_embed_client()
    resp = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=[text],
        config=EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
    )
    # New API: resp.results is a list; each item has .values
    return resp.embeddings[0].values


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def search_prompts(conn, query: str, top_k: int = 5) -> list[dict]:
    """Embed query text and return top-k most similar prompts from DB.

    Args:
        conn: sqlite3.Connection
        query: semantic search query string
        top_k: number of results to return

    Returns:
        list of dicts with keys: id, prompt_text, score
    """
    query_vec = embed_text(query)

    rows = conn.execute(
        """
        SELECT pe.prompt_id, pe.embedding, p.title, p.prompt_text,
               p.quality_scores, p.image_status
        FROM prompt_embeddings pe
        JOIN prompts p ON p.id = pe.prompt_id
        """
    ).fetchall()

    if not rows:
        return []

    scored = []
    for row in rows:
        raw_emb = row["embedding"]
        # embedding may be stored as JSON string (TEXT) or BLOB (bytes)
        if isinstance(raw_emb, bytes):
            stored_vec = json.loads(raw_emb.decode("utf-8"))
        else:
            stored_vec = json.loads(raw_emb)
        sim = cosine_similarity(query_vec, stored_vec)
        scored.append({
            "id": row["prompt_id"],
            "title": row["title"],
            "prompt_text": row["prompt_text"],
            "quality_scores": row["quality_scores"],
            "image_status": row["image_status"],
            "score": sim,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def embed_pending_prompts(conn) -> int:
    """Generate and store embeddings for all prompts with embedding_status='pending'.

    Returns the number of prompts successfully embedded.
    """
    rows = conn.execute(
        """
        SELECT id, title, prompt_text
        FROM prompts
        WHERE embedding_status = 'pending'
        """
    ).fetchall()

    count = 0
    now = datetime.now(timezone.utc).isoformat()

    for row in rows:
        text = f"{row['title']}: {row['prompt_text']}"
        try:
            vec = embed_text(text)
            vec_json = json.dumps(vec)
            conn.execute(
                """
                INSERT INTO prompt_embeddings (prompt_id, embedding, model, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (row["id"], vec_json, EMBEDDING_MODEL, now),
            )
            conn.execute(
                "UPDATE prompts SET embedding_status = 'embedded' WHERE id = ?",
                (row["id"],),
            )
            count += 1
        except Exception:
            conn.execute(
                "UPDATE prompts SET embedding_status = 'failed' WHERE id = ?",
                (row["id"],),
            )

    conn.commit()
    return count
