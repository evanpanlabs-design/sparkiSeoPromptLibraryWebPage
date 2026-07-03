# Database Contract — extract_prompts

## Target DB

- **Path:** `data/veo_prompts.db`
- **Schema source:** `src/memory/schema.py` (`SCHEMA` literal, applied by `init_db()`).
- **Tables touched by this skill:** `tweets` (UPDATE 4 cols), `prompts` (INSERT 15 cols), and **`category_suggestions` is never written to** — see the Handoff Notes in `SKILL.md`.
- **Tables read by this skill:** `tweets` (SELECT), `categories` (SELECT for known-category filter, falls back to `["video-generation", "cinematic", "other"]` if empty).

---

## `tweets` Table Layout

Verified by `PRAGMA table_info(tweets)` on the live DB:

| Col# | Column | Type | NOT NULL | DEFAULT | Notes |
|---|---|---|---|---|---|
| 0 | `id` | INTEGER | ✓ | autoincrement | DB-internal row id. |
| 1 | `tweet_id` | TEXT | ✓ | — | Apify `id`. `UNIQUE`. The `INSERT OR REPLACE` key for `crawl_tweets`. |
| 2 | `url` | TEXT | ✓ | — | Apify `url` or `https://x.com/{screen_name}/status/{id}`. |
| 3 | `text` | TEXT | — | NULL | Tweet body. NULL is allowed (the source row may be empty before enrichment). |
| 4 | `short_text` | TEXT | — | NULL | Search-card text. |
| 5 | `author_name` | TEXT | — | NULL | `author.name`. |
| 6 | `author_screen` | TEXT | — | NULL | `author.userName`. |
| 7 | `author_followers` | INTEGER | — | 0 | `author.followers` (search-context value). |
| 8 | `likes_count` | INTEGER | — | 0 | |
| 9 | `retweet_count` | INTEGER | — | 0 | |
| 10 | `reply_count` | INTEGER | — | 0 | |
| 11 | `view_count` | INTEGER | — | 0 | |
| 12 | `scraped_at` | TEXT | — | NULL | Apify timestamp (often empty). |
| 13 | `detail_enriched` | INTEGER | — | 0 | Always 0 from current pipeline. |
| 14 | `prompt_text` | TEXT | — | NULL | **Filled by this skill. NULL means "not yet extracted".** |
| 15 | `category` | TEXT | — | NULL | **Filled by this skill. NULL means "not yet extracted".** |
| 16 | `title` | TEXT | — | NULL | **Filled by this skill. NULL means "not yet extracted".** |
| 17 | `notes` | TEXT | — | NULL | **Filled by this skill. NULL means "not yet extracted".** |
| 18 | `created_at` | TEXT | ✓ | — | UTC ISO-8601 insertion time. |

### `tweets` — Fields Written by `extract_prompts`

The skill does **one** UPDATE per extracted prompt (`core_tools.py:210-226`):

| `tweets` column | Source |
|---|---|
| `prompt_text` | LLM extraction result (`prompt_obj.prompt_text`). |
| `category` | LLM extraction result, **downgraded to `"other"` if it was a new category** (see `build_extracted_prompt()` in `extractor.py:480-525`). |
| `title` | LLM extraction result (`prompt_obj.title`). |
| `notes` | LLM extraction result (`prompt_obj.notes`). |

The WHERE clause is `tweet_id = ?`. **No other column is touched.** The `likes_count`, `view_count`, `author_*`, `created_at` columns stay frozen.

The pre-LLM SELECT filters with `WHERE prompt_text IS NULL ORDER BY likes_count DESC LIMIT ?` — confirmed compatible with the nullable `TEXT` column.

---

## `prompts` Table Layout

Verified by `PRAGMA table_info(prompts)` on the live DB:

