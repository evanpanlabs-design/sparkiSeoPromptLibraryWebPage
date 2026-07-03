---
name: build-html
description: Build the static HTML landing page for the Veo Prompt Library — writes `outputs/index.html` (one root page with an embedded `const prompts = [...]` JSON array) plus `outputs/prompts/{slug}.html` detail pages (1 + N). Reads `prompts` table with hard-coded filter `image_status='done' AND image_gcs_url IS NOT NULL`, optional `category` (string) / `min_score` (float) / `limit` (int) filters, ORDER BY `quality_scores DESC`. Use after `generate_images` has populated cover images and before `publish` ships the site. Use when the agent says "build HTML", "rebuild the landing page", "preview the static site locally", or invokes `tool_build_html`. Do NOT use for crawling, extraction, scoring, image generation, or git push — those are separate skills.
---

# Build HTML (V3.2 — 1+N Static Site Generator)

## What It Does

Reads `prompts` rows where the cover image is finished (`image_status='done'` AND `image_gcs_url IS NOT NULL`), serializes them as a JSON array, splices the array into the index template (`outputs/templates/index.html`) at the `PROMPTS_ARRAY_SENTINEL` markers, and writes:

1. **One** root page: `outputs/index.html` (grid of all prompt cards, client-side filter/sort in JS).
2. **N** detail pages: `outputs/prompts/{title-slug}-{tweet_id}.html` (one per prompt, all data baked into the HTML — no JS routing).

Optionally first copies cover images from `outputs/images/{cat}/{yyyy-mm}/{tweet_id}.png` to the flat `outputs/generated_images/{db_id}.png` directory the HTML expects. **That copy step is the deprecated GCS-sync path** — see Handoff Notes.

This skill does **not** crawl, extract, score, generate images, or push to git.

## When To Use

- After `generate_images` (or `retry_failed`) has set rows to `image_status='done'`.
- Before `publish` (which `git add outputs/` and pushes to `gh-pages`).
- When the operator says: "build HTML", "rebuild landing page", "preview site", "重新生成 index", or asks the ReAct agent to invoke `tool_build_html`.

## When NOT To Use

