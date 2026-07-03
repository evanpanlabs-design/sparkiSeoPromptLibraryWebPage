# Database Schema — sync_images (READ-ONLY)

The `sync-images` skill **does not write** to the database. Both underlying
scripts read the `prompts` table (and Step 2's wider join via `tweets`) to
decide which GCS blobs to pull and which local files to copy.

This document is intentionally minimal — see the full schema in
`src/memory/schema.py` and the V3.2 → V3.3 migration target in
`docs/11_ToolInterface.md` §"数据库写入汇总".

## Tables read by this skill

### `prompts` (Step 1 + Step 2)

| Column | Used by | Notes |
|---|---|---|
| `id` | Step 1 + Step 2 | Integer PK. Matches the `{db_id}` in the GCS blob name `prompts/{cat}/{yyyy-mm}/{db_id}.png`. Also the filename under `outputs/generated_images/`. |
| `tweet_id` | Step 1 + Step 2 | Used to build `outputs/images/{cat}/{yyyy-mm}/{tweet_id}.png` (canonical mirror) and as the join key to `tweets.created_at` in Step 2. |
| `category` | Step 1 + Step 2 | Determines the `{safe_category}` subdir under `outputs/images/`. |
| `title` | Step 1 | Read but not used in the local path. |
| `image_status` | Step 1 + Step 2 | Filter: `image_status = 'done'`. Step 2 adds `AND image_gcs_url IS NOT NULL`. |
| `image_gcs_url` | Step 2 | Required for Step 2 to consider the row. The blob lookup is by `id`, not by URL — the column is just a "GCS row exists" flag. |
| `quality_scores` | Step 2 | `ORDER BY CAST(quality_scores AS REAL) DESC` — drives the iteration order of Step 2. |

### `tweets` (Step 2 only)

| Column | Used by | Notes |
|---|---|---|
| `tweet_id` | Step 2 | Join key (LEFT JOIN). |
| `created_at` | Step 2 | Surfaced as `prompt['created_at']` and formatted into the detail HTML. **Not used in the image sync logic itself** — this is just a side-effect of `fetch_all_prompts()` reusing the same query. |

## What the skill does NOT touch

- `tweets.prompt_text`, `tweets.category`, `tweets.title`, `tweets.notes` — these are set by `extract_prompts`, not here.
- `prompts.quality_scores` — set by `score_prompts`.
- `prompts.image_status`, `prompts.image_gcs_url` — set by `generate_images`. This skill only **reads** them.
- Any new tables introduced in V3.3 (`image_attempts`, `has_raw_tweet`/`has_prompt`/`has_cover_image` flags) — V3.3 collapses the GCS step entirely and this skill stops being called.

## Verification queries

```sql
-- How many rows does Step 1 see?
SELECT COUNT(*) FROM prompts WHERE image_status = 'done';

-- How many rows does Step 2 see?
SELECT COUNT(*) FROM prompts WHERE image_status = 'done' AND image_gcs_url IS NOT NULL;

-- Are there done rows WITHOUT a GCS URL? These are V3.3-style rows that this skill ignores.
SELECT COUNT(*) FROM prompts WHERE image_status = 'done' AND image_gcs_url IS NULL;

-- Quality distribution of Step 2 rows (informational).
SELECT CAST(quality_scores AS REAL) AS q, COUNT(*)
FROM prompts
WHERE image_status = 'done' AND image_gcs_url IS NOT NULL
GROUP BY q
ORDER BY q DESC;
```

## Live state at time of writing

- `prompts WHERE image_status = 'done' AND image_gcs_url IS NOT NULL`: depends on
  the most recent `generate_images` run. On a clean V3.2 deploy that has run
  the V3.2 image gen, this count should match the number of blobs under
  `gs://sparki-op-test/prompts/`.
- `prompts WHERE image_status = 'done' AND image_gcs_url IS NULL`: rows produced
  by V3.3-style `generate_images` (writes locally, no GCS URL). These will be
  invisible to this skill.
