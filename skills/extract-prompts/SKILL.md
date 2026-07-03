---
name: extract-prompts
description: Extract Veo/Gemini video generation prompts from tweets in the local SQLite pipeline database using a three-pass LLM flow (extract → recheck → repair), update the `tweets` row in place, insert a new row in `prompts`, and down-classify any LLM-suggested new category to `other`. Use when the agent needs to run or debug the `extract_prompts` phase, when the tweet pool has rows where `tweets.prompt_text IS NULL`, or when triaging `category_suggestions` / `is_prompt` / "three-pass" extraction behaviour.
---

# Extract Prompts (V3.2 — Three-Pass LLM Flow)

## What It Does

Pulls the next batch of tweets where `tweets.prompt_text IS NULL` (ordered by `likes_count DESC`), runs each through a **three-pass** Gemini extraction:

1. **Pass 1 — `extract()`**: classification + structured extraction (uses the `_SYSTEM_PROMPT_CONTENT` from `src/worker/extractor.py`).
2. **Pass 2 — `_recheck()`**: only triggered if Pass 1 says `is_prompt=false` **and** the tweet text contains a `PROMPT_INDICATORS` keyword (`prompt:`, `见评论`, `prompt in`, `prompt_details`, etc.).
3. **Pass 3 — `_reextract_structured()`**: only triggered by `_validate_and_repair()` when the extracted `prompt_text` looks like a JSON key name (`"style":`, `"scenes":` …) or a placeholder (`...`, `see comments`, `[the full prompt text]`, length < 15 chars).

After validation, the tool **atomically** UPDATEs `tweets` (4 columns) and INSERTs into `prompts` (15 columns) under a single `conn.commit()`. New categories (those not in the `categories` table) are downgraded to `"other"` on the `prompts` row.

This skill does **not** score prompts, generate images, or publish — those are separate skills (`score_prompts`, `generate_images`, `publish`).

## When To Use

- Run **after** `crawl_tweets` has inserted fresh rows and **before** `score_prompts`.
- Use when the user says: "提取 prompt", "跑 extract_prompts", "把待提取的推文处理一下", or asks the ReAct agent to invoke `tool_extract_prompts`.

## When NOT To Use

- For scoring quality of already-extracted prompts → use `score_prompts`.
- For cover-image generation → use `generate_images`.
- For HTML build / GitHub Pages publish → use `build_html` / `publish`.
- For re-classifying tweets that were *skipped* by the content filter — re-crawl with broader queries instead. Tweaking the filter on its own is brittle (see `Failure Handling` below).

## Required Context

- Project root: `16_NewCrawler`
- Tool implementation: `src/agent/skills/core_tools.py:135-262` (`tool_extract_prompts`)
- LLM client: `src/llm/gemini_client.py` → `GeminiClient` (Vertex AI, default `gemini-3.5-flash`)
- Three-pass logic: `src/worker/extractor.py` → `PromptExtractor.extract()` (line 268), `_recheck()` (line 308), `_reextract_structured()` (line 326), `_validate_and_repair()` (line 364)
- Category downgrade: `src/worker/extractor.py:480-525` → `build_extracted_prompt()`
- System prompt source of truth: `src/worker/extractor.py:157-230` (`_SYSTEM_PROMPT_CONTENT`)
- Type defs: `src/types/prompt.py` (`ExtractedPrompt`), `src/types/tweet.py` (`Tweet`, `AuthorRef`), `src/types/category.py` (`CategorySuggestion`, `CategorySuggestionStatus`)
- Schema: `src/memory/schema.py` (`tweets`, `prompts`, `categories`, `category_suggestions`)
- Exceptions: `src/exceptions.py` (`LLMError`, `LLMParseError`)
- V3.2 contract (where to find the canonical record): `docs/11_ToolInterface.md` §2

## Preconditions

1. **Database initialized**: run `python -m src.main init-db` so the `tweets`, `prompts`, and `categories` tables exist. The `category_suggestions` table is created in the same `init_db()` call.
2. **Vertex AI auth**: the `GeminiClient` constructor calls `genai.Client(vertexai=True, project="sparki-op", location="global")`. Set `GOOGLE_APPLICATION_CREDENTIALS` (or run `gcloud auth application-default login`) before invoking.
3. **`tweets` table populated** with rows where `prompt_text IS NULL` (this is the implicit input — the skill `SELECT`s them itself, ordered by `likes_count DESC`).
4. **`categories` table may be empty** — current production DB has 0 rows. In that case every LLM-suggested category will be downgraded to `"other"`. Seed the table or accept the downgrade (see `Failure Handling`).
5. Python dependencies: `google-genai` is the only hard requirement beyond the project base (`pip install -r requirements.txt`).

