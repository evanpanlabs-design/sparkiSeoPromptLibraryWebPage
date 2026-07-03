---
name: generate-images
description: Generate cover images for pending prompts in the Veo Prompt Library pipeline via the `RateLimitSafeGenerator` + `GeminiImageClient` (multi-model fallback over `gemini-2.5-flash-image` / `gemini-3-pro-image-preview` / `gemini-3.1-flash-image-preview`), upload to GCS bucket `sparki-op-test`, and flip `prompts.image_status` from `'pending'` to `'done'` or `'failed'`. Use when the agent needs to run or debug the `generate_images` pipeline phase, when there are rows where `image_status='pending'`, when the user asks to "生成封面图" / "跑 generate_images" / "make cover images", when triaging image_status state machine (pending/generating/done/failed/published), when tuning `--filter={'min_score': X}` to skip low-quality prompts, or when migrating from the deprecated GCS path to a local `outputs/generated_images/{id}.png` path. Does NOT score, extract, sync to GitHub Pages, or build HTML.
---

# Generate Images (V3.2 — RateLimitSafeGenerator + GCS)

## What It Does

Pulls the next batch of `prompts` rows where `image_status='pending' AND image_gcs_url IS NULL`, generates one cover image per row through the `RateLimitSafeGenerator` (parallel, 2-second interval, per-task retry on `429` / `RESOURCE_EXHAUSTED`), uploads each successful image to GCS, then UPDATEs the row with `image_gcs_url` and `image_status='done'` (or `'failed'` on error).

This is the **fourth** stage of the V3.2 pipeline. It is **not** the last step before publishing — `build_html` and `publish` come after. This skill does not touch `index.html`, `prompts/*.html`, or the `gh-pages` branch.

## When To Use

- Run **after** `score_prompts` (so you can use `filter={'min_score': 0.6}` to skip low-quality prompts) and **before** `build_html`.
- Use when the user says: "生成封面图", "跑 generate_images", "make covers", or asks the ReAct agent to invoke `tool_generate_images`.
- Use the **CLI wrapper** for one-off runs and the **tool function** for ReAct agent dispatch.
- Pair with `tool_retry_failed` (separate skill) to re-run rows that ended up in `image_status='failed'`.

## When NOT To Use

- For extracting prompt text from tweets → use `extract-prompts`.
- For quality scoring → use `score-prompts`.
- For HTML build / GitHub Pages publish → use `build-html` / `publish`.
- For searching the prompt pool → use `search-prompts` (V3 system skill).
- For re-classifying categories → use `extract-prompts` (handles the new-category downgrade in the same transaction).

## Required Context

- Project root: `16_NewCrawler`
- Tool implementation: `src/agent/skills/core_tools.py:520-613` (`tool_generate_images`)
- Generator: `src/image_gen/generator.py` (`RateLimitSafeGenerator`)
- Image client: `src/image_gen/client.py` (`GeminiImageClient`, 3-model fallback)
- Style keywords: `src/image_gen/style.py` (`build_image_prompt()` + `_DEFAULT_STYLE_KEYWORDS`)
- Retry / image-config: `configs/gemini.yaml` (`image_models`, `generation.concurrency`, `retry_delay_base`, `gcs_bucket`)
- Scoring source for `filter.min_score`: `prompts.quality_scores` (CSV: `spec,vis,nov,gen,overall`)
- V3.2 contract: `docs/11_ToolInterface.md` §4

## Preconditions

