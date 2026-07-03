"""Database schema and migrations for Sparki Memory layer."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "veo_prompts.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS scrape_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL UNIQUE,
    started_at   TEXT NOT NULL,
    completed_at TEXT,
    queries      TEXT NOT NULL,
    phase        TEXT NOT NULL,
    total_tweets INTEGER DEFAULT 0,
    total_prompts INTEGER DEFAULT 0,
    total_images INTEGER DEFAULT 0,
    total_cost_usd REAL DEFAULT 0,
    status       TEXT DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS queries (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    scrape_run_id    INTEGER REFERENCES scrape_runs(id),
    text             TEXT NOT NULL,
    scroll_budget    INTEGER DEFAULT 20,
    tweets_raw       INTEGER DEFAULT 0,
    tweets_filtered  INTEGER DEFAULT 0,
    prompts_extracted INTEGER DEFAULT 0,
    qualified        INTEGER DEFAULT 0,
    qualified_rate   REAL DEFAULT 0,
    prompt_yield_rate REAL DEFAULT 0,
    last_run_at      TEXT
);

CREATE TABLE IF NOT EXISTS tweets (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    tweet_id         TEXT NOT NULL UNIQUE,
    url              TEXT NOT NULL,
    text             TEXT,
    short_text       TEXT,
    author_name      TEXT,
    author_screen    TEXT,
    author_followers INTEGER DEFAULT 0,
    likes_count      INTEGER DEFAULT 0,
    retweet_count    INTEGER DEFAULT 0,
    reply_count      INTEGER DEFAULT 0,
    view_count       INTEGER DEFAULT 0,
    scraped_at       TEXT,
    detail_enriched  INTEGER DEFAULT 0,
    prompt_text      TEXT,
    category         TEXT,
    title            TEXT,
    notes            TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS authors (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    screen_name      TEXT NOT NULL UNIQUE,
    display_name     TEXT,
    profile_url      TEXT,
    followers_count  INTEGER DEFAULT 0,
    total_prompts    INTEGER DEFAULT 0,
    qualified_prompts INTEGER DEFAULT 0,
    high_value_ratio REAL DEFAULT 0,
    last_active_at   TEXT,
    last_crawled_at  TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    tweet_id         TEXT NOT NULL UNIQUE,
    scrape_run_id    INTEGER REFERENCES scrape_runs(id),
    url              TEXT NOT NULL,
    category         TEXT NOT NULL,
    title            TEXT NOT NULL,
    prompt_text      TEXT NOT NULL,
    notes            TEXT,
    author_id        INTEGER REFERENCES authors(id),
    likes_count      INTEGER DEFAULT 0,
    retweet_count    INTEGER DEFAULT 0,
    reply_count      INTEGER DEFAULT 0,
    view_count       INTEGER DEFAULT 0,
    quality_scores   TEXT,
    extracted_at     TEXT NOT NULL,
    image_gcs_url    TEXT,
    image_generated_at TEXT,
    category_path    TEXT,
    embedding_vector  BLOB,
    needs_image      INTEGER DEFAULT 1,
    FOREIGN KEY (scrape_run_id) REFERENCES scrape_runs(id)
);

CREATE TABLE IF NOT EXISTS images (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id        INTEGER NOT NULL REFERENCES prompts(id),
    generated_url    TEXT,
    model_used       TEXT,
    status           TEXT DEFAULT 'pending',
    error_message    TEXT,
    generated_at     TEXT
);

CREATE TABLE IF NOT EXISTS category_suggestions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    suggested_name  TEXT NOT NULL,
    suggested_desc  TEXT,
    reason          TEXT NOT NULL,
    suggested_by    TEXT NOT NULL,
    sample_prompt   TEXT NOT NULL,
    status          TEXT DEFAULT 'pending',
    reviewed_at     TEXT,
    reviewed_by     TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prompts_category ON prompts(category);
CREATE INDEX IF NOT EXISTS idx_prompts_quality ON prompts(quality_scores);
CREATE INDEX IF NOT EXISTS idx_authors_hvr ON authors(high_value_ratio DESC);
CREATE INDEX IF NOT EXISTS idx_queries_yield ON queries(prompt_yield_rate DESC);

CREATE TABLE IF NOT EXISTS categories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT,
    color           TEXT,
    created_at      TEXT NOT NULL
);
"""

_connection: Optional[sqlite3.Connection] = None


def _conn() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _connection.row_factory = sqlite3.Row
    return _connection


