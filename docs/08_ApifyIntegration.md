# Apify Integration — Twitter Scraper Component

> **Actor**: `twitter-scraper-lite` (`nfp1fpt5gUlBwPcor`)
> **Apify Console**: https://console.apify.com/actors/nfp1fpt5gUlBwPcor

---

## 1. Overview

The Apify crawler is a drop-in replacement for the Playwright `BrowserManager`-based X.com scraper. It delegates to the Apify cloud platform, which handles browser infrastructure, proxy rotation, and rate limiting server-side. This eliminates cookie management, anti-bot detection, and session maintenance that the Playwright path requires.

**Key advantages over Playwright**:
- No cookie/session management
- No User-Agent spoofing or proxy setup
- Server-side execution (not bandwidth-constrained)
- Predictable cost per tweet via `max_total_charge_usd`

**Key limitation**:
- Author enrichment via profile-page visit is not available (followers come from search-context metadata)
- Detail enrichment (view counts from tweet page) is not available — Apify provides views from search context

---

## 2. Architecture

```
src/crawler/apify.py          ApifyCrawler class
    └── _map_actor_item()       Maps Apify fields → pipeline format
    └── crawl(query, max_cost_usd)  Starts Actor, polls, returns tweets

configs/crawler.yaml           type: "apify" + apify.* settings
src/types/config.py            CrawlerConfig with apify fields
src/agent/nodes.py              _crawl_query() dispatches to ApifyCrawler
```

---

## 3. Configuration

**`configs/crawler.yaml`**:

```yaml
crawler:
  type: "apify"   # switch from "browser"

  apify:
    actor_id: "nfp1fpt5gUlBwPcor"
    api_token_env: "APIFY_API_TOKEN"   # token read from env var
    timeout_ms: 120000                 # 2 min
    max_retries: 2
    retry_delay_s: 30
    max_cost_usd: 1.0                  # ~200 tweets per query
```

**Environment variable**:

```bash
export APIFY_API_TOKEN="your_apify_token_here"
```

---

## 4. API — ApifyCrawler

### Constructor

```python
ApifyCrawler(
    actor_id: str = "nfp1fpt5gUlBwPcor",
    api_token: str = "",      # or from APIFY_API_TOKEN env var
    timeout_ms: int = 120_000,
    max_retries: int = 2,
    retry_delay_s: int = 30,
)
```

### `crawl(query, max_cost_usd=0.05)`

```python
async def crawl(self, query: str, max_cost_usd: float = 0.05) -> list[dict]:
```

Starts the Apify Actor for one search query, waits for completion (blocking `.call()`), fetches the dataset, and maps each item to the pipeline tweet format.

**Returns**: `list[dict]` — each dict contains:

| Field | Type | Description |
|---|---|---|
| `tweet_id` | str | X.com status ID |
| `url` | str | Full `https://x.com/user/status/{id}` |
| `text` | str | Full tweet text |
| `short_text` | str | Same as `text` (no detail visit) |
| `author` | dict | `{ name, screen_name, profile_url, followers_count }` |
| `created_at` | str | X timestamp, e.g. `"Tue May 19 23:09:01 +0000 2026"` |
| `favorite_count` | int | Likes |
| `retweet_count` | int | Retweets |
| `reply_count` | int | Replies |
| `view_count` | int | Views (from search context) |
| `scraped_at` | str | Empty (filled by caller) |
| `author_enriched` | bool | `False` — followers from search, not profile page |
| `detail_enriched` | bool | `False` — views from search, not detail page |

---

## 5. Cost Control

**Pricing model** (twitter-scraper-lite):
- ~$0.005 USD per tweet dataset item saved
- Minimum billing increment: 20 items

**Budget examples**:

| `max_cost_usd` | Approx tweets | Use case |
|---|---|---|
| `0.05` | 125 tweets | Quick test |
| `0.25` | ~500 tweets | Single query |
| `1.00` | ~2000 tweets | Full production run |

The Actor automatically stops when `max_total_charge_usd` is reached. It saves all items collected up to that point.

---

## 6. Apify Actor Input Schema

```python
run_input = {
    "searchTerms": [query],       # list of search terms
    "tweetsDesired": 100,         # target tweets (upper bound)
    "maxTweetsPerQuery": 100,     # max per query term
}
```

Additional Actor options (via Apify Console or API):

| Parameter | Description |
|---|---|
| `sort` | `"Latest"` (default) or `"Top"` |
| `maxItems` | Client-side item limit (not enforced by Actor) |
| `maxTotalChargeUsd` | Max cost budget (use this for control) |

---

## 7. Testing

```bash
# Install apify-client
pip install apify-client

# Set token
export APIFY_API_TOKEN="your_apify_token_here"

# Run minimal test ($1 budget, ~200 tweets)
python test_apify_minimal.py

# Run unit tests
python -m pytest tests/unit/node_contract/test_apify_crawler_contract.py -v
```

---

## 8. Integrating into Pipeline

Switch crawler type in `configs/crawler.yaml`:

```yaml
crawler:
  type: "apify"
```

Then run the pipeline normally:

```bash
export APIFY_API_TOKEN="apify_api_..."
python -m src.main run
```

The `crawler_node` in `nodes.py` handles the routing:

```python
if crawler_type == "apify":
    crawler = ApifyCrawler(actor_id=apify_actor_id, api_token=token)
    tweets = await crawler.crawl(query, max_cost_usd=apify_max_cost_usd)
    return tweets, len(tweets), None
else:
    # Playwright path...
```

---

## 9. Known Differences from Playwright Path

| Aspect | Playwright | Apify |
|---|---|---|
| `author_enriched` | `True` (profile visited) | `False` (search metadata only) |
| `followers_count` | Exact from profile page | Estimate from search context |
| `detail_enriched` | `True` (tweet page visited) | `False` (search context only) |
| `view_count` | Exact from tweet detail page | Estimate from search context |
| Cookie management | Required | None |
| Anti-bot handling | Manual (proxy, delays) | Apify-managed |

The pipeline downstream (worker_node, quality_scorer_node) does not require `author_enriched=True`. Filter thresholds (`min_followers`, `min_views`) use the Apify-supplied values which are approximate but functional for the filtering pipeline.