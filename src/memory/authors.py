"""Author repository for managing author metrics in the database."""

from datetime import datetime, timezone
from typing import Optional

from src.memory.schema import _conn
from src.types.author import AuthorMetrics


class AuthorRepository:
    """Repository for author metrics CRUD operations."""

    def upsert(
        self,
        screen_name: str,
        display_name: str,
        profile_url: str,
        followers_count: int,
    ) -> int:
        """Insert or replace an author and return the author ID."""
        conn = _conn()
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """
            INSERT OR REPLACE INTO authors
                (screen_name, display_name, profile_url, followers_count, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (screen_name, display_name, profile_url, followers_count, now),
        )
        conn.commit()
        return cur.lastrowid

    def record_prompt(self, author_id: int, qualified: bool) -> None:
        """Record that an author contributed a prompt, optionally qualified."""
        conn = _conn()
        now = datetime.now(timezone.utc).isoformat()

        if qualified:
            conn.execute(
                """
                UPDATE authors SET
                    total_prompts = total_prompts + 1,
                    qualified_prompts = qualified_prompts + 1,
                    last_active_at = ?
                WHERE id = ?
                """,
                (now, author_id),
            )
        else:
            conn.execute(
                """
                UPDATE authors SET
                    total_prompts = total_prompts + 1,
                    last_active_at = ?
                WHERE id = ?
                """,
                (now, author_id),
            )

        self._recalculate_high_value_ratio(conn, author_id)
        conn.commit()

    def _recalculate_high_value_ratio(
        self, conn: "sqlite3.Connection", author_id: int
    ) -> None:
        """Recalculate high_value_ratio for an author."""
        row = conn.execute(
            """
            SELECT total_prompts, qualified_prompts FROM authors WHERE id = ?
            """,
            (author_id,),
        ).fetchone()

        if row and row["total_prompts"] > 0:
            ratio = row["qualified_prompts"] / row["total_prompts"]
            conn.execute(
                """
                UPDATE authors SET high_value_ratio = ?
                WHERE id = ?
                """,
                (ratio, author_id),
            )

    def get_high_value(self, top_n: int = 20) -> list[AuthorMetrics]:
        """Get authors with high_value_ratio > 0.5 and total_prompts >= 3."""
        conn = _conn()
        rows = conn.execute(
            """
            SELECT * FROM authors
            WHERE high_value_ratio > 0.5 AND total_prompts >= 3
            ORDER BY high_value_ratio DESC
            LIMIT ?
            """,
            (top_n,),
        ).fetchall()
        return [self._row_to_metrics(row) for row in rows]

    def get_or_create(
        self, screen_name: str, display_name: str = "", profile_url: str = ""
    ) -> AuthorMetrics:
        """Get an existing author or create a new one."""
        conn = _conn()
        row = conn.execute(
            "SELECT * FROM authors WHERE screen_name = ?", (screen_name,)
        ).fetchone()
        if row:
            return self._row_to_metrics(row)

        author_id = self.upsert(screen_name, display_name, profile_url, 0)
        return AuthorMetrics(
            screen_name=screen_name,
            display_name=display_name,
            profile_url=profile_url,
            followers_count=0,
            total_prompts=0,
            qualified_prompts=0,
            high_value_ratio=0.0,
            last_active_at="",
            last_crawled_at="",
            is_high_value=False,
        )

    def get_by_id(self, author_id: int) -> Optional[AuthorMetrics]:
        """Get an author by ID."""
        conn = _conn()
        row = conn.execute(
            "SELECT * FROM authors WHERE id = ?", (author_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_metrics(row)

    def _row_to_metrics(self, row: "sqlite3.Row") -> AuthorMetrics:
        """Convert a database row to AuthorMetrics dataclass."""
        total_prompts = row["total_prompts"]
        qualified_prompts = row["qualified_prompts"]
        high_value_ratio = row["high_value_ratio"]
        is_high_value = high_value_ratio > 0.5 and total_prompts >= 3
        return AuthorMetrics(
            screen_name=row["screen_name"],
            display_name=row["display_name"] or "",
            profile_url=row["profile_url"] or "",
            followers_count=row["followers_count"],
            total_prompts=total_prompts,
            qualified_prompts=qualified_prompts,
            high_value_ratio=high_value_ratio,
            last_active_at=row["last_active_at"] or "",
            last_crawled_at=row["last_crawled_at"] or "",
            is_high_value=is_high_value,
        )
