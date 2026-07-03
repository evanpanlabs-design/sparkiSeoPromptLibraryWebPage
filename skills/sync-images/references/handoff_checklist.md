# Handoff Checklist — sync_images (DEPRECATED)

> **Before doing anything else: verify you actually need this skill.**
> In V3.3 the GCS step is gone. If you're on a fresh V3.3+ deploy, delete this
> folder, delete `scripts/sync_images_from_gcs.py`, and move on.

This checklist is for operators who **have confirmed** they're on a legacy
V3.2 deploy with the GCS round-trip intact.

## Pre-flight

- [ ] **Confirm V3.2 (legacy) deploy.** Run the three detection queries in
      `references/gcs_to_local_migration.md` §"How to detect which version
      you're on". If any answer points at V3.3, stop here.
- [ ] **Database exists** at `data/veo_prompts.db` with `prompts` table.
- [ ] **Vertex AI auth works** (`gcloud auth application-default login` or
      `GOOGLE_APPLICATION_CREDENTIALS` exported).
- [ ] **GCS bucket reachable** — `gsutil ls gs://sparki-op-test/prompts/`
      returns at least one blob.
- [ ] **`google-cloud-storage` installed** — `pip show google-cloud-storage`
      shows a version. If `ModuleNotFoundError`, `pip install
      google-cloud-storage` and consider adding it to `requirements.txt`.
- [ ] **At least one `done` row in DB** —
      `sqlite3 data/veo_prompts.db "SELECT COUNT(*) FROM prompts WHERE image_status='done'"`.
      Zero rows means there's nothing to sync.

## Run sequence (legacy V3.2)

```bash
# 1. Sanity: how many done rows do we have?
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print('done:', c.execute(\"SELECT COUNT(*) FROM prompts WHERE image_status='done' AND image_gcs_url IS NOT NULL\").fetchone()[0])"

# 2. Wrapper self-check
python skills/sync-images/scripts/sync_images.py --help
# Expected: usage text + the deprecation banner. Exit 0.

# 3. Dry-run a small batch (Step 1 only; Step 2 still runs — see SKILL.md drift #3)
python skills/sync-images/scripts/sync_images.py --dry-run --limit 5
# Expected: "Images: 0|5 copied, X skipped, Y errors" — Step 2 will probably
# show errors because Step 1's dry-run didn't actually write the source files.

# 4. Real run
python skills/sync-images/scripts/sync_images.py
# Expected: "Images: N copied, M skipped, K errors" where N+M ≈ done rows.

# 5. Verify outputs
ls outputs/generated_images/ | head
ls outputs/images/ | head
```

## Post-run checks

- [ ] `outputs/generated_images/{db_id}.png` exists for every
      `image_status='done' AND image_gcs_url IS NOT NULL` row.
- [ ] `outputs/images/{safe_cat}/{yyyy-mm}/{tweet_id}.png` exists for the same
      rows (the canonical mirror).
- [ ] No new files in `outputs/prompts/` (this skill does not touch the
      detail HTML).
- [ ] No DB writes — confirm by checking `mtime` of `data/veo_prompts.db`.

## Known drift / open issues

These are the 8 drift points documented in `SKILL.md` §"Handoff Notes". The
top three are the most likely to bite a new operator:

1. **GCS stats hidden in the return string** (`core_tools.py:384`). The
   wrapper says `"Images: ..."` but Step 1's `downloaded` / `skipped` /
   `errors` are computed and discarded. Suggested fix:

   ```python
   # in tool_sync_images
   gcs_stats = download_all(dry_run=False, limit=None)
   img_stats = _sync_images_to_flat_dir()
   return (
       f"GCS: {gcs_stats['downloaded']} downloaded, "
       f"{gcs_stats['skipped']} skipped, {gcs_stats['errors']} errors; "
       f"Local: {img_stats['copied']} copied, "
       f"{img_stats['skipped']} skipped, {img_stats['errors']} errors"
   )
   ```

2. **`--dry-run` only affects Step 1.** Step 2 still copies files. Add a
   `dry_run` kwarg to `_sync_images_to_flat_dir()` and gate the `shutil.copy2`
   call. The CLI flag name should then be `--dry-run-step-1` or similar to
   reflect the partial effect.

3. **No retry on GCS errors.** Add `tenacity` (already in `requirements.txt`
   for other tools) around the per-blob download loop, with exponential
   backoff capped at 3 attempts.

4-8. See `SKILL.md` Handoff Notes for: hard-coded bucket name in two places,
silent skip on malformed GCS paths, missing `google-cloud-storage` in
`requirements.txt`, function-name cosmetic drift (`sync_images_to_flat_dir`
vs `_sync_images_to_flat_dir`), and the leading-underscore-as-public
convention confusion.

## When to escalate to a V3.3 migration

If **any** of these are true, just migrate:

- You're writing a new operator onboarding doc — don't make them learn GCS.
- `gs://sparki-op-test` is unreliable (e.g. you see `429 RESOURCE_EXHAUSTED`
  on `list_blobs`).
- The image gen host and the build host are the **same machine** (the most
  common case now). There's no reason to round-trip through GCS.
- You've already removed `google-cloud-storage` from your environment and
  don't want to re-add it.

See `references/gcs_to_local_migration.md` for the upgrade steps.
