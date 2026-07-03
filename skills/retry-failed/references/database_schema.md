# Database Schema — `prompts` Image Columns

> Source of truth: `src/memory/schema.py` (CREATE TABLE + `_migrate_v3_prompts_cols()`).
> The `retry-failed` skill only reads/writes the `image_status`, `image_gcs_url`, and (in V3.3) `image_local_path` columns.

---

## Table: `prompts`

Full definition at `src/memory/schema.py:78-100`. Image-relevant columns:

| Column | Type | Default | Notes |
|---|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | autoinc | Used as the `prompt_id` argument to `RateLimitSafeGenerator.generate()`. |
| `image_status` | `TEXT` | `'pending'` | **CHECK** constraint: `IN ('pending','generating','done','failed','published')`. Added by `_migrate_v3_prompts_cols()` at `schema.py:248-256`. |
| `image_gcs_url` | `TEXT` | `NULL` | GCS URL of the generated cover image. Written by `tool_generate_images` and `tool_retry_failed` on success. **V3.3 target: replaced by `image_local_path`**. |
| `image_generated_at` | `TEXT` | `NULL` | ISO-8601 timestamp of the last successful generation. **Not written by `tool_retry_failed`** — see Handoff Notes drift #2. |

### `image_status` state machine

```
                  ┌──────────────┐
                  │  pending     │ ◀── reset by retry_failed
                  └──────┬───────┘
                         │ generator.generate() succeeds
                         ▼
                  ┌──────────────┐
                  │     done     │
                  └──────┬───────┘
                         │ tool_publish (HTML build + git push)
                         ▼
                  ┌──────────────┐
                  │  published   │
                  └──────────────┘

  Any state ──[generator exception]──▶ failed
  Any state ──[tool_retry_failed]──▶ pending  (NO published-state guard, see Handoff Notes drift #3)
```

### CHECK constraint DDL

```sql
ALTER TABLE prompts ADD COLUMN image_status TEXT DEFAULT 'pending'
    CHECK (image_status IN ('pending','generating','done','failed','published'));
```

If you try to `UPDATE prompts SET image_status = 'something_else'` the DB will raise an `IntegrityError`. The five legal values are exhaustive — there is no `archived`, `cancelled`, etc.

### Indexes on `prompts` (from `schema.py:125-126`)

- `idx_prompts_category` ON `(category)`
- `idx_prompts_quality` ON `(quality_scores)`

**There is NO index on `image_status`.** So `SELECT ... WHERE image_status = 'failed'` does a full table scan. This is fine for the current scale (low thousands of rows) but will become slow once the pool reaches 100k+ rows. A V3.3 cleanup should add `CREATE INDEX idx_prompts_image_status ON prompts(image_status)`.

### Queries used by `tool_retry_failed`

```sql
-- Candidate selection (no ORDER BY — implementation-defined order)
SELECT id, prompt_text, category
FROM prompts
WHERE image_status = 'failed'
LIMIT ?;

-- Bulk reset (NO published-state guard)
UPDATE prompts
SET image_status = 'pending'
WHERE id IN (?, ?, ...);

-- Success path
UPDATE prompts
SET image_gcs_url = ?, image_status = 'done'
WHERE id = ?;

-- Failure path
UPDATE prompts
SET image_status = 'failed'
WHERE id = ?;
```

### Pool-count query (used in the return string)

```sql
SELECT COUNT(*) FROM prompts WHERE image_status = 'pending';
SELECT COUNT(*) FROM prompts WHERE image_status = 'done';
SELECT COUNT(*) FROM prompts WHERE image_status = 'failed';
```

These three are run unconditionally after the loop. They are full scans — fine for V3.2 scale, will need an index in V3.3.

### Related table: `images`

There is also an `images` table (`schema.py:102-110`) with `(prompt_id, generated_url, model_used, status, error_message, generated_at)`. **`tool_retry_failed` does NOT write to it.** V3.3 target is to add an `image_attempts` audit log — see Handoff Notes drift #6 in `SKILL.md`.

### GCS object key format

The GCS key (URL) for a cover image is:

```
gs://sparki-op-test/prompts/{category}/{yyyy-mm}/{tweet_id}.png
```

But `tweet_id` here is the **integer** `prompts.id` row key cast to string — see `src/image_gen/generator.py:60-65` where `_generate_one` does `tweet_id=str(prompt_id)`. The original `prompts.tweet_id` (X.com snowflake) is **not** used. See Handoff Notes drift #4 in `SKILL.md`.

Example: row `prompts.id=123`, `prompts.category='cinematic-scene'`, generated on 2026-05-27 → `gs://sparki-op-test/prompts/cinematic-scene/2026-05/123.png`.
