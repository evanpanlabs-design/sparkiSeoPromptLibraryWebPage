# Database Schema — `prompts` columns used by `build-html`

The build_html skill is **read-only** with respect to the database. It only SELECTs
from `prompts` (LEFT JOIN `tweets` for `created_at`) and never INSERTs/UPDATEs.

## Source table — `prompts`

Defined in `src/memory/schema.py:78-100`.

### Columns read by `fetch_all_prompts()` (`scripts/build_html.py:54-95`)

| Column | Type | Read for | Notes |
|---|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Detail page filename keying (`generated_images/{id}.png`), `{{db_id}}` placeholder | Used as the **image filename key** — not the `tweet_id`. |
| `tweet_id` | `TEXT NOT NULL UNIQUE` | Slug suffix, X URL fallback, picsum seed, `{{tweet_id}}` | Cast to `str()` in the row mapper. |
| `url` | `TEXT NOT NULL` | `{{x_url}}` detail link, "View on X" button | Falls back to `https://x.com/unknown/status/{tweet_id}` if NULL. |
| `category` | `TEXT NOT NULL` | **Filter** (`WHERE p.category = ?`), `{{category}}`, `{{category_display}}` (with `-` → space) | Indexed via `idx_prompts_category`. Defaults to `"other"` if NULL in mapper. |
| `title` | `TEXT NOT NULL` | Slug base, `{{title}}` placeholder | Truncated to `[:120]` chars in mapper. |
| `prompt_text` | `TEXT NOT NULL` | `{{prompt_text}}`, `{{prompt_text_json}}` (clipboard copy) | NULL becomes `""` in mapper. |
| `notes` | `TEXT` | `{{notes}}` block (Mustache-ish `{{#notes}}…{{/notes}}` conditional) | NULL strips the entire `<div class="detail-section">` for Notes. |
| `author_name` | `TEXT` | Author byline | denormalized from `tweets` at `extract_prompts` time. |
| `author_screen` | `TEXT` | `@handle` link, X URL | denormalized. |
| `author_followers` | `INTEGER` | Stats panel | `_format_number()` adds `k` suffix at ≥1000. |
| `likes_count` | `INTEGER DEFAULT 0` | Stats panel | `_format_number()`. |
| `retweet_count` | `INTEGER DEFAULT 0` | Stats panel | `_format_number()`. |
| `reply_count` | `INTEGER DEFAULT 0` | Stats panel | `_format_number()`. |
| `quality_scores` | `TEXT` | **Filter** (`CAST AS REAL >= ?`) + **ORDER BY** (`DESC`) | CSV string `spec,vis,nov,gen,overall` written by `score_prompts`. SQLite `CAST AS REAL` reads the leading numeric component (the `spec` value, not `overall`). |
| `image_status` | `TEXT CHECK IN ('pending','generating','done','failed','published')` | **Hard-coded filter** (`WHERE image_status = 'done'`) | Added via `ALTER TABLE` migration (`schema.py:252`). |
| `image_gcs_url` | `TEXT` | **Hard-coded filter** (`AND image_gcs_url IS NOT NULL`) | **V3.3 drift target**: will be replaced by `image_local_path IS NOT NULL` after GCS removal. |

### Columns present in schema but **not read** by build_html

These exist in `prompts` but the builder ignores them:

- `scrape_run_id` (FK to `scrape_runs`)
- `author_id` (FK to `authors`)
- `view_count` (read by other tools, but not embedded in the HTML payload)
- `extracted_at`
- `image_generated_at`
- `category_path`
- `embedding_vector` (BLOB; read by `search_prompts`)
- `needs_image`

## JOIN — `tweets`

Joined for **one** field only:

| Column | Read for | Notes |
|---|---|---|
| `tweets.created_at` | `{{published_at}}` (formatted YYYY-MM-DD via `_format_date()`) | LEFT JOIN — NULL becomes `""` and the date `<span>` is stripped from the detail page. |

## Indexes used

| Index | Defined at | Used when |
|---|---|---|
| `idx_prompts_category` | `schema.py:125` | `--category cinematic` filter — O(log n) lookup. |
| `idx_prompts_quality` | `schema.py:126` | `--min-score 0.5` filter and the always-on `ORDER BY quality_scores DESC` — index is on the raw TEXT column, so `CAST AS REAL` still does a sequential cast on the index-ordered rows. |

The `image_status='done' AND image_gcs_url IS NOT NULL` filter is **not indexed** — it's a sequential scan after the category/quality filter. For the current corpus size this is fast (< 1000 done rows); revisit if the table grows past ~100k.

## Sample query (post all filters)

```sql
SELECT p.*, t.created_at
FROM prompts p
LEFT JOIN tweets t ON p.tweet_id = t.tweet_id
WHERE p.image_status = 'done'
  AND p.image_gcs_url IS NOT NULL
  AND p.category = 'cinematic'                       -- optional
  AND CAST(p.quality_scores AS REAL) >= 0.5          -- optional
ORDER BY CAST(p.quality_scores AS REAL) DESC;
-- Then sliced by `prompts[:limit]` in Python.
```

## V3.3 schema migration impact

When the `image_local_path` column is added (per `docs/11_ToolInterface.md` line 187):

1. Add `OR p.image_local_path IS NOT NULL` to the WHERE clause (transition window).
2. After GCS removal, replace `image_gcs_url IS NOT NULL` entirely with `image_local_path IS NOT NULL`.
3. The `image_status` column itself is also slated for replacement by a `has_cover_image` boolean flag (`docs/11_ToolInterface.md` line 432). When that lands, change `image_status = 'done'` to `has_cover_image = 1`.
