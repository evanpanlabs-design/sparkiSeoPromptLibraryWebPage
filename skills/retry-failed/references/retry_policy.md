# Retry Policy — Sequential vs Parallel

> This file explains **why** `tool_retry_failed` uses the single-shot `RateLimitSafeGenerator.generate()` method in a serial loop, while `tool_generate_images` uses the parallel `RateLimitSafeGenerator.generate_batch()` method. The two tools are intentionally different.

---

## TL;DR

| Aspect | `tool_generate_images` | `tool_retry_failed` |
|---|---|---|
| Generator method | `RateLimitSafeGenerator.generate_batch()` (parallel) | `RateLimitSafeGenerator.generate()` (single-shot, called in a `for` loop) |
| Concurrency | `ThreadPoolExecutor(max_workers=3)` | Serial |
| Per-task interval | `time.sleep(2.0)` in each worker thread | `time.sleep(2.0)` per call (in the loop) |
| Per-task retries on 429 | 3× with exponential backoff (2s, 4s, 8s) | Same — inherited from `_generate_one` |
| `max_workers` setting | **Used** (drives the thread pool size) | **Unused** (dead config in this code path) |
| Default batch | 8 | 8 |
| Read pattern | `WHERE image_status = 'pending' ORDER BY ...` | `WHERE image_status = 'failed' LIMIT ?` (no ORDER BY) |
| Write pattern | Batch-level UPDATE (one transaction) | Per-row UPDATE (in the same transaction) |

---

## Why sequential for retries

The design intent is **fail-loud, not fail-fast**:

1. **Diagnostic value.** When a batch fails, the operator wants to know *which* row failed and *why*. Serial means you can read the failure rate row-by-row. Parallel hides it behind aggregated counts.

2. **Reduce cascade 429s.** If Vertex AI is throttling because the project is at the per-minute quota, firing 3 simultaneous `gemini-2.5-flash-image` requests just makes the throttle worse. Serial + 2s interval keeps the request rate at ≤0.5 req/s, well under the typical Vertex AI default of 60 req/min per model.

3. **The bulk reset is a write-side hazard.** `tool_retry_failed` does a single `UPDATE ... WHERE id IN (...)` before generating. If we used `generate_batch` here, all 3 workers would race to UPDATE different rows — and if the thread pool raised an unhandled exception, we could end up with 0 rows updated (or 3 partially-updated rows). Serial keeps the write semantics linear and easy to reason about.

4. **The "thundering herd" anti-pattern.** If 100 failed rows pile up during a Vertex AI outage, and 5 operators all run `retry_failed` at once with `--batch 8`, parallel mode would generate 40 simultaneous requests. Serial + 2s interval + per-task 3× retry = 40 × ~14s worst case wall time, spread over ~5 minutes.

---

## When NOT to retry in parallel

- **The failure was caused by a quota or rate-limit error.** All parallel retries will hit the same quota. Sequential with backoff gives the quota bucket time to refill.

- **The failure is reproducible on a single row** (e.g. a malformed `prompt_text` that triggers Vertex's content filter). Parallel retries will all fail in the same way. Sequential lets you identify the bad row quickly.

- **The DB is the suspect.** If you suspect the failure was a connection error or a CHECK constraint violation, serial gives you a clean stack trace per row. Parallel hides the first error behind the rest.

---

## When to retry in parallel

- **Failures are non-deterministic** (e.g. transient 5xx errors, network blips). Parallel retries will mostly succeed; the rare failure is acceptable noise.

- **You have confirmed quota headroom** for the model and want maximum throughput.

- **You are doing the initial generation pass**, not a recovery pass. `tool_generate_images` is the right tool for this.

---

## The GCS path coupling

The GCS object key is computed inside `RateLimitSafeGenerator._generate_one()` (called by both `generate()` and `generate_batch()`):

```python
# src/image_gen/generator.py:60-65
image_bytes, model, gcs_url = self._client.generate(
    prompt_text=prompt_text,
    category=category,
    title="",
    tweet_id=str(prompt_id),
)
```

The `tweet_id` keyword is misleadingly named — it is the **integer** `prompts.id` row key, not the X.com snowflake in `prompts.tweet_id`. So the GCS key is:

```
gs://{gcs_bucket}/prompts/{category}/{yyyy-mm}/{prompts.id}.png
```

with `gcs_bucket = "sparki-op-test"` (default), and `yyyy-mm` computed at upload time from `datetime.now(timezone.utc)`.

**Coupling consequence:** if you change `gcs_bucket` in `RateLimitSafeGenerator.__init__`, every retry writes to the new bucket. If the old bucket's objects were already published to GitHub Pages, the rendered HTML will 404. The retry does not delete the old objects.

**Migration consequence (V3.3):** the GCS upload is being abolished entirely. `tool_retry_failed` will write to `outputs/generated_images/{id}.png` instead, and `image_local_path` will be the column. See Handoff Notes drift #1 in `SKILL.md`.

---

## Failure-vs-success row semantics

| Outcome of `generator.generate()` | What the wrapper does | Side effect on `image_status` | Side effect on `image_gcs_url` |
|---|---|---|---|
| Returns a non-empty `gcs_url` string | `UPDATE prompts SET image_gcs_url=?, image_status='done' WHERE id=?` | `'pending' → 'done'` | Overwritten with new GCS URL |
| Returns `None` (falsy) | `UPDATE prompts SET image_status='failed' WHERE id=?` | `'pending' → 'failed'` | Untouched (prior URL may linger) |
| Raises any exception (caught at line 662) | `UPDATE prompts SET image_status='failed' WHERE id=?` | `'pending' → 'failed'` | Untouched |

**Important:** in the failure case, the `image_gcs_url` from a **prior** successful attempt is **not** cleared. So a row can have `image_status='failed'` AND `image_gcs_url='gs://...'` pointing to a stale image. The HTML build (`tool_build_html`) selects `WHERE image_status = 'done'`, so a `'failed'` row with a stale URL is invisible to the build — but the URL is still in the DB and could be exposed by future tools.

---

## Recommended migration to parallel (if needed)

If the V3.3 workload demands parallel retries, the safe way to add it is:

1. Replace the `for row in rows:` loop with a call to `generator.generate_batch(items)`.
2. The result is a `list[dict]` with `{"prompt_id", "gcs_url", "error", "model_used"}` for each input item.
3. Iterate the result and apply the same per-row UPDATE logic.
4. **Add the published-state guard** to the bulk UPDATE: change `WHERE id IN (...)` to `WHERE id IN (...) AND image_status = 'pending'` (i.e. only flip rows we just put in pending). This is a one-line fix and eliminates the published-state-loss caveat.
5. **Write an `image_attempts` row** for each failure with the `error` field from the result dict.

Until then, the serial design is correct for the current V3.2 scale.
