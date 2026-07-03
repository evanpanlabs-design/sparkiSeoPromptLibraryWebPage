---
name: pool-status
description: Query the Veo Prompt Library SQLite database for prompt pool status counts grouped by `prompts.image_status` (5 states: pending / generating / done / failed / published) plus a total. Use this skill before any pipeline run to decide which phase to invoke next, after a long `generate_images` or `retry_failed` batch to verify how many prompts are still pending, when investigating "is anything stuck" (pending / generating not draining, failed growing), and as a quick health check that the DB is reachable and the `prompts` table is populated. Takes no arguments. Read-only, no side effects, no LLM calls, no network.
---

# Pool Status (V3.2 — Read-Only DB Health Check)

## What It Does

Runs a single `SELECT image_status, COUNT(*) FROM prompts GROUP BY image_status` against `data/veo_prompts.db` and prints a 5-row table with the count for each of the five `image_status` states defined by the `prompts` CHECK constraint, plus a `总计` (total) row.

This skill:

- **Reads** the `prompts` table (no other tables).
- **Writes** nothing.
- **Calls no LLM, no Apify, no GCS, no Git.**
- Has **no arguments** — the tool signature is `tool_pool_status(args: dict)` but `args` is ignored.

Use it as a sanity check between every other phase, especially after `generate_images` and `retry_failed` which mutate `image_status` in place.

## When To Use

- **Before any pipeline run** — see how many prompts are in each bucket and decide whether to run `extract_prompts`, `score_prompts`, `generate_images`, or `build_html` next.
- **After `generate_images` / `retry_failed`** — verify the batch drained the `pending` pool and grew the `done` count.
- **After `publish`** — confirm the `done` count didn't drop unexpectedly (publish does not currently mutate `image_status` — see Handoff Notes).
- **When something looks stuck** — if `pending` or `generating` is unexpectedly high, or `failed` keeps growing across retries, this is the fastest signal.
- **Quick DB health check** — confirms the SQLite file is openable and the `prompts` table is populated.

## When NOT To Use

- For semantic search of prompts — use `search_prompts`.
- For per-row details (title, prompt_text, author, score) — query the `prompts` table directly with `sqlite3`.
- For inspecting the `tweets` table or the `images` table — `pool_status` only reads `prompts.image_status`.
- For pipeline control — `pool_status` is read-only and cannot start, stop, or retry anything.

## Required Context

- Project root: `16_NewCrawler`
- Tool implementation: `src/agent/skills/core_tools.py:436-462` (`tool_pool_status`)
- Schema (column + CHECK constraint): `src/memory/schema.py:248-256` (`_migrate_v3_prompts_cols`)
- DB singleton: `src/memory.schema._conn()` (resolves to `data/veo_prompts.db`)
- V3.2 contract: `docs/11_ToolInterface.md` §8 (`pool_status`)

## Preconditions

1. **Database initialized** — run `python -m src.main init-db` at least once. The `prompts` table must exist (created by `init_db()` in `src/memory/schema.py`).
2. **Database file exists** at `<project-root>/data/veo_prompts.db`. The wrapper resolves the project root from `--project-root` or the parent of the `pool-status/` skill directory.
3. **No env vars required.** `pool_status` does not call Vertex AI, Apify, or GCS.

## Inputs

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| _(none)_ | — | — | `tool_pool_status` ignores `args`. |

The CLI wrapper (`scripts/pool_status.py`) accepts `--project-root` (override auto-detected project root) and `--json` (emit JSON instead of the text table).

## Outputs

The tool returns a Chinese status string formatted as:

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

- Header is `Prompt Pool 状态:` (always, even on empty DB).
- Each state is left-padded label (`{label:12s}`), 4-wide count (`{cnt:4d}`).
- The 5 rows are emitted in the **fixed order** `pending, generating, done, failed, published`, even if a count is zero.
- `总计` sums every distinct `image_status` value present in the `prompts` table (including any drift values, not just the 5 declared labels).
- If `image_status` is `NULL` for a row, it is bucketed under `pending` (see line 448: `row["image_status"] or "pending"`).
- On exception, the tool returns `错误: {ExceptionType}: {message}` and the wrapper exits with code `1`.

## Data Contract

### Read

