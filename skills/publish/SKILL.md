---
name: publish
description: Build the static Veo Prompt Library HTML, sync cover images into the flat `generated_images/` directory, commit the resulting `outputs/index.html` + `outputs/prompts/*.html` to the local Git repo, and `git push origin gh-pages` so the GitHub Pages site at `sparkiSeoPromptLibraryWebPage` deploys. Use this skill whenever the agent is asked to "发布" / "publish" / "push to GitHub Pages" / "上线" / "部署 gh-pages" / "更新主页" / "跑 publish" / "跑 build_html + push" / "deploy the prompt library", or whenever the user wants to take a freshly built `outputs/index.html` and ship it to GitHub Pages. This is the last step of the V3.2 pipeline — it MUST be run after `build_html` (or after the full Pipeline-mode auto-chain) and MUST NOT be run for dry-runs / smoke tests without `--dry-run`. The tool also still embeds the legacy GCS-coupled image-sync step inside `scripts/build_html.py --sync-images`, even though the GCS upload has been retired (V3.2 footnote in the wiki).
---

# Publish (V3.2 — Build HTML + Git Push to gh-pages)

## What It Does

Runs `scripts/build_html.py --sync-images` (which rebuilds `outputs/index.html` + `outputs/prompts/*.html` and copies cover images into `outputs/generated_images/`), then `git add` the output paths and `git commit` + `git push origin gh-pages` so the GitHub Pages site at `https://github.com/evanpanlabs-design/sparkiSeoPromptLibraryWebPage` (branch `gh-pages`) goes live.

This is a **terminal** pipeline step — nothing in the V3.2 chain runs after `publish`. The skill is **destructive** in the sense that it mutates git state: a successful run will create a new commit on `gh-pages` and a failed `git push` can leave the working tree dirty.

This skill does **not** call any LLM, does **not** write to the SQLite `prompts` table, and does **not** score or generate anything. The DB is read-only at this stage — only `prompts WHERE image_status = 'done' AND image_gcs_url IS NOT NULL` is selected (see `scripts/build_html.py:54-95`).

## When To Use

- Run **after** `build_html` (or after the full Pipeline auto-chain has finished) and only when you actually want the static site to update.
- Use when the user says: "发布", "publish", "push to GitHub Pages", "上线", "部署 gh-pages", "更新主页", "deploy the prompt library", or asks the ReAct agent to invoke `tool_publish`.
- Use with `--dry-run` whenever the user wants a preview of what would be committed (HTML rebuild only — no git commit, no push).

## When NOT To Use

