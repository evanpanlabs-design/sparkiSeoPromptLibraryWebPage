---
name: sync-images
description: DEPRECATED two-step GCS-to-local image sync for the Veo Prompt Library — pulls cover images from gs://sparki-op-test/prompts/ into outputs/images/{cat}/{yyyy-mm}/, then copies them flat to outputs/generated_images/ for the static HTML build. Use this ONLY on a legacy V3.2 deploy that still writes cover images to GCS. Do NOT use for V3.3+ or fresh deploys — generate_images now writes directly to outputs/generated_images/ and this whole pipeline is scheduled for removal.
---

# Sync Images (V3.2 — DEPRECATED)

## What It Does

**WARNING: DEPRECATED since V3.2.** The GCS transfer layer is being phased out. In V3.3+ images are written directly to local storage by `generate_images`. Use this only for legacy GCS-based deploys.

This skill is a thin two-step wrapper around two scripts. It does **not** write to the database itself — both steps read the DB and the local filesystem.

**Step 1 — `download_all(dry_run, limit)`** (`scripts/sync_images_from_gcs.py`):
- Connects to GCS bucket `sparki-op-test` (project `sparki-op`).
- Lists all blobs under prefix `prompts/`.
- Parses path as `prompts/{category...}/{yyyy-mm}/{db_id}.png`.
- Looks up `tweet_id`, `category`, `title` from the local `prompts` table WHERE `image_status = 'done'` (keyed by `db_id`).
- Downloads the blob to `outputs/images/{safe_category}/{yyyy-mm}/{tweet_id}.png`, skipping files that already exist with the correct size.

**Step 2 — `_sync_images_to_flat_dir()`** (`scripts/build_html.py:104-134`):
- For every prompt with `image_status = 'done' AND image_gcs_url IS NOT NULL`, looks for a source file at `outputs/images/{safe_category}/*/{tweet_id}.png` and copies it to `outputs/generated_images/{db_id}.png`.
- The static HTML build then references `../generated_images/{db_id}.png`.

The final return string is built from Step 2 stats only:
```
Images: {copied} copied, {skipped} skipped, {errors} errors
```

Step 1 stats (`downloaded`, `skipped`, `errors`, `total_gcs_blobs`) are computed but **not surfaced** in the wrapper's return value. See **Handoff Notes** for this drift.

## When To Use

- You are on a **legacy V3.2 deploy** that writes cover images to GCS (`prompts.image_gcs_url` is set) and reads them back here.
- You have a `google-cloud` service account configured and `GOOGLE_APPLICATION_CREDENTIALS` (or `gcloud auth application-default login`) is set up.
- The bucket `gs://sparki-op-test` exists and is reachable from the host.
- You need to **refresh** the local `outputs/images/` mirror before `build_html` runs.

## When NOT To Use

- **For V3.3+ or fresh deploys — use `generate_images` which writes directly to `outputs/generated_images/`.** This entire skill is scheduled for removal.
- For HTML generation itself → use `build_html`. That tool already calls `_sync_images_to_flat_dir()` inline when its `sync_images=True` flag is passed.
- For cover image generation → use `generate_images`.
- If `google.cloud.storage` is not installed and the host has no GCS credentials, this skill will hard-fail at import time.

## Required Context

