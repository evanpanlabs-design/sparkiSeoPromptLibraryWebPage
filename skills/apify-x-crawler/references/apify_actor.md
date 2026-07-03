# Apify Actor Reference

## Actor

- **Actor id:** `nfp1fpt5gUlBwPcor` (Apify `twitter-scraper-lite`)
- **Purpose:** X/Twitter search scraping for the Veo Prompt Library raw tweet pool.
- **Called by:** `src/crawler/apify.py` → `ApifyCrawler.crawl()` via `ApifyClient(token=APIFY_API_TOKEN)`.

## Required Credentials

- Environment variable: `APIFY_API_TOKEN`
- The token must have permission and balance to call the actor. The env-var name itself is configurable through `crawler.apify.api_token_env` in `configs/crawler.yaml` (default: `APIFY_API_TOKEN`).

## Run Input

```json
{
  "searchTerms": ["Veo prompt"],
  "maxItems": 500,
  "sort": "Latest + Top",
  "includeSearchTerms": false
}
```

The project also passes, at the client level:

- `max_total_charge_usd`: from `tool_crawl_tweets(args)["max_cost"]` (default `0.10`)
- `timeout_secs`: derived from `crawler.apify.timeout_ms / 1000` (default `600_000` ms = 600 s)

## Supported Args (passed by `tool_crawl_tweets`)

| Field | Source | Notes |
|---|---|---|
| `searchTerms` | `queries` | One actor run per query. |
| `maxItems` | `max_items` | Default in tool wrapper: `500`. |
| `sort` | `sort` | `Latest + Top`, `Latest`, or `Top`. |
| `includeSearchTerms` | `include_search_terms` | Default `false`. |

## Output Fields Used

| Actor field | Meaning | Mapped to |
|---|---|---|
| `id` | Tweet id. | `tweet_id` |
| `url` | Tweet URL (Apify-preferred, falls back to `https://x.com/{screen_name}/status/{id}`). | `url` |
| `text` / `fullText` | Tweet body. Whichever is non-empty wins; identical to `short_text` for Apify. | `text`, `short_text` |
| `author.name` | Display name. | `author_name` |
| `author.userName` | X handle. | `author_screen` |
| `author.url` | Author profile URL. | author nested `profile_url` |
| `author.followers` | Follower count from actor context (search-context value, not profile-page value). | `author_followers` |
| `likeCount` | Like count. | `likes_count` |
| `retweetCount` | Retweet count. | `retweet_count` |
| `replyCount` | Reply count. | `reply_count` |
| `viewCount` | View count. | `view_count` |
| `createdAt` | Source timestamp returned by Apify. | kept in normalized dict, **not** currently written into `tweets.created_at` |

`ApifyCrawler._map_actor_item()` returns `None` for items with an empty `id` — those are silently dropped, which is why the row count in the wrapper's return string may be lower than the actor's dataset length.

## Status Handling

- `SUCCEEDED` and `TIMED-OUT` are both treated as "data is available" — the wrapper still reads `defaultDatasetId` and pulls items, because a TIMED-OUT run often has partial data.
- Other statuses (e.g. `FAILED`, `ABORTED`, `RUNNING`) raise a `RuntimeError` and the retry loop kicks in.

## Cost Policy

Production runs must explicitly choose a budget policy. Current mismatch:

- `configs/crawler.yaml` → `apify.max_cost_usd: 10.0` (legacy field; not consumed by the tool)
- `tool_crawl_tweets()` default → `max_cost=0.10`

Use a small run first (e.g. `max_cost=0.05`, `max_items=20`), then increase only after confirming output quality and Apify cost. Apify's own per-run cost is reported on the run page; reconcile against the wrapper's `爬取完成:` summary before any multi-query production run.

## Retry Policy

- `crawler.apify.max_retries` (default `2`) plus the initial attempt = up to 3 attempts per query.
- `crawler.apify.retry_delay_s` (default `30`) between attempts.
- On final failure, `tool_crawl_tweets` returns `错误: RuntimeError: Apify crawl failed after 3 attempts: {last_error}`.