| Col# | Column | Type | NOT NULL | DEFAULT | Notes |
|---|---|---|---|---|---|
| 0 | `id` | INTEGER | ✓ | autoincrement | DB-internal row id. |
| 1 | `tweet_id` | TEXT | ✓ | — | **UNIQUE.** The `INSERT OR REPLACE` key. |
| 2 | `scrape_run_id` | INTEGER | — | NULL | FK to `scrape_runs.id`. Not set by this skill. |
| 3 | `url` | TEXT | ✓ | — | |
| 4 | `category` | TEXT | ✓ | — | `NOT NULL` — must always be a non-empty string. The skill writes `"other"` as the safe fallback for new categories. |
| 5 | `title` | TEXT | ✓ | — | `NOT NULL` — empty string `""` if the LLM didn't provide one. |
| 6 | `prompt_text` | TEXT | ✓ | — | `NOT NULL` — the actual prompt text. |
| 7 | `notes` | TEXT | — | NULL | |
| 8 | `author_id` | INTEGER | — | NULL | FK to `authors.id`. Not set by this skill. |
| 9 | `likes_count` | INTEGER | — | 0 | |
| 10 | `retweet_count` | INTEGER | — | 0 | |
| 11 | `reply_count` | INTEGER | — | 0 | |
| 12 | `view_count` | INTEGER | — | 0 | |
| 13 | `quality_scores` | TEXT | — | NULL | CSV `"spec,vis,nov,gen,overall"`, set later by `score_prompts`. This skill writes `NULL`. |
| 14 | `extracted_at` | TEXT | ✓ | — | UTC ISO-8601 at insert time. |
| 15 | `image_gcs_url` | TEXT | — | NULL | Set later by `generate_images` (V3.2). |
| 16 | `image_generated_at` | TEXT | — | NULL | |
| 17 | `category_path` | TEXT | — | NULL | |
| 18 | `embedding_vector` | BLOB | — | NULL | Set by `search_prompts` later. |
| 19 | `needs_image` | INTEGER | — | 1 | Added by `_migrate_prompts_needs_image` (`schema.py:182`). |
| 20 | `image_status` | TEXT | — | `'pending'` | CHECK constraint: `'pending'`, `'generating'`, `'done'`, `'failed'`, `'published'`. **This skill hard-codes `'pending'`.** |
| 21 | `embedding_status` | TEXT | — | `'pending'` | CHECK: `'pending'`, `'embedded'`, `'failed'`. Not set by this skill. |
| 22 | `author_name` | TEXT | — | NULL | denormalized (added by `_migrate_prompts_author_cols`). |
| 23 | `author_screen` | TEXT | — | NULL | denormalized. |
| 24 | `author_followers` | INTEGER | — | 0 | denormalized. |

### `prompts` — Fields Written by `extract_prompts`

The skill does **one** INSERT per extracted prompt (`core_tools.py:229-254`):

| `prompts` column | Source | Notes |
|---|---|---|
| `tweet_id` | `tweet.tweet_id` | `UNIQUE` key — collision re-INSERTs the same row. |
| `url` | `tweet.url` | |
| `category` | `prompt_obj.category` | Already downgraded to `"other"` if it was new. |
| `title` | `prompt_obj.title` | Empty string `""` if missing. |
| `prompt_text` | `prompt_obj.prompt_text` | Empty string `""` if missing. |
| `notes` | `prompt_obj.notes` | |
| `author_name` | `tweet.author.name` | denormalized. |
| `author_screen` | `tweet.author.screen_name` | denormalized. |
| `author_followers` | `tweet.author.followers_count` | denormalized. |
| `likes_count` | `tweet.favorite_count` | |
| `retweet_count` | `tweet.retweet_count` | |
| `reply_count` | `tweet.reply_count` | |
| `view_count` | `tweet.view_count` | |
| `extracted_at` | `datetime.now(timezone.utc).isoformat()` | |
| `image_status` | `'pending'` | Hard-coded. |
| `quality_scores` | `NULL` | Set later by `score_prompts`. |

The INSERT uses `INSERT OR REPLACE` — re-running on an already-extracted tweet overwrites the row. This means `image_status` is reset to `'pending'` on every re-run, which can break `generate_images` if the row was already published. **Caveat:** if the pipeline has already started generating / publishing an image, do not re-run `extract_prompts` on that tweet.

---

## `categories` Table Layout

| Col# | Column | Type | Notes |
|---|---|---|---|
| 0 | `id` | INTEGER PK | |
| 1 | `name` | TEXT NOT NULL UNIQUE | The "known" category. |
| 2 | `description` | TEXT | |
| 3 | `color` | TEXT | |
| 4 | `created_at` | TEXT NOT NULL | |

**Read by this skill** (`core_tools.py:172-173`): the `name` column. If the table is empty, the skill falls back to the hard-coded list `["video-generation", "cinematic", "other"]`.

**Current production state: 0 rows.** Every LLM-suggested label is therefore treated as "new" and downgraded to `"other"`.

---

## `category_suggestions` Table Layout