def init_db():
    """Create all tables and run all migrations. Returns the connection."""
    conn = _conn()
    conn.executescript(SCHEMA)
    _migrate_scrape_runs_completed_at(conn)
    _migrate_authors_last_crawled_at(conn)
    _migrate_prompts_needs_image(conn)
    _migrate_v3_tables(conn)
    _migrate_v3_prompts_cols(conn)
    _migrate_prompts_author_cols(conn)
    _migrate_keyword_tables(conn)
    conn.commit()
    return conn


def _migrate_scrape_runs_completed_at(conn: sqlite3.Connection):
    """Add completed_at column to scrape_runs if missing."""
    try:
        conn.execute("ALTER TABLE scrape_runs ADD COLUMN completed_at TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists


def _migrate_authors_last_crawled_at(conn: sqlite3.Connection):
    """Add last_crawled_at column to authors if missing."""
    try:
        conn.execute("ALTER TABLE authors ADD COLUMN last_crawled_at TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists


def _migrate_prompts_needs_image(conn: sqlite3.Connection):
    """Add needs_image column to prompts if missing."""
    try:
        conn.execute("ALTER TABLE prompts ADD COLUMN needs_image INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass  # column already exists


# ── V3 Memory Tables ───────────────────────────────────────────────────────────

def _migrate_v3_tables(conn: sqlite3.Connection):
    """Create V3 memory tables if not exist."""

    # conversation_history — session turn archive
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            role       TEXT NOT NULL CHECK (role IN ('user', 'agent', 'tool')),
            content    TEXT NOT NULL,
            tool_name  TEXT,
            tool_args  TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversation_created
        ON conversation_history(created_at DESC)
    """)

    # user_preferences — key-value store
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_preferences (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # prompt_embeddings — per-prompt embedding vectors
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prompt_embeddings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt_id  INTEGER NOT NULL REFERENCES prompts(id),
            embedding  BLOB NOT NULL,
            model      TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_prompt_emb_prompt_id
        ON prompt_embeddings(prompt_id)
    """)

    # task_history — completed ReAct task archive
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            description     TEXT NOT NULL,
            steps_json      TEXT NOT NULL,
            result_summary  TEXT,
            created_at      TEXT NOT NULL,
            completed_at    TEXT
        )
    """)


def _migrate_v3_prompts_cols(conn: sqlite3.Connection):
    """Add V3 columns to prompts table if missing."""
    try:
        conn.execute(
            "ALTER TABLE prompts ADD COLUMN image_status TEXT DEFAULT 'pending' "
            "CHECK (image_status IN ('pending','generating','done','failed','published'))"
        )
    except sqlite3.OperationalError:
        pass  # column already exists

    try:
        conn.execute(
            "ALTER TABLE prompts ADD COLUMN embedding_status TEXT DEFAULT 'pending' "
            "CHECK (embedding_status IN ('pending','embedded','failed'))"
        )
    except sqlite3.OperationalError:
        pass  # column already exists


def _migrate_prompts_author_cols(conn: sqlite3.Connection):
    """Add author denormalization cols to prompts if missing."""
    for col, dtype in [
        ("author_name", "TEXT"),
        ("author_screen", "TEXT"),
        ("author_followers", "INTEGER DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE prompts ADD COLUMN {col} {dtype}")
        except sqlite3.OperationalError:
            pass  # column already exists


def _migrate_keyword_tables(conn: sqlite3.Connection):
    """Create keyword strategy tables if not exist (DevGuide §8B.5)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS keyword_yields (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword             TEXT NOT NULL,
            scrape_run_id       INTEGER REFERENCES scrape_runs(id),
            raw_tweets          INTEGER DEFAULT 0,
            filtered_tweets     INTEGER DEFAULT 0,
            extracted_prompts   INTEGER DEFAULT 0,
            qualified_prompts   INTEGER DEFAULT 0,
            qualified_rate      REAL DEFAULT 0,
            yield_score         REAL DEFAULT 0,
            created_at          TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS keyword_suggestions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            suggested_keyword   TEXT NOT NULL,
            reason              TEXT,
            based_on_keyword    TEXT,
            status              TEXT DEFAULT 'pending',
            created_at          TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS approved_keywords (
            keyword             TEXT PRIMARY KEY,
            source              TEXT,
            approved_at         TEXT NOT NULL,
            note                TEXT
        )
    """)
    # Add qualified_rate column if table existed before migration
    try:
        conn.execute("ALTER TABLE keyword_yields ADD COLUMN qualified_rate REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists


def close():
    global _connection
    if _connection:
        _connection.close()
        _connection = None


def insert_scrape_run(run_id: str, queries: list[str], phase: str) -> int:
    """Insert a new scrape run record and return its ID."""
    conn = _conn()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """
        INSERT INTO scrape_runs (run_id, started_at, queries, phase, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, now, json.dumps(queries, ensure_ascii=False), phase, "running"),
    )
    conn.commit()
    return cur.lastrowid


def load_query_metrics() -> dict[str, "QueryMetrics"]:
    """Load all query metrics from DB into a dict keyed by query text."""
    from src.types.query import QueryMetrics
    conn = _conn()
    rows = conn.execute("SELECT * FROM queries").fetchall()
    metrics: dict[str, QueryMetrics] = {}
    for row in rows:
        qm = QueryMetrics(
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
        # Use qualified_rate as a proxy for scroll_budget_hint
        qm.scroll_budget_hint = 20  # default
        metrics[row["text"]] = qm
    return metrics


def load_author_metrics() -> dict[str, "AuthorMetrics"]:
    """Load all author metrics from DB into a dict keyed by screen_name."""
    from src.types.author import AuthorMetrics
    conn = _conn()
    rows = conn.execute("SELECT * FROM authors").fetchall()
    metrics: dict[str, AuthorMetrics] = {}
    for row in rows:
        total_prompts = row["total_prompts"]
        qualified_prompts = row["qualified_prompts"]
        high_value_ratio = row["high_value_ratio"]
        am = AuthorMetrics(
            screen_name=row["screen_name"],
            display_name=row["display_name"] or "",
            profile_url=row["profile_url"] or "",
            followers_count=row["followers_count"],
            total_prompts=total_prompts,
            qualified_prompts=qualified_prompts,
            high_value_ratio=high_value_ratio,
            last_active_at=row["last_active_at"] or "",
            last_crawled_at=row["last_crawled_at"] or "",
            is_high_value=high_value_ratio > 0.5 and total_prompts >= 3,
        )
        metrics[row["screen_name"]] = am
    return metrics


def update_query_metrics(metrics: "QueryMetrics") -> None:
    """Update or insert a query metrics record in DB."""
    conn = _conn()
    existing = conn.execute(
        "SELECT id FROM queries WHERE text = ? AND scrape_run_id = ?",
        (metrics.query_text, metrics.scrape_run_id),
    ).fetchone()

    if existing:
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
                metrics.tweets_raw,
                metrics.tweets_filtered,
                metrics.prompts_extracted,
                metrics.qualified_prompts,
                metrics.qualified_rate,
                metrics.prompt_yield_rate,
                metrics.last_run_at,
                existing["id"],
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO queries (scrape_run_id, text, scroll_budget, tweets_raw, tweets_filtered,
                                 prompts_extracted, qualified, qualified_rate, prompt_yield_rate, last_run_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metrics.scrape_run_id,
                metrics.query_text,
                metrics.scroll_budget_hint,
                metrics.tweets_raw,
                metrics.tweets_filtered,
                metrics.prompts_extracted,
                metrics.qualified_prompts,
                metrics.qualified_rate,
                metrics.prompt_yield_rate,
                metrics.last_run_at,
            ),
        )
    conn.commit()


def update_author_metrics(metrics: "AuthorMetrics") -> None:
    """Update or insert an author metrics record in DB."""
    conn = _conn()
    existing = conn.execute(
        "SELECT id FROM authors WHERE screen_name = ?",
        (metrics.screen_name,),
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE authors SET
                display_name = ?,
                profile_url = ?,
                followers_count = ?,
                total_prompts = ?,
                qualified_prompts = ?,
                high_value_ratio = ?,
                last_active_at = ?
            WHERE id = ?
            """,
            (
                metrics.display_name,
                metrics.profile_url,
                metrics.followers_count,
                metrics.total_prompts,
                metrics.qualified_prompts,
                metrics.high_value_ratio,
                metrics.last_active_at,
                existing["id"],
            ),
        )
    else:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO authors (screen_name, display_name, profile_url, followers_count,
                                 total_prompts, qualified_prompts, high_value_ratio, last_active_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metrics.screen_name,
                metrics.display_name,
                metrics.profile_url,
                metrics.followers_count,
                metrics.total_prompts,
                metrics.qualified_prompts,
                metrics.high_value_ratio,
                metrics.last_active_at,
                now,
            ),
        )
    conn.commit()
