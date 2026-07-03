# Handoff Checklist

## Install

- [ ] Run `pip install -r requirements.txt`.
- [ ] Confirm `pyyaml` and `python-dotenv` are available.
- [ ] Confirm `google-genai` is installed (the `GeminiClient` hard-depends on it).

## Configure

- [ ] Confirm `configs/quality.yaml` weights and thresholds are the ones you want. **Note** the tool reads the dataclass defaults in `src/types/config.py:120-134`, not the YAML — see SKILL.md drift #2. If you edit the YAML, also edit the dataclass (or extend the tool to load the YAML).
- [ ] (Optional) Set `GOOGLE_APPLICATION_CREDENTIALS` in the shell or `.env` to point at a service account with Vertex AI access. The default project is `sparki-op`, location is `global`.
- [ ] (Optional) Add `GOOGLE_APPLICATION_CREDENTIALS` to `.env.example` so the next operator does not miss it.

## Initialize

- [ ] Run `python -m src.main init-db` if `data/veo_prompts.db` is missing.
- [ ] Confirm the `prompts` table has the `quality_scores` column and the `idx_prompts_quality` index:

  ```bash
  python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print([r for r in c.execute('PRAGMA table_info(prompts)').fetchall() if r[1]=='quality_scores'])"
  python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print(c.execute(\"SELECT name FROM sqlite_master WHERE type='index' AND name='idx_prompts_quality'\").fetchone())"
  ```

- [ ] Confirm there are `prompt_text IS NOT NULL` rows (i.e. the upstream `extract_prompts` has run):

  ```bash
  python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print('pending scoring:', c.execute('SELECT COUNT(*) FROM prompts WHERE quality_scores IS NULL AND prompt_text IS NOT NULL').fetchone()[0])"
  ```

## Smoke Test

```bash
# 1. Preview: count scoring candidates without calling the LLM
python score-prompts/scripts/score_prompts.py \
  --project-root . \
  --batch 5 \
  --dry-run

# Expected: prints "Would score: N/5 prompts (passed candidate filter) [min_score=0.4]"
# with up to 3 sample candidates. Exit code 0. No LLM call, no DB write.

# 2. Real run on a tiny batch
python score-prompts/scripts/score_prompts.py \
  --project-root . \
  --batch 5

# Expected: prints "评分完成: {Q}/{T} qualified（min=0.4，batch=5）". Exit code 0.
# Vertex AI auth + balance required.
```

## Verify

- [ ] Command exits with code `0` (non-zero = see "Escalation" below).
- [ ] Output starts with `评分完成:`.
- [ ] The `prompts.quality_scores` column has been updated for the scored rows:

  ```bash
  python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print('scored:', c.execute('SELECT COUNT(*) FROM prompts WHERE quality_scores IS NOT NULL').fetchone()[0])"
  python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print('sample CSV:', c.execute(\"SELECT quality_scores FROM prompts WHERE quality_scores IS NOT NULL LIMIT 3\").fetchall())"
  ```

  Each value should be a 5-field CSV like `0.72,0.65,0.50,0.80,0.6705`. **No spaces** in the CSV.
