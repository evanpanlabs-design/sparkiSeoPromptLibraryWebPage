# Publish Handoff Checklist

Copy-pasteable runbook for the next operator. Tick each box before the
first production publish.

## 1. Install

Nothing to `pip install` — `tool_publish` uses only `subprocess` (stdlib)
and the project's existing `python` interpreter. The HTML rebuild
delegates to `scripts/build_html.py`, which in turn uses `sqlite3`
(stdlib) and the `outputs/templates/index.html` file.

Required:
- `git` on `$PATH`
- A Python 3.11+ interpreter (matches the project standard)
- Write access to `outputs/index.html`, `outputs/prompts/`, and the git
  working tree

## 2. Configure (one-time per machine / per repo)

```bash
# A. Git author identity (required for `git commit`)
git config --global user.name "Your Name"
git config --global user.email "you@example.com"

# B. Verify the personal repo remote
cd <project_root>
git remote -v
# Expected:
#   origin  https://github.com/evanpanlabs-design/sparkiSeoPromptLibraryWebPage.git (fetch)
#   origin  https://github.com/evanpanlabs-design/sparkiSeoPromptLibraryWebPage.git (push)

# C. Verify gh-pages branch exists
git branch -a | grep gh-pages
# Expected: remotes/origin/gh-pages  (local copy is optional — see D)

# D. (If needed) Bootstrap local gh-pages
git fetch origin
git checkout -b gh-pages origin/gh-pages
```

If you also need the **official** repo (`sparki-ai/veo-prompt-station`)
per the wiki, add a second remote — but note the wrapper does **not**
push to it today (see `git_workflow.md`):

```bash
git remote add official git@github.com:sparki-ai/veo-prompt-station.git
```

## 3. Smoke test (dry-run)

The wrapper's `--dry-run` rebuilds HTML but skips git ops. Run it on
any branch and any working-tree state — it does not commit or push.

```bash
# From project root
python skills/publish/scripts/publish.py --dry-run
echo "exit=$?"

# Expected:
#   [dry-run] Rebuilding HTML only; skipping git commit + git push.
#   Syncing images...
#     0 copied, N skipped, 0 errors
#     index.html written (M prompts)
#     N detail pages written to <project>/outputs/prompts
#   Done: index=1, details=N
#   [dry-run] git commit/push skipped. Use without --dry-run to publish.
#   exit=0
```

Then confirm `git status` is **clean** (or at least: no new commit
on `gh-pages` was created):

```bash
git status
git log -1 --oneline
```

## 4. Real run (production)

```bash
# A. Make sure you are on the branch you want to publish
git checkout gh-pages        # standard setup
git merge --no-ff master     # sync from master (or cherry-pick)

# B. Dry-run one more time
python skills/publish/scripts/publish.py --dry-run

# C. Real publish
python skills/publish/scripts/publish.py --message "Publish YYYY-MM-DD"
echo "exit=$?"

# Expected exit=0 with output:
#   发布完成! N 条 Prompt
#   HTML: <project>/outputs/index.html
#   Git: OK

# D. Confirm the live site updated
gh api repos/evanpanlabs-design/sparkiSeoPromptLibraryWebPage/pages
# (or: open https://github.com/evanpanlabs-design/sparkiSeoPromptLibraryWebPage
#  → Settings → Pages → "View deployment")
```

## 5. V3.3 migration TODOs

Before the V3.3 schema migration lands, the following items in this
skill will need to be re-validated:

- [ ] `scripts/build_html.py:56-59` — replace
  `p.image_status = 'done' AND p.image_gcs_url IS NOT NULL` with
  `p.has_cover_image = 1` (per `docs/11_ToolInterface.md` §"V3.3 三 Flag
  状态机").
- [ ] `core_tools.py:715-720` — fix the fragile `"Built HTML:"` parser
  to match the current `Done: index=..., details=...` output of
  `build_html.py:564`.
- [ ] `core_tools.py:704-705` — pass `--category` and `--min-score`
  to `build_html.py` so the filter args stop being silently dropped.
- [ ] `core_tools.py:723-728` — change `git add outputs/index.html`
  to `git add outputs/` so `outputs/prompts/*.html` and
  `outputs/generated_images/*.png` are actually committed.
- [ ] `core_tools.py:736-741` — add a second `git push` for the
  official repo (if the dual-repo workflow is still desired).
- [ ] `core_tools.py:746-750` — add an optional
  `UPDATE prompts SET image_status = 'published'` (or
  `has_cover_image_published = 1`) so the `published` state in the
  wiki becomes a real reachable state.
- [ ] The wrapper's `--dry-run` guard at `scripts/publish.py:_build_html_only`
  is a workaround for the missing guard in `tool_publish`. If the
  upstream tool grows its own `--dry-run` flag, the wrapper can
  delegate to it instead of duplicating the subprocess call.

## 6. Anomalies worth flagging in code review

- `core_tools.py:704-705` — filter args declared in docstring, never
  passed to the subprocess.
- `core_tools.py:715-720` — parser looks for `"Built HTML:"` literal
  that `build_html.py` no longer prints.
- `core_tools.py:723-725` — `git add outputs/index.html` only; the
  rest of `outputs/` is missed.
- `core_tools.py:726-728` — glob is `<project_root>/generated_images`,
  wrong path; the real one is `outputs/generated_images/`.
- `core_tools.py:730-735` — `git commit` uses `capture_output=True`,
  swallows stderr; failures are silent.
- `core_tools.py:736-741` — `git push` failures recorded as a string
  flag, not raised. The operator must read the success string to
  notice.
- `scripts/build_html.py:104-134` — `sync_images_to_flat_dir()` is
  legacy GCS-coupled; with the V3.2 direct-write path, it is mostly
  a no-op for existing rows.
- The wrapper's `--dry-run` short-circuits before calling
  `tool_publish`. This is correct, but the original tool has **no
  built-in dry-run guard** — fix at the source rather than relying
  on the wrapper.
