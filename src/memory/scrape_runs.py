"""Scrape run repository for managing scrape run records in the database."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.memory.schema import _conn


@dataclass
class ScrapeRun:
    """A scrape run record."""
    id: int
    run_id: str
    started_at: str
    completed_at: Optional[str]
    queries: list[str]
    phase: str
    total_tweets: int
    total_prompts: int
    total_images: int
    total_cost_usd: float
    status: str


class ScrapeRunRepository:
    """Repository for scrape run CRUD operations."""

    def create(self, run_id: str, queries: list[str]) -> int:
        """Create a new scrape run and return its ID."""
        conn = _conn()
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """
            INSERT INTO scrape_runs (run_id, started_at, queries, phase, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, now, json.dumps(queries, ensure_ascii=False), "initializing", "running"),
        )
        conn.commit()
        return cur.lastrowid

    def update_phase(self, scrape_run_id: int, phase: str) -> None:
        """Update the current phase of a scrape run."""
        conn = _conn()
        conn.execute(
            "UPDATE scrape_runs SET phase = ? WHERE id = ?",
            (phase, scrape_run_id),
        )
        conn.commit()

    def update_stats(
        self,
        scrape_run_id: int,
        total_tweets: int,
        total_prompts: int,
        total_images: int,
        total_cost_usd: float,
    ) -> None:
        """Update scrape run statistics."""
        conn = _conn()
        conn.execute(
            """
            UPDATE scrape_runs SET
                total_tweets = ?,
                total_prompts = ?,
                total_images = ?,
                total_cost_usd = ?
            WHERE id = ?
            """,
            (total_tweets, total_prompts, total_images, total_cost_usd, scrape_run_id),
        )
        conn.commit()

    def complete(self, scrape_run_id: int) -> None:
        """Mark a scrape run as completed."""
        conn = _conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE scrape_runs SET
                completed_at = ?,
                phase = 'done',
                status = 'completed'
            WHERE id = ?
            """,
            (now, scrape_run_id),
        )
        conn.commit()

    def fail(self, scrape_run_id: int) -> None:
        """Mark a scrape run as failed."""
        conn = _conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE scrape_runs SET
                completed_at = ?,
                phase = 'failed',
                status = 'failed'
            WHERE id = ?
            """,
            (now, scrape_run_id),
        )
        conn.commit()

    def get_by_id(self, scrape_run_id: int) -> Optional[ScrapeRun]:
        """Get a scrape run by ID."""
        conn = _conn()
        row = conn.execute(
            "SELECT * FROM scrape_runs WHERE id = ?", (scrape_run_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_scrape_run(row)

    def get_by_run_id(self, run_id: str) -> Optional[ScrapeRun]:
        """Get a scrape run by its UUID."""
        conn = _conn()
        row = conn.execute(
            "SELECT * FROM scrape_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_scrape_run(row)

    def get_latest(self) -> Optional[ScrapeRun]:
        """Get the most recent scrape run."""
        conn = _conn()
        row = conn.execute(
            "SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return self._row_to_scrape_run(row)

    def get_all(self) -> list[ScrapeRun]:
        """Get all scrape runs."""
        conn = _conn()
        rows = conn.execute("SELECT * FROM scrape_runs ORDER BY id DESC").fetchall()
        return [self._row_to_scrape_run(row) for row in rows]

    def _row_to_scrape_run(self, row: "sqlite3.Row") -> ScrapeRun:
        """Convert a database row to ScrapeRun dataclass."""
        queries = []
        try:
            queries = json.loads(row["queries"])
        except (json.JSONDecodeError, TypeError):
            pass

        return ScrapeRun(
            id=row["id"],
            run_id=row["run_id"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            queries=queries,
            phase=row["phase"],
            total_tweets=row["total_tweets"],
            total_prompts=row["total_prompts"],
            total_images=row["total_images"],
            total_cost_usd=row["total_cost_usd"],
            status=row["status"],
        )
