"""Prompt repository for managing prompts in the database."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.memory.schema import _conn
from src.types.prompt import ExtractedPrompt, QualityScores
from src.types.tweet import AuthorRef


@dataclass
class PromptRecord:
    """A prompt record to be inserted into the database."""
    tweet_id: str
    scrape_run_id: int
    url: str
    category: str
    title: str
    prompt_text: str
    notes: str
    author_id: int
    likes_count: int
    retweet_count: int
    reply_count: int
    view_count: int
    extracted_at: str


@dataclass
class PromptWithAuthor:
    """A prompt record with author information."""
    id: int
    tweet_id: str
    scrape_run_id: int
    url: str
    category: str
    title: str
    prompt_text: str
    notes: str
    author_id: int
    author_screen_name: str
    author_display_name: str
    likes_count: int
    retweet_count: int
    reply_count: int
    view_count: int
    quality_scores: Optional[QualityScores]
    extracted_at: str
    image_gcs_url: Optional[str]
    image_generated_at: Optional[str]
    category_path: Optional[str]
    needs_image: bool


class PromptRepository:
    """Repository for prompt CRUD operations."""

    def insert(self, prompt: PromptRecord) -> int:
        """Insert a new prompt and return its ID."""
        conn = _conn()
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """
            INSERT INTO prompts
                (tweet_id, scrape_run_id, url, category, title, prompt_text,
                 notes, author_id, likes_count, retweet_count, reply_count,
                 view_count, extracted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prompt.tweet_id,
                prompt.scrape_run_id,
                prompt.url,
                prompt.category,
                prompt.title,
                prompt.prompt_text,
                prompt.notes,
                prompt.author_id,
                prompt.likes_count,
                prompt.retweet_count,
                prompt.reply_count,
                prompt.view_count,
                prompt.extracted_at,
            ),
        )
        conn.commit()
        return cur.lastrowid

    def update_quality(self, prompt_id: int, scores: QualityScores) -> None:
        """Update prompt quality scores."""
        conn = _conn()
        scores_json = json.dumps(
            {
                "specificity": scores.specificity,
                "visual_detail": scores.visual_detail,
                "novelty": scores.novelty,
                "generatable": scores.generatable,
                "overall": scores.overall,
            }
        )
        conn.execute(
            "UPDATE prompts SET quality_scores = ? WHERE id = ?",
            (scores_json, prompt_id),
        )
        conn.commit()

    def update_image_url(
        self, prompt_id: int, gcs_url: str, category_path: Optional[str] = None
    ) -> None:
        """Update prompt with generated image URL."""
        conn = _conn()
        now = datetime.now(timezone.utc).isoformat()
        if category_path:
            conn.execute(
                """
                UPDATE prompts SET
                    image_gcs_url = ?,
                    image_generated_at = ?,
                    category_path = ?
                WHERE id = ?
                """,
                (gcs_url, now, category_path, prompt_id),
            )
        else:
            conn.execute(
                """
                UPDATE prompts SET
                    image_gcs_url = ?,
                    image_generated_at = ?
                WHERE id = ?
                """,
                (gcs_url, now, prompt_id),
            )
        conn.commit()

    def get_without_images(
        self, scrape_run_id: Optional[int] = None, limit: Optional[int] = None
    ) -> list[PromptWithAuthor]:
        """Get prompts that haven't had images generated yet."""
        conn = _conn()
        sql = """
            SELECT p.*, a.screen_name, a.display_name
            FROM prompts p
            LEFT JOIN authors a ON p.author_id = a.id
            WHERE p.image_gcs_url IS NULL
        """
        params = []
        if scrape_run_id is not None:
            sql += " AND p.scrape_run_id = ?"
            params.append(scrape_run_id)
        sql += " ORDER BY p.id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [self._row_to_prompt_with_author(row) for row in rows]

    def get_by_category(
        self, category: str, limit: int = 100
    ) -> list[PromptWithAuthor]:
        """Get prompts by category."""
        conn = _conn()
        rows = conn.execute(
            """
            SELECT p.*, a.screen_name, a.display_name
            FROM prompts p
            LEFT JOIN authors a ON p.author_id = a.id
            WHERE p.category = ?
            ORDER BY p.id DESC
            LIMIT ?
            """,
            (category, limit),
        ).fetchall()
        return [self._row_to_prompt_with_author(row) for row in rows]

    def search(
        self,
        query: str,
        min_score: float = 0,
        category: Optional[str] = None,
    ) -> list[PromptWithAuthor]:
        """Search prompts by text content."""
        conn = _conn()
        sql = """
            SELECT p.*, a.screen_name, a.display_name
            FROM prompts p
            LEFT JOIN authors a ON p.author_id = a.id
            WHERE (p.prompt_text LIKE ? OR p.title LIKE ?)
        """
        params = [f"%{query}%", f"%{query}%"]

        if min_score > 0:
            sql += " AND CAST(p.quality_scores AS REAL) >= ?"
            params.append(min_score)

        if category:
            sql += " AND p.category = ?"
            params.append(category)

        rows = conn.execute(sql, params).fetchall()
        return [self._row_to_prompt_with_author(row) for row in rows]

    def get_by_id(self, prompt_id: int) -> Optional[PromptWithAuthor]:
        """Get a prompt by ID."""
        conn = _conn()
        row = conn.execute(
            """
            SELECT p.*, a.screen_name, a.display_name
            FROM prompts p
            LEFT JOIN authors a ON p.author_id = a.id
            WHERE p.id = ?
            """,
            (prompt_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_prompt_with_author(row)

    def _row_to_prompt_with_author(self, row: "sqlite3.Row") -> PromptWithAuthor:
        """Convert a database row to PromptWithAuthor dataclass."""
        quality_scores = None
        if row["quality_scores"]:
            try:
                scores_dict = json.loads(row["quality_scores"])
                quality_scores = QualityScores(
                    specificity=scores_dict.get("specificity", 0.0),
                    visual_detail=scores_dict.get("visual_detail", 0.0),
                    novelty=scores_dict.get("novelty", 0.0),
                    generatable=scores_dict.get("generatable", 0.0),
                    overall=scores_dict.get("overall", 0.0),
                )
            except (json.JSONDecodeError, TypeError):
                pass

        return PromptWithAuthor(
            id=row["id"],
            tweet_id=row["tweet_id"],
            scrape_run_id=row["scrape_run_id"],
            url=row["url"],
            category=row["category"],
            title=row["title"],
            prompt_text=row["prompt_text"],
            notes=row["notes"] or "",
            author_id=row["author_id"],
            author_screen_name=row["screen_name"] or "",
            author_display_name=row["display_name"] or "",
            likes_count=row["likes_count"],
            retweet_count=row["retweet_count"],
            reply_count=row["reply_count"],
            view_count=row["view_count"],
            quality_scores=quality_scores,
            extracted_at=row["extracted_at"],
            image_gcs_url=row["image_gcs_url"],
            image_generated_at=row["image_generated_at"],
            category_path=row["category_path"],
            needs_image=bool(row["needs_image"]),
        )
