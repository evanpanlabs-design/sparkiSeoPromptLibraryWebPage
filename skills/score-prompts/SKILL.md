---
name: score-prompts
description: Score the quality of already-extracted Veo prompts using a four-dimension LLM rubric (specificity, visual_detail, novelty, generatable), compute a weighted overall score from configs/quality.yaml, and write the result as a CSV string into the prompts.quality_scores column. Use when the agent needs to run or debug the score_prompts phase, when the prompts pool has rows where quality_scores IS NULL, when triaging which prompts are worth generating a cover image for, when the user asks "is this prompt worth generating an image for", or when filtering by a min_score threshold before generate_images.
---

# Score Prompts (V3.2 — Four-Dimension LLM Scoring)

## What It Does

Pulls the next batch of extracted prompts where `prompts.quality_scores IS NULL AND prompts.prompt_text IS NOT NULL` (ordered by `likes_count DESC`), sends each `prompt_text` to Gemini for a **four-dimension** quality score, computes a **weighted overall** score, and writes a CSV string into `prompts.quality_scores`.

The four dimensions (per `src/worker/scorer.py:56-69`):

1. **specificity** — detail level of the visual description (0.0=generic, 1.0=highly specific)
2. **visual_detail** — presence of camera / lighting / composition / style terms (0.0=none, 1.0=rich)
3. **novelty** — uniqueness / rarity of structure or subject (0.0=common, 1.0=unique)
4. **generatable** — can this directly drive Veo/Gemini generation? (0.0=unusable, 1.0=ready)

The **overall** score is a **weighted average** using weights from `configs/quality.yaml` (default: `0.25/0.30/0.20/0.25` — specificity/visual_detail/novelty/generatable). The tool counts prompts whose `overall >= min_score` as "qualified" — these are the candidates the next phase (`generate_images`) will pick up.

The CSV written to the DB has **5 fields** in this fixed order:
```
{ specificity } , { visual_detail } , { novelty } , { generatable } , { overall }
```
Example: `0.72,0.65,0.50,0.80,0.6705`

This skill does **not** extract prompts, generate images, build HTML, or publish — those are separate skills (`extract_prompts`, `generate_images`, `build_html`, `publish`).

## When To Use

- Run **after** `extract_prompts` has filled `prompts.prompt_text` and **before** `generate_images` (image generation filters on `CAST(quality_scores AS REAL) >= ?`).
- Use when the user says: "评分", "打质量分", "跑 score_prompts", "过滤掉低分 prompt", "看看哪些 prompt 值得生成图", "filter by min_score 0.6", or asks the ReAct agent to invoke `tool_score_prompts`.
- Use when the prompts pool has rows where `quality_scores IS NULL` (the implicit input — the skill `SELECT`s them itself).
- Use to re-tune the quality threshold: raise `min_score` to be more selective, lower it to feed the image generator more candidates.

## When NOT To Use

