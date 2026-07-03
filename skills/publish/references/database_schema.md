# Database Schema for publish

`tool_publish` is **read-only** with respect to the SQLite database at
`data/veo_prompts.db`. It does not `INSERT`, `UPDATE`, or `DELETE` anything.
The `prompts` table is read once, inside `scripts/build_html.py:54-95`
(`fetch_all_prompts`), to decide which rows go into `outputs/index.html`.

This document records the *expected* state of the database before the
publish step is invoked — i.e. what the pipeline must have produced by
the time you get here.

## Table: `prompts` (read-only)

| Field | Required value at publish time | Source |
|---|---|---|
| `image_status` | `'done'` (string literal) | Set by `generate_images` after a successful cover-image generation. |
| `image_gcs_url` | `NOT NULL` | Legacy — was set to the GCS URL after upload. In V3.2 the local file path is also written to `outputs/generated_images/{db_id}.png`. **V3.3 migration: this column is being replaced with `image_local_path` or `has_cover_image`.** |
| `image_local_path` | optional, used by V3.3 only | Set by `generate_images` if running on the new schema. |
| `quality_scores` | not required to be non-null, but recommended | Set by `score_prompts`. Rows are sorted by `CAST(quality_scores AS REAL) DESC`, so a NULL cast sorts to the bottom. |
| `category` | not required, but used in the build | Downgraded to `"other"` by `extract_prompts` if the LLM suggested a new label. |
| `tweet_id` | required (UNIQUE key) | The `INSERT OR REPLACE` key — re-running is safe. |
| `title`, `prompt_text`, `notes`, `url`, `author_*`, `engagement counts` | all read and emitted into the HTML | Denormalized from `tweets` at extract time. |

## SELECT performed by `build_html.py`

```sql
SELECT p.*, t.created_at
FROM prompts p
LEFT JOIN tweets t ON p.tweet_id = t.tweet_id
WHERE p.image_status = 'done' AND p.image_gcs_url IS NOT NULL
ORDER BY CAST(p.quality_scores AS REAL) DESC
```

The `LEFT JOIN tweets` is a soft dep — if a row's source tweet has been
deleted from `tweets`, the prompt still shows up with `created_at = NULL`.

## What the publish step does NOT update

- It does **not** set `image_status = 'published'` (the wiki mentions this
  state but no tool writes it — see `SKILL.md` §"Handoff Notes" drift #3).
- It does **not** record a `published_at` timestamp.
- It does **not** mark any `task_history` row.
- It does **not** touch `tweets`, `categories`, `category_suggestions`,
  `prompt_embeddings`, or any keyword table.

## Pre-publish sanity queries (optional)

```sql
-- 0) How many prompts are eligible for publish?
SELECT COUNT(*) FROM prompts
WHERE image_status = 'done' AND image_gcs_url IS NOT NULL;

-- 1) Are any rows stuck in pending / failed?
SELECT image_status, COUNT(*) FROM prompts GROUP BY image_status;

-- 2) Any rows missing quality scores (these will sort last)?
SELECT COUNT(*) FROM prompts
WHERE image_status = 'done' AND quality_scores IS NULL;
```

## V3.3 migration note

Per `docs/11_ToolInterface.md` §"V3.3 目标版", the `prompts` table is
being merged from `tweets` + `prompts` + `images` and the columns are
being renamed:

- `image_status` (string) → `has_cover_image` (0/1 flag)
- `image_gcs_url` (URL) → `image_local_path` (path)
- `image_gcs_url IS NOT NULL` → `has_cover_image = 1`

The `build_html.py:56-59` SELECT will need to be updated as part of that
migration. Until then, any environment running on the V3.3 schema will
fail the build with `no such column: p.image_gcs_url`.
