# Database Schema (image-gen relevant)

The `generate_images` skill reads and writes a small subset of the `prompts`
table. The full schema lives at `src/memory/schema.py:78-100`; this document
covers only the columns and index that the skill touches.

## `prompts` — columns read by `tool_generate_images`

The SELECT in `core_tools.py:531` reads:

| Column | Purpose | Where set |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` — used as `prompt_id` in the generator and as the `tweet_id` slug in the GCS upload path. | Auto. |
| `prompt_text` | The actual prompt text. Sent to the image model. | `extract_prompts`. |
| `category` | Used to pick a style-keyword bucket (`style.py:_DEFAULT_STYLE_KEYWORDS`) and to build the GCS path `prompts/{category}/{yyyy-mm}/{tweet_id}.png`. | `extract_prompts`. |
| `quality_scores` | The CSV string `"{spec},{vis},{nov},{gen},{overall}"`. Used for `sort_by=score` and `filter.min_score`. See **Quality scores** below — the SQL CAST reads the first field, not overall. | `score_prompts` (`core_tools.py:336-339`). |
| `image_gcs_url` | The SELECT filters `WHERE image_gcs_url IS NULL`. On success, this column is filled with the GCS URL (`gs://sparki-op-test/prompts/{cat}/{yyyy-mm}/{tweet_id}.png`). | `tool_generate_images`, `tool_retry_failed`. **Deprecated in V3.3** — see SKILL.md drift #2. |
| `image_status` | The state machine column. SELECTed as `= 'pending'`; UPDATEd to `'done'` on success, `'failed'` on error. | `extract_prompts` (`'pending'`), `generate_images` (`'done'` / `'failed'`), `retry_failed` (`'pending'` reset + `'done'` / `'failed'`). |
| `image_generated_at` | `TEXT`, exists in schema, **never written** — see SKILL.md drift #5. | Nobody today. |

The SELECT also implicitly filters by row-existence (`prompt_text IS NOT NULL`),
but that is enforced by the `prompts` schema being a downstream of `extract_prompts`,
which always writes a non-NULL value.

## `prompts` — full column list (for context)

```sql
id                INTEGER PRIMARY KEY AUTOINCREMENT
tweet_id          TEXT NOT NULL UNIQUE
scrape_run_id     INTEGER REFERENCES scrape_runs(id)
url               TEXT NOT NULL
category          TEXT NOT NULL
title             TEXT NOT NULL
prompt_text       TEXT NOT NULL
notes             TEXT
author_id         INTEGER REFERENCES authors(id)
likes_count       INTEGER DEFAULT 0
retweet_count     INTEGER DEFAULT 0
reply_count       INTEGER DEFAULT 0
view_count        INTEGER DEFAULT 0
quality_scores    TEXT                              -- CSV, see above
extracted_at      TEXT NOT NULL
image_gcs_url     TEXT                              -- legacy; V3.3 → image_local_path
image_generated_at TEXT                             -- exists, never written
category_path     TEXT
embedding_vector  BLOB
needs_image       INTEGER DEFAULT 1
```

The `image_status` column is **not** in the original CREATE TABLE. It is added by
the V3 migration `_migrate_v3_prompts_cols` in `schema.py:248-256`:

```sql
ALTER TABLE prompts ADD COLUMN image_status TEXT DEFAULT 'pending'
  CHECK (image_status IN ('pending','generating','done','failed','published'))
```

The CHECK constraint is informative only — SQLite does not enforce CHECK
constraints by default. Still, no code path writes `'generating'` or
`'published'` (see SKILL.md drift #3).

## Indexes on `prompts`

```sql
CREATE INDEX idx_prompts_category ON prompts(category);
CREATE INDEX idx_prompts_quality  ON prompts(quality_scores);
```

`idx_prompts_quality` is the relevant one. The image-gen SELECTs
`CAST(quality_scores AS REAL)` for both filter and sort. A TEXT-column index
does **not** accelerate a CAST — SQLite has to compute the CAST for every row.
At 100k+ rows this becomes a seq scan + per-row CAST. If you need to scale
beyond ~10k pending prompts, the recommended fix is a separate
`quality_overall REAL` column (filled by `score_prompts`) with its own index.
See SKILL.md drift #4.

## `images` table (not used by this skill)

`src/memory/schema.py:102-110` defines an `images` table with columns
`prompt_id, generated_url, model_used, status, error_message, generated_at`.
**The V3.2 tool does not write to this table.** It writes directly to
`prompts.image_gcs_url` and `prompts.image_status`. The `images` table is
reserved for the V3.3 `image_attempts` per-attempt audit log
(`docs/11_ToolInterface.md:425-428`). Treat it as a future home for the
per-row progress lines that today are printed to stdout and lost.

## Quick verification queries

```bash
# Image-relevant columns
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print([r for r in c.execute('PRAGMA table_info(prompts)').fetchall() if 'image' in r[1] or 'quality' in r[1]])"

# Pool state
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); [print(s, ':', c.execute(f\"SELECT COUNT(*) FROM prompts WHERE image_status='{s}'\").fetchone()[0]) for s in ['pending','generating','done','failed','published']]"

# Recent done rows (verify image_gcs_url is populated)
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print(c.execute('SELECT id, category, image_gcs_url FROM prompts WHERE image_status=\"done\" ORDER BY id DESC LIMIT 3').fetchall())"
```