- For raw tweet → prompt text extraction → use `extract_prompts`.
- For cover image generation → use `generate_images`.
- For HTML / sitemap build → use `build_html`.
- For re-classifying tweets that were filtered out by the content filter — that's an extraction-phase concern, not a scoring one. Quality scoring cannot rescue a row that has no `prompt_text`.
- For **changing the scoring weights** — edit `configs/quality.yaml` (and `QualityWeights` defaults in `src/types/config.py`), not the code path. Re-run `score_prompts` after a YAML change because the existing CSV will still encode the old weights.
- For **swapping the LLM** used to score — pass `default_model` to `QualityScorer` (the tool does not expose this). The current `tool_score_prompts` hard-codes `QualityScorer(llm, quality_cfg)` with no `default_model` override, so the scorer falls back to `"gemini-3.5-flash"` (see drift #1 in Handoff Notes).

## Required Context

- Project root: `16_NewCrawler`
- Tool implementation: `src/agent/skills/core_tools.py:269-359` (`tool_score_prompts`)
- Scorer: `src/worker/scorer.py` → `QualityScorer` (line 72) + `SCORING_SYSTEM_PROMPT` (line 56) + `score()` (line 102)
- LLM client: `src/llm/gemini_client.py` → `GeminiClient` (default `gemini-3.5-flash`)
- Type defs: `src/types/prompt.py` → `QualityScores` (4 base fields + computed `overall`), `ExtractedPrompt`
- Config types: `src/types/config.py` → `QualityConfig`, `QualityWeights`, `QualityThresholds`
- YAML: `configs/quality.yaml` — weights and thresholds
- Schema: `src/memory/schema.py` — `prompts.quality_scores TEXT` (line 92) + `idx_prompts_quality` (line 126)
- Exceptions: `src/exceptions.py` — `LLMError`, `LLMParseError`
- V3.2 contract: `docs/11_ToolInterface.md` §3

## Preconditions

1. **Database initialized**: run `python -m src.main init-db` so the `prompts` table exists with the `quality_scores` column.
2. **Vertex AI auth**: the `GeminiClient` constructor calls `genai.Client(vertexai=True, project="sparki-op", location="global")`. Set `GOOGLE_APPLICATION_CREDENTIALS` (or run `gcloud auth application-default login`) before invoking.
3. **Prompts present**: the `prompts` table must have rows with `prompt_text IS NOT NULL` and `quality_scores IS NULL`. The skill's `SELECT` is:
   ```sql
   SELECT ... FROM prompts
   WHERE quality_scores IS NULL AND prompt_text IS NOT NULL
   ORDER BY likes_count DESC
   LIMIT ?;
   ```
4. **Weights & thresholds**: `configs/quality.yaml` must be parseable. If the file is missing, the tool falls back to the dataclass defaults in `src/types/config.py:119-134` — which happen to match the YAML, so behaviour is identical (see drift #2 in Handoff Notes).
5. Python dependencies: `google-genai` is the only hard requirement beyond the project base (`pip install -r requirements.txt`).

## Inputs

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `batch` | `int` | `50` | Max prompts to score in this call. The SELECT is `WHERE quality_scores IS NULL ... LIMIT ?`. |
| `min_score` | `float` | `0.4` | Minimum `overall` score to count as "qualified". Compared against the weighted average. |

The CLI wrapper (`scripts/score_prompts.py`) additionally accepts `--project-root` and `--dry-run` (see Validation below).

## Outputs

- **Success string** (printed to stdout):
  ```
  评分完成: {Q}/{T} qualified（min={min_score}，batch={batch}）
  ```
  where `Q` = prompts with `overall >= min_score` and `T` = `Q + unqualified` (all rows the SQL `SELECT` returned this call).

- **No-work string**:
  ```
  评分完成: 0 qualified（没有待评分的 prompts）
  ```
  Returned when the SELECT returns 0 rows (i.e. no prompts have `quality_scores IS NULL`).

- **Failure string** (returned by the tool, also non-zero exit code from the wrapper):
  ```
  错误: {ExceptionType}: {message}
  ```

- **Side effects** (all under one `conn.commit()` at the end of the batch, see `core_tools.py:351`):
  - `prompts` UPDATE 1 column: `quality_scores` set to CSV string `"{spec},{vis},{nov},{gen},{overall}"`.

## Data Contract

This skill writes **one** column in the `prompts` table. The DB column is `TEXT` — the values are stored as a 5-field CSV, **not** as a JSON blob. This matters because `tool_generate_images` and `build_html` both read it back with `CAST(quality_scores AS REAL)` to extract the `overall` value.

### `prompts.quality_scores` — UPDATE 1 column (in place)

| Field | Source | Notes |
|---|---|---|
| Column type | `TEXT` (nullable) | `schema.py:92` |
| Value format | `"{spec},{vis},{nov},{gen},{overall}"` | 5 comma-separated floats; **no spaces** |
| Index | `idx_prompts_quality ON prompts(quality_scores)` | `schema.py:126` (text index, used for `IS NULL` / `IS NOT NULL` filters, not for ordering) |
| `specificity` | LLM score, clamped to `[0.0, 1.0]` | `scorer.py:119` |
| `visual_detail` | LLM score, clamped to `[0.0, 1.0]` | `scorer.py:120` |
| `novelty` | LLM score, clamped to `[0.0, 1.0]` | `scorer.py:121` |
| `generatable` | LLM score, clamped to `[0.0, 1.0]` | `scorer.py:122` |
| `overall` | Weighted average, rounded to 4 decimals | `scorer.py:124-129, 136` |

The 4 LLM-returned values are **clamped** (`max(0.0, min(1.0, x))`) and the `overall` is **rounded** (`round(overall, 4)`) before write. The tool writes ALL 5 fields as one string — the LLM never sees the `overall`, and the DB never stores the 4 base fields separately.

The WHERE clause is `id = ?` (the row's `INTEGER PRIMARY KEY`), not `tweet_id = ?`. No other columns are touched.

### Reading it back

```sql
-- Just the overall (used by generate_images and build_html)
SELECT id, CAST(quality_scores AS REAL) AS overall
FROM prompts
WHERE quality_scores IS NOT NULL
ORDER BY overall DESC;

-- All 5 fields
SELECT id,
       CAST(substr(quality_scores, 1, instr(quality_scores, ',') - 1) AS REAL) AS specificity,
       ...
FROM prompts
WHERE quality_scores IS NOT NULL;
```

(The tool does **not** expose an "all 5 fields" read — the most common pattern is `CAST(quality_scores AS REAL)`, which reads the leading float, which is `specificity` because the 4 base scores are clamped to `[0,1]`. **This is a latent bug** — see drift #4 in Handoff Notes.)

## Procedure

1. **Open DB connection** via `src.memory.schema._conn()` (singleton, `row_factory=sqlite3.Row`).
2. **SELECT candidates**:
   ```sql
   SELECT id, tweet_id, url, category, title, prompt_text, notes,
          author_name, author_screen, author_followers,
          likes_count, retweet_count, reply_count, view_count
   FROM prompts
   WHERE quality_scores IS NULL AND prompt_text IS NOT NULL
   ORDER BY likes_count DESC
   LIMIT ?;
   ```
   If 0 rows, return early with `评分完成: 0 qualified（没有待评分的 prompts）`.
3. **Build LLM client**: `llm = GeminiClient()` — defaults to `project="sparki-op"`, `location="global"`, `default_model="gemini-3.5-flash"`, `timeout=60s`. Thinking disabled via `ThinkingConfig(thinking_budget=0)`.
4. **Build quality config**: `quality_cfg = QualityConfig(weights=QualityWeights(), thresholds=QualityThresholds(min_overall=min_score))`. The `weights` field is the dataclass default (which matches `configs/quality.yaml` — see drift #2). The `thresholds.min_overall` is the value the user passed in.
5. **Instantiate scorer**: `scorer = QualityScorer(llm, quality_cfg)`. No `default_model` kwarg is passed, so the scorer uses `"gemini-3.5-flash"` (line 79 default).
6. **For each candidate prompt**:
   1. **Construct `ExtractedPrompt`** from the row (`core_tools.py:315-333`). The dataclass field `quality_scores` is set to `None` (it is about to be re-filled by the scorer).
   2. **Call `scorer.score(prompt_obj)`** (line 335). The scorer:
      - Calls `self.llm.complete(prompt=f"Prompt to score:\n{prompt_text}", system=SCORING_SYSTEM_PROMPT, model="gemini-3.5-flash", temperature=0.0, max_tokens=300)` (`scorer.py:88-100`).
      - Parses JSON via `_parse_json_response` (handles ` ```json ... ``` ` fences, line 38).
      - Clamps each of the 4 dimensions to `[0.0, 1.0]`.
      - Computes `overall = sum(dim_i * weight_i)`, rounded to 4 decimals.
      - **Returns `QualityScores` with all-zeros fallback** (`scorer.py:111-117`) if `_parse_json_response` returns `None`.
   3. **Build the CSV string** at `core_tools.py:336-339`:
      ```python
      f"{scores.specificity},{scores.visual_detail},{scores.novelty},{scores.generatable},{scores.overall}"
      ```
   4. **DB write**: `UPDATE prompts SET quality_scores = ? WHERE id = ?` (`core_tools.py:341-344`).
   5. **Count as qualified / unqualified** based on `scores.overall >= min_score` (`core_tools.py:346-349`).
7. **Commit once** at the end (`core_tools.py:351`). If the loop raises, the partial writes are rolled back.
8. **Return status string**.

## Validation

```bash
# 1. Make sure the DB and tables exist
python -m src.main init-db

# 2. Smoke test: count scoring candidates without calling LLM
python score-prompts/scripts/score_prompts.py \
  --project-root . \
  --batch 5 \
  --dry-run

# 3. Real run (requires Vertex AI auth + balance)
python score-prompts/scripts/score_prompts.py \
  --project-root . \
  --batch 5

# 4. Inspect the writes
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print('scored:', c.execute('SELECT COUNT(*) FROM prompts WHERE quality_scores IS NOT NULL').fetchone()[0])"
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print('pending scoring:', c.execute('SELECT COUNT(*) FROM prompts WHERE quality_scores IS NULL AND prompt_text IS NOT NULL').fetchone()[0])"
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print('sample CSV:', c.execute(\"SELECT quality_scores FROM prompts WHERE quality_scores IS NOT NULL LIMIT 3\").fetchall())"
```

The wrapper exits with code:
- `0` on success (real run or dry-run)
- `1` if the tool returned a `错误:` string
- `2` if the project root cannot be located (`src/agent/skills/core_tools.py` missing)

## Failure Handling

| Symptom | Likely cause | Action |
|---|---|---|
| `错误: ... GeminiClient ... google.genai ...` | Vertex AI auth missing. | Run `gcloud auth application-default login` or set `GOOGLE_APPLICATION_CREDENTIALS`. |
| `错误: ... 429 ... RESOURCE_EXHAUSTED` | Vertex AI rate limit. | Wait 60s and retry with a smaller `--batch`. The skill has **no built-in retry** on `LLMError` — the loop in `tool_score_prompts` re-raises to the boundary. |
| All 4 dimensions come back as `0.0` for a prompt | LLM JSON parse failed (markdown fence stripping, truncated response, etc.) → `_parse_json_response` returned `None` → the all-zeros fallback in `scorer.py:111-117` fired. | Inspect the raw response in the LLM logs. Lower `temperature` (already `0.0`). If the model keeps emitting prose instead of JSON, swap to a more deterministic model. |
| `quality_scores` shows as `0,0,0,0,0.0` for many rows | JSON parse failure storm. | Same as above — fix the LLM, then re-run `score_prompts` (the existing CSV is overwritten). |
| `0/{N} qualified` despite a large batch | `min_score` is too high for your prompt pool. | Lower `--min_score` (0.4 is a reasonable default). Or accept that the pool is genuinely low quality and re-run `crawl_tweets` + `extract_prompts` with broader queries. |
| `idx_prompts_quality` is missing from the schema | Migration skipped. | Run `python -m src.main init-db` — the index is created by `init_db()` via the `SCHEMA` literal. |
| The `CAST(quality_scores AS REAL)` value seems wrong | The CSV's first field is `specificity`, not `overall`. The `CAST` only reads the **leading** float. | See drift #4 in Handoff Notes. Use `CAST(quality_scores AS REAL)` only when you want `specificity`; for `overall`, parse the 5th comma-separated field instead. |

## Handoff Notes

These are the **five verified** drift points between the project wiki, the current code, and the live database. The wiki document is `prompts/scoring/01_scoring_system.md` and the canonical interface is `docs/11_ToolInterface.md` §3. **Prioritize the code as the source of truth.**

1. **Default model — wiki matches the code, not a drift, but the call site hides the override.**
   - `prompts/scoring/01_scoring_system.md` line 5 says: `Model: gemini-3.5-flash (default)`.
   - `src/worker/scorer.py:79` defaults to: `default_model: str = "gemini-3.5-flash"`.
   - **The tool wrapper `tool_score_prompts()` calls `QualityScorer(llm, quality_cfg)` with no `default_model` kwarg** (`core_tools.py:309`). So the actual model is `gemini-3.5-flash` end-to-end.
   - Implication: if you swap the default in `scorer.py`, the change takes effect immediately. If you want to **per-call** choose a different model (e.g. for a one-off quality audit), you'd need to extend the tool to accept `default_model` in `args`.

2. **`QualityConfig` is constructed with default `QualityWeights()` — the YAML is never read.**
   - `core_tools.py:305-308`:
     ```python
     quality_cfg = QualityConfig(
         weights=QualityWeights(),         # dataclass default, NOT from YAML
         thresholds=QualityThresholds(min_overall=min_score),  # only min_score is dynamic
     )
     ```
   - The dataclass defaults in `src/types/config.py:120-125` happen to be `0.25 / 0.30 / 0.20 / 0.25`, which **match** `configs/quality.yaml` lines 3-6.
   - **But** if you edit `configs/quality.yaml` to, say, `novelty: 0.40`, the tool **will keep using 0.20** until you also update the dataclass default. The YAML is documentation here, not configuration. The other 3 thresholds (`good_overall=0.60`, `min_specificity=0.30`, `min_visual_detail=0.20`) are also not enforced — the tool only checks `overall >= min_score`.
   - Implication: the YAML is the **single source of truth** for documentation, but a re-tune of the weights requires editing `src/types/config.py` (or extending the tool to load the YAML).

3. **The `overall` written into the CSV is the *weighted average*, not the LLM's `overall` (if it ever returned one).**
   - The system prompt (`scorer.py:56-69`) asks for **4 fields** (`specificity`, `visual_detail`, `novelty`, `generatable`) and explicitly does NOT ask for `overall`. The LLM is expected to return 4 numbers; `overall` is computed client-side.
   - The tool builds the CSV at `core_tools.py:336-339` using `scores.overall` (the Python-computed weighted average, `scorer.py:124-129`).
   - `core_tools.py:336-339` writes `f"{scores.specificity},{scores.visual_detail},{scores.novelty},{scores.generatable},{scores.overall}"` — 5 floats in that fixed order.
   - Implication: editing the system prompt to also ask the LLM for `overall` would have **no effect** on what's stored — the tool ignores any LLM-returned `overall` and re-computes it.

4. **`CAST(quality_scores AS REAL)` reads the *first* CSV field (specificity), not `overall`.**
   - The CSV format is `"spec,vis,nov,gen,overall"` (`core_tools.py:336-339`).
   - `tool_generate_images` filters with `AND CAST(quality_scores AS REAL) >= ?` (`core_tools.py:535`).
   - `tool_generate_images` sorts with `ORDER BY CAST(quality_scores AS REAL) DESC` (`core_tools.py:539`).
   - `build_html.py` likely uses the same pattern (read the leading float).
   - **SQLite `CAST('0.72,0.65,0.50,0.80,0.6705' AS REAL)` returns `0.72`** (the leading float, stopping at the first non-numeric char).
   - So **all downstream tools are currently filtering and sorting on `specificity`, not `overall**. They probably work *well enough* because `specificity` and `overall` correlate, but the contract is misleading. A fix is to store the 5-field CSV in the opposite order, or to store JSON / a separate `quality_overall REAL` column. The `idx_prompts_quality` index is a plain text index, so it cannot fix this either.

5. **The all-zeros fallback (line 111-117) is silent — a parse failure looks identical to a "this prompt is genuinely bad".**
   - If the LLM returns invalid JSON (e.g. a truncated response, prose, an off-by-one bracket), `_parse_json_response` returns `None` and the scorer returns `QualityScores(0,0,0,0,0)`.
   - The CSV is still written: `0.0,0.0,0.0,0.0,0.0`. The prompt is counted as `unqualified` (since `0.0 < min_score`). **There is no error log, no metric, no flag.**
   - Implication: a JSON parse failure storm is invisible. A "quality of 0" prompt and a "JSON parse failed" prompt look the same in the DB. If you see a sudden spike of `0,0,0,0,0.0` rows, suspect a model change or a Vertex AI rate-limit-induced truncation.

### Other things the next operator should know

- **Live DB state at the time of writing**: see the verification command output. (Run `python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print('pending scoring:', c.execute('SELECT COUNT(*) FROM prompts WHERE quality_scores IS NULL AND prompt_text IS NOT NULL').fetchone()[0])"`.)
- **Sequential loop, no concurrency**: the tool runs `scorer.score(prompt_obj)` in a `for` loop, one LLM call at a time. `QualityScorer` does not expose a batch method. If you need throughput, wrap the loop with `asyncio.gather` and a `RateLimitSafeGenerator`-style gate, or batch the prompts in one LLM call (`SCORING_SYSTEM_PROMPT` would need to be extended to accept a list).
- **The LLM call has `max_tokens=300` (`scorer.py:96`)** — a 4-float JSON is ~50 tokens, so this is generous. If the model is occasionally returning a truncated response, the truncation is the model's choice, not a token cap.
- **`temperature=0.0` (`scorer.py:95`)** is the right setting for scoring — re-running on the same prompt should give the same scores.
- **V3.3 migration target** (per `docs/11_ToolInterface.md` §"V3.3 目标版"): `tweets` and `prompts` collapse into a single `prompts` table with `has_raw_tweet`, `has_prompt`, `has_cover_image` flags. The scoring skill's `SELECT` stays the same (still on the same row), but the `idx_prompts_quality` index may be replaced with a per-column index. Drift #4 will likely be fixed in V3.3 by storing `quality_scores` as JSON or as separate `quality_specificity` / `quality_overall` columns.
- **The `QualityScores` dataclass (`src/types/prompt.py:13-30`) has `is_qualified()` and `should_generate_image()` helpers** with `threshold=0.40` defaults that match the YAML. The tool does **not** call these helpers — it does the comparison inline at `core_tools.py:346`. A small refactor opportunity.
- **Wiki says "the score is on the prompt text"** — the `SCORING_SYSTEM_PROMPT` line "Only score based on the PROMPT TEXT itself, not on engagement or author" matches the code. The `QualityScorer.score()` method receives the full `ExtractedPrompt` but only uses `prompt.prompt_text` (line 107), so the prompt text is the only signal. Engagement (`likes_count`, etc.) is not fed to the LLM. The DB ordering by `likes_count DESC` is a *candidate selection* heuristic (high-engagement prompts get scored first), not a *scoring* input.