## Inputs

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `batch` | `int` | `50` | Max tweets to process in this call. The SELECT is `WHERE prompt_text IS NULL ORDER BY likes_count DESC LIMIT ?`. |

The CLI wrapper (`scripts/extract_prompts.py`) additionally accepts `--project-root` and `--dry-run` (see Validation below).

## Outputs

- **Success string** (printed to stdout):
  ```
  提取完成: {M}/{N} prompts extracted（跳过 {S} 条非 Prompt 推文）
  ```
  where `M` = rows that produced a real prompt, `N` = rows the SQL `SELECT` returned, `S` = rows the LLM (or content filter) rejected.

- **No-work string**:
  ```
  提取完成: 0/0 — 没有需要提取的推文
  ```

- **Failure string** (returned by the tool, also non-zero exit code from the wrapper):
  ```
  错误: {ExceptionType}: {message}
  ```

- **Side effects** (all under one `conn.commit()` at the end of the batch, see `core_tools.py:257`):
  - `tweets` UPDATE (4 columns): `prompt_text`, `category`, `title`, `notes`
  - `prompts` INSERT (15 columns + fixed `image_status='pending'` + `quality_scores=NULL`)
  - `category_suggestions` INSERT: **0 rows** today — see the **drift** in Handoff Notes. The skill builds `CategorySuggestion` objects in memory but the wrapper discards the second return value of `build_extracted_prompt()`.

## Data Contract

This skill writes **two** tables in a single SQLite transaction. Keep them separate — they serve different consumers.

### `tweets` — UPDATE 4 columns (in place)

| Field | Source | Notes |
|---|---|---|
| `prompt_text` | LLM extraction (or downgraded to `""` on `is_prompt=false`) | NULL → filled |
| `category` | LLM extraction (or `"other"` for new categories) | NULL → filled |
| `title` | LLM extraction (or `""`) | NULL → filled |
| `notes` | LLM extraction (rejection / recheck / repair notes) | NULL → filled |

The `WHERE` clause is `tweet_id = ?`. No other columns are touched (`likes_count`, `author_*`, `created_at` stay frozen).

### `prompts` — INSERT 15 columns (one row per extracted prompt)

| Field | Source | Notes |
|---|---|---|
| `tweet_id` | `tweets.tweet_id` | The `UNIQUE` key — INSERT OR REPLACE on collision. |
| `url` | `tweets.url` | |
| `category` | LLM extraction (already downgraded to `"other"` if it was new) | NOT NULL column — `other` is the only safe fallback. |
| `title` | LLM extraction | NOT NULL — `""` if the LLM didn't give one. |
| `prompt_text` | LLM extraction | NOT NULL — the actual prompt text. |
| `notes` | LLM extraction | |
| `author_name` | `tweets.author_name` | denormalized for sorting without JOIN |
| `author_screen` | `tweets.author_screen` | denormalized |
| `author_followers` | `tweets.author_followers` | denormalized |
| `likes_count` | `tweets.likes_count` | |
| `retweet_count` | `tweets.retweet_count` | |
| `reply_count` | `tweets.reply_count` | |
| `view_count` | `tweets.view_count` | |
| `extracted_at` | `datetime.now(timezone.utc).isoformat()` | set on insert |
| `image_status` | `'pending'` (string literal) | hard-coded, see `core_tools.py:236` |
| `quality_scores` | `NULL` | set later by `score_prompts` |

### `category_suggestions` — INSERT 0 rows (current behaviour)

| Field | Expected source | Today |
|---|---|---|
| `suggested_name` | LLM new category | **not inserted** |
| `suggested_desc` | (optional) | not inserted |
| `reason` | `build_extracted_prompt()` builds the string | not inserted |
| `suggested_by` | `suggested_by="gemini-3.5-flash"` (hard-coded, see `extractor.py:500`) | not inserted |
| `sample_prompt` | first 200 chars of `result.prompt_text` | not inserted |
| `status` | `'pending'` | not inserted |
| `created_at` | `datetime.now(timezone.utc).isoformat()` | not inserted |

See **Handoff Notes** for the gap and the proposed fix.

## Procedure

