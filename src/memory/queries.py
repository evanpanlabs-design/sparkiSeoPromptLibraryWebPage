"""Query repository for managing query metrics in the database."""

import json
from datetime import datetime, timezone
from typing import Optional

from src.memory.schema import _conn
from src.types.query import QueryMetrics


class QueryRepository:
    """Repository for query metrics CRUD operations."""

    def create(
        self,
        scrape_run_id: int,
        query_text: str,
        scroll_budget: int = 20,
    ) -> int:
        """Create a new query record and return its ID."""
        conn = _conn()
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """
            INSERT INTO queries (scrape_run_id, text, scroll_budget, last_run_at)
            VALUES (?, ?, ?, ?)
            """,
            (scrape_run_id, query_text, scroll_budget, now),
        )
        conn.commit()
        return cur.lastrowid

    def update_yield(
        self,
        query_id: int,
        tweets_raw: int,
        tweets_filtered: int,
        prompts_extracted: int,
        qualified: int,
    ) -> None:
        """Update query yield metrics and recalculate rates."""
        conn = _conn()
        now = datetime.now(timezone.utc).isoformat()

        qualified_rate = qualified / tweets_filtered if tweets_filtered > 0 else 0.0
        prompt_yield_rate = (
            prompts_extracted / tweets_filtered if tweets_filtered > 0 else 0.0
        )

        conn.execute(
            """
            UPDATE queries SET
                tweets_raw = ?,
                tweets_filtered = ?,
                prompts_extracted = ?,
                qualified = ?,
                qualified_rate = ?,
                prompt_yield_rate = ?,
                last_run_at = ?
            WHERE id = ?
            """,
            (
                tweets_raw,
                tweets_filtered,
                prompts_extracted,
                qualified,
                qualified_rate,
                prompt_yield_rate,
                now,
                query_id,
            ),
        )
        conn.commit()

    def get_top_performing(
        self, scrape_run_id: Optional[int] = None, top_n: int = 5
    ) -> list[QueryMetrics]:
        """Get top performing queries by prompt_yield_rate."""
        conn = _conn()
        if scrape_run_id is not None:
            rows = conn.execute(
                """
                SELECT * FROM queries
                WHERE scrape_run_id = ?
                ORDER BY prompt_yield_rate DESC
                LIMIT ?
                """,
                (scrape_run_id, top_n),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM queries
                ORDER BY prompt_yield_rate DESC
                LIMIT ?
                """,
                (top_n,),
            ).fetchall()

        return [self._row_to_metrics(row) for row in rows]

    def get_all(self) -> list[QueryMetrics]:
        """Get all query records."""
        conn = _conn()
        rows = conn.execute("SELECT * FROM queries").fetchall()
        return [self._row_to_metrics(row) for row in rows]

    def get_by_id(self, query_id: int) -> Optional[QueryMetrics]:
        """Get a query by its ID."""
        conn = _conn()
        row = conn.execute(
            "SELECT * FROM queries WHERE id = ?", (query_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_metrics(row)

    def _row_to_metrics(self, row: "sqlite3.Row") -> QueryMetrics:
        """Convert a database row to QueryMetrics dataclass."""
        return QueryMetrics(
            query_text=row["text"],
            scrape_run_id=row["scrape_run_id"],
            tweets_raw=row["tweets_raw"],
            tweets_filtered=row["tweets_filtered"],
            prompts_extracted=row["prompts_extracted"],
            qualified_prompts=row["qualified"],
            qualified_rate=row["qualified_rate"],
            prompt_yield_rate=row["prompt_yield_rate"],
            last_run_at=row["last_run_at"] or "",
        )
