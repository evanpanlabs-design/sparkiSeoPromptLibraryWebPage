# Git Workflow for publish

`tool_publish` runs three git commands in sequence inside the project root
(`PROJECT_ROOT/.git` by default). This document records the assumed
working-tree state, the one-time setup for a fresh checkout, and the
submodule / branch drift that the next operator should know about.

## Assumed state at run time

1. A git working tree exists at `PROJECT_ROOT`.
2. `git remote -v` shows an `origin` pointing at the personal GitHub
   Pages repo (in this checkout:
   `https://github.com/evanpanlabs-design/sparkiSeoPromptLibraryWebPage.git`).
3. The branch the operator wants to publish from is checked out
   (`gh-pages` in the standard setup).
4. `git config user.name` and `git config user.email` are set on this
   repo or globally.

## Commands run by `tool_publish` (in order)

```bash
# 1. Rebuild HTML (subprocess.run, NOT a git call but runs in cwd=PROJECT_ROOT)
python scripts/build_html.py --sync-images

# 2. Stage outputs/index.html
git add outputs/index.html

# 3. (Conditional) Stage generated_images/ IF <project_root>/generated_images exists
git add generated_images/

# 4. Commit (capture_output=True — failures swallowed)
git commit -m "Update prompt library"

# 5. Push to gh-pages (capture_output=True — failures recorded but not raised)
git push origin gh-pages
```

Note the **conditional `git add generated_images/`** at step 3 is a
**bug** — the actual flat image directory is `outputs/generated_images/`,
not `<project_root>/generated_images/`. See `SKILL.md` §"Handoff Notes"
drift #5. Today this means `outputs/prompts/*.html` and
`outputs/generated_images/*.png` are **not** added by `tool_publish` —
they must already be on `gh-pages` from a prior commit.

## First-time gh-pages setup

If `git branch -a` does **not** show `remotes/origin/gh-pages` or the
local branch is missing, you need to bootstrap it once:

```bash
# From project root, on a clean master:
git fetch origin
git checkout -b gh-pages origin/gh-pages   # or: git switch -c gh-pages origin/gh-pages
git merge --no-ff master -m "Initial sync of gh-pages from master"
git push origin gh-pages
```

Then for every publish:

```bash
git checkout gh-pages
git merge --no-ff master -m "Sync from master before publish"
python skills/publish/scripts/publish.py --message "Update prompt library"
```

(Or, in the long run, set up GitHub Actions to deploy `gh-pages` from
`master` automatically — the V3.3 plan.)

## Personal repo vs official repo drift

The V3.2 wiki (`docs/11_ToolInterface.md` §7) claims the workflow is:

> 4. `git push origin gh-pages`（个人仓库）
> 5. `git push origin main`（官方仓库）

The code at `src/agent/skills/core_tools.py:736-741` only does step 4.
There is **no second `git push`**, and `git remote -v` in this checkout
shows only the personal repo. If the operator needs to publish to the
official repo too, the fix is:

```python
# After the existing push_r block, add:
official_push = subprocess.run(
    ["git", "push", "official", "main"],
    cwd=repo, capture_output=True, text=True,
)
```

…and configure the official remote:

```bash
git remote add official git@github.com:sparki-ai/veo-prompt-station.git
```

No such remote or code path exists today.

## `generated_images/` submodule note

`core_tools.py:726-728` does:

```python
submodules = list(PROJECT_ROOT.glob("generated_images"))
if submodules:
    subprocess.run(["git", "add", "generated_images/"], cwd=repo, check=True)
```

The `PROJECT_ROOT.glob("generated_images")` check matches any directory
or symlink at the project root with that name. The intent was clearly
to support a git submodule at `<project_root>/generated_images/` that
contains the cover images. In this checkout, the path is absent, so the
step is a no-op — and the actual flat image directory
`outputs/generated_images/` is **not** added.

If you set up the submodule as intended, the `git add generated_images/`
will work — but the rest of the pipeline (`generate_images` writing to
`outputs/generated_images/`, `build_html.py` reading from it) still
operates on the *outputs/* path. Pick one of:

- **Option A — current behaviour (no submodule)**: add a V3.3 fix that
  changes the `git add` to `git add outputs/`. Most operators want this.
- **Option B — submodule at root**: move the image pipeline to write
  directly to `<project_root>/generated_images/{db_id}.png`, then add it
  as a submodule. The current glob will pick it up.

## Working-tree safety

- `tool_publish` uses `subprocess.run` with no `check=True` on the
  `git commit` or `git push` calls. A failed commit is silently
  swallowed (`capture_output=True`); a failed push is recorded as
  `push_ok = False` but the tool still returns success.
- **There is no `--force` in the push** — if `gh-pages` has diverged,
  the push will be rejected.
- **There is no rollback** if the commit succeeds but the push fails —
  the local `gh-pages` branch will be ahead of `origin/gh-pages` by 1
  commit. Run `git push origin gh-pages` manually to recover.
- **Working tree can be dirty elsewhere** — only `outputs/index.html`,
  `outputs/prompts/*.html` (drift #5), and the optional `generated_images/`
  are touched. Files outside `outputs/` stay dirty. The tool does not
  run `git stash` first.

## Quick health check (run before publishing)

```bash
git status                                # working tree state
git branch --show-current                 # are you on gh-pages?
git remote -v                             # is origin set up?
git config --get user.name                # commit author
git config --get user.email               # commit email
git log origin/gh-pages..HEAD --oneline   # would your push be fast-forward?
```