1. **Open DB connection** via `src.memory.schema._conn()` (singleton, `row_factory=sqlite3.Row`).
2. **SELECT candidates**:
   ```sql
   SELECT tweet_id, url, text, short_text, author_name, author_screen,
          author_followers, likes_count, retweet_count, reply_count, view_count
   FROM tweets
   WHERE prompt_text IS NULL
   ORDER BY likes_count DESC
   LIMIT ?;
   ```
   If 0 rows, return early with `提取完成: 0/0 — 没有需要提取的推文`.
3. **Build LLM client**: `llm = GeminiClient()` — defaults to `project="sparki-op"`, `location="global"`, `default_model="gemini-3.5-flash"`, `timeout=60s`. Thinking is disabled via `ThinkingConfig(thinking_budget=0)`.
4. **Load categories** from `categories` table. If empty, fall back to `["video-generation", "cinematic", "other"]` (see `core_tools.py:173`).
5. **Instantiate extractor**: `PromptExtractor(llm, categories=...)`. The hard-coded `_SYSTEM_PROMPT_CONTENT` lives in `extractor.py:157-230`.
6. **For each candidate tweet**:
   1. **Construct `Tweet` object** from the row (see `core_tools.py:181-197`). Falls back: `text=row["text"] or row["short_text"] or ""`.
   2. **Pre-LLM content filter** (`_content_filter` at `extractor.py:92-105`, called from `extractor.py:275`):
      - tweet text (lowercased) must contain `"veo"`
      - `len(text.split()) >= 15`
      - If not, return `ExtractionResult(is_prompt=False)` immediately. **No LLM call is made.** This is the `S` (skipped) counter.
   3. **Pass 1 — `extract()`** (line 268): send `Tweet:\n{text}` with the system prompt, get back a parsed JSON dict.
   4. **Pass 2 — `_recheck()`** (line 308): only when Pass 1 says `is_prompt=false` **and** `_should_recheck(text)` (line 83) returns True. Uses a different, stricter system prompt.
   5. **Pass 3 — `_reextract_structured()`** (line 326): only when `_validate_and_repair()` (line 364) detects:
      - `_looks_like_json_extraction(prompt_text)` (line 108) — starts with `"style":` / `"scenes":` / `"camera":` / `"mood":` / `"aspect_ratio":` / `"scene_number":` / `"description":` / `"audio":` / `"background_music":`, OR
      - `_looks_like_placeholder(prompt_text)` (line 117) — is one of `...`, `[the full prompt text]`, `see comments`, `见评论`, `prompt below`, `in reply`, or is shorter than 15 chars.
   6. **Pass 4 — `MIN_PROMPT_WORDS` gate** (line 417): even after a successful recheck/repair, if `len(prompt_text.split()) < 25`, the result is rejected. The `notes` field gets a `[rejected: prompt_text only N words, minimum 25 required]` suffix. **This is not in the wiki — see Handoff Notes.**
   7. **Build `ExtractedPrompt` via `build_extracted_prompt()`** (line 480): applies the new-category downgrade. If `result.category` is not in `known_categories`, set `prompt.category = "other"` and emit a `CategorySuggestion` in the second return value (currently dropped — see Handoff Notes).
   8. **DB write (still inside the loop)**: `UPDATE tweets SET prompt_text=?, category=?, title=?, notes=? WHERE tweet_id=?`, then `INSERT OR REPLACE INTO prompts (...)`.
7. **Commit once** at the end (`core_tools.py:257`). If the loop raises, the partial writes are rolled back.
8. **Return status string**.

## Validation

```bash
# 1. Make sure the DB and tables exist
python -m src.main init-db

# 2. Smoke test: process 5 tweets in dry-run (no LLM call)
python extract-prompts/scripts/extract_prompts.py \
  --project-root . \
  --batch 5 \
  --dry-run

# 3. Real run (requires Vertex AI auth + balance)
python extract-prompts/scripts/extract_prompts.py \
  --project-root . \
  --batch 5

# 4. Confirm the writes landed
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print('tweets with prompt:', c.execute('SELECT COUNT(*) FROM tweets WHERE prompt_text IS NOT NULL').fetchone()[0])"
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print('prompts total:', c.execute('SELECT COUNT(*) FROM prompts').fetchone()[0])"
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print('pending tweets:', c.execute('SELECT COUNT(*) FROM tweets WHERE prompt_text IS NULL').fetchone()[0])"
```

The wrapper exits with code:
- `0` on success (real run or dry-run)
- `1` if the tool returned a `错误:` string
- `2` if the project root cannot be located (`src/agent/skills/core_tools.py` missing)