```sql
SELECT image_status, COUNT(*) AS cnt
FROM prompts
GROUP BY image_status;
```

- One row per distinct non-NULL `image_status`. Rows with `image_status IS NULL` are still included once, bucketed as `pending` in the Python dict.
- The `idx_prompts_category` index does **not** speed this up — it indexes `category`, not `image_status`. For a production `prompts` table of <100k rows the GROUP BY is trivially fast; consider an `idx_prompts_image_status` if the table grows past 1M.

### Write

- **None.** The skill is read-only.

### Column constraint (source of truth)

```sql
ALTER TABLE prompts ADD COLUMN image_status TEXT DEFAULT 'pending'
CHECK (image_status IN ('pending','generating','done','failed','published'))
```

Added by `_migrate_v3_prompts_cols` at `src/memory/schema.py:251-254`. The CHECK constraint is enforced by SQLite; any other value would have been rejected at INSERT/UPDATE time.

## Procedure

1. **Resolve project root** from `--project-root` or the parent of the `pool-status/` skill package.
2. **Validate project root**: confirm `src/agent/skills/core_tools.py` exists at `<root>/src/agent/skills/core_tools.py`. If not, print `错误: 无法定位项目根目录…` to stderr and exit `2`.
3. **Insert `<root>` into `sys.path`** so `src.*` imports resolve. Optionally call `dotenv.load_dotenv(<root>/'.env')` (no env vars are required by this skill; the dotenv call is defensive — same pattern as the other wrappers).
4. **Import and call** `from src.agent.skills.core_tools import tool_pool_status` and invoke `tool_pool_status({})` (the tool ignores its argument).
5. **Print** the returned string verbatim. Exit `0` on a successful `Prompt Pool 状态:` string, `1` if it starts with `错误:`.

## Validation

```bash
# 1. --help
python skills/pool-status/scripts/pool_status.py --help
# expect: usage text, exit 0

# 2. Bad project root
python skills/pool-status/scripts/pool_status.py --project-root /nonexistent
# expect: "错误: 无法定位项目根目录 ..." on stderr, exit 2

# 3. Real call
python skills/pool-status/scripts/pool_status.py
# expect: "Prompt Pool 状态:" header + 5 numeric rows + separator + 总计, exit 0

# 4. JSON mode
python skills/pool-status/scripts/pool_status.py --json
# expect: {"pending": N, "generating": N, "done": N, "failed": N, "published": N, "total": N}, exit 0

# 5. Cross-check with raw SQL
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); \
  [print(s, ':', c.execute(f\"SELECT COUNT(*) FROM prompts WHERE image_status='{s}'\").fetchone()[0]) \
   for s in ['pending','generating','done','failed','published']]"
# expect: 5 numeric counts; must match the wrapper output (modulo NULL → pending fallback)
```

The wrapper exit codes:

- `0` — success (text or JSON mode)
- `1` — tool returned a `错误:` string
- `2` — project root cannot be located (no `core_tools.py` at expected path)

## Failure Handling

| Symptom | Likely cause | Action |
|---|---|---|
| `错误: ... FileNotFoundError ... data/veo_prompts.db` | DB not initialized or wrong project root. | Run `python -m src.main init-db` from project root, or pass `--project-root` explicitly. |
| `错误: ... sqlite3.OperationalError ... no such table: prompts` | `init-db` never ran, or `--project-root` points at the wrong project. | Same as above. |
| `错误: ... PermissionError ... data/veo_prompts.db` | DB file locked by another process. | Close any other script/REPL that holds the connection (`_conn()` uses `check_same_thread=False` and a module-level singleton — restart the Python process). |
| All five rows show `0` | Empty `prompts` table. | Run `crawl_tweets` and `extract_prompts` first. |
| `总计` is 0 but the DB has rows | Rows have a `image_status` value outside the 5 declared labels AND a NULL value. | Inspect with `SELECT DISTINCT image_status FROM prompts;` — the most likely culprit is a row that was INSERTed before the V3 migration ran (would have no `image_status` column at all, returning NULL). |
| `--json` flag is rejected | Old wrapper version. | Re-run `git pull` on the skill package. |

## Handoff Notes

These are the **verified** drift points between the project wiki, the current code, and the live database. **Prioritize the code as the source of truth.**

