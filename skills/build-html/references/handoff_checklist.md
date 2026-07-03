# Handoff Checklist — `build-html`

Use this when onboarding a new operator to the build_html phase or after
bumping to V3.3.

## 1. Install

```bash
# From project root
cd 16_NewCrawler

# Base project deps (stdlib is enough for build_html itself, but the
# project as a whole needs google-genai etc.)
pip install -r requirements.txt

# Optional but recommended: python-dotenv so the wrapper picks up .env
pip install python-dotenv
```

No additional packages are required for `build-html` specifically — the
builder uses stdlib only (`json`, `re`, `shutil`, `sqlite3`, `pathlib`,
`datetime`).

## 2. Configure

### Required files

| Path | Purpose | Action if missing |
|---|---|---|
| `data/veo_prompts.db` | SQLite database | `python -m src.main init-db` |
| `outputs/templates/index.html` | Index page template | Restore from git (`gh-pages` branch has the canonical version) |
| `outputs/generated_images/` | Flat dir for cover PNGs | Will be created by `sync_images_to_flat_dir()` on first run with `sync_images=True` |
| `outputs/prompts/` | Detail page output dir | Created automatically by `build_detail_pages()` |

### Template sentinel check

Open `outputs/templates/index.html` and confirm **both** sentinel substrings
appear exactly once:

```bash
grep -c "const prompts = \[" outputs/templates/index.html      # must be 1
grep -c "] // PROMPTS_ARRAY_SENTINEL;" outputs/templates/index.html  # must be 1
```

If the count is 0 or > 1, `build_index()` will raise `ValueError`.

### No env vars required

`build-html` reads **nothing** from environment variables. No `APIFY_API_TOKEN`,
no `GOOGLE_APPLICATION_CREDENTIALS`, no GCS credentials. It is a pure
DB-to-HTML transformer.

If you set `sync_images=True` (default), the **copy step** is purely local
filesystem — it does **not** call GCS. Pre-syncing from GCS is a separate
script: `python scripts/sync_images_from_gcs.py`.

## 3. Smoke test (no filters)

```bash
# Step 1 — dry-run, no file writes
python skills/build-html/scripts/build_html.py --dry-run
# Expected output:
#   Would build: <N>/<N> prompts (category=None, min_score=None, limit=None)
#   → outputs/index.html: WOULD be written
#   → outputs/prompts/*.html: WOULD be written (<N> detail pages)
# Exit code: 0

# Step 2 — verify the DB has eligible rows
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print('done with gcs:', c.execute(\"SELECT COUNT(*) FROM prompts WHERE image_status='done' AND image_gcs_url IS NOT NULL\").fetchone()[0])"
# Expect: a number > 0. If 0, the build will write nothing.

# Step 3 — real build, skip deprecated sync (V3.3 forward-compatible)
python skills/build-html/scripts/build_html.py --no-sync-images
# Expected: "Built HTML: <N> prompts (index=1, details=<N>)"
# Exit code: 0

# Step 4 — confirm artefacts
ls -la outputs/index.html
ls outputs/prompts/ | head
```

## 4. Filtered builds

```bash
# Single category, top 20 by quality score
python skills/build-html/scripts/build_html.py \
    --category cinematic \
    --min-score 0.5 \
    --limit 20 \
    --no-sync-images

# Verify category match
grep -c '"category": "cinematic"' outputs/index.html
```

## 5. V3.3 migration steps

When the GCS-removal migration lands:

| Step | File | Change |
|---|---|---|
| 1 | `src/agent/skills/core_tools.py:413` | Change `sync_images = bool(args.get("sync_images", True))` to `False`. |
| 2 | `src/agent/skills/core_tools.py:416-417` | Delete the `if sync_images: _ = _sync_images_to_flat_dir()` block. |
| 3 | `src/agent/skills/core_tools.py:409` | Patch the import: `from scripts.build_html import build as build_html` (drop `_sync_images_to_flat_dir`). |
| 4 | `src/agent/skills/core_tools.py:419-424` | Drop `only_with_image=True` kwarg (no-op). |
| 5 | `src/agent/skills/core_tools.py:426` | `return f"Built HTML: {stats.get('total_prompts', 0)} prompts"`. |
| 6 | `scripts/build_html.py:59` | Change `image_gcs_url IS NOT NULL` to `image_local_path IS NOT NULL` (after the column is added). |
| 7 | `scripts/build_html.py:529` | Change `def build(sync_images: bool = False, ...)` default to remove the param entirely, or keep as `False` with deprecation warning. |
| 8 | `skills/build-html/scripts/build_html.py` | Drop `--no-sync-images` flag; sync becomes a separate skill. |
| 9 | `docs/11_ToolInterface.md` §6 | Update detail filename pattern (`{slug}.html`, not `{tweet_id}.html`), output count ("1 + N", not "1"), and remove `sync_images` from the input table. |
| 10 | `docs/tools/06_build_html.md` | Mark `--no-image-filter` and `--repo PATH` as removed (they never existed). |

## 6. Common errors

| Error | Cause | Fix |
|---|---|---|
| `ImportError: cannot import name 'build_html'` | Trying to call `tool_build_html()` directly without patching core_tools.py. | Use this skill's CLI wrapper (which calls `build()` directly), or apply patch from §5 step 3. |
| `ValueError: Sentinel markers not found in index template` | Template was edited and lost the splice markers. | Restore `outputs/templates/index.html` from git (`gh-pages` branch). |
| `Built HTML: 0 prompts` | `WHERE image_status='done' AND image_gcs_url IS NOT NULL` matches nothing. | Run `generate_images` first; verify `pool_status` shows `done > 0`. |
| Detail pages render picsum placeholders only | `outputs/generated_images/{db_id}.png` missing for all rows. | Run `python scripts/sync_images_from_gcs.py` then re-build with `sync_images=True`. |
| Orphan detail pages from old runs | `outputs/prompts/` is never wiped. | `rm outputs/prompts/*.html` before re-build. |

## 7. Pipeline position

```
crawl_tweets → extract_prompts → score_prompts → generate_images → [sync_images?]
    → build_html  ← you are here
    → publish
```

`build-html` runs **after** images are done, **before** git push. It is
re-runnable — re-running with the same DB state overwrites `outputs/`
deterministically (modulo the orphan-detail-page caveat above).
