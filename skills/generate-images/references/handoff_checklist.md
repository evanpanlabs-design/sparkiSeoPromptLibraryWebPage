# Handoff Checklist — generate_images

A copy-pasteable runbook for the next operator.

## 1. Install

```bash
# From project root
pip install -r requirements.txt
# Optional but recommended (loads .env automatically)
pip install python-dotenv
# Required by the image client
pip install google-genai Pillow google-cloud-storage
```

## 2. Configure

### 2a. Auth

```bash
# Vertex AI: pick one
gcloud auth application-default login
# OR
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json
```

### 2b. GCS bucket

The image client writes to `gs://sparki-op-test` by default
(`generator.py:28`, `client.py:34`). To override, edit those two lines or
extend `RateLimitSafeGenerator.__init__` to take a `gcs_bucket` kwarg.

Verify the active ADC has `storage.objects.create` on the bucket:

```bash
gcloud storage buckets get-iam-policy gs://sparki-op-test \
  --project=sparki-op \
  --flatten="bindings[].members" \
  --format="table(bindings.role)"
```

### 2c. Model list

`configs/gemini.yaml:image_models` is **not** read at runtime. To change the
active list, edit `src/image_gen/client.py:20-24` (`MODELS = [...]`).

The yaml's `generation.concurrency` and `retry_delay_base` are also
documented-only for this skill (the legacy `GeminiImageClient.generate_batch`
path does read them; the ReAct `tool_generate_images` does not).

### 2d. Database

```bash
python -m src.main init-db
```

## 3. Smoke test (no Gemini call, no DB write)

```bash
python skills/generate-images/scripts/generate_images.py \
  --project-root . \
  --batch 5 \
  --min-score 0.5 \
  --dry-run
```

Expected output: `Would generate: N cover images ...` with N rows previewed.

## 4. Real run (smallest blast radius)

```bash
python skills/generate-images/scripts/generate_images.py \
  --project-root . \
  --batch 1 \
  --max-workers 1
```

Expected: `图片生成完成: 1/1 成功, 0/1 失败` and one new row with
`image_gcs_url` populated.

## 5. Inspect the writes

```bash
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); \
  print([r for r in c.execute('PRAGMA table_info(prompts)').fetchall() if 'image' in r[1] or 'quality' in r[1]])"
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); \
  [print(s, ':', c.execute(f\"SELECT COUNT(*) FROM prompts WHERE image_status='{s}'\").fetchone()[0]) \
   for s in ['pending','generating','done','failed','published']]"
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); \
  print(c.execute('SELECT id, category, image_gcs_url FROM prompts WHERE image_status=\"done\" ORDER BY id DESC LIMIT 3').fetchall())"
```

## 6. Retry failed rows

```bash
# From the Python REPL or a one-liner — the skill is `tool_retry_failed`
python -c "
import sys; sys.path.insert(0, '.')
from src.agent.skills.core_tools import tool_retry_failed
print(tool_retry_failed({'batch': 8}))
"
```

## 7. Known drift (full detail in `../SKILL.md` Handoff Notes)

1. **Summary line lies about the model.** The return string hard-codes
   `gemini-2.5-flash-image` regardless of which model actually produced the
   image. Trust the per-row `model_used` in stdout, not the summary.
2. **`image_gcs_url` is deprecated.** V3.3 will rename it to
   `image_local_path` and write the image to `outputs/generated_images/`.
3. **`image_status='generating'` and `'published'` are dead states** in the
   CHECK constraint. No code writes them. `pool_status` will always show 0
   for both.
4. **`--min-score` filter reads the wrong CSV field.** `quality_scores` is
   stored as `"spec,vis,nov,gen,overall"`, but `CAST(... AS REAL)` parses
   only the leading number. The filter ends up comparing **specificity**,
   not overall quality. Workaround: pre-filter in SQL, or add a separate
   `quality_overall REAL` column.
5. **`image_generated_at` is never written** by either `generate_images` or
   `retry_failed`. Freshness-based regen queries will not work today.

## 8. V3.3 migration prep

Before flipping to V3.3, do all of the following:

1. Add `image_local_path TEXT` to `prompts` (`schema.py:78-100`).
2. Update `core_tools.py:577` to also write `image_local_path =
   'outputs/generated_images/{id}.png'`.
3. Add a `quality_overall REAL` column to `prompts` (drift #4 fix) and
   update both `score_prompts` and `generate_images` to read/write it.
4. Update `image_status` CHECK to remove `'generating'` and `'published'`
   (or wire them up).
5. Start writing `image_generated_at` on success.
6. Update `tool_build_html` to prefer `image_local_path` over the GCS URL
   (`docs/11_ToolInterface.md:245-251`).
7. Mark `tool_sync_images` as deprecated and remove its caller
   (`tool_build_html` calls `scripts/sync_images_from_gcs.py` only when
   `sync_images=True` is passed; flip that default to `False`).
8. Re-validate this skill end-to-end with `--dry-run` + a `--batch 1` real
   run.
