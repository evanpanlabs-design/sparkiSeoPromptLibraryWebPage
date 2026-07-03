# Handoff Checklist — `pool-status`

A copy-pasteable runbook for the next operator picking up this skill.

## 30-Second Health Check

```bash
cd <project-root>
python pool-status/scripts/pool_status.py
```

Expected output (example):

```
Prompt Pool 状态:
  pending    :   12
  generating :    0
  done       :  148
  failed     :    3
  published  :    0
  ──────────────────
  总计        :  163
```

If you see this, the skill is working. If you see `错误: ...`, jump to **Failure Modes** below.

## When To Run

| Trigger | Reason | What you learn |
|---|---|---|
| Before `crawl_tweets` | Baseline counts. | Existing backlog. |
| Before `extract_prompts` | Are there rows waiting? | `pending` covers all phases, so this is a coarse signal. |
| Before `score_prompts` | Are there unscored prompts? | Better: query `quality_scores IS NULL` directly. |
| Before `generate_images` | How big is the image backlog? | `pending` count (with the caveat below about `pending` over-counting). |
| After `generate_images` | Did the batch land? | `pending` should drop, `done` or `failed` should grow. |
| After `retry_failed` | Did the retry move anything? | `failed` should drop, `done` should grow. |
| After `publish` | _(misleading — see below.)_ | `published` is always 0 today, do not use it to verify a publish. |
| "Is anything stuck?" | Long-running pipeline triage. | If `pending` is not draining across runs, suspect a quota / auth issue. |
| First thing in a debugging session | Cheap sanity check. | If `总计` looks wrong, the DB is probably in a drift state. |

## What The 5 States Mean

| Label | Means today | Means in V3.3 |
|---|---|---|
| `pending` | Prompt row exists, no successful cover image yet. | Replaced by `has_cover_image = 0`. |
| `generating` | _(no writer today — see drift.)_ | A row in `image_attempts` with `status='running'`. |
| `done` | Cover image generated and stored. | `has_cover_image = 1`. |
| `failed` | All generation attempts exhausted without success. | A row in `image_attempts` with `status='failed'` (or no such row + `has_cover_image = 0`). |
| `published` | _(no writer today — see drift.)_ | Probably removed; publication is a separate concern tracked in a publish log. |

## Caveats (Read These Before Trusting The Output)

1. **`pending` is a catch-all bucket.** It includes:
   - Prompts that just came out of `extract_prompts` and have never been processed by `generate_images`.
   - Prompts that `retry_failed` reset from `failed` back to `pending`.
   - **(V1 pre-migration rows)** Prompts that were inserted before the V3 migration ran and have `image_status = NULL` — the `DEFAULT 'pending'` only applies to subsequent `INSERT`s, not to `ALTER TABLE`-added columns on existing rows.
   So `pending` is a **superset** of "ready for the next image batch." Cross-check with `WHERE image_status='pending' AND quality_scores IS NOT NULL` if you want a precise "ready for `generate_images`" count.

2. **`generating` is always 0 in production.** There is no in-flight marker in the codebase. If you see a non-zero `generating` count, it is either a stale row from a future release or a row someone hand-edited. Today: trust zero.

3. **`published` is always 0 in production.** No tool writes it. `tool_publish` does not touch `image_status`. If you see a non-zero `published` count, it is either a stale row or hand-edited. **Do not use `pool_status` to verify a publish landed.** Use `git log -1 outputs/` or check the GitHub Pages URL directly.

4. **The `总计` row sums over what `GROUP BY` returned.** If a row has a drift value (e.g. `image_status='archived'`), it inflates `总计` without showing in any of the 5 visible rows. If the numbers look wrong, run:
   ```sql
   SELECT image_status, COUNT(*) FROM prompts GROUP BY image_status;
   ```
   to see the raw buckets.

5. **No `idx_prompts_image_status`.** For the current small `prompts` table this is irrelevant. For a future 1M-row table, add the index in `_migrate_v3_prompts_cols` after the `ALTER TABLE`.

## Failure Modes

| Output | Cause | Action |
|---|---|---|
| `错误: ... FileNotFoundError ... data/veo_prompts.db` | DB not initialized, or wrong project root. | `python -m src.main init-db`. Or pass `--project-root` explicitly. |
| `错误: ... no such table: prompts` | `init-db` never ran. | Same. |
| `错误: ... PermissionError ...` | DB file locked by another process. | Close the other script. The `_conn()` singleton holds the connection for the lifetime of the Python process. |
| All five rows show `0` | `prompts` is empty (or the DB has the wrong project). | Run `crawl_tweets` + `extract_prompts` first. Or `SELECT COUNT(*) FROM prompts;` to disambiguate. |
| `总计` does not match `SELECT COUNT(*) FROM prompts` | Drift value in `image_status`. | `SELECT image_status, COUNT(*) FROM prompts GROUP BY image_status;` to see the drift. |

## Cross-Check Recipe

```bash
# 1. Tool output (the canonical reading)
python pool-status/scripts/pool_status.py

# 2. Raw SQL — same query
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); \
  [print(s, ':', c.execute(f\"SELECT COUNT(*) FROM prompts WHERE image_status='{s}'\").fetchone()[0]) \
   for s in ['pending','generating','done','failed','published']]"

# 3. Drift detector
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); \
  print('NULLs:', c.execute('SELECT COUNT(*) FROM prompts WHERE image_status IS NULL').fetchone()[0]); \
  print('Drift:', c.execute('SELECT image_status, COUNT(*) FROM prompts WHERE image_status NOT IN (\"pending\",\"generating\",\"done\",\"failed\",\"published\") GROUP BY image_status').fetchall())"
```

If step 1 and step 2 disagree, the Python parser is wrong. If step 2's `total` does not match the sum of its 5 rows, NULL or drift rows are present — see step 3.

## V3.3 Migration TODO

When the V3.3 migration lands (`docs/11_ToolInterface.md` §"V3.3 目标版"):

1. Replace the `SELECT image_status, COUNT(*) FROM prompts GROUP BY image_status` query with:
   ```sql
   SELECT has_cover_image, COUNT(*) FROM prompts GROUP BY has_cover_image;
   ```
2. Move in-flight state to a join against the new `image_attempts` table.
3. Drop the `published` label — publication status is a separate concern.
4. Update this skill's `SKILL.md`, the `database_schema.md` reference, and any tests that assert the 5-row format.