## Failure Handling

| Symptom | Likely cause | Action |
|---|---|---|
| `错误: ... GeminiClient ... google.genai ...` | Vertex AI auth missing. | Run `gcloud auth application-default login` or set `GOOGLE_APPLICATION_CREDENTIALS`. |
| `错误: ... 429 ... RESOURCE_EXHAUSTED` | Vertex AI rate limit. | Wait 60s and retry with a smaller `--batch`. The skill has **no built-in retry** on `LLMError` for the batch path — `extract_batch()` (line 431) has retries, but the tool calls `extract()` directly, not `extract_batch()`. |
| Skipped counter is suspiciously high (S ≫ M) | Content filter is too strict OR queries are too broad. | Adjust `_REQUIRED_TWEET_KEYWORDS` at `extractor.py:33` and `_MIN_CONTENT_WORDS` at line 34. Avoid the temptation to lower them too far — most "veo" tweets without a usable prompt are correctly filtered by the LLM and the MIN_PROMPT_WORDS gate. |
| All rows come back as `category="other"` | `categories` table is empty (current production state — 0 rows) or the LLM is inventing free-form labels. | Either seed `categories` with the standard list (`cinematic-scene`, `product-showcase`, …) **or** accept the downgrade. Seeding requires a one-shot INSERT script. |
| `category_suggestions` is empty after a run | Drift: the skill builds the suggestion in memory but never INSERTs. | See Handoff Notes — the fix is one extra `INSERT` in `tool_extract_prompts()`. |
| Extraction quality is poor on a specific query | The LLM is misclassifying that query's tweets. | Re-crawl with a more specific query, then re-run extraction on the new rows. Do not tweak `_SYSTEM_PROMPT_CONTENT` for one query — the prompt is global. |
| Vertex AI returns a thinking-only response (no `text`) | The model is in "thinking" mode. | `GeminiClient` already disables thinking via `thinking_budget=0` (`gemini_client.py:54`). If you see this, check whether a custom `model` was passed that bypasses the default. |

## Handoff Notes

These are the five **verified** drift points between the project wiki, the current code, and the live database. The wiki document is `prompts/extraction/01_extraction_system.md` and `docs/11_ToolInterface.md`. **Prioritize the code as the source of truth.**

1. **Default model — wiki matches the code, not a drift.**
   - `prompts/extraction/01_extraction_system.md` says: `gemini-3.5-flash`.
   - `src/llm/gemini_client.py:30` and `src/worker/extractor.py:240` both default to: `gemini-3.5-flash`.
   - **The tool wrapper `tool_extract_prompts()` calls `GeminiClient()` with no args** (`core_tools.py:169`), so the actual model is `gemini-3.5-flash` end-to-end.

2. **Pre-LLM content filter is undocumented in the wiki.**
   - The wiki describes the three-pass LLM flow but does **not** mention the cheap content filter that runs *before* the first LLM call. The filter is implemented in `_content_filter()` at `extractor.py:92-105`, called from `extract()` at `extractor.py:275`. Requirements: tweet text (lowercased) contains `"veo"` AND `len(text.split()) >= 15`. Tweets that fail the filter are counted in the `S` (skipped) bucket **without an LLM call**.
   - The wiki's "few-shot" examples and "STRICT CRITERIA" are still accurate — they live in `_SYSTEM_PROMPT_CONTENT` at `extractor.py:157-230`. The 15-word floor is **in addition to** the LLM's own strict criteria.

3. **`tweets.prompt_text` is correctly nullable** — no issue. `PRAGMA table_info(tweets)` confirms `prompt_text TEXT` with no `NOT NULL`, no `DEFAULT`. The `WHERE prompt_text IS NULL` selector works as intended.