- Project root: `16_NewCrawler`
- Tool implementation: `src/agent/skills/core_tools.py:366-391` (`tool_sync_images`, 26 lines)
- Step 1: `scripts/sync_images_from_gcs.py` → `download_all(dry_run, limit)` (line 49)
- Step 2: `scripts/build_html.py` → `_sync_images_to_flat_dir()` (line 104, also called `sync_images_to_flat_dir` in the public name at line 104)
- Database: `data/veo_prompts.db` (READ-ONLY from this skill's perspective)
- GCS bucket: `gs://sparki-op-test` (project `sparki-op`)
- Required env: `GOOGLE_APPLICATION_CREDENTIALS` (or ADC via `gcloud auth application-default login`)
- Required Python package: `google-cloud-storage` (NOT in `requirements.txt` — install separately)

## Preconditions

1. **Database initialized** with `prompts` table populated. This skill reads `prompts WHERE image_status = 'done'` and `prompts WHERE image_status = 'done' AND image_gcs_url IS NOT NULL`.
2. **GCS auth configured**: `gcloud auth application-default login` OR `GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json`.
3. **GCS bucket accessible**: `gs://sparki-op-test` must exist and the SA must have `storage.objects.list` + `storage.objects.get` on it.
4. **GCS blobs present under `prompts/` prefix** in the `prompts/{category}/{yyyy-mm}/{db_id}.png` shape. Blobs that do not match this layout are silently skipped.
5. **Install `google-cloud-storage`**: `pip install google-cloud-storage`. The package is not in `requirements.txt` because the project is mid-migration to V3.3 (local-only). If you see `ModuleNotFoundError: No module named 'google.cloud'`, install it before re-running.
6. **Local write target writable**: `outputs/images/` and `outputs/generated_images/` must be creatable.

## Inputs

This tool takes **no** runtime parameters. `args` is accepted for the Skill Registry contract but ignored.

The CLI wrapper accepts:

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `--project-root` | path | parent of `sync-images/` | Override project root resolution. |
| `--dry-run` | flag | off | Pass `dry_run=True` to `download_all` (Step 1 only; Step 2 still runs and writes files — see Handoff Notes). |
| `--limit` | int | `None` | Forwarded to `download_all(limit=...)` to cap GCS iterations. |

## Outputs

- **Success string** (from Step 2 stats only):
  ```
  Images: {C} copied, {S} skipped, {E} errors
  ```
  where `C` = files newly copied into `outputs/generated_images/`, `S` = already present, `E` = no source file found in `outputs/images/`.

- **Failure string** (returned on exception, non-zero exit code from wrapper):
  ```
  错误: {ExceptionType}: {message}
  ```

- **Side effects**:
  - Files written to `outputs/images/{safe_category}/{yyyy-mm}/{tweet_id}.png` (Step 1)
  - Files copied to `outputs/generated_images/{db_id}.png` (Step 2)
  - **No DB writes.**

## Data Contract

This skill does **not** write to the database. It only reads:

### `prompts` (READ)

Step 1 reads:
```sql
SELECT id, tweet_id, category, title
FROM prompts
WHERE image_status = 'done'
```

Step 2 reads (via `fetch_all_prompts` in `build_html.py:54-95`):
```sql
SELECT p.*, t.created_at
FROM prompts p
LEFT JOIN tweets t ON p.tweet_id = t.tweet_id
WHERE p.image_status = 'done' AND p.image_gcs_url IS NOT NULL
ORDER BY CAST(p.quality_scores AS REAL) DESC
```

### GCS bucket layout (READ)

| Path component | Meaning | Example |
|---|---|---|
| Bucket | `sparki-op-test` | — |
| Prefix | `prompts/` | — |
| `{category}` | prompt category; may contain `/` | `cinematic-scene`, `Action/Suspense` |
| `{yyyy-mm}` | Year-month folder | `2026-05` |
| `{db_id}` | Integer primary key from `prompts.id` | `42` |
| Filename | `{db_id}.png` | `42.png` |

Blobs that do not match this layout (e.g. wrong segment count, non-`yyyy-mm` date segment, non-numeric id) are **silently skipped** — no warning is printed.

## Procedure

1. **Open tool** via `tool_sync_images({})` (no args).
2. **Step 1 — `download_all(dry_run=False, limit=None)`**:
   - Calls `_get_gcs_blobs()` → `storage.Client().bucket("sparki-op-test").list_blobs(prefix="prompts/")`. **No try/except around this** — fails hard on auth errors.
   - Calls `_sync_db_info()` → opens `data/veo_prompts.db` and reads `prompts WHERE image_status = 'done'`.
   - For each blob, parses `name.split("/")`. If `len(parts) < 4`, or `parts[-1]` doesn't end in `.png`, or `parts[-1][:-4]` isn't an int, or `parts[-2]` isn't a `yyyy-mm` shape — skip silently.
   - Computes `local_path = outputs/images/{safe_category}/{yyyy-mm}/{tweet_id}.png`.
   - If file exists and `local_path.stat().st_size == blob.size` → `skipped += 1`.
   - Otherwise opens `local_path` for writing and calls `blob.download_to_file(f)`. On exception → `errors += 1` and `continue`.
   - Returns `{downloaded, skipped, errors, total_gcs_blobs}`. **These stats are not in the final return string.**
3. **Step 2 — `_sync_images_to_flat_dir()`**:
   - Re-queries the DB via `fetch_all_prompts()` (the full `image_status='done' AND image_gcs_url IS NOT NULL` set, ordered by quality score).
   - For each prompt: if `outputs/generated_images/{db_id}.png` exists → `skipped`. Otherwise search `outputs/images/{safe_cat}/*/{tweet_id}.png`, copy to `generated_images/{db_id}.png` with `shutil.copy2`. If no source found → `errors += 1`.
   - Returns `{copied, skipped, errors}`.
4. **Return** `"Images: {copied} copied, {skipped} skipped, {errors} errors"`.

## Validation

```bash
# 1. Make sure the DB has rows with image_status='done' and GCS URLs
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print('done:', c.execute(\"SELECT COUNT(*) FROM prompts WHERE image_status='done' AND image_gcs_url IS NOT NULL\").fetchone()[0])"

# 2. Smoke test the wrapper
python skills/sync-images/scripts/sync_images.py --help
echo "exit=$?"

# 3. Dry-run (Step 1 only)
python skills/sync-images/scripts/sync_images.py --dry-run --limit 5
echo "exit=$?"

# 4. Real run (requires GCS auth)
python skills/sync-images/scripts/sync_images.py
echo "exit=$?"

# 5. Confirm files landed
ls outputs/generated_images/ | head
```

The wrapper exits with code:
- `0` on success (including dry-run)
- `1` if the tool returned a `错误:` string
- `2` if the project root cannot be located

## Failure Handling

| Symptom | Likely cause | Action |
|---|---|---|
| `ModuleNotFoundError: No module named 'google.cloud'` | `google-cloud-storage` not installed. | `pip install google-cloud-storage`. Not in `requirements.txt` because V3.3 is removing the GCS dependency. |
| `google.auth.exceptions.DefaultCredentialsError` | ADC not set up. | `gcloud auth application-default login` or `export GOOGLE_APPLICATION_CREDENTIALS=/path/sa.json`. |
| `403 ... sparki-op-test` | SA lacks `storage.objects.list` / `storage.objects.get` on the bucket. | Grant the SA `roles/storage.objectViewer` (or broader). |
| `Images: 0 copied, N skipped, M errors` and `M > 0` | Step 2 cannot find source files. | Step 1 may have failed silently, or GCS layout doesn't match expected `prompts/{cat}/{yyyy-mm}/{id}.png` shape. Check `outputs/images/` contents. |
| `Image: ...` return but `outputs/generated_images/` is empty | Step 1 succeeded but Step 2 saw no `image_status='done'` rows. | Run `score_prompts` and `generate_images` first. This tool only mirrors images that already exist in GCS. |
| Many blobs silently skipped | Blob path doesn't match the parser's expectation. | The parser is strict about `len(parts) >= 4` and `parts[-2]` being `yyyy-mm`. Check the actual blob names in the bucket. |
| GCS quota / network errors | Transient. | Retry. There is **no built-in retry** in `download_all` — any failed download increments `errors` and `continue`s. |

## Handoff Notes

These are the **verified** drift points between the wiki (`docs/11_ToolInterface.md` §5), the current code, and the live database. **Prioritize the code as the source of truth.**

1. **Skill is explicitly deprecated in V3.2, scheduled for removal in V3.3.** `docs/11_ToolInterface.md` §5 carries an explicit `> ⚠️ 状态: GCS 中转已废除，此工具保留用于兼容，后续可能废弃。` callout. The V3.3 target pipeline (same document, §"Pipeline 阶段链 (V3.3 目标版)") states `build_html ← sync_images 已废除，直接引用 generated_images/`. **If you are starting a new deploy, do not enable GCS image upload in `generate_images`.** The whole layer is going away.

2. **The return string hides Step 1 stats.** `tool_sync_images()` computes `gcs_stats = download_all(...)` and **never references it** in the return value. The user only sees Step 2 (`Images: {copied} copied, {skipped} skipped, {errors} errors`). If Step 1 silently skips many blobs (e.g. wrong path shape), the operator has no idea from the return string. The fix is a one-liner — concatenate `gcs_stats` into the return. See `references/handoff_checklist.md` for the patch.

3. **`--dry-run` only affects Step 1, not Step 2.** The wrapper passes `dry_run` to `download_all` but Step 2 (`_sync_images_to_flat_dir`) is unconditional. A `--dry-run` invocation can still write files to `outputs/generated_images/`. This is a UX bug: the flag name implies "no writes" but the contract is "no GCS downloads". Fix: gate Step 2 on `not dry_run` too.

4. **`_sync_images_to_flat_dir()` is named differently in two places.** `scripts/build_html.py` defines `def sync_images_to_flat_dir():` at line 104 and re-exports it as `_sync_images_to_flat_dir` via the `build()` function path (and as the import target in `core_tools.py:376`). The leading-underscore convention is for "private" but the function is the public contract of the script's `__main__` path. The duplication is harmless but slightly confusing. Drift is purely cosmetic.

5. **No retry on GCS errors.** `download_all()` (line 117-124) catches the per-file exception and increments `errors`. There is no exponential backoff, no per-blob retry, and no global `tenacity` decoration. A flaky network will produce a high `errors` count and silently fail the operator's view (see drift #2).

6. **GCS bucket name is hard-coded in two places** (`sync_images_from_gcs.py:32` and `:56`). Changing the bucket requires editing both. The `tool_sync_images()` wrapper has no override. If a multi-tenant deploy needs to point at a different bucket, refactor `download_all` to take a `bucket_name` kwarg.

7. **The GCS layout parser is strict and silent.** Blobs with fewer than 4 path segments, a non-`yyyy-mm` second-to-last segment, or a non-integer filename are silently skipped. No warning, no log. Operators debugging "where are my images?" have no breadcrumb. The fix is to add a `warnings` counter to the return dict and surface it in the wrapper.

8. **`google-cloud-storage` is not in `requirements.txt`.** Confirmed by inspection. The V3.3 target removes the dependency entirely. For V3.2 legacy deploys, install it manually before running this skill.

### Other things the next operator should know

- The path `outputs/images/{safe_category}/{yyyy-mm}/{tweet_id}.png` is the **canonical mirror**. The flat `outputs/generated_images/{db_id}.png` is the **build target**. The HTML templates (`outputs/templates/*.html`) reference the flat target only.
- `_safe_category()` replaces `[<>:"/\\|?*]` with `_`. If a category name has a `/` in it (e.g. `Action/Suspense`), the GCS parser correctly preserves the `/` in the path, but the safe_category on the local side becomes `Action_Suspense` — the **search directory on the local side uses the safe name, not the GCS-side name**. This is internally consistent for V3.2 but worth knowing.
- This skill is **idempotent on the source side** (size check on existing files) but **not atomic on the destination** (Step 2 uses `shutil.copy2`, not a temp-rename). A crash mid-copy leaves a partial file. `build_html` will then render a truncated PNG.
- Live DB state at time of writing: `prompts WHERE image_status = 'done' AND image_gcs_url IS NOT NULL` is whatever the most recent `generate_images` run produced. The `image_gcs_url` column is what ties a local row to a GCS blob — without it, Step 2 has no source file to copy from.
- See `references/database_schema.md` for the `prompts` table contract and `references/gcs_to_local_migration.md` for the V3.3 migration story.