| Col# | Column | Type | Notes |
|---|---|---|---|
| 0 | `id` | INTEGER PK | |
| 1 | `suggested_name` | TEXT NOT NULL | |
| 2 | `suggested_desc` | TEXT | |
| 3 | `reason` | TEXT NOT NULL | |
| 4 | `suggested_by` | TEXT NOT NULL | Hard-coded `"gemini-3.5-flash"` in `extractor.py:500`. |
| 5 | `sample_prompt` | TEXT NOT NULL | First 200 chars of `result.prompt_text`. |
| 6 | `status` | TEXT DEFAULT `'pending'` | `pending` / `approved` / `rejected`. |
| 7 | `reviewed_at` | TEXT | |
| 8 | `reviewed_by` | TEXT | |
| 9 | `created_at` | TEXT NOT NULL | |

**Written by this skill: 0 rows** (verified against the live DB and the `tool_extract_prompts()` source). The skill builds `CategorySuggestion` objects in `build_extracted_prompt()` (line 480-525) but `tool_extract_prompts()` discards the second return value (`prompt_obj, _ = ...` at `core_tools.py:204`).

This is a known drift — see `SKILL.md` Handoff Notes for the proposed one-liner fix.

---

## Two-Table Write Summary

```
┌──────────────────────────┐                  ┌──────────────────────────┐
│  tweets (UPDATE 4 cols)  │                  │  prompts (INSERT 15+2)   │
├──────────────────────────┤                  ├──────────────────────────┤
│  prompt_text  ← LLM      │                  │  tweet_id         ← row  │
│  category     ← LLM/other│                  │  url              ← row  │
│  title        ← LLM      │                  │  category         ← LLM/other │
│  notes        ← LLM      │                  │  title            ← LLM  │
│  (WHERE tweet_id = ?)    │                  │  prompt_text      ← LLM  │
│                          │                  │  notes            ← LLM  │
│  Untouched:              │                  │  author_name/screen/foll │
│   - likes_count          │                  │  likes/retweet/reply/view│
│   - view_count           │                  │  extracted_at     ← now  │
│   - author_*             │                  │  image_status     ← 'pending' │
│   - created_at           │                  │  quality_scores   ← NULL │
└──────────────────────────┘                  └──────────────────────────┘
       │                                              │
       └──────────── single conn.commit() ────────────┘
                       (core_tools.py:257)
```

---

## Validation SQL

```sql
-- 1. Pending extraction pool
SELECT COUNT(*) AS pending
FROM tweets
WHERE prompt_text IS NULL;

-- 2. Already-extracted rows
SELECT COUNT(*) AS extracted
FROM tweets
WHERE prompt_text IS NOT NULL;

-- 3. Latest extractions (with prompt preview)
SELECT tweet_id, category, title, substr(prompt_text, 1, 80) AS preview
FROM prompts
ORDER BY extracted_at DESC
LIMIT 10;

-- 4. Sanity: no extractions should be older than the corresponding tweet
SELECT t.tweet_id, t.created_at AS tweet_seen_at, p.extracted_at
FROM prompts p JOIN tweets t ON p.tweet_id = t.tweet_id
WHERE p.extracted_at < t.created_at;

-- 5. Check that every prompt has a category (NOT NULL contract)
SELECT tweet_id FROM prompts WHERE category IS NULL OR category = '';

-- 6. Sample rejected-by-filter tweets (content filter)
SELECT tweet_id, substr(text, 1, 100) AS text
FROM tweets
WHERE prompt_text IS NULL
  AND (lower(text) NOT LIKE '%veo%' OR length(text) - length(replace(text, ' ', '')) + 1 < 15)
ORDER BY likes_count DESC
LIMIT 10;

-- 7. category_suggestions (should remain 0 — drift is documented)
SELECT COUNT(*) FROM category_suggestions;

-- 8. categories (currently 0 — every LLM label becomes "other")
SELECT COUNT(*) FROM categories;
```

---

## Index Strategy

Relevant indexes (from `schema.py:125-128`):

- `idx_prompts_category` on `prompts(category)` — speeds up `generate_images` / `build_html` category filters.
- `idx_prompts_quality` on `prompts(quality_scores)` — speeds up score-based queries.

There is **no index on `tweets.prompt_text`**. The `WHERE prompt_text IS NULL` scan is a full table scan but is fine for the current ~9,000 row size. Add an index if the table grows past 100K rows.