- For HTML rebuild **without** git push → use `--dry-run` (still rebuilds `outputs/`) or use the `build_html` skill / call `scripts/build_html.py` directly. `tool_publish` will always attempt git operations unless `--dry-run` is set in the wrapper.
- For scoring / image generation / prompt extraction → those are separate skills.
- For publishing to a non-`gh-pages` branch or to the official `main` repo → **the wrapper does not support it** today (see **Handoff Notes — drift #2**). The wiki claims it pushes to both repos; the code only pushes to `gh-pages`.
- For local previews → open `outputs/index.html` directly in a browser.

## Required Context

- Project root: `16_NewCrawler`
- Tool implementation: `src/agent/skills/core_tools.py:691-750` (`tool_publish`)
- Build script: `scripts/build_html.py` (`build(sync_images, category, min_score, limit)`)
- Git remote: `https://github.com/evanpanlabs-design/sparkiSeoPromptLibraryWebPage.git` (verified via `git remote -v` in this checkout)
- Default branch for push: `gh-pages`
- HTML output: `outputs/index.html` (relative path used for `git add`)
- Generated images: `outputs/generated_images/{db_id}.png` (built from `outputs/images/{cat}/{yyyy-mm}/{tweet_id}.png` by the legacy `sync_images` step inside `build_html.py`)
- DB: `data/veo_prompts.db` — **read-only at this stage** (the `prompts` table must already be populated with rows where `image_status='done'`).
- No LLM dependency, no Vertex AI auth needed.
- No environment variables required by `tool_publish` itself. The `git push` uses the user's existing git credentials (SSH key, `gh auth`, or `GITHUB_TOKEN` in env).

## Preconditions

1. **Database initialized and `prompts` populated**: run `python -m src.main init-db`, then run `crawl_tweets` → `extract_prompts` → `score_prompts` → `generate_images` first. The `build_html.py` script's SELECT is:
   ```sql
   SELECT p.*, t.created_at
   FROM prompts p
   LEFT JOIN tweets t ON p.tweet_id = t.tweet_id
   WHERE p.image_status = 'done' AND p.image_gcs_url IS NOT NULL
   ORDER BY CAST(p.quality_scores AS REAL) DESC
   ```
   If 0 rows match, the build still succeeds but `outputs/index.html` will contain an empty `prompts` array (and `outputs/prompts/` will be empty).
2. **Git repo is set up** at `PROJECT_ROOT/.git` with a working `origin` remote pointing at the personal repo (`sparkiSeoPromptLibraryWebPage`). Verify with `git remote -v`.
3. **`gh-pages` branch exists locally** and is tracking `origin/gh-pages`. If it does not exist yet, the push will fail with `error: src refspec gh-pages does not match any`. See `references/git_workflow.md` for one-time setup.
4. **`generated_images/` submodule** (optional): `tool_publish` does `git add generated_images/` only if `<project_root>/generated_images` exists (a glob check at `core_tools.py:726-728`). In this checkout that path is absent, so the step is a no-op. Most operators use the flat `outputs/generated_images/` instead — and the `git add outputs/...` step at line 725 already covers it via the relative-path `html_path` (see **drift #5** below).
5. **Working tree is clean** (or at least: any unrelated dirty files won't get auto-added). The `git add` call is **scoped** to `outputs/index.html` + `outputs/prompts/` + (optionally) `generated_images/`, so dirty files elsewhere stay dirty. If `gh-pages` branch is checked out, the `git add` + `git commit` run **on `gh-pages`**, not on whatever feature branch is checked out — verify with `git branch --show-current` before running.
6. **Git user / email configured**: `git commit` will fail with `Please tell me who you are` if `user.name` and `user.email` are not set globally or on this repo.

## Inputs

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `repo` | `str` | `PROJECT_ROOT/.git` | Path to the git working tree (this is what `cwd=` is set to for git subprocesses). Almost always leave at the default. |
| `message` | `str` | `"Update prompt library"` | The commit message for the `git commit -m` call. |
| `category` | `str` | `None` | **DRIFT — declared in the docstring but NOT passed to `scripts/build_html.py`**. The build will include all categories regardless. See **drift #1**. |
| `min_score` | `float` | `None` | **DRIFT — declared in the docstring but NOT passed to `scripts/build_html.py`**. Same as above. See **drift #1**. |

The CLI wrapper (`scripts/publish.py`) adds `--project-root` and `--dry-run` (see Validation below).

## Outputs

- **Success string** (printed to stdout):
  ```
  发布完成! {N} 条 Prompt
  HTML: {OUTPUT_PATH}
  Git: OK
  ```
  where `N` is parsed from the `Built HTML: N prompts` line in the `build_html.py` stdout. The match is **fragile** — if `build_html.py` ever changes its output format, this count silently drops to `0` (see `core_tools.py:713-720`).

- **HTML-build-failure string**:
  ```
  HTML build failed: {stderr from build_html.py}
  ```
  Returned without attempting any git operations.

- **Git-failure string**:
  ```
  Git operations failed: {exception class}: {message}
  Build succeeded with {N} prompts.
  ```
  Returned when `git add` / `git commit` raises (note: a `git push` failure does **not** raise — see below).

- **`Git: failed - check repo` line in success output** when `git push` returns non-zero. The tool does not raise on a failed push; it just sets `push_ok = False` and embeds the result in the return string. The local commit is still in place.

- **No DB writes** — `tool_publish` does not touch `data/veo_prompts.db`. The `prompts.image_status = 'published'` state mentioned in the V3.2 wiki (`docs/11_ToolInterface.md` §8 `pool_status`) is **unreachable** from this code path — see **drift #3**.

## Procedure

1. **Load .env** (no-op — the tool itself reads no env vars; only `python-dotenv` is consulted so any downstream call gets clean env).
2. **Resolve `repo` and `commit_msg`** from `args`, falling back to `PROJECT_ROOT/.git` and `"Update prompt library"`.
3. **Build HTML** (always — even in `--dry-run`):
   ```python
   subprocess.run(
       ["python", "scripts/build_html.py", "--sync-images"],
       capture_output=True, text=True, cwd=str(PROJECT_ROOT),
   )
   ```
   If the return code is non-zero, return `HTML build failed: {stderr}` and stop.
4. **Parse the count** out of `Built HTML: N prompts` in the stdout (lines 713-720). On parse failure, `built_count` stays at `0` — no exception is raised.
5. **`git add`** the relative path to `outputs/index.html` (line 723-725). Note: only the index file is added explicitly. The `outputs/prompts/*.html` files are added only if they're under a `generated_images` submodule (line 727-728), which is the wrong glob — see **drift #5**.
6. **`git commit -m "{message}"`** with `capture_output=True` — stderr is swallowed.
7. **`git push origin gh-pages`** with `capture_output=True` — a failure is recorded as `push_ok = False` but does **not** raise.
8. **Return** the success/failure string.

## Validation

```bash
# 1. --help must exit 0
python skills/publish/scripts/publish.py --help

# 2. Bad project root must exit 2 with a clear Chinese error
python skills/publish/scripts/publish.py --project-root /nonexistent

# 3. Dry-run rebuilds HTML but does NOT touch git
python skills/publish/scripts/publish.py --dry-run
# (Check: `git status` should NOT show a new commit; `outputs/index.html` SHOULD be regenerated.)

# 4. Verify git remote + gh-pages branch
git remote -v
git branch -a | head -20

# 5. Real run (use a personal / scratch repo first time)
python skills/publish/scripts/publish.py --message "smoke test publish"
```

The wrapper exits with code:
- `0` on success (real run or dry-run)
- `1` if the tool returned a `错误:` string **or** if `HTML build failed:` or `Git operations failed:` was returned
- `2` if the project root cannot be located (`src/agent/skills/core_tools.py` missing)

## Failure Handling

| Symptom | Likely cause | Action |
|---|---|---|
| `HTML build failed: ... no such table: prompts` | `data/veo_prompts.db` not initialized or empty. | Run `python -m src.main init-db`, then re-run `crawl_tweets` → `extract_prompts` → `score_prompts` → `generate_images`. |
| `HTML build failed: ...Sentinel markers not found in index template` | `outputs/templates/index.html` is missing the `const prompts = [` / `] // PROMPTS_ARRAY_SENTINEL;` markers. | Restore the template; do not edit it without re-validating `build_index()`. |
| `HTML build failed: ... no such column: p.image_gcs_url` | DB schema drift — the V3.2 `prompts` table does not have `image_gcs_url` (it was replaced by `image_local_path` per the V3.3 migration plan). | Either downgrade the SQL or migrate the schema. **Real risk today.** |
| `Git: failed - check repo` in success output | `git push origin gh-pages` failed (auth, no upstream, branch protection). | Run `git push origin gh-pages` manually to see the real error. The local commit is in place. |
| `Git operations failed: ... Please tell me who you are` | Git `user.name` / `user.email` not set. | `git config --global user.email "you@example.com" && git config --global user.name "Your Name"`. |
| `Git operations failed: ... src refspec gh-pages does not match any` | `gh-pages` branch does not exist locally. | See `references/git_workflow.md` §"First-time gh-pages setup". |
| `Git operations failed: ... pathspec 'outputs/index.html' did not match any file(s)` | The build step did not write `outputs/index.html` (empty pool, or build_html crashed silently). | Re-run `python scripts/build_html.py --sync-images` and check stdout. |
| `Git operations failed: ...` after a permission error on `outputs/prompts/` | The `outputs/prompts/` directory exists but is read-only (common on Windows with `chmod 555`). | `chmod -R u+w outputs/prompts/`. |
| `publish` exits 0 with `Built HTML: 0 prompts` | Empty `prompts` table or all rows have `image_status != 'done'`. | Run `generate_images` first. |
| `git push` succeeds but the live site is not updated | GitHub Pages is configured to deploy from a different branch / folder. | Check the repo's Settings → Pages. The `gh-pages` branch root is the standard. |

## Handoff Notes

These are the **five verified drift points** between the V3.2 wiki (`docs/11_ToolInterface.md` §7), the current code, and the live database. **Prioritize the code as the source of truth.**

1. **`category` and `min_score` are accepted but ignored.** The `tool_publish` docstring (line 694-695) lists `category: only this category` and `min_score: minimum quality score filter` as args, and the wiki (`docs/11_ToolInterface.md` §7) also lists them. But the subprocess call at `core_tools.py:704-705` only passes `--sync-images`:
   ```python
   ["python", "scripts/build_html.py", "--sync-images"]
   ```
   The `--category` / `--min-score` flags supported by `build_html.py` (line 552-554) are never invoked. **Result**: any `category` / `min_score` you pass to `tool_publish` is silently dropped, and the build always includes every row with `image_status='done'`. The wrapper does not expose these flags either, so the only way to filter today is to call `scripts/build_html.py` directly.

2. **The wiki says it pushes to two repos; the code only pushes to one.** `docs/11_ToolInterface.md` §7 says the workflow is:
   > 4. `git push origin gh-pages`（个人仓库）
   > 5. `git push origin main`（官方仓库）
   The code at `core_tools.py:736-741` only does step 4. There is no step 5, no second `subprocess.run` for the official repo. In this checkout, `git remote -v` shows only the personal repo (`sparkiSeoPromptLibraryWebPage.git`) — the official repo is not configured as a remote. **If the user wants dual-repo publish, the second `git push` needs to be added and a second remote configured.** No code path exists today for `main`-branch push.

3. **No "published" state is ever written to `prompts`.** The wiki's `pool_status` tool (`docs/11_ToolInterface.md` §8) describes a `published` bucket in the prompt lifecycle, and `docs/11_ToolInterface.md` "Pipeline 阶段链" ends with "publish → git push → 个人仓 gh-pages + 官方仓 main" — but `tool_publish` never UPDATEs the DB. The `prompts.image_status` column stays at `'done'` (or `'failed'`) forever. The `image_status='published'` state in the wiki is **documentation only** — no tool today transitions a row into it. If you need a "published at" column, the fix is one extra `UPDATE prompts SET image_status = 'published' WHERE id IN (...)` after a successful `git push`.

4. **The build-count parse is fragile.** `core_tools.py:715-720` does:
   ```python
   if "Built HTML:" in line:
       try:
           built_count = int(line.split(":")[1].strip().split()[0])
       except Exception:
           pass
   ```
   `build_html.py:564` prints `Done: index={...}, details={...}` and the per-step prints are `index.html written (N prompts)` and `N detail pages written to ...`. **There is no line in the current `build_html.py` that contains the literal `"Built HTML: N prompts"`** — that string format was retired. The current `build_html.py` does not print it. So `built_count` will silently drop to `0` in the success string, even when the build actually succeeded. The `Done: ...` line is the new format. **Fix**: either re-introduce a `Built HTML: N prompts` print in `build_html.py` or update the parser to match `Done:`.

5. **The `generated_images/` git-add glob is wrong.** `core_tools.py:726-728` does:
   ```python
   submodules = list(PROJECT_ROOT.glob("generated_images"))
   if submodules:
       subprocess.run(["git", "add", "generated_images/"], cwd=repo, check=True)
   ```
   This adds `<project_root>/generated_images/` if it exists at the project root. **But the actual flat image directory is `outputs/generated_images/`**, not `<project_root>/generated_images/`. The relative-path `html_path` at line 723 (`OUTPUT_PATH.relative_to(PROJECT_ROOT)`) is `outputs/index.html` only — `outputs/prompts/*.html` and `outputs/generated_images/*.png` are never added by `tool_publish`. They are added only by accident: if you happened to have `<project_root>/generated_images` checked out (e.g. as a git submodule of the personal repo), the second `git add` fires — but for the wrong directory. **Net effect**: the commit will include `outputs/index.html` only. The detail pages and cover images must already be in `gh-pages` from a prior commit, or the live site will 404 on every detail page. **Fix**: extend the `git add` to `git add outputs/`.

### Other things the next operator should know

- **Live state at the time of writing** (per `git remote -v` + `git branch -a`):
  - `origin` = `https://github.com/evanpanlabs-design/sparkiSeoPromptLibraryWebPage.git` (the **personal** repo — matches the wiki, but the **official** repo is not a remote here).
  - Local branches: `master` (current). Remotes: `origin/gh-pages`, `origin/main`, `origin/feat/veo3-prompt-library`. The local repo is on `master`, **not** on `gh-pages` — so the `git add` + `git commit` + `git push` runs in the `master` working tree. The push to `gh-pages` will be rejected by git as a non-fast-forward if `gh-pages` and `master` have diverged.
  - **Most operators need to `git checkout gh-pages` before running publish**, or set up `master` to track `gh-pages`. The tool does not check this — see "Safety" below.
- **Safety**: the tool uses `subprocess.run` with no `check=True` on the `git commit` or `git push` calls. A failed commit is swallowed (`capture_output=True`); a failed push is recorded as `push_ok = False` but the tool still returns "Git: OK" if commit succeeded. There is **no dry-run guard inside `tool_publish`** — the wrapper (`scripts/publish.py`) must enforce it.
- **No retries**: if `git push` fails because of a transient network error, the tool does not retry. The local commit is in place; just run `git push origin gh-pages` manually.
- **V3.3 migration target** (per `docs/11_ToolInterface.md` §"V3.3 目标版"): the `prompts.image_gcs_url` column is being replaced with `image_local_path` (or `has_cover_image` flag). The `build_html.py` SELECT at line 56-59 still references `image_gcs_url` — when the migration lands, the publish step will fail with "no such column" until `build_html.py` is updated. Add a CI check for the column's existence.
- **The legacy `sync_images` step inside `build_html.py`** (line 104-134) copies from `outputs/images/{cat}/{yyyy-mm}/{tweet_id}.png` to `outputs/generated_images/{db_id}.png`. This is the **GCS-coupled legacy path** — in the V3.2 era, `generate_images` would have downloaded from GCS into `outputs/images/...` first, and `build_html.py --sync-images` flattens it. With the GCS-coupling being retired (V3.2 footnote), `generate_images` writes **directly** to `outputs/generated_images/{db_id}.png`, so `sync_images` is mostly a no-op (`skipped=N` for every existing row). It is still called because removing it would break the old test fixtures.
- **Empty-pool publish is allowed**: if `prompts WHERE image_status='done' AND image_gcs_url IS NOT NULL` returns 0 rows, `build()` returns `{"index": 0, "details": 0}` and prints `Done: index=0, details=0` — the success string will say `发布完成! 0 条 Prompt`, and the `git commit` will record an empty `outputs/index.html`. The live site will show an empty list. The wrapper does not warn about this.
- **Force-push is not used**: `git push origin gh-pages` will be rejected by the remote if the local branch has diverged. There is no `--force` in the tool. If you need to overwrite the remote, do it manually with `git push --force-with-lease origin gh-pages`.
- **`html_path` is computed but only `outputs/index.html` is added** (line 723, 725). The intent was clearly to add the whole `outputs/` directory; the code as written adds exactly one file. This is a typo-class bug, not a design choice.
- **`prompts` table state assumption**: the tool assumes `image_gcs_url IS NOT NULL`. The V3.3 schema removes this column. See drift / V3.3 note above.
