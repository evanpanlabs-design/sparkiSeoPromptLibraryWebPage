# Handoff Checklist — retry-failed

> Runbook for the next operator. Each step has a copy-pasteable command. Verify each box before moving to the next.

---

## 1. Install

- [ ] Python 3.11+ is on `PATH`.
- [ ] Project dependencies installed: `pip install -r requirements.txt`.
- [ ] `google-genai` is installed (the `RateLimitSafeGenerator` uses it transitively via `src/image_gen/client.py`).
- [ ] `python-dotenv` is installed (optional — only needed if you want the wrapper to auto-load `.env`).

Verify:

```bash
python -c "from src.image_gen.generator import RateLimitSafeGenerator; print('OK')"
```

---

## 2. Configure

- [ ] `GOOGLE_APPLICATION_CREDENTIALS` is set in your shell, **or** `gcloud auth application-default login` has been run in the last 12 hours.
- [ ] The service account has `roles/aiplatform.user` on project `sparki-op` (the default project used by `RateLimitSafeGenerator`).
- [ ] The service account has `roles/storage.objectCreator` on bucket `gs://sparki-op-test/`.
- [ ] `.env` (if used) does not need any new vars for this skill — `RateLimitSafeGenerator` reads Vertex config from the ADC chain, not from env.

Verify:

```bash
gcloud auth application-default print-access-token | head -c 20 && echo "..."
gcloud storage ls gs://sparki-op-test/prompts/ | head -5
```

---

## 3. Smoke test (no Vertex AI calls)

- [ ] DB exists: `ls data/veo_prompts.db` shows a file (or run `python -m src.main init-db` first).
- [ ] `prompts.image_status` column exists with the CHECK constraint.

Verify:

```bash
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print([r for r in c.execute('PRAGMA table_info(prompts)').fetchall() if 'image' in r[1]])"
```

Expected: at least three rows — `(id, image_status, TEXT, 0, None, 0)`, `(id, image_gcs_url, TEXT, 0, None, 0)`, `(id, image_generated_at, TEXT, 0, None, 0)`.

- [ ] `--help` exits 0.
- [ ] `--project-root /nonexistent` exits 2.
- [ ] `--dry-run` prints candidate failed rows (or the no-work string).

Verify:

```bash
python skills/retry-failed/scripts/retry_failed.py --help
echo "exit=$?"   # expect 0

python skills/retry-failed/scripts/retry_failed.py --project-root /nonexistent
echo "exit=$?"   # expect 2

python skills/retry-failed/scripts/retry_failed.py --batch 5 --dry-run
echo "exit=$?"   # expect 0
```

---

## 4. Minimal real run (`--batch 1`)

- [ ] At least one row in `image_status = 'failed'`. If not, hand-flip one for the smoke test:

```bash
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); c.execute(\"UPDATE prompts SET image_status='failed' WHERE id=(SELECT id FROM prompts WHERE image_status='done' LIMIT 1)\"); c.commit()"
```

- [ ] Real run with `--batch 1` succeeds (exits 0, prints the success string).

```bash
python skills/retry-failed/scripts/retry_failed.py --batch 1
```

- [ ] After the run, the row that was `'failed'` is now either `'done'` (with a new `image_gcs_url`) or back to `'failed'` (if Vertex is down).

```bash
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print(c.execute(\"SELECT id, image_status, image_gcs_url FROM prompts WHERE id IN (SELECT id FROM prompts ORDER BY id DESC LIMIT 1)\").fetchall())"
```

---

## 5. Full retry pass

- [ ] `--batch 8` (or higher) — runs serially with 2s interval per row, ~14s per row worst case (3 retries).

```bash
python skills/retry-failed/scripts/retry_failed.py --batch 50
```

- [ ] Pool counts look right:

```bash
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print({r['image_status']: r['cnt'] for r in c.execute('SELECT image_status, COUNT(*) as cnt FROM prompts GROUP BY image_status').fetchall()})"
```

---

## 6. V3.3 migration TODO

> These are the changes that will be required when V3.3 lands (GCS 中转废除 → 本地直存). They are **not** required for V3.2 operation, but they will become mandatory.

- [ ] Replace `image_gcs_url` with `image_local_path` in `tool_retry_failed` (success-path UPDATE on `core_tools.py:652`).
- [ ] Replace the `generator.generate()` call with a local file write to `outputs/generated_images/{id}.png`.
- [ ] Update the schema migration: drop `image_gcs_url`, add `image_local_path TEXT`.
- [ ] Update `RateLimitSafeGenerator` (or replace it with a local writer) — the GCS client logic moves to a separate `image_attempts` logger.
- [ ] Add the published-state guard to the bulk UPDATE: `WHERE id IN (...) AND image_status = 'pending'` (instead of the current un-guarded version).
- [ ] Add an `image_attempts` row insert on every failure with `error_message = str(e)`.
- [ ] Stop using `image_status = 'generating'` as a real state — V3.3 wants the simpler 3-flag model (`has_raw_tweet`, `has_prompt`, `has_cover_image`).
- [ ] Add an index `CREATE INDEX idx_prompts_image_status ON prompts(image_status)` (or rename to `has_cover_image` and index that).
- [ ] Write `image_generated_at` on the success path (currently `tool_retry_failed` does not — see Handoff Notes drift #2 in `SKILL.md`).

---

## 7. Known issues / future cleanup

- [ ] **Published-state loss caveat** (Handoff Notes drift #3). Add the `AND image_status = 'pending'` guard to the bulk UPDATE.
- [ ] **No exception logging.** The bare `except Exception:` on `core_tools.py:662` swallows the error message. Replace with `except Exception as e: print(f"  [retry_failed] id={row['id']} error: {e}", file=sys.stderr)`.
- [ ] **`max_workers` is dead config in this path** — `RateLimitSafeGenerator` is constructed with `max_workers=3` but only the single-shot `generate()` is called. Either remove the constructor kwarg or migrate to `generate_batch()`.
- [ ] **No `image_status = 'generating'` recovery path.** If a parallel `generate_images` run is killed mid-flight, those rows stay in `'generating'` forever. This tool does not pick them up. Either add `'generating'` to the SELECT or do a one-time UPDATE before invoking.
- [ ] **GCS key uses integer `prompts.id`, not `prompts.tweet_id`.** Cosmetic drift (see `SKILL.md` Handoff Notes drift #4). Fix in V3.3 if you want human-readable GCS keys.

---

## 8. Quick-reference command summary

```bash
# Smoke test (no LLM/GCS)
python skills/retry-failed/scripts/retry_failed.py --batch 5 --dry-run

# Single-row real run
python skills/retry-failed/scripts/retry_failed.py --batch 1

# Full retry
python skills/retry-failed/scripts/retry_failed.py --batch 50

# Pool counts
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print({r['image_status']: r['cnt'] for r in c.execute('SELECT image_status, COUNT(*) as cnt FROM prompts GROUP BY image_status').fetchall()})"

# List candidate failed rows (manual triage)
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); [print(r) for r in c.execute(\"SELECT id, tweet_id, category, image_gcs_url FROM prompts WHERE image_status='failed' LIMIT 20\").fetchall()]"
```