1. **`published` count is always 0 in production — `image_status = 'published'` is unreachable.**
   - The CHECK constraint at `src/memory/schema.py:253` allows the value, and the label list at `core_tools.py:450` includes it.
   - But **no tool ever writes `published`**. `generate_images` sets `done` or `failed` (`core_tools.py:577, 586, 652, 658, 664`). `retry_failed` resets `failed → pending` then sets `done` or `failed` again. `publish` (`tool_publish`, called from `core_tools.py` near the HTML build flow) does **not** touch `image_status` — see `docs/11_ToolInterface.md` §7.
   - **Implication for the next operator**: the `published` row in the output is dead weight. If you want a "this prompt is live on the public site" signal, add a `UPDATE prompts SET image_status='published' WHERE id IN (...)` inside `tool_publish` **after** the `git push` succeeds. Until that is wired up, treat the `published` row as a UI placeholder and ignore its count.

2. **`generating` count is also usually 0 — there is no in-flight marker.**
   - The 5-state list implies a `pending → generating → done` flow, but `tool_generate_images` writes only the terminal `done` or `failed` values (`core_tools.py:577, 586`). It never writes `generating`. The label is reserved for a future in-flight marker (e.g. a V3.3 worker that takes row-level locks). Today the row goes straight from `pending` to `done`/`failed` per item.
   - The same dead-label situation is acknowledged in `src/agent/memory/long_term.py:38-42`, which queries the same 5 states for the long-term-memory summary view. Both views show `generating = 0` for any healthy run.

3. **NULL `image_status` is silently bucketed as `pending`.**
   - At `core_tools.py:448`: `status_counts[row["image_status"] or "pending"] = row["cnt"]`. If a row has `image_status IS NULL` (e.g. it was inserted by a V1 pre-migration code path that pre-dated the V3 column add), the raw SQL `GROUP BY image_status` returns no row for it, so the Python loop's `or "pending"` fallback never runs in practice — NULL values simply do not appear in `rows` at all.
   - **But** if a future INSERT bypasses the `image_status` default (e.g. `INSERT ... image_status = NULL`), it will be invisible to this query. The safe invariant: rely on the column `DEFAULT 'pending'` (set at `schema.py:252`) rather than relying on the Python fallback to catch NULLs.

### Other things the next operator should know

- **V3.3 migration target** (per `docs/11_ToolInterface.md` §"V3.3 目标版"): the `image_status` column is renamed to `has_cover_image` (0/1) and the 5-state enum is replaced by a join to a new `image_attempts` table. The `pool_status` skill will need to be rewritten to `SELECT has_cover_image, COUNT(*) FROM prompts GROUP BY has_cover_image` and to query `image_attempts` for in-flight and failed states. Keep the drift points above in mind when porting.
- **No `idx_prompts_image_status`**: the only index that touches a related column is `idx_prompts_category` (`schema.py:125`) and `idx_prompts_quality` (line 126). For the current 100-row `prompts` table this is fine; for a future 1M-row table, add `CREATE INDEX idx_prompts_image_status ON prompts(image_status)` in `_migrate_v3_prompts_cols` (after the `ALTER TABLE`).
- **The `总计` row sums over what `GROUP BY` returned, not the 5 declared labels.** If a drift value sneaks in (e.g. a row written with `image_status='archived'`), it will inflate the total without showing in any of the 5 visible rows. Cross-check with `SELECT COUNT(*) FROM prompts` if the numbers look wrong.
- **Live DB state at the time of writing** (subject to drift): the `prompts` table is small (≈148 rows from prior runs). Most rows are `image_status='pending'`. `done` and `failed` are populated by the few historical image-generation runs.
- **The skill is callable from the ReAct agent** as `tool_pool_status` (no args), so the LLM can decide to invoke it as a free tool in Agent mode. It is also a step in the Pipeline mode chain (status_query intent maps to this tool inside `think_node`).
- **Concurrency**: the tool holds no locks. Safe to call from a parallel worker as long as no other process is mid-INSERT into `prompts` (which would briefly shift counts).
- **No test in the V3 suite** currently asserts the 5-row format. The Validation block above is the closest thing to a regression test — if you change the label list or the format string, re-run all four steps.
