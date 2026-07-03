---
name: apify-x-crawler
description: Crawl X/Twitter posts for the Veo Prompt Library through Apify and write normalized tweet rows into the local SQLite pipeline database. Use when the agent needs fresh X posts for Veo/Gemini/video prompt discovery, needs to run or debug the crawl_tweets phase, or needs to verify the Apify actor output mapping.
---

# Apify X Crawler

## What It Does
Crawl X/Twitter search results through Apify Actor `nfp1fpt5gUlBwPcor`, normalize actor items into the project tweet schema, and write rows into `data/veo_prompts.db` table `tweets`. This is the upstream of the Veo Prompt Library pipeline — it does not call any LLM, and it does not extract prompts or score them.

## When To Use
Use this skill before prompt extraction when the raw tweet pool needs fresh posts. Do not use it for prompt extraction, scoring, image generation, HTML build, sitemap generation, or publishing.

## Required Context
- Project root: `16_NewCrawler`
- Main code: `src/crawler/apify.py` (`ApifyCrawler`), `src/agent/skills/core_tools.py` (`tool_crawl_tweets`)
- Config: `configs/crawler.yaml`, `configs/queries.yaml`
- Database: `data/veo_prompts.db`
- Required env: `APIFY_API_TOKEN`

## Preconditions
1. Install runtime dependencies: `pip install -r requirements.txt` plus `pip install apify-client` (currently missing from `requirements.txt`).
2. Set `APIFY_API_TOKEN` in the shell or `.env`.
3. Run `python -m src.main init-db` if the SQLite database or `tweets` table does not exist.
4. Confirm `configs/crawler.yaml` has `crawler.type: "apify"` and `crawler.apify.actor_id: "nfp1fpt5gUlBwPcor"`.
5. Confirm `configs/queries.yaml` has the default search terms you want to crawl.

## Inputs
| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `queries` | `list[str]` | `configs/queries.yaml` | X search terms to crawl. |
| `from_cache` | `bool` | `False` | Skip actual crawl and return a cache-mode message. |
| `max_cost` | `float` | `0.10` | Apify `max_total_charge_usd` per query in USD. |
| `max_items` | `int` | `500` | Apify `maxItems` per query. |
| `sort` | `str` | `Latest + Top` | Actor sort order: `Latest + Top`, `Latest`, or `Top`. |
| `include_search_terms` | `bool` | `False` | Whether actor results include matched search terms. |

## Outputs
- Returns a human-readable status string such as `爬取完成: {total_tweets} tweets, {query_count} queries` on success, or `错误: {ExceptionType}: {message}` on failure.
- Side effect: writes normalized tweet rows into `tweets` via `INSERT OR REPLACE` (key: `tweet_id`).
- A `爬取完成: 使用缓存模式…` message is returned (no DB writes) when `from_cache=True`.

## Data Contract
| Apify item | Normalized dict | tweets field |
|---|---|---|
| `id` | `tweet_id` | `tweet_id` |
| `url` | `url` | `url` |
| `text` or `fullText` | `text`, `short_text` | `text`, `short_text` |
| `author.name` | `author.name` | `author_name` |
| `author.userName` | `author.screen_name` | `author_screen` |
| `author.followers` | `author.followers_count` | `author_followers` |
| `likeCount` | `favorite_count` | `likes_count` |
| `retweetCount` | `retweet_count` | `retweet_count` |
| `replyCount` | `reply_count` | `reply_count` |
| `viewCount` | `view_count` | `view_count` |
| `createdAt` | `created_at` | source timestamp, currently not written into `tweets.created_at` by `tool_crawl_tweets` |
| — | — | `detail_enriched` = `0` |

## Procedure
1. Load query list from args, falling back to `configs/queries.yaml`.
2. Load Apify config from `configs/crawler.yaml` (`apify.actor_id`, `apify.api_token_env`, `apify.timeout_ms`, `apify.max_retries`, `apify.retry_delay_s`).
3. Resolve `APIFY_API_TOKEN` from the env var named in `apify.api_token_env` (default: `APIFY_API_TOKEN`).
4. Build `ApifyCrawler(actor_id, api_token, timeout_ms, max_retries, retry_delay_s)`.
5. For each query, call `await crawler.crawl(query, max_cost_usd=max_cost, max_items=max_items, sort=sort, include_search_terms=include_search_terms)`.
6. For each mapped tweet, run `INSERT OR REPLACE INTO tweets` with the columns listed in the Data Contract table.
7. Commit after each query and report total crawled rows.

## Validation
Run a small crawl before any large production run:

```bash
python -m src.main init-db
python apify-x-crawler/scripts/crawl_tweets.py \
  --project-root . \
  --query "Veo prompt" \
  --max-items 20 \
  --max-cost 0.05
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print(c.execute('select count(*) from tweets').fetchone()[0])"
```

The wrapper exits with code `0` on success and `1` if the tool returns a `错误:` string.

## Failure Handling
- `apify-client is not installed`: install `apify-client`; it is currently missing from `requirements.txt`.
- Empty or missing `APIFY_API_TOKEN`: set the token, or fix `crawler.apify.api_token_env` to point at a different env var.
- Actor timeout: the code still reads the default dataset if Apify returns `TIMED-OUT` (the wrapper does not raise).
- Empty results: check query wording, `max_cost`, `max_items`, actor availability, and Apify account balance.
- Repeated retry exhaustion: lower `max_cost_usd`, narrow query scope, or check the Apify dashboard for account status.

## Handoff Notes
- Current `configs/crawler.yaml` sets `apify.max_cost_usd: 10.0`, while `tool_crawl_tweets()` defaults to `max_cost=0.10`. Pick one budget policy before production handoff.
- Apify author and view metrics are search-context values. `author_enriched=False` and `detail_enriched=False` mean no profile-page or detail-page enrichment happened.
- Add `APIFY_API_TOKEN` to `.env.example` during cleanup so a new operator does not miss it.
- See `references/handoff_checklist.md` for a copy-pasteable runbook and `references/database_schema.md` for the `tweets` table contract.
