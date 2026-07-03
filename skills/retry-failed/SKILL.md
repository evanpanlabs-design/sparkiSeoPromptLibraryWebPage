---
name: retry-failed
description: Retry cover image generation for prompts whose `prompts.image_status = 'failed'`, by resetting them to `'pending'` and re-invoking `RateLimitSafeGenerator` SEQUENTIALLY (one row at a time, NOT in parallel like `generate_images`). Use when the user says "重试失败的图", "retry failed", "为什么这张图 failed", "跑一下 retry_failed", or after a `generate_images` run that left some rows in `'failed'`. Also use to triage persistent failures for a single prompt. This skill writes `image_gcs_url` (V3.2, will be replaced by `image_local_path` in V3.3). Do NOT use this on `image_status = 'pending'` rows (use `generate_images`), and be aware that the bulk reset of `'failed' → 'pending'` does NOT filter out `'published'` rows — see Handoff Notes caveat.
---

# Retry Failed (V3.2 — Sequential GCS Regeneration)

## What It Does

Selects the next batch of `prompts` rows where `image_status = 'failed'`, bulk-UPDATEs them to `'pending'`, then calls `RateLimitSafeGenerator.generate()` **once per row** in a serial loop. The success path writes `image_gcs_url` and sets `image_status = 'done'`. The failure path leaves `image_status = 'failed'` and increments the per-row `failed` counter.

This is **not** the same code path as `generate_images`:

- `generate_images` → `RateLimitSafeGenerator.generate_batch(...)` → `ThreadPoolExecutor(max_workers=3)` → parallel with per-thread 2s interval.
- `retry_failed` → `RateLimitSafeGenerator.generate(...)` → single-shot sequential loop.

The sequential design is intentional: when an entire batch fails (e.g. Vertex AI is down or a single model version is being throttled), parallelising the retry just produces 8 simultaneous 429 errors. Sequential lets one row succeed and proves the pipeline is healthy before continuing.

## When To Use

- After `tool_generate_images()` returns a string ending in `失败` count > 0.
- When the operator runs `python -c "import sqlite3; ... WHERE image_status='failed'"` and the count is non-zero.
- When triaging a single stubborn prompt: the dry-run mode lists candidate rows so you can inspect `prompt_text`, `category`, and `id` without writing.
- When the user asks: "retry failed", "重试失败的封面图", "重跑 failed 的图", "把 failed 的状态恢复一下".

## When NOT To Use

- For pending rows that have never been attempted → use `generate_images` (it is the only tool that respects `sort_by` / `filter` / `max_workers`).
- For score-only re-evaluation → use `score_prompts`.
- For re-extraction from a tweet that has a `prompt_text` → use `extract_prompts` (this is a separate flow, the prompt rows already exist).
- For publishing a successful prompt to GitHub Pages → use `publish`.

## Required Context

- Project root: `16_NewCrawler`
- Tool implementation: `src/agent/skills/core_tools.py:615-690` (`tool_retry_failed`)
- Generator: `src/image_gen/generator.py` → `RateLimitSafeGenerator.generate(prompt, category, prompt_id)` (the **single-shot** method, NOT `generate_batch`).
- Image client: `src/image_gen/client.py` → `GeminiImageClient` (Vertex AI, GCS upload to `gs://sparki-op-test/prompts/{cat}/{yyyy-mm}/{tweet_id}.png`).
- Schema: `src/memory/schema.py` (`prompts.image_status` added by `_migrate_v3_prompts_cols()` at line 248, with CHECK constraint `IN ('pending','generating','done','failed','published')`).
- V3.2 contract: `docs/11_ToolInterface.md` §10.
- V3.3 migration target: `image_gcs_url` → `image_local_path` (`docs/11_ToolInterface.md` §V3.3).

## Preconditions

1. **Database initialized**: `python -m src.main init-db` (creates `prompts` table and the `image_status` CHECK constraint).
2. **Vertex AI auth**: `GOOGLE_APPLICATION_CREDENTIALS` set, or `gcloud auth application-default login` already run. The `GeminiImageClient` constructor uses `project="sparki-op"`, `location="global"`, `gcs_bucket="sparki-op-test"` (see `generator.py:23-31`).
3. **There is at least one `image_status = 'failed'` row**. If not, the tool returns the no-op string `没有需要重试的failed prompt` and the wrapper exits 0.
4. **GCS write access** to `gs://sparki-op-test/`. If the bucket is down, all retries will fail and the rows will revert to `failed`.