- For X.com crawl → `apify-x-crawler`.
- For LLM prompt extraction → `extract-prompts`.
- For quality scoring → `score_prompts`.
- For Gemini image generation → `generate_images`.
- For git commit + push → `publish`.
- For GCS download → `sync_images_from_gcs.py` (run separately; do **not** rely on this skill's deprecated `sync_images=True` default).

## Required Context

- Project root: `16_NewCrawler`
- Tool wrapper: `src/agent/skills/core_tools.py:398-429` (`tool_build_html`)
- Builder script: `scripts/build_html.py` (functions: `build()`, `fetch_all_prompts()`, `build_index()`, `build_detail_pages()`, `_build_detail_static()`, `sync_images_to_flat_dir()`, `slugify()`, `make_slug()`)
- Index template: `outputs/templates/index.html` (1504 lines; sentinel markers at lines 1130 and 1285)
- Detail template: **inline** in `scripts/build_html.py:163-421` (`_DETAIL_HTML` string constant — Mustache-ish `{{placeholder}}` syntax)
- Output dirs: `outputs/index.html`, `outputs/prompts/`, `outputs/generated_images/`
- DB: `data/veo_prompts.db` → table `prompts` (LEFT JOIN `tweets` for `created_at`)
- Docs: `docs/11_ToolInterface.md` §6, `docs/tools/06_build_html.md` (both partly stale — see Handoff Notes)

## Preconditions

1. **DB initialized**: `python -m src.main init-db` (creates `prompts` table with `idx_prompts_category` index).
2. **Rows with finished images** exist: `SELECT COUNT(*) FROM prompts WHERE image_status='done' AND image_gcs_url IS NOT NULL` > 0. If 0, the builder writes neither `index.html` nor any detail page and returns `{"index": 0, "details": 0}`.
3. **Index template present**: `outputs/templates/index.html` exists and contains both sentinel markers: `const prompts = [` and `] // PROMPTS_ARRAY_SENTINEL;`. Otherwise `build_index()` raises `ValueError("Sentinel markers not found in index template")`.
4. **Cover images present** in `outputs/generated_images/{db_id}.png` — either pre-synced by `generate_images` (V3.3 target) or freshly copied by the deprecated `sync_images=True` step. Missing images fall back to `https://picsum.photos/seed/{tweet_id}/...` at render time, so the build still succeeds.
5. Python deps: stdlib only for the builder (`json`, `re`, `shutil`, `sqlite3`, `datetime`, `pathlib`). No LLM call, no GCS call, no network.

## Inputs

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `category` | `str` | `None` | Filter `WHERE p.category = ?`. Free-form; pass the exact category as stored in the DB (e.g. `"cinematic"`, `"video-generation"`, `"other"`). |
| `min_score` | `float` | `None` | Filter `WHERE CAST(p.quality_scores AS REAL) >= ?`. Casts the CSV `quality_scores` field as REAL; values without a numeric leading component will be silently dropped by SQLite's CAST. |
| `limit` | `int` | `None` | Cap the number of prompts in both `index.html` and `prompts/*.html`. Applied **after** the SQL `ORDER BY quality_scores DESC`. |
| `sync_images` | `bool` | `True` (V3.2) → `False` (V3.3) | Whether to first copy `outputs/images/{cat}/{yyyy-mm}/*.png` → `outputs/generated_images/{db_id}.png`. **Deprecated; see Handoff Notes #1.** |

The CLI wrapper (`scripts/build_html.py`) additionally accepts `--project-root`, `--no-sync-images` (flips the default to `False`), and `--dry-run` (counts SELECT rows without writing files).

## Outputs

- **Success string** (returned by `tool_build_html`, printed to stdout by the CLI):
  ```
  Built HTML: {N} prompts
  ```
  where `{N}` is `len(prompts)` after filters. The wrapper currently reads `stats['source_rows']` which is a **broken key** — see Handoff Notes #4.

- **Side effects**:
  - Overwrites `outputs/index.html` (1 file).
  - Overwrites `outputs/prompts/{slug}.html` (N files, one per surviving prompt). Stale files from prior runs are **not** cleaned.
  - If `sync_images=True`, copies any missing covers into `outputs/generated_images/{db_id}.png`.

- **Failure string** (returned, non-zero exit code from wrapper):
  ```
  错误: {ExceptionType}: {message}
  ```

## Data Contract

### Input — `prompts` (+ LEFT JOIN `tweets` for `created_at`)

| Column | Used as | Notes |
|---|---|---|
| `id` | `{{db_id}}` in detail template, image filename `generated_images/{id}.png` | INTEGER PRIMARY KEY |
| `tweet_id` | `{{tweet_id}}`, slug suffix, X URL fallback, picsum fallback seed | TEXT UNIQUE |
| `url` | `{{x_url}}`, detail "View on X" link | TEXT NOT NULL; fallback `https://x.com/unknown/status/{tweet_id}` if NULL |
| `category` | filter, `{{category}}` / `{{category_display}}` (with `-` → space) | TEXT NOT NULL; default `"other"` if NULL |
| `title` | `{{title}}` and slug base | truncated to `[:120]` chars; `""` if NULL |
| `prompt_text` | `{{prompt_text}}` and `{{prompt_text_json}}` (for clipboard copy) | NOT NULL |
| `notes` | `{{notes}}` block (conditionally rendered via Mustache `{{#notes}}…{{/notes}}`) | NULL → block stripped |
| `author_name`, `author_screen`, `author_followers` | author byline | denormalized |
| `likes_count`, `retweet_count`, `reply_count` | engagement stats panel | formatted with `_format_number()` (k-suffix at ≥1000) |
| `quality_scores` | SELECT filter (`CAST AS REAL >= ?`) + ORDER BY (`DESC`) | CSV string `spec,vis,nov,gen,overall` from `score_prompts` |
| `image_status` | SELECT filter (`= 'done'`, hard-coded) | TEXT CHECK IN ('pending','generating','done','failed','published') |
| `image_gcs_url` | SELECT filter (`IS NOT NULL`, hard-coded) | drift target — see Handoff Notes #2 |
| `tweets.created_at` | `{{published_at}}` (formatted as YYYY-MM-DD) | from LEFT JOIN; `""` if NULL |

### Output — files

| Path | Owner | Contents |
|---|---|---|
| `outputs/index.html` | `build_index()` (line 139) | Template with JSON array spliced between `const prompts = [` and `] // PROMPTS_ARRAY_SENTINEL;` |
| `outputs/prompts/{slug}.html` | `build_detail_pages()` (line 510) | `_DETAIL_HTML` (line 163) with `{{placeholder}}` substitutions + `{{#notes}}…{{/notes}}` conditional + Same-Category recommendation cards (up to 3) |
| `outputs/generated_images/{db_id}.png` | `sync_images_to_flat_dir()` (line 104) — only when `sync_images=True` | Copy of `outputs/images/{safe_cat}/{yyyy-mm}/{tweet_id}.png` |

**Slug format**: `slugify(title)[:80] + "-" + tweet_id` (see `make_slug()` line 38). `slugify()` lowercases, strips non-`\w\s-` chars, collapses whitespace to `-`, deduplicates `-`. URL-safe and Windows-safe.

## Procedure

1. **`tool_build_html(args)`** (`core_tools.py:398`) reads `category`, `min_score`, `limit`, `sync_images` (default `True`) from `args`.
2. **If `sync_images=True`**: calls `_sync_images_to_flat_dir()` — **this import is currently broken**, see Handoff Notes #3.
3. **Calls `build_html(limit=..., category=..., min_score=..., only_with_image=True)`** — **this call is currently broken**: the function is named `build()` and does not accept `only_with_image`. See Handoff Notes #3.
4. **`build()`** (`scripts/build_html.py:529`):
   1. If `sync_images=True`, calls `sync_images_to_flat_dir()` again (double sync when invoked via the tool).
   2. `fetch_all_prompts(category, min_score)` runs the SQL:
      ```sql
      SELECT p.*, t.created_at
      FROM prompts p
      LEFT JOIN tweets t ON p.tweet_id = t.tweet_id
      WHERE p.image_status = 'done' AND p.image_gcs_url IS NOT NULL
      [AND p.category = ?]
      [AND CAST(p.quality_scores AS REAL) >= ?]
      ORDER BY CAST(p.quality_scores AS REAL) DESC
      ```
   3. If `limit`, slices `prompts[:limit]`.
   4. If no rows, returns `{"index": 0, "details": 0}` — neither file is touched.
   5. `build_index(prompts)`: reads `outputs/templates/index.html`, locates the two sentinel markers, splices `json.dumps(prompts, ensure_ascii=False, indent=4)` (stripped of outer `[...]`), writes `outputs/index.html`.
   6. `build_detail_pages(prompts)`: for each prompt, runs `_build_detail_static()` (Mustache-ish replace + Same-Category sidebar), writes `outputs/prompts/{slug}.html`.
   7. Returns `{"index": 1, "details": N, "total_prompts": N}`.
5. **`tool_build_html`** reads `stats['source_rows']` — **does not exist**; would raise `KeyError`. See Handoff Notes #4.

## Validation

```bash
# 1. CLI help
python skills/build-html/scripts/build_html.py --help

# 2. Dry-run (no file writes, just SELECT count)
python skills/build-html/scripts/build_html.py --dry-run

# 3. Real build, no sync (recommended for V3.3 forward-compatible flow)
python skills/build-html/scripts/build_html.py --no-sync-images

# 4. Real build with the deprecated sync step (V3.2 default behaviour)
python skills/build-html/scripts/build_html.py

# 5. Category + score filter
python skills/build-html/scripts/build_html.py \
  --category cinematic \
  --min-score 0.5 \
  --limit 20 \
  --no-sync-images

# 6. Confirm artefacts
ls outputs/index.html
ls outputs/prompts/ | wc -l
```

Wrapper exit codes:
- `0` on success (real run or dry-run)
- `1` if the tool returned `错误: ...`
- `2` if the project root cannot be located

## Failure Handling

| Symptom | Likely cause | Action |
|---|---|---|
| `ImportError: cannot import name 'build_html' from 'scripts.build_html'` | The tool wrapper imports `build_html`, but the actual function is `build()`. | Patch `core_tools.py:409` to `from scripts.build_html import build as build_html` **or** rename `build()` → `build_html()`. See Handoff Notes #3. |
| `ImportError: cannot import name '_sync_images_to_flat_dir'` | The tool wrapper imports the underscore-prefixed name; the actual function is `sync_images_to_flat_dir` (no underscore). | Same patch as above, or `from scripts.build_html import sync_images_to_flat_dir as _sync_images_to_flat_dir`. |
| `KeyError: 'source_rows'` | The tool reads `stats['source_rows']`, but `build()` returns `{"index", "details", "total_prompts"}`. | Patch the tool to read `stats.get('total_prompts', 0)`. |
| `ValueError: Sentinel markers not found in index template` | `outputs/templates/index.html` was edited and lost the `const prompts = [` and `] // PROMPTS_ARRAY_SENTINEL;` markers. | Re-insert both markers around the seed `prompts` array (lines 1130 and 1285 in the current template). |
| `index.html` written with 0 prompts | Either the DB has no `image_status='done'` rows with `image_gcs_url`, or `category`/`min_score` over-filtered. | Drop filters and re-run; check `SELECT COUNT(*) FROM prompts WHERE image_status='done' AND image_gcs_url IS NOT NULL`. |
| All detail pages render the picsum fallback image | Cover images never landed in `outputs/generated_images/`. | Run `python scripts/sync_images_from_gcs.py` first (legacy GCS path) or wait for the V3.3 inline-copy migration in `generate_images`. |
| Stale `outputs/prompts/{slug}.html` files from prior runs | The builder never cleans `outputs/prompts/`; deleted prompts leave orphan pages. | Manually `rm outputs/prompts/*.html` before a clean rebuild, or add a wipe step in V3.3. |
| `outputs/index.html` doubles in size after each run | Re-running the build appends a fresh JSON array each time **only if the sentinel logic mis-matches**. With current sentinels, this should be idempotent. | If you see growth, verify the splice indices in `build_index()` (line 143-156) — sentinels must be unique substrings. |

## Handoff Notes

These are the **five verified drift points** between the wiki (`docs/11_ToolInterface.md` §6, `docs/tools/06_build_html.md`), the tool wrapper (`tool_build_html`), and the actual builder (`scripts/build_html.py`). **Prioritize `scripts/build_html.py` and the live DB as the source of truth.**

1. **`sync_images=True` is the V3.2 default but the path it triggers is DEPRECATED.**
   - `docs/11_ToolInterface.md` §5 (`sync_images`) says: "⚠️ GCS 中转已废除，此工具保留用于兼容，后续可能废弃." (GCS relay is abolished; this tool is preserved for compatibility and may be deprecated later.)
   - `tool_build_html()` still calls `_sync_images_to_flat_dir()` on every invocation (line 416-417). The CLI wrapper defaults to the same behaviour for parity.
   - **V3.3 migration**: flip the default to `sync_images=False`. The V3.3 plan (`docs/11_ToolInterface.md` line 451: "build_html ← sync_images 已废除，直接引用 generated_images/") has `generate_images` copy directly to `outputs/generated_images/{id}.png`. After that migration, the `_sync_images_to_flat_dir` call must be removed from this tool entirely.
   - **In the meantime**: pass `--no-sync-images` (CLI) or `{"sync_images": False}` (tool args) to skip the deprecated path. Pre-sync separately with `python scripts/sync_images_from_gcs.py` if cover images need refreshing.

2. **The SQL hard-codes `image_gcs_url IS NOT NULL` — V3.3 will need `image_local_path IS NOT NULL`.**
   - `fetch_all_prompts()` (`scripts/build_html.py:59`): `WHERE p.image_status = 'done' AND p.image_gcs_url IS NOT NULL`. The `image_status='done'` half matches the wiki's "WHERE image_status='done'" claim, but the GCS-URL half is **not in the wiki**.
   - The schema today (`schema.py:78-100`) has only `image_gcs_url` — there is no `image_local_path` column. The V3.3 plan adds it (`docs/11_ToolInterface.md` line 187, line 408, line 451). When that column lands, this SELECT must be updated to `OR image_local_path IS NOT NULL` (transition) and eventually `image_local_path IS NOT NULL` (after GCS removal).
   - The `tool_build_html()` wrapper passes `only_with_image=True` to the inner function (line 423), but **`build()` does not accept that parameter** — the filter is hard-coded, the kwarg is ignored if it ever reaches the right function. See drift #3.

3. **`tool_build_html()` imports symbols that do not exist in `scripts/build_html.py`.**
   - `core_tools.py:409`: `from scripts.build_html import build_html, _sync_images_to_flat_dir`
   - Actual names in `scripts/build_html.py`: `build()` (line 529) and `sync_images_to_flat_dir()` (line 104, **no leading underscore**).
   - Same broken import is in `tool_sync_images()` (`core_tools.py:376`).
   - **The tool wrapper is currently un-callable end-to-end.** It will raise `ImportError` on the first invocation. The CLI wrapper in this skill therefore bypasses `tool_build_html()` and calls `scripts.build_html.build()` directly. Once `core_tools.py` is patched, the wrapper can be reverted to delegate to `tool_build_html()`.
   - Recommended patch (`core_tools.py:409`):
     ```python
     from scripts.build_html import build as _build, sync_images_to_flat_dir as _sync_images_to_flat_dir
     ```
     Then call `_build(...)` instead of `build_html(...)`, and drop the `only_with_image=True` kwarg (no-op).

4. **`tool_build_html()` reads `stats['source_rows']` — the key does not exist.**
   - `build()` returns `{"index": 1, "details": N, "total_prompts": N}` (line 546). There is no `source_rows`.
   - Even after the import fix in #3, the very next line (`core_tools.py:426`) raises `KeyError: 'source_rows'`.
   - Recommended patch: `return f"Built HTML: {stats.get('total_prompts', 0)} prompts"`.

5. **Wiki says detail pages are `outputs/prompts/{tweet_id}.html`; actual filename is `{title-slug}-{tweet_id}.html`.**
   - `docs/11_ToolInterface.md` line 249: `outputs/prompts/{tweet_id}.html`.
   - Actual: `outputs/prompts/{slug}.html` where `slug = slugify(title)[:80] + "-" + tweet_id` (see `make_slug()` line 38, `build_detail_pages()` line 520).
   - **Implication**: any external link or sitemap that assumes `prompts/{tweet_id}.html` is wrong. The Same-Category recommendation cards inside detail pages correctly use the slug (`{rp['slug']}.html`, line 495), so internal navigation works. External consumers must read the actual filename from a manifest.

### Other things the next operator should know

- **Live DB state at the time of writing** (from `PRAGMA table_info(prompts)` + the documented count queries):
  - `prompts.image_status='done'`: see verification output below.
  - `prompts.image_status='done' AND image_gcs_url IS NOT NULL`: this is the effective input set.
  - `idx_prompts_category` index (`schema.py:125`) means category filters are O(log n); `quality_scores` index also exists.
- **The builder writes `1 + N` files; the wiki sometimes says "1 page only".** Both `outputs/index.html` and per-prompt detail pages under `outputs/prompts/` are written on every successful run. `docs/tools/06_build_html.md` only mentions `outputs/index.html`.
- **The detail HTML template lives inline in `scripts/build_html.py:163-421` (the `_DETAIL_HTML` constant).** It is **not** a file in `outputs/templates/`. If you want to externalize it, do that in V3.3 — be aware that the current `_build_detail_static()` uses Mustache-ish `{{placeholder}}` and a custom `{{#notes}}…{{/notes}}` conditional that a real Mustache engine would not parse the same way (the `notes` block is rendered with `re.DOTALL`).
- **`build_index()` splices a JSON array between two sentinel substrings** (line 143-156). The sentinels must remain unique in the template — adding the substring `const prompts = [` anywhere else (e.g. inside a JS comment) will break the splice. Today's template has them only at lines 1130 and 1285.
- **No cleanup of stale detail pages.** Renaming a prompt's title changes its slug, leaving the old `prompts/{old-slug}.html` orphaned on disk. `publish` will commit the orphan. Manual `rm outputs/prompts/*.html` before a rebuild is the only safe cleanup today.
- **The CLI in `scripts/build_html.py:549-564` (`if __name__ == "__main__"`)** has a different default for `--sync-images` (default `False`, opt-in flag) than the tool wrapper (`sync_images=True`). The CLI wrapper in **this** skill follows the **tool wrapper** default (`True`, with `--no-sync-images` to flip) to preserve V3.2 behaviour. V3.3 will align everything to `False`.
- **V3.3 migration checklist** (when GCS is fully removed):
  1. Drop `_sync_images_to_flat_dir()` call from `tool_build_html()` and `tool_sync_images()` (delete the latter).
  2. Replace `image_gcs_url IS NOT NULL` with `image_local_path IS NOT NULL` in `fetch_all_prompts()`.
  3. Flip CLI + tool default for `sync_images` to `False` (or remove the parameter entirely).
  4. Update wiki: detail filename pattern, 1+N count, `source_rows` → `total_prompts`.
- **Concurrency / safety**: this skill is **single-threaded and idempotent for the same input set**. Re-running with the same DB state overwrites `outputs/index.html` and each `prompts/{slug}.html` in place — safe to re-run in CI.
- See `references/database_schema.md` for the `prompts` columns used, `references/html_template.md` for the template structure, and `references/handoff_checklist.md` for the install / smoke-test / V3.3 migration runbook.
