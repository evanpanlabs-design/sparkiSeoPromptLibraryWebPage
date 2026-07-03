# Database Contract

## Target DB

- **Path:** `data/veo_prompts.db`
- **Schema source:** `src/memory/schema.py` (`SCHEMA` literal, applied by `init_db()`)
- **Target table:** `tweets`
- **Write mode:** `INSERT OR REPLACE` keyed on `tweet_id` (the column has a `UNIQUE` constraint)

## `tweets` Table Layout

| Column | Type | Source / Notes |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | DB-internal row id. |
| `tweet_id` | `TEXT NOT NULL UNIQUE` | Apify `id`. The `INSERT OR REPLACE` key. |
| `url` | `TEXT NOT NULL` | Apify `url`, or `https://x.com/{screen_name}/status/{id}`. |
| `text` | `TEXT` | Apify `text` (preferred) or `fullText`. |
| `short_text` | `TEXT` | Same as `text` for Apify — no detail-page enrichment happens. |
| `author_name` | `TEXT` | `author.name`. |
| `author_screen` | `TEXT` | `author.userName`. |
| `author_followers` | `INTEGER DEFAULT 0` | `author.followers` (search-context value). |
| `likes_count` | `INTEGER DEFAULT 0` | `likeCount`. |
| `retweet_count` | `INTEGER DEFAULT 0` | `retweetCount`. |
| `reply_count` | `INTEGER DEFAULT 0` | `replyCount`. |
| `view_count` | `INTEGER DEFAULT 0` | `viewCount`. |
| `scraped_at` | `TEXT` | Empty string from the current mapping (the Apify item does not carry a separate scrape timestamp). |
| `detail_enriched` | `INTEGER DEFAULT 0` | Always `0` from this skill — no detail-page visits. |
| `prompt_text` | `TEXT` | Filled later by the `extract_prompts` skill; `NULL` for fresh crawl rows. |
| `category` | `TEXT` | Filled later by the `extract_prompts` skill; `NULL` for fresh crawl rows. |
| `title` | `TEXT` | Filled later by the `extract_prompts` skill; `NULL` for fresh crawl rows. |
| `notes` | `TEXT` | Filled later by the `extract_prompts` skill; `NULL` for fresh crawl rows. |
| `created_at` | `TEXT NOT NULL` | Insertion timestamp in UTC ISO-8601 — **not** the tweet's `createdAt` from Apify. |

## Fields Written by `crawl_tweets`

| `tweets` column | Source |
|---|---|
| `tweet_id` | Apify `id` |
| `url` | Apify `url` or fallback X status URL |
| `text` | Apify `text` or `fullText` |
| `short_text` | Same as `text`; no detail-page enrichment |
| `author_name` | `author.name` |
| `author_screen` | `author.userName` |
| `author_followers` | `author.followers` |
| `likes_count` | `likeCount` |
| `retweet_count` | `retweetCount` |
| `reply_count` | `replyCount` |
| `view_count` | `viewCount` |
| `scraped_at` | Empty string from mapped item |
| `detail_enriched` | `0` |
| `created_at` | Current UTC insertion time (overwritten on re-insert) |

## Important Data Semantics

- `author_enriched=False` and `detail_enriched=False` (in the normalized dict) mean the crawler does **not** visit author profile pages or tweet detail pages. Follower counts are whatever the actor saw during the search.
- `short_text == text`: Apify output is treated as full enough for downstream extraction.
- The Apify `createdAt` field is present in the normalized dict but is **not** written into the `tweets.created_at` column by `tool_crawl_tweets()`. If a future schema requires tweet-post time, add a column and write it explicitly.
- `INSERT OR REPLACE` means a re-crawl of the same `tweet_id` overwrites all of the columns above and resets `created_at` to the new insert time. Anything downstream of `created_at` (e.g. the recent-tweets ordering in the HTML page) will re-rank accordingly.

## Validation SQL

```sql
-- Total rows
SELECT COUNT(*) FROM tweets;

-- Recent rows
SELECT tweet_id, author_screen, likes_count, view_count, substr(text, 1, 120)
FROM tweets
ORDER BY created_at DESC
LIMIT 10;

-- Empty-text rows (should be zero for healthy crawls)
SELECT COUNT(*) AS rows_missing_text
FROM tweets
WHERE text IS NULL OR length(trim(text)) = 0;

-- Per-query / per-day distribution
SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS rows_added
FROM tweets
GROUP BY day
ORDER BY day DESC
LIMIT 14;
```

## Downstream Contract

The next skill, `prompt-extractor`, expects rows in `tweets` with:

- non-empty `tweet_id`, `url`, and `text`
- usable `author_screen` and engagement metrics (`likes_count`, `view_count`)

It does **not** require image fields or quality scores. Run `extract_prompts` immediately after a successful `crawl_tweets` to keep the pipeline moving, and re-run `crawl_tweets` only when the raw tweet pool needs fresh posts.
