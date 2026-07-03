# GCS → Local Migration (V3.2 → V3.3)

The `sync_images` tool exists because V3.2 generates cover images **on a remote
host** (the GCS bucket `gs://sparki-op-test`) and then **mirrors** them down to
the build host before the static HTML is generated. In V3.3 the image
generator runs **on the build host itself** and writes directly to
`outputs/generated_images/` — the GCS round-trip disappears.

This document tells the operator which version they're on, and what to do
about it.

## How to detect which version you're on

```bash
# 1. Does your generate_images write to GCS?
grep -n "image_gcs_url" src/image_gen/generator.py
# V3.2: matches (writes to GCS, sets image_gcs_url in DB)
# V3.3: no match (writes only to outputs/generated_images/, sets image_local_path in DB)

# 2. Does your prompts table have image_gcs_url populated?
sqlite3 data/veo_prompts.db \
  "SELECT COUNT(*) FROM prompts WHERE image_gcs_url IS NOT NULL"
# V3.2 legacy: > 0
# V3.3 fresh: 0

# 3. Is google-cloud-storage a hard dependency?
grep -n "google-cloud-storage" requirements.txt
# V3.2 legacy: present (or should be — see SKILL.md drift #8)
# V3.3 fresh: absent
```

**If any of these point at V3.3, you do not need `sync_images`. Delete the
skill folder and the dead scripts.** They are dead code.

## The two flows side by side

### V3.2 (legacy — GCS round-trip)

```
[build host]                          [GCS bucket]
generate_images
  → POST to Vertex AI / Imagen
  → upload PNG ─────────────────────► gs://sparki-op-test/prompts/{cat}/{yyyy-mm}/{db_id}.png
  → UPDATE prompts SET image_status='done', image_gcs_url=...
                                                            │
[build host]                                                │
sync_images (this skill)                                    │
  Step 1: download_all() ◄──────────────────────────────────┘
    → list_blobs(prefix='prompts/')
    → blob.download_to_file()
    → outputs/images/{safe_cat}/{yyyy-mm}/{tweet_id}.png
  Step 2: _sync_images_to_flat_dir()
    → outputs/generated_images/{db_id}.png
                                                            │
build_html                                                  │
  → reads outputs/generated_images/ ◄──────────────────────┘
publish
  → git push outputs/
```

Failure modes:
- Network blip on the GCS download → blob is skipped silently (size-mismatch
  on next run retries).
- Bucket permissions → entire step fails hard.
- GCS quota → silent `errors` counter.
- `image_gcs_url IS NULL` for a `done` row → Step 2 reports `errors` and the
  cover is missing from the HTML.

### V3.3 (target — local-only)

```
[build host]
generate_images
  → POST to Vertex AI / Imagen
  → write PNG to outputs/generated_images/{db_id}.png
  → UPDATE prompts SET has_cover_image=1, image_local_path=...
                                                            │
build_html (sync_images flag is ignored / removed)         │
  → reads outputs/generated_images/ ◄──────────────────────┘
publish
  → git push outputs/
```

Failure modes (simpler):
- Disk full on the build host → write fails. Easy to detect.
- Vertex AI rate limit → handled by `RateLimitSafeGenerator`'s serial mode.
- No remote dependency, no auth dance, no silent skip.

## Upgrade checklist (V3.2 → V3.3)

1. **Stop writing to GCS** in `generate_images`. Remove the `image_gcs_url`
   column writes (or keep the column as nullable legacy).
2. **Update `tool_generate_images()`** to write to `outputs/generated_images/{id}.png`
   directly. Set `image_status='done'` (or `has_cover_image=1` in V3.3 schema).
3. **Remove the `sync_images` skill**:
   - Delete `skills/sync-images/` (this folder).
   - Delete `scripts/sync_images_from_gcs.py`.
   - Remove `tool_sync_images` from `src/agent/skills/core_tools.py` (line 366-391).
   - Remove the `sync_images=True` parameter from `tool_build_html()` and the
     inline call to `_sync_images_to_flat_dir()` in `scripts/build_html.py`.
4. **Remove `google-cloud-storage`** from any deploy docs and the
   (currently missing) `requirements.txt` entry.
5. **Optionally delete the `image_gcs_url` column** in `src/memory/schema.py`
   once no rows have it populated.
6. **Update `docs/11_ToolInterface.md`** — remove §5 `sync_images` and the
   callout. Update the V3.3 pipeline diagram to confirm `sync_images 已废除`.

## Staying on V3.2 (when you can't migrate yet)

Some operators are stuck on V3.2 because:
- Image generation runs on a different host than the build (common when
  `image_gen/` runs on a GPU box and `build_html` runs on a small VPS).
- A staging environment still needs the GCS round-trip for cost-accounting
  reasons.

In that case, keep this skill. The wrapper exits cleanly, the GCS bucket
remains the source of truth, and the rest of the pipeline doesn't change.

But:
- Add `google-cloud-storage` to `requirements.txt` so a fresh clone doesn't
  fail at the `from google.cloud import storage` line.
- Surface `gcs_stats` in the wrapper's return string (see
  `references/handoff_checklist.md` drift #2).
- Add a deployment flag in `configs/gemini.yaml` (`deploy.local_only: bool`)
  so future operators can flip the V3.3 path on without code changes.

## What the next operator should know

- The GCS bucket `sparki-op-test` is a **test** bucket. The "official" path
  is documented in `docs/10_ProjectOverview.md` and points at a different
  bucket. If you see references to `sparki-op-prod` or similar in your
  environment, the V3.2 deploy was already customized — confirm before
  re-running.
- The GCS layout `prompts/{cat}/{yyyy-mm}/{db_id}.png` is **not** enforced by
  the uploader — it's a convention. If you ever see `prompts/{db_id}.png` (no
  category or date folder), this skill's parser will skip it silently.
- `_safe_category` replaces `/` with `_` on the local side, but the GCS side
  keeps the original `/`. If you `gsutil ls gs://sparki-op-test/prompts/`,
  you'll see the original names; if you `ls outputs/images/`, you'll see the
  sanitized names. This is intentional but confusing.
