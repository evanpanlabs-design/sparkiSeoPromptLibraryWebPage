# Handoff Checklist

## Install

- [ ] Run `pip install -r requirements.txt`.
- [ ] Install the missing dependency: `pip install apify-client`.
- [ ] Confirm `pyyaml` and `python-dotenv` are available.
- [ ] *(Recommended)* Add `apify-client` to `requirements.txt` so a fresh install picks it up.

## Configure

- [ ] Set `APIFY_API_TOKEN` in the shell or `.env` (token must have permission to call actor `nfp1fpt5gUlBwPcor` and have Apify account balance).
- [ ] Confirm `configs/crawler.yaml` has `crawler.type: "apify"`.
- [ ] Confirm `crawler.apify.actor_id` is `nfp1fpt5gUlBwPcor`.
- [ ] Decide on a cost policy — either the call-level `max_cost` argument or the config-level `apify.max_cost_usd` (currently they disagree: `0.10` vs `10.0`).
- [ ] Review default queries in `configs/queries.yaml`.
- [ ] *(Optional)* Add `APIFY_API_TOKEN` to `.env.example` with a placeholder so the next operator does not miss it.

## Initialize

- [ ] Run `python -m src.main init-db` if `data/veo_prompts.db` is missing.
- [ ] Confirm the `tweets` table exists:

  ```bash
  python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print(c.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='tweets'\").fetchone())"
  ```

## Smoke Test

```bash
python apify-x-crawler/scripts/crawl_tweets.py \
  --project-root . \
  --query "Veo prompt" \
  --max-items 20 \
  --max-cost 0.05
```

Expected:

- Exit code `0`.
- Output starts with `爬取完成:`.
- The wrapper prints one line per query with the count of tweets crawled.

## Verify

- [ ] Command exits with code `0` (non-zero = see "Escalation" below).
- [ ] Output includes `爬取完成`.
- [ ] `SELECT COUNT(*) FROM tweets;` increases, or stays stable if all `tweet_id`s were already present (duplicate replacement).
- [ ] Sample rows have non-empty `tweet_id`, `url`, `text`, and `author_screen`:

  ```sql
  SELECT tweet_id, author_screen, likes_count, view_count
  FROM tweets
  ORDER BY created_at DESC
  LIMIT 5;
  ```

- [ ] No rows have `text IS NULL OR length(trim(text)) = 0` (run the validation SQL in `database_schema.md`).

## Hand Off To The Next Skill

- [ ] Trigger `extract_prompts` (e.g. via Agent message: "提取前 50 条 prompt") so the freshly inserted rows are processed.
- [ ] Keep this skill's logs around for the first production run — the Apify run page links from each `tweet_id` are useful when triaging noisy extractions.

## Escalation

| Symptom | Likely cause | Action |
|---|---|---|
| `ModuleNotFoundError: apify_client` | Dependency missing. | `pip install apify-client`; then add to `requirements.txt`. |
| `RuntimeError: Apify crawl failed ... 401` / `403` | Token invalid or actor permission missing. | Verify token and Apify account role; rotate token if needed. |
| `RuntimeError: Apify crawl failed ... 402` | Insufficient Apify balance. | Top up the Apify account, then lower `max_cost` while you diagnose. |
| `错误: 没有配置搜索关键词…` | `configs/queries.yaml` is missing `queries:`. | Add at least one query to the file, or pass `--query` on the CLI. |
| Empty results, no error | Query too specific, `max_items` too low, or `max_cost` too low. | Broaden the query, raise `max_items`, or raise `max_cost` slightly. |
| `错误: RuntimeError: Apify crawl failed after 3 attempts: ...` | Actor repeatedly timing out. | Lower `max_items` per query, raise `timeout_ms` in `configs/crawler.yaml`, or split into more queries with smaller `max_cost` each. |
| Tweets have followers = `0` for known accounts | `author.followers` is a search-context value from the actor and may be absent for some entries. | Acceptable for the current pipeline; if profile-level followers are needed, add an enrichment pass. |
| High Apify cost on a single run | Budget policy mismatch — wrapper default `0.10` vs YAML `10.0`. | Pick one policy; set the other to `None` or align the values. |