- [ ] No row contains `0,0,0,0,0.0` (a parse-failure storm — see SKILL.md drift #5). If a few rows do, the LLM response was truncated or non-JSON. Inspect the LLM logs.
- [ ] The `idx_prompts_quality` index still exists:

  ```bash
  python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print(c.execute(\"SELECT name FROM sqlite_master WHERE type='index' AND name='idx_prompts_quality'\").fetchone())"
  ```

## Re-tuning the weights

The tool reads `QualityWeights()` defaults (which mirror `configs/quality.yaml`). To re-tune:

1. Edit both `configs/quality.yaml` (for documentation) **and** `src/types/config.py:120-125` (for actual behaviour). See SKILL.md drift #2.
2. Re-run `score_prompts` on the existing pool. The new CSV will encode the new weights:

   ```bash
   python score-prompts/scripts/score_prompts.py --batch 200 --min-score 0.0
   ```

   (`--min-score 0.0` re-scores everything, regardless of the previous score.)

3. Confirm the new distribution:

   ```bash
   python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); rows = c.execute(\"SELECT quality_scores FROM prompts WHERE quality_scores IS NOT NULL\").fetchall(); overalls = [float(r[0].split(',')[-1]) for r in rows if r[0]]; import statistics; print(f'n={len(overalls)} mean={statistics.mean(overalls):.3f} median={statistics.median(overalls):.3f} stdev={statistics.stdev(overalls):.3f}')"
   ```

   (This reads the **5th** field, i.e. `overall`. Don't use `CAST(quality_scores AS REAL)` for that — see SKILL.md drift #4.)

## Re-tuning the threshold

The threshold is **per-call**, not a config value. To run a stricter filter:

```bash
python score-prompts/scripts/score_prompts.py --batch 50 --min-score 0.6
```

This counts prompts with `overall >= 0.6` as "qualified". It does **not** overwrite the CSV — the same scores are written regardless of `min_score`. The threshold only affects the `qualified` count in the output string.

## Hand Off To The Next Skill

- [ ] Trigger `generate_images` (e.g. via Agent message: "按分数生成前 5 张", or directly: `python score-prompts/../generate-images/scripts/generate_images.py --batch 10 --sort-by score --filter '{"min_score": 0.5}'`).
- [ ] Or trigger the full pipeline mode (Agent message: "跑一遍完整流程") which chains: `crawl_tweets` → `extract_prompts` → `score_prompts` → `generate_images` → `sync_images` → `build_html` → `publish`.
- [ ] Keep this skill's output string for the run log — the `qualified / total` ratio is the main quality KPI.

## Escalation

| Symptom | Likely cause | Action |
|---|---|---|
| `错误: ModuleNotFoundError: No module named 'google.genai'` | `google-genai` not installed. | `pip install google-genai`; consider adding to `requirements.txt`. |
| `错误: ... GeminiClient ... google.genai ...` | Vertex AI auth missing. | Run `gcloud auth application-default login` or set `GOOGLE_APPLICATION_CREDENTIALS`. |
| `错误: ... 429 ... RESOURCE_EXHAUSTED` | Vertex AI rate limit. | Wait 60s and retry with a smaller `--batch`. The skill has **no built-in retry** on `LLMError`. |
| `错误: IndentationError` / `NameError` from inside `tool_score_prompts` | Stale `.pyc` or partial edit. | Re-`pip install -e .`, clear `__pycache__`. |
| `评分完成: 0 qualified（没有待评分的 prompts）` | The pool is fully scored, or no rows have `prompt_text IS NOT NULL`. | Re-run `extract_prompts` to fill the pool. Verify the upstream with `python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); print('pending extract:', c.execute('SELECT COUNT(*) FROM tweets WHERE prompt_text IS NULL').fetchone()[0])"`. |
| `评分完成: 0/50 qualified` | `min_score` too high for the prompt pool. | Lower `--min-score` (0.4 is a reasonable default) or accept that the pool is low quality. |
| Many `0,0,0,0,0.0` rows after a run | LLM JSON parse storm (truncation, prose response, etc.) — silent fallback fired. | See SKILL.md drift #5. Inspect raw LLM logs, lower `max_tokens` if truncation is suspected, or add a JSON-mode flag if the model supports it. Re-run `score_prompts` to overwrite. |
| `idx_prompts_quality` missing | Migration skipped. | Run `python -m src.main init-db` — the index is in the `SCHEMA` literal. |
| `quality_scores` shows truncated values like `0.72,0.65,0.50,0.8,0.` | A previous tool version wrote a different format. | Re-run `score_prompts` on the affected rows. The new format always has 5 fields with full float precision. |
| The qualified count seems too high (> 80%) or too low (< 10%) | The `min_score` doesn't match your intuition. | Print the actual `overall` distribution (see "Re-tuning the weights" above). Adjust `--min-score` accordingly. |
