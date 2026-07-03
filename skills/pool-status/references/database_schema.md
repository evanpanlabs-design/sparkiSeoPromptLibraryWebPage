# Database Schema — `prompts.image_status`

The `pool-status` skill reads **only** the `prompts` table in `data/veo_prompts.db`. The single column it depends on is `image_status`, which is added by the V3 migration `_migrate_v3_prompts_cols` in `src/memory/schema.py:248-256`.

## Migration SQL (authoritative)

```sql
ALTER TABLE prompts ADD COLUMN image_status TEXT DEFAULT 'pending'
CHECK (image_status IN ('pending','generating','done','failed','published'));
```

- Added by `_migrate_v3_prompts_cols(conn)` in `src/memory/schema.py:248-256`.
- The migration is wrapped in a `try/except sqlite3.OperationalError` so re-running `init_db()` is idempotent.
- The CHECK constraint is enforced by SQLite at INSERT/UPDATE time — any value outside the 5 states is rejected.

## Column Reference

| Attribute | Value |
|---|---|
| Table | `prompts` |
| Column | `image_status` |
| Type | `TEXT` |
| Default | `'pending'` |
| Nullable | yes (any TEXT column is nullable unless `NOT NULL` is added) |
| Allowed values | `pending`, `generating`, `done`, `failed`, `published` |
| Index | **none** — see "Index notes" below |

## 5 States — Meanings and Who Writes Them

| State | Intended meaning | Writer (today) | Drift note |
|---|---|---|---|
| `pending` | Not yet processed (or re-queued by `retry_failed`). | `tool_extract_prompts` (initial INSERT, `core_tools.py:235`). `tool_retry_failed` (reset on retry, `core_tools.py:635`). | Safe — both writers exist. |
| `generating` | In flight in a worker. | **none.** | Dead label. `tool_generate_images` goes straight from `pending` to `done`/`failed`. See Handoff Notes drift #2. |
| `done` | Cover image successfully generated and stored. | `tool_generate_images` (`core_tools.py:577, 652`). `tool_retry_failed` (`core_tools.py:652`). | Safe. |
| `failed` | Cover image generation failed (after retries). | `tool_generate_images` (`core_tools.py:586, 658, 664`). `tool_retry_failed` (when the retry itself fails, `core_tools.py:664`). | Safe. |
| `published` | Prompt is live on the public site. | **none.** | Dead label. `tool_publish` does not UPDATE `image_status`. See Handoff Notes drift #1. |

## Index Notes

The `prompts` table has two relevant indexes (`schema.py:125-126`):

```sql
CREATE INDEX IF NOT EXISTS idx_prompts_category ON prompts(category);
CREATE INDEX IF NOT EXISTS idx_prompts_quality ON prompts(quality_scores);
```

Neither index covers `image_status`. The `pool-status` query:

```sql
SELECT image_status, COUNT(*) AS cnt FROM prompts GROUP BY image_status;
```

performs a full table scan + a hash aggregate. For a 148-row table this is microseconds. For a 1M-row table, consider:

```sql
CREATE INDEX IF NOT EXISTS idx_prompts_image_status ON prompts(image_status);
```

The `prompts` table PRIMARY KEY is `id` (auto-increment) and it has a UNIQUE constraint on `tweet_id`. Neither is the right index for this query.

## NULL Handling

- The migration `DEFAULT 'pending'` means that **rows inserted before the migration ran** would have `image_status = NULL` — SQLite back-fills the default only for `INSERT`s that omit the column, not for `ALTER TABLE`-added columns.
- `tool_pool_status` then either:
  - **Skips NULLs** in the `GROUP BY` (the SELECT returns zero rows for `image_status IS NULL`).
  - **Falls back** to `pending` if a row's value is `None` (Python's `or "pending"` at `core_tools.py:448`). In practice this branch never runs because the SQL `GROUP BY` never returns a row with `image_status IS NULL`.
- **Safe invariant**: any future `INSERT INTO prompts` should omit the `image_status` column (or pass `'pending'`) so the column default does the work. Do not write `image_status = NULL` explicitly — that would make the row invisible to `pool-status`.

## Sample Diagnostic Queries

```sql
-- Counts per state (the core query, with the same fallback behavior as the tool)
SELECT
  COUNT(*) FILTER (WHERE image_status = 'pending')    AS pending,
  COUNT(*) FILTER (WHERE image_status = 'generating') AS generating,
  COUNT(*) FILTER (WHERE image_status = 'done')       AS done,
  COUNT(*) FILTER (WHERE image_status = 'failed')     AS failed,
  COUNT(*) FILTER (WHERE image_status = 'published')  AS published,
  COUNT(*)                                            AS total
FROM prompts;

-- Detect drift values (any value outside the 5 declared states)
SELECT image_status, COUNT(*) AS cnt
FROM prompts
WHERE image_status NOT IN ('pending','generating','done','failed','published')
GROUP BY image_status;

-- Detect NULL `image_status` (rows that pre-date the V3 migration and lost their default)
SELECT COUNT(*) AS null_image_status
FROM prompts
WHERE image_status IS NULL;
```

The first query is a copy of what `src/agent/memory/long_term.py:38-44` does for the long-term-memory summary view. If the two counts ever disagree, suspect a race between two writers or a NULL value the `tool_pool_status` Python loop swallowed.