## Inputs

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `batch` | `int` | `8` | Max failed rows to retry in this call. The SELECT is `WHERE image_status = 'failed' LIMIT ?`. No `ORDER BY` — order is implementation-defined (effectively the order of insertion, since `id` is the clustered PK). |

The CLI wrapper (`scripts/retry_failed.py`) additionally accepts `--project-root` and `--dry-run`.

## Outputs

- **Success string**:
  ```
  已重置 {N} 条 failed → pending
  图片生成完成: {S}/{T} 成功, {F}/{T} 失败
  当前池: {P} pending, {D} done, {F} failed
  ```
  where `N` = rows reset, `S` = new successes, `F` = new failures, `T = S + F`, `P` / `D` / `F` are pool counts after the run.

- **No-work string**: `没有需要重试的failed prompt`.

- **Failure string** (returned by the tool, also non-zero exit code from the wrapper): `错误: {ExceptionType}: {message}`.

- **Side effects**:
  - `prompts.image_status` set to `'pending'` for all selected rows (in a single bulk UPDATE).
  - Per row, after generation:
    - **Success**: `image_gcs_url = <GCS URL>`, `image_status = 'done'`.
    - **Failure (any exception)**: `image_status = 'failed'`. The `image_gcs_url` from a prior attempt is **not** cleared.
  - The `prompts.image_generated_at` column is **not** updated by this tool (see Handoff Notes drift #2).

## Data Contract

### `prompts` — bulk UPDATE on selected rows

```sql
UPDATE prompts SET image_status = 'pending' WHERE id IN (?, ?, ...);
```

This happens **before** any image generation. If the run is interrupted between the bulk UPDATE and the per-row UPDATE, the selected rows will sit in `pending` indefinitely. There is no crash recovery.

### `prompts` — per-row UPDATE after generation

| Path | `image_status` | `image_gcs_url` |
|---|---|---|
| `gcs_url` is truthy | `'done'` | overwritten with new URL |
| `gcs_url` is falsy (`None` or `""`) | `'failed'` | untouched |
| Exception in `generator.generate()` | `'failed'` | untouched |

The generator itself uploads the bytes to GCS and returns the URL — the wrapper does not download or copy anything. So the GCS-side artefacts are updated as a side effect of the generator's call. Local files are not produced by this tool in V3.2.

## Procedure

1. **Open DB connection** via `src.memory.schema._conn()`.
2. **SELECT failed candidates**:
   ```sql
   SELECT id, prompt_text, category FROM prompts WHERE image_status = 'failed' LIMIT ?;
   ```
   No `ORDER BY`. The CHECK constraint on `image_status` is `(IN ('pending','generating','done','failed','published'))` (see `schema.py:253`). Note that the tool does not add an `image_status = 'failed' AND image_status <> 'published'` guard — see Handoff Notes drift #3.
3. **Bulk UPDATE** the selected ids to `'pending'`. `conn.commit()` after.
4. **Instantiate generator**: `RateLimitSafeGenerator()` with defaults (`interval=2.0`, `max_workers=3`, `max_retries=3`, `retry_delay_base=2.0`, `gcs_bucket="sparki-op-test"`). Note: even though the generator is constructed with `max_workers=3`, `tool_retry_failed` never calls `generate_batch()` — it calls the single-shot `generate()` method in a `for` loop, so `max_workers` is effectively ignored here.
5. **For each row** (sequential):
   1. `gcs_url = generator.generate(prompt=row["prompt_text"], category=row["category"], prompt_id=row["id"])`.
   2. The internal `_generate_one` sleeps `interval=2.0` seconds before each call (including retries), and retries 3× with exponential backoff (2s, 4s, 8s) on `RESOURCE_EXHAUSTED` / `429`.
   3. **Success**: `UPDATE prompts SET image_gcs_url=?, image_status='done' WHERE id=?`. The GCS object key is `gs://sparki-op-test/prompts/{category}/{yyyy-mm}/{tweet_id}.png` (the `tweet_id` here is the **integer** `prompts.id` cast to string, **not** the original `tweet_id` column — see Handoff Notes drift #4).
   4. **Failure**: `UPDATE prompts SET image_status='failed' WHERE id=?`. The `image_gcs_url` from any prior attempt is left intact (so the row can still be displayed via the URL even though `image_status` says `failed`).
6. **Final commit** after the loop.
7. **Compute pool counts** and return the multi-line status string.

## Validation

```bash
# 1. Make sure the DB exists
python -m src.main init-db

# 2. Confirm there is something to retry
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print('failed:', c.execute(\"SELECT COUNT(*) FROM prompts WHERE image_status='failed'\").fetchone()[0])"

# 3. Dry-run (no DB writes, no LLM/GCS calls) — see the candidate rows
python skills/retry-failed/scripts/retry_failed.py --batch 5 --dry-run

# 4. Real run, smallest possible batch (will hit Vertex AI)
python skills/retry-failed/scripts/retry_failed.py --batch 1

# 5. Confirm the writes landed
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print('failed:', c.execute(\"SELECT COUNT(*) FROM prompts WHERE image_status='failed'\").fetchone()[0]); print('done:', c.execute(\"SELECT COUNT(*) FROM prompts WHERE image_status='done'\").fetchone()[0])"
```

The wrapper exits with code:
- `0` on success (real run, dry-run, or no-work).
- `1` if the tool returned a `错误:` string.
- `2` if the project root cannot be located (`src/agent/skills/core_tools.py` missing).

## Failure Handling

| Symptom | Likely cause | Action |
|---|---|---|
| `没有需要重试的failed prompt` | There were no rows in `image_status = 'failed'`. | Run `tool_generate_images` first, or check if a previous run left rows in `pending` (then this tool won't help — use `generate_images`). |
| `错误: ... google.api_core.exceptions.ResourceExhausted: 429 ...` | Vertex AI rate limit. | Wait 60s and retry with smaller `--batch`. Note: `RateLimitSafeGenerator` already has built-in 3× retry with exponential backoff, so this string usually means every attempt 429'd. |
| `错误: ... google.auth.exceptions.DefaultCredentialsError ...` | Vertex AI auth missing. | `gcloud auth application-default login` or set `GOOGLE_APPLICATION_CREDENTIALS`. |
| All rows revert to `failed` after a real run | Generator is fundamentally broken (bad bucket name, model retired, etc.). | Inspect `image_gcs_url` for the most recent attempt — if it still points to an old key, the generator never succeeded. Check `gcloud storage ls gs://sparki-op-test/prompts/` to see if any new objects were created. |
| `image_status = 'published'` row got reset to `pending` | The published-state-loss caveat (see Handoff Notes drift #3). The bulk UPDATE is unguarded. | Add `AND image_status = 'failed' AND image_status <> 'published'` to the WHERE clause, or skip `retry_failed` for published rows by hand. |
| `AttributeError: 'NoneType' object has no attribute 'generate'` | The image client failed to initialise. | Check that `configs/gemini.yaml` has `image_worker` set, and that the Vertex AI project `sparki-op` is accessible. |

## Handoff Notes

These are the **verified** drift points between the wiki, the code, and the V3.3 roadmap. Prioritize the code as the source of truth.

1. **`image_gcs_url` is the V3.2 column; V3.3 target is `image_local_path`.**
   - Today (`core_tools.py:652`): `UPDATE prompts SET image_gcs_url = ?, image_status = 'done' WHERE id = ?`.
   - V3.3 (per `docs/11_ToolInterface.md` §V3.3 目标版): the column will be renamed/migrated to `image_local_path`, and the file path will be `outputs/generated_images/{id}.png` (GCS 中转废除).
   - The CHECK constraint on `image_status` does not change, so the `'pending' → 'done' / 'failed'` flow is the same — only the URL/path column changes. When migrating, the WHERE clause and the per-row UPDATE both need to be updated.

2. **`image_generated_at` is not written by this tool.**
   - The column exists (`schema.py:95`), and `tool_generate_images` is expected to update it. `tool_retry_failed` does not. If you rely on this column to know "when was the last successful cover image generated for this prompt", it will be stale for any row that succeeded via retry. Suggested fix: add `image_generated_at = ?` (set to `datetime.now(timezone.utc).isoformat()`) to the success-path UPDATE on line 652.

3. **The bulk UPDATE does not filter out `'published'` rows.**
   - The SELECT on line 625 is `WHERE image_status = 'failed'` — but the CHECK constraint allows `image_status = 'published'`. If a `'published'` row gets marked `'failed'` (e.g. by a hand-edited SQL or by a future migration that backfills failed states), running this tool will silently rewind it to `'pending'`, and the next successful retry will set `image_status = 'done'`, losing the `'published'` mark.
   - The published-page build (`tool_publish`) may then rebuild HTML with this row (since `image_status = 'done'`), or skip it (depends on whether `tool_publish` uses a different filter). Either way, the data is in an inconsistent state.
   - **Mitigation**: the SELECT should be `WHERE image_status = 'failed' AND id NOT IN (SELECT id FROM prompts WHERE image_status = 'published')`, **OR** the bulk UPDATE should be `WHERE id IN (...) AND image_status = 'pending'` (i.e. only flip rows we just put in pending). The current code has neither guard.

4. **The GCS object key uses the integer `prompts.id`, not the original `tweet_id`.**
   - In `generator.py:60-65`, `tweet_id=str(prompt_id)` — and `prompt_id` is the **integer** `prompts.id` row key passed from the wrapper. The original `tweet_id` column (the X.com snowflake) is **not** used. So the GCS key is `gs://sparki-op-test/prompts/{category}/{yyyy-mm}/{prompts.id}.png`, e.g. `gs://sparki-op-test/prompts/cinematic-scene/2026-05/123.png`.
   - This is a minor cosmetic drift: the `tweet_id` field would be more "human traceable" in the GCS console, but the integer PK is fine for programmatic access. The two columns are 1:1 in practice (the `prompts.tweet_id` column is `UNIQUE`), so collision risk is zero.

5. **The generator is constructed with `max_workers=3` but used sequentially.**
   - `core_tools.py:640` instantiates `RateLimitSafeGenerator()` with the default `max_workers=3` (from `generator.py:29`). However, the tool never calls `generate_batch()`. It uses the legacy single-shot `generate()` method (line 645), which internally calls `_generate_one` and applies the `interval=2.0` sleep per call. So `max_workers` is dead config in this code path.
   - The `max_workers` setting matters only for `generate_images`. If you want to change retry parallelism, edit the loop in `tool_retry_failed` to call `generate_batch()` (and handle the result dict format) — or accept that the tool is intentionally serial.

6. **There is no `image_attempts` audit log written by this tool.**
   - V3.3 target (`docs/11_ToolInterface.md`): `retry_failed` should write a row to `image_attempts` with `attempt_index++`, `status`, `error_message`. The current code does not. So the operator has no machine-readable history of *why* a row failed twice. The closest workaround is to log the exception message to stderr (which the tool does not do — it `except Exception: pass` on line 662).
   - **Mitigation for the next operator**: replace the bare `except Exception:` with `except Exception as e: print(f"  [retry_failed] id={row['id']} error: {e}", file=sys.stderr)` and add an `INSERT INTO image_attempts` here.

### Other things the next operator should know

- **The `image_status = 'generating'` state is never used by this tool.** The CHECK constraint allows it, and `tool_generate_images` may set it briefly, but `tool_retry_failed` only ever writes `'pending'`, `'done'`, or `'failed'`. So a `'generating'` row from a crashed parallel run will be invisible to this tool — it sits in `'generating'` forever. Use `generate_images` to sweep those, or update the SELECT to include them.
- **The `_generate_one` `interval=2.0` sleep happens per call, including retries.** So a row that needs all 3 retries (2s + 4s + 8s) takes ~14 seconds end-to-end. With `--batch 8`, the worst case is ~112s wall time. Plan accordingly.
- **V3.3 migration target** (per `docs/11_ToolInterface.md`): replace `image_gcs_url` with `image_local_path` in both the success-path UPDATE and the column reference in `references/database_schema.md`. The migration also wants to drop the GCS upload entirely and write to `outputs/generated_images/{id}.png` instead.