4. **`category_suggestions` table is never written to by this skill — actual behaviour drift.**
   - The table exists in `schema.py:112-123` and the `build_extracted_prompt()` function in `extractor.py:480-525` builds a `CategorySuggestion` object with all the right fields (`suggested_by="gemini-3.5-flash"`, `sample_prompt=result.prompt_text[:200]`, `status=PENDING`, `created_at=_utc_now()`).
   - **But `tool_extract_prompts()` discards the second return value** (`prompt_obj, _ = build_extracted_prompt(...)`, `core_tools.py:204`). No `INSERT INTO category_suggestions` is ever issued.
   - **Implication for the next operator**: when the LLM invents a new free-form label (e.g. `"surreal-dreamscape"`), the `prompts` row is correctly downgraded to `"other"`, but **no audit trail is left**. If you need a "review these new labels" workflow, you must add a third write to the tool. A one-liner would be:
     ```python
     # after `prompt_obj, _ = build_extracted_prompt(...)`
     if result.category not in known_categories:
         conn.execute(
             "INSERT INTO category_suggestions "
             "(suggested_name, suggested_desc, reason, suggested_by, sample_prompt, status, created_at) "
             "VALUES (?, ?, ?, ?, ?, ?, ?)",
             (result.category, "",
              f"LLM classified a tweet as '{result.category}' but this category is not in DB",
              "gemini-3.5-flash",
              (result.prompt_text or "")[:200],
              "pending",
              datetime.now(timezone.utc).isoformat()),
         )
     ```
   - This is **not** a bug in the strict sense — the behaviour is documented as "downgrade to other" — but the surrounding code (the dataclass, the schema, the docstring) is misleading without the INSERT.

5. **There is a fourth gate that the wiki does not mention: `MIN_PROMPT_WORDS = 25`.**
   - At `extractor.py:417-427`, after repair, if the final `prompt_text` is shorter than 25 words, the result is flipped to `is_prompt=false` and a `[rejected: prompt_text only N words, minimum 25 required]` note is appended. This catches trivial prompts like `"Football Magic"` or `"show me a fitness app demo"` that slip through the LLM and the placeholder detector.
   - This is a quality gate, not a recheck. It does not call the LLM again.

### Other things the next operator should know

- **Live DB state at the time of writing**:
  - `tweets WHERE prompt_text IS NULL`: **9,099** rows pending.
  - `tweets WHERE prompt_text IS NOT NULL`: **1** row (a single early smoke-test).
  - `prompts`: **148** rows (from prior runs; the schema in `prompts` has the `tweet_id UNIQUE` constraint, so re-running on already-extracted tweets is safe — `INSERT OR REPLACE`).
  - `categories`: **0** rows. Every LLM-suggested label will be downgraded to `"other"`.
  - `category_suggestions`: **0** rows. (See drift #4 above.)
- **Sample pending tweet** (randomly picked from the 9,099): tweet id `2055359128789307832`, text `"This is honestly the best prompt I have ever seen https://t.co/jPBxXiLIjs"`, by `aitrendz_xyz` (119,356 likes). This tweet contains no `"veo"` keyword and will be filtered by `_content_filter` *before* any LLM call. Expect the skipped counter to dominate early batches.
- **The `extractor.py:500` line hard-codes `suggested_by="gemini-3.5-flash"`** even though the actual model can be overridden via `PromptExtractor(default_model=...)`. If a future operator swaps to a different model, this string will be wrong. Fix: read `self.default_model` instead of the literal.
- **The "extraction system" prompt in the wiki (`prompts/extraction/01_extraction_system.md`) is a slimmed-down version** of the real `_SYSTEM_PROMPT_CONTENT`. The real prompt includes 12 few-shot examples and a more aggressive "fail if it's a meme / explanation / diagram" rule set. If you tune the prompt, tune `_SYSTEM_PROMPT_CONTENT`, not the wiki.
- **Concurrency**: the tool runs the loop **sequentially**. `PromptExtractor.extract_batch()` (line 431) supports `concurrency=15` + retries, but it is not what the tool calls. If you need throughput, replace the loop body with `extractor.extract_batch(tweets)`.
- **V3.3 migration target** (per `docs/11_ToolInterface.md` §"V3.3 目标版"): `tweets` and `prompts` collapse into a single `prompts` table with `has_raw_tweet`, `has_prompt`, `has_cover_image` flags. The Data Contract above will become a single-table UPDATE. The `extract-prompts` skill will need to be re-validated after that migration.
- **No `image_status` semantics here**: this skill writes `'pending'` to the `prompts.image_status` column. The `generate_images` skill reads it. A V3.3 migration may rename this column to `has_cover_image`.
- **The `_recheck()` system prompt is the only one that lives inline** in a method (line 310-320), not in `_SYSTEM_PROMPT_CONTENT`. If you need to tune recheck behaviour, edit there.
- **The hard-coded comment at `extractor.py:240` says `default_model: str = "gemini-3.5-flash"`** but is overridden by the constructor in `tool_extract_prompts()` via `PromptExtractor(llm, categories=...)` with no `default_model` kwarg. The `extractor.py` default is the fallback. The actual call site passes no `default_model` override, so the wiki string is the one in effect.
