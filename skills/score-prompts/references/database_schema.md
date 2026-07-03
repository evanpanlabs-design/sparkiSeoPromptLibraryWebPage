# Database Contract — `score-prompts`

## Target DB

- **Path:** `data/veo_prompts.db`
- **Schema source:** `src/memory/schema.py` (`SCHEMA` literal + migrations, applied by `init_db()`)
- **Target table:** `prompts` (this skill does **not** read or write `tweets`, `authors`, `category_suggestions`, `images`, etc.)
- **Write mode:** `UPDATE` keyed on the `id` column (`INTEGER PRIMARY KEY AUTOINCREMENT`). The CSV overwrite is idempotent — re-running `score_prompts` on a previously-scored row replaces the CSV with a new one (different LLM output may differ in the 4th decimal).

## `prompts.quality_scores` Column

| Property | Value |
|---|---|
| Column name | `quality_scores` |
| Type | `TEXT` (nullable) |
| Index | `idx_prompts_quality ON prompts(quality_scores)` (text index; used for `IS NULL` / `IS NOT NULL` filters) |
| Value format (5 fields, CSV) | `"{specificity},{visual_detail},{novelty},{generatable},{overall}"` |
| Example value | `0.72,0.65,0.50,0.80,0.6705` |
| Written by | `tool_score_prompts()` at `core_tools.py:336-344` |
| Read by | `tool_generate_images()` (filter + sort, `core_tools.py:535, 539`); `scripts/build_html.py` (min_score filter) |

### The 5 fields

| Position | Field | Source | Range |
|---|---|---|---|
| 1 | `specificity` | LLM score, clamped to `[0.0, 1.0]` at `scorer.py:119` | float |
| 2 | `visual_detail` | LLM score, clamped at `scorer.py:120` | float |
| 3 | `novelty` | LLM score, clamped at `scorer.py:121` | float |
| 4 | `generatable` | LLM score, clamped at `scorer.py:122` | float |
| 5 | `overall` | Weighted average, **rounded to 4 decimals** at `scorer.py:124-129, 136` | float |

Weights (from `src/types/config.py:120-125`, which mirror `configs/quality.yaml`):
```python
QualityWeights(
    specificity=0.25,
    visual_detail=0.30,
    novelty=0.20,
    generatable=0.25,
)
```

### Important data semantics

- **`CAST(quality_scores AS REAL)` reads the LEADING float — i.e. `specificity`, not `overall`.** This is a latent contract mismatch with `tool_generate_images` and `build_html` (see SKILL.md drift #4). SQLite's `CAST` stops at the first non-numeric character, so `CAST('0.72,0.65,0.50,0.80,0.6705' AS REAL)` returns `0.72`. Sorting and filtering downstream is therefore operating on `specificity`, not on the true weighted overall.
- **The 4 base scores are clamped to `[0.0, 1.0]`** but the `overall` is not clamped. With the default weights `0.25+0.30+0.20+0.25 = 1.00`, `overall` is bounded by `[0.0, 1.0]` automatically, but if a future YAML change makes the weights sum to > 1.0, `overall` could exceed 1.0.
- **The all-zeros fallback** (`scorer.py:111-117`) writes `0.0,0.0,0.0,0.0,0.0` — indistinguishable from a "this prompt is genuinely terrible" score. See SKILL.md drift #5.
- **The `idx_prompts_quality` index is a text index** — it accelerates `WHERE quality_scores IS NULL` and `WHERE quality_scores IS NOT NULL`, but it cannot accelerate `ORDER BY CAST(quality_scores AS REAL)`. Downstream ordering is a full sort.
- **The column is nullable** — the `tool_extract_prompts()` writes `NULL` on INSERT (`core_tools.py:236`); the `score_prompts` skill then fills it. A `NOT NULL` constraint would force a two-phase write, so the nullable design is correct.

## Fields written by `score_prompts`

| `prompts` column | Source |
|---|---|
| `quality_scores` | 5-field CSV string from `QualityScorer.score(prompt_obj)` |

The `WHERE` clause is `id = ?` (the row's `INTEGER PRIMARY KEY`), not `tweet_id = ?`. No other columns are touched — engagement metrics, `image_status`, `extracted_at` all stay frozen.

## Related columns (read-only for this skill)

| Column | Why the tool cares |
|---|---|
| `id` | `UPDATE` key |
| `tweet_id` | Denormalized on the row; not used in the write |
| `url` | Passed to `ExtractedPrompt` (not used by the scorer) |
| `category` | Passed to `ExtractedPrompt` (not used by the scorer) |
| `title` | Passed to `ExtractedPrompt` (not used by the scorer) |
| `prompt_text` | The only field fed to the LLM via `f"Prompt to score:\n{prompt_text}"` |
| `likes_count` | Used for the `ORDER BY likes_count DESC` candidate selection only — **not** fed to the LLM |
| `extracted_at`, `image_status`, `image_gcs_url` | Not touched by this skill |

## Validation SQL

```sql
-- Pending scoring candidates (the implicit input)
SELECT COUNT(*) AS pending_scoring
FROM prompts
WHERE quality_scores IS NULL AND prompt_text IS NOT NULL;

-- Sample candidates (ordered by engagement, as the tool does)
SELECT id, tweet_id, category, title, substr(prompt_text, 1, 100) AS preview, likes_count
FROM prompts
WHERE quality_scores IS NULL AND prompt_text IS NOT NULL
ORDER BY likes_count DESC
LIMIT 5;

-- Already scored (the implicit output)
SELECT COUNT(*) AS scored
FROM prompts
WHERE quality_scores IS NOT NULL;

-- Sample CSV strings (5 fields, comma-separated, no spaces)
SELECT id, quality_scores
FROM prompts
WHERE quality_scores IS NOT NULL
LIMIT 5;

-- Distribution of overall (the 5th field — use a Python-side parse, not CAST)
-- SQLite doesn't have a built-in split_part, so a portable check is:
SELECT quality_scores
FROM prompts
WHERE quality_scores IS NOT NULL
LIMIT 100;
-- then split on commas in your client.

-- Index check
SELECT name FROM sqlite_master
WHERE type='index' AND tbl_name='prompts' AND name='idx_prompts_quality';
```

## Downstream Contract

The next skills, `generate_images` and `build_html`, read `quality_scores` in two ways:

1. **Filter / sort by `CAST(quality_scores AS REAL)`** — reads `specificity`, not `overall`. See SKILL.md drift #4. This is the current (mis-)behaviour.
2. **Pass `min_score` as a parameter** — the filter is `CAST(quality_scores AS REAL) >= ?` with the user's threshold. Same `specificity`-vs-`overall` caveat.

If you fix the storage format in V3.3 (e.g. move `overall` to the front of the CSV, or store it in a separate `REAL` column), **update both this skill's `tool_score_prompts` and all downstream readers in the same commit**.

## Related tables (not touched by this skill)

- `tweets` — the source rows that `extract_prompts` reads from
- `authors` — denormalized in the `prompts` row; not relevant to scoring
- `images`, `image_attempts` (V3.3) — populated by `generate_images`, not by scoring
- `category_suggestions` — populated by `extract_prompts` (when the LLM invents a new category); not relevant to scoring