1. **Database initialized**: `python -m src.main init-db` so the `prompts` table exists with the `image_status` column (added in `_migrate_v3_prompts_cols`, `schema.py:248-256`).
2. **Vertex AI auth**: `gcloud auth application-default login` or `GOOGLE_APPLICATION_CREDENTIALS` set. The `GeminiImageClient` (`client.py:42`) uses `genai.Client()` which picks up ADC.
3. **GCS bucket reachable**: the project uses `sparki-op-test`. The image client uploads to `prompts/{category}/{yyyy-mm}/{tweet_id}.png`. **The bucket write is a hard requirement today** — see Drift #2 in Handoff Notes for the V3.3 plan to drop it.
4. **At least one row with `image_status='pending'`** and `image_gcs_url IS NULL`. Run the dry-run or `tool_pool_status()` first to confirm.
5. **Python deps**: `google-genai`, `Pillow` (PIL), `google-cloud-storage` (implicit via `src/image_gen/gcs.py`).
6. **Recommended**: also run `score_prompts` first. `quality_scores IS NULL` rows have `CAST(quality_scores AS REAL) = 0.0`, so without scoring the SQL CAST will *always fail the `min_score` filter* (see Drift #4).

## Inputs

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `batch` | `int` | `8` | Max prompts to process. `0` = all pending (unbounded). |
| `sort_by` | `str` | `"score"` | `score` = `ORDER BY CAST(quality_scores AS REAL) DESC`; `newest` = `ORDER BY id DESC`. |
| `filter` | `dict` | `None` | `{"min_score": 0.6}` adds `AND CAST(quality_scores AS REAL) >= ?`. **See Drift #4 — this reads the first CSV field, not overall.** |
| `max_workers` | `int` | `3` | ThreadPool size inside `RateLimitSafeGenerator`. Each thread enforces its own 2s interval. |

The CLI wrapper (`scripts/generate_images.py`) additionally accepts `--project-root`, `--sort-by {score,newest}`, `--min-score` (translates to `filter`), `--max-workers`, and `--dry-run`.

## Outputs

- **Success string** (printed to stdout):
  ```
  图片生成完成: {S}/{T} 成功, {F}/{T} 失败
  模型: gemini-2.5-flash-image
  当前池: {P} pending, {D} done, {F} failed
  ```
  Per-row progress is printed to stdout by both the tool and the generator (`  [N/T] OK id=... cat=... [model]` / `  [N/T] FAIL id=... err=...`).

- **No-work string**:
  ```
  没有需要生成图片的pending prompt
  ```

- **Failure string**:
  ```
  错误: {ExceptionType}: {message}
  ```

- **Side effects** (one `conn.commit()` at the end of the batch, `core_tools.py:592`):
  - `prompts` UPDATE on success: `image_gcs_url = ?, image_status = 'done'` (note: `image_generated_at` is **not** set by the tool — see Drift #5).
  - `prompts` UPDATE on failure: `image_status = 'failed'` (no `image_gcs_url` write, no timestamp).
  - `prompts` is **not** touched in the `image_status='generating'` state — the column is in the schema's CHECK constraint (`schema.py:252-254`) but the tool never writes it.

## Data Contract

The tool writes **one** table (`prompts`). The state machine is:

| `image_status` | Set by | Notes |
|---|---|---|
| `pending` | `extract_prompts` (initial), `retry_failed` (reset) | Source of the SELECT. |
| `generating` | (nobody) | **Dead write** — column allows it, nothing emits it. See Drift #3. |
| `done` | `generate_images`, `retry_failed` | Successful generation + GCS upload. |
| `failed` | `generate_images`, `retry_failed` | All retry attempts exhausted. Retry by running `tool_retry_failed()`. |
| `published` | (nobody) | **Dead state** — schema allows it, `pool_status` reports it, but no tool writes it. See Drift #3. |

The `image_gcs_url` column is the legacy storage target. The V3.3 target is `image_local_path` pointing at `outputs/generated_images/{id}.png` — that column does **not** exist in the current schema (`schema.py:78-100`), so the migration is a pending PR. See Drift #2.

## Procedure

1. **Open DB connection** via `src.memory.schema._conn()`.
2. **SELECT candidates** (this exact query, `core_tools.py:531`):
   ```sql
   SELECT id, prompt_text, category
   FROM prompts
   WHERE image_gcs_url IS NULL AND image_status = 'pending'
   ```
   With `filter={"min_score": X}`:
   ```sql
   ... AND CAST(quality_scores AS REAL) >= ?   -- (X,)
   ```
   With `sort_by="score"`:
   ```sql
   ... ORDER BY CAST(quality_scores AS REAL) DESC
   ```
   With `batch > 0`:
   ```sql
   ... LIMIT {batch}
   ```
3. **Build generator**:
   ```python
   RateLimitSafeGenerator(
       max_workers=max_workers,    # default 3
       max_retries=3,
       retry_delay_base=2.0,
   )
   ```
   Defaults: `project="sparki-op"`, `location="global"`, `gcs_bucket="sparki-op-test"`, `interval=2.0`.
4. **For each row**, call `generator.generate_batch(items)` where each item is `{"prompt_id": id, "prompt_text": ..., "category": ...}`. The generator uses a `ThreadPoolExecutor(max_workers=N)`, each thread does `time.sleep(2.0)` then calls `client.generate(...)`. The client tries each model in `MODELS` (`client.py:20-24`) with up to `max_retries_per_model=3` retries on `429`/`RESOURCE_EXHAUSTED`. Successful calls upload to GCS via `src/image_gen/gcs.upload_bytes_to_gcs()`.
5. **Aggregate results** in a `result_map`. For each row, look up the matching result; if `gcs_url` is set, UPDATE `image_gcs_url` + `image_status='done'`. Otherwise UPDATE `image_status='failed'`. Print one line per row.
6. **Commit once** at the end.
7. **Report counts** (total, pending, done, failed) and return the status string.

## Validation

```bash
# 1. Make sure DB is up
python -m src.main init-db

# 2. Smoke test: preview what would be generated (no Gemini call, no DB write)
python skills/generate-images/scripts/generate_images.py \
  --project-root . \
  --batch 5 \
  --min-score 0.5 \
  --dry-run

# 3. Real run with the smallest batch (--batch 1, --max-workers 1)
python skills/generate-images/scripts/generate_images.py \
  --project-root . \
  --batch 1 \
  --max-workers 1

# 4. Inspect the writes
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); [print(s, ':', c.execute(f\"SELECT COUNT(*) FROM prompts WHERE image_status='{s}'\").fetchone()[0]) for s in ['pending','generating','done','failed','published']]"

# 5. Confirm the URL is reachable (GCS)
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print(c.execute('SELECT id, image_gcs_url FROM prompts WHERE image_status=\"done\" ORDER BY id DESC LIMIT 3').fetchall())"
```

The wrapper exits with code:
- `0` on success (real run, no-work, or dry-run)
- `1` if the tool returned a `错误:` string
- `2` if the project root cannot be located (`src/agent/skills/core_tools.py` missing)

## Failure Handling

| Symptom | Likely cause | Action |
|---|---|---|
| `错误: ... 429 ... RESOURCE_EXHAUSTED` | Vertex AI rate limit on the active model. | The generator retries with `retry_delay_base * 2^attempt` (`generator.py:78`). If exhausted, row → `failed`. Re-run with `tool_retry_failed` after a few minutes. |
| `错误: google.auth.exceptions.DefaultCredentialsError` | ADC not set. | `gcloud auth application-default login`. |
| `错误: ... google.cloud.storage ... 403` | Service account lacks `storage.objects.create` on `sparki-op-test`. | Check IAM, or set `gcs_bucket` to a bucket the identity can write to. |
| `没有需要生成图片的pending prompt` | No rows match. | Either `score_prompts`/`extract_prompts` haven't run yet, or all rows already have `image_gcs_url`. Run `tool_pool_status()` to check. |
| All rows fail with `No image in response from <model>` | `response_modalities` returns only TEXT (e.g. model in "thinking" mode). | The `GeminiImageClient` already requests `[TEXT, IMAGE]` (`client.py:71-73`). If a new model only returns text, drop it from `MODELS` in `client.py:20-24` or from `gemini.yaml:image_models`. |
| `image_status='failed'` rows pile up | Sustained rate limit or model outage. | Drop to `--batch 1 --max-workers 1`, then `tool_retry_failed` after a few minutes. |
| Cover images contain visible text/words | `style.py:build_image_prompt` no longer passes `title` (it caused text artifacts). | If you see artifacts after re-introducing a `title` argument, remove it again — the explicit "no text" instruction is in the prompt template (`style.py:42`). |
| `--filter min_score=0.6` filters out everything | Quality scores are missing OR Drift #4 bug. | See Drift #4: `CAST(quality_scores AS REAL)` reads the **first** CSV value (specificity), not overall. Either re-run `score_prompts` first, or override the SQL. |

## Handoff Notes

These are the **five** verified drift points between the project wiki, the current code, and the live database. The wiki document is `docs/11_ToolInterface.md` §4. **Prioritize the code as the source of truth.**

1. **The return string hard-codes `模型: gemini-2.5-flash-image` — but the actual call is a 3-model fallback.**
   - `core_tools.py:607` emits the literal string `"模型: gemini-2.5-flash-image"` regardless of which model actually produced the image.
   - The real client (`client.py:20-24` + `client.py:65-93`) iterates over `MODELS = ["gemini-2.5-flash-image", "gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview"]` and returns the first model that succeeds. The per-row `model_used` is printed by the tool (`core_tools.py:581`), but the summary line lies.
   - **Implication**: when you see "all 8 failed" in the summary but the per-row log shows different model names, the failure may be model-specific, not config-specific. The summary line is informational only.

2. **`image_gcs_url` is being deprecated in V3.3 — V3.2 still writes to it.**
   - `core_tools.py:577` writes to `image_gcs_url` (a `TEXT` column on `prompts`).
   - `docs/11_ToolInterface.md` §4 (line 187) and §"V3.3 目标版" say the target column is `image_local_path`, with the file at `outputs/generated_images/{id}.png`.
   - **The `image_local_path` column does not exist in the current schema** (`schema.py:78-100`). The migration is a pending PR.
   - **Implication for the next operator**: any code that reads `image_gcs_url` to build HTML (e.g., `sync_images`, `build_html`) will break when the migration lands. The `sync_images` skill already says "GCS 中转已废除，此工具保留用于兼容" (`docs/11_ToolInterface.md:207`).
   - **Fix**: when V3.3 lands, the tool should `SELECT` from `image_local_path` (falling back to GCS for old rows) and write to the local file first, then mark `image_status='done'`. The GCS upload becomes optional / archive-only.

3. **`image_status='generating'` and `image_status='published'` are dead states.**
   - The `CHECK (image_status IN ('pending','generating','done','failed','published'))` constraint allows both (`schema.py:252-254`).
   - `tool_pool_status` reports the `published` count in its output (`docs/11_ToolInterface.md:308`).
   - `src/agent/memory/long_term.py:42` reads the `published` count for some metric.
   - **No tool in `core_tools.py` ever writes `generating` or `published`.** Grep confirms the only writes are `'pending'` (in `retry_failed`), `'done'`, and `'failed'`.
   - **Implication**: the `pool_status` report will always show `0` for both. Either remove them from the CHECK constraint (cleanest) or add the missing transitions (`generating` at the top of the batch, `published` in `tool_publish`).

4. **`CAST(quality_scores AS REAL)` reads the **first** CSV field, not `overall`.**
   - `quality_scores` is stored as a CSV string: `"{specificity},{visual_detail},{novelty},{generatable},{overall}"` (`core_tools.py:336-339`).
   - `tool_generate_images` filters with `AND CAST(quality_scores AS REAL) >= ?` (`core_tools.py:535`).
   - `CAST('0.5,0.6,0.7,0.8,0.65' AS REAL)` returns `0.5` (the leading number). `overall` is the 5th field.
   - **Implication**: passing `--min-score 0.6` with `sort_by=score` orders by **specificity**, not overall quality. The 5-field CSV has to be split (`substr(quality_scores, ...)` or stored as JSON) to support per-field filtering. Workaround today: pre-filter in SQL with `WHERE overall_score = ?` — but the tool does not expose `overall` as a separate column.
   - **Fix**: add a `quality_overall REAL` column to `prompts` (filled by `score_prompts`) and migrate the filter to read from it. This is also a prerequisite for the V3.3 schema simplification.

5. **`image_generated_at` is never written.**
   - The column exists in the schema (`schema.py:95`, type `TEXT`, no default) and is mentioned as a goal in the V3.3 contract (`docs/11_ToolInterface.md:187`).
   - Neither `tool_generate_images` (`core_tools.py:520-613`) nor `tool_retry_failed` (`core_tools.py:615+`) writes to it.
   - **Implication**: any "freshness" filter (e.g., "regenerate covers older than 30 days") cannot work today. Fix: add `datetime.now(timezone.utc).isoformat()` to the `done` UPDATE.

### Other things the next operator should know

- **Live DB state at the time of writing** (run the validation commands to confirm):
  - `pending`: typically hundreds after a fresh `extract_prompts` run.
  - `generating`: **always 0** (drift #3).
  - `done`: 0 if you have never run `generate_images` in this DB; otherwise grows by `--batch` per run.
  - `failed`: grows on rate-limit storms; reduce via `tool_retry_failed`.
  - `published`: **always 0** (drift #3).
- **`configs/gemini.yaml` lists the same 3 models as `client.py:MODELS`** but the file is **not** read by `RateLimitSafeGenerator` (it builds a `GeminiImageClient(project=..., location=..., gcs_bucket=...)` with hard-coded `models=list(MODELS)` from `client.py`). The yaml is documentation-only at runtime. To change the active model list, edit `client.py:20-24`.
- **`max_retries_per_model=3` in the yaml is not honored** — `client.py:35` defaults to `3` and `RateLimitSafeGenerator` constructs the client without overriding it. In practice the values agree, so no drift, but the yaml is not the source of truth.
- **`title=""` is hard-coded in `_generate_one` (`generator.py:64`)** because passing `title` to the image model produced text artifacts in earlier runs. The "title" column on `prompts` is still populated by `extract_prompts` and is read by `build_html` — only the image prompt is built without it.
- **`batch=0` means unbounded** (`core_tools.py:543-544` — the `if batch > 0: sql += f" LIMIT {batch}"` branch). The default in the code is `8`, not `0`. The comment at `core_tools.py:526` says "changed default from 0 to 8" — a one-character edit that prevents accidental "drain the whole pool" runs.
- **No `image_status='generating'` write → no crash recovery** if the process is killed mid-batch. If a row was UPDATEd to `'done'` but the commit never fired, the next run will re-pick it (the `WHERE image_gcs_url IS NULL` is the source of truth, not the status). That's safe.
- **V3.3 migration target** (per `docs/11_ToolInterface.md` §"V3.3 目标版"): `image_gcs_url` → `image_local_path`; add `image_attempts` table for per-attempt audit log (`prompt_id, attempt_index, model_used, status, error_message`); rename `image_status` to `has_cover_image` (0/1). The skill will need a full re-validation after that migration.
- **The wrapper's `--dry-run` only reproduces the SELECT** — it does not run the content filter, score, or any LLM call. It is a "would-pick" preview, not a "would-pass" preview. To predict failures, look at the per-row log of the real run.
- **CLI exit codes** match `extract-prompts`: 0 = ok, 1 = `错误:` string returned, 2 = project root not found.

### See also
- `references/database_schema.md` — the `prompts` columns touched by this skill + the `idx_prompts_quality` index.
- `references/image_generation.md` — model list, style keywords, rate-limit / retry policy, GCS vs local decision.
- `references/handoff_checklist.md` — copy-pasteable runbook for the next operator (install → configure → smoke test → V3.3 migration).
