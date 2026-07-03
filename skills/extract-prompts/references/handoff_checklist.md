# Handoff Checklist — extract_prompts

A copy-pasteable runbook for the next operator.

---

## Install

- [ ] Run `pip install -r requirements.txt`.
- [ ] Confirm `google-genai` is available (the only LLM SDK required).
- [ ] Confirm `pyyaml` and `python-dotenv` are available (project-wide deps).

## Configure

- [ ] Set up **Vertex AI auth** for the `GeminiClient`:
  - Either run `gcloud auth application-default login` once on the machine that will run extraction, or
  - Set `GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json`.
- [ ] Confirm the GCP project (`sparki-op`, hard-coded in `src/llm/gemini_client.py:28`) and location (`global`, line 29) are correct for your environment. The default model `gemini-3.5-flash` must be available in the project's Vertex AI model garden.
- [ ] *(Optional)* Add a `GOOGLE_APPLICATION_CREDENTIALS` entry to `.env.example` with a placeholder.
- [ ] Review the content filter constants in `src/worker/extractor.py:33-34` if you want to widen or narrow the gate:
  ```python
  _REQUIRED_TWEET_KEYWORDS = ["veo"]      # case-insensitive
  _MIN_CONTENT_WORDS = 15                 # tweet text word-count floor
  ```
  Current DB has **9,099** pending tweets; the filter is currently strict enough to skip most "this is a great prompt" hype tweets.

## Initialize

- [ ] Run `python -m src.main init-db` if `data/veo_prompts.db` is missing.
- [ ] Confirm the four tables exist:

  ```bash
  python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); \
    [print(r[0]) for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name IN ('tweets','prompts','categories','category_suggestions')\").fetchall()]"
  ```

  Expected: `tweets`, `prompts`, `categories`, `category_suggestions` (in any order).

- [ ] *(Recommended)* Seed the `categories` table with the standard list if you want the LLM's labels to survive the downgrade. **Current state: 0 rows → everything becomes `"other"`.**

  ```sql
  INSERT OR IGNORE INTO categories (name, description, color, created_at) VALUES
    ('cinematic-scene',     'Film-like dramatic lighting + camera movement',  '#e74c3c', datetime('now')),
    ('product-showcase',    'Product rotating/displayed in studio or lifestyle setting', '#3498db', datetime('now')),
    ('character-portrait',  'Person or character face/body, portrait-style',   '#9b59b6', datetime('now')),
    ('3d-render',           '3D animated object, environment, architectural viz','#1abc9c', datetime('now')),
    ('animation-clip',      'Cartoon style, motion graphics, stylized animation','#f39c12', datetime('now')),
    ('nature-scene',        'Landscape, animals, plants, outdoor environments', '#27ae60', datetime('now')),
    ('urban-scene',         'City streets, buildings, traffic, architecture',  '#34495e', datetime('now')),
    ('food-beverage',       'Food styling, cooking, drink cinematography',     '#e67e22', datetime('now')),
    ('fashion-apparel',     'Clothing model, fabric detail, runway style',    '#fd79a8', datetime('now')),
    ('sports-action',       'Athletic movement, game footage simulation',     '#00b894', datetime('now')),
    ('sci-fi-fantasy',      'Futuristic, space, CG environments',             '#6c5ce7', datetime('now')),
    ('historical-period',   'Period drama, vintage aesthetics',               '#a29bfe', datetime('now')),
    ('abstract-motion',     'Artistic particles, shaders, generative visuals','#ffeaa7', datetime('now')),
    ('tutorial-demo',       'Screen recording style, product demo, how-to',   '#74b9ff', datetime('now')),
    ('social-media-content','Vertical video, reel-style, phone-native',       '#ff7675', datetime('now')),
    ('music-visualizer',    'Audio-reactive visual, album art motion',        '#55efc4', datetime('now')),
    ('other',               'Generic fallback',                                '#b2bec3', datetime('now'));
  ```

## Smoke Test (no LLM)

```bash
python extract-prompts/scripts/extract_prompts.py \
  --project-root . \
  --batch 5 \
  --dry-run
```

Expected:

- Exit code `0`.
- Output starts with `Would extract:`.
- Prints `skipped by filter: N` (often 4-5 for the top-likes batch — see drift #2 in `SKILL.md`).

## Smoke Test (real LLM call)

```bash
python extract-prompts/scripts/extract_prompts.py \
  --project-root . \
  --batch 5
```

Expected:

- Exit code `0` (success) or `1` (LLM error).
- Output starts with `提取完成:`.
- `M + S = N` where `M` is the prompts-extracted count and `S` is the skipped count.

## Verify

- [ ] The wrapper exited with code `0`.
- [ ] `tweets.prompt_text` count went up:

  ```bash
  python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); \
    print('tweets with prompt:', c.execute('SELECT COUNT(*) FROM tweets WHERE prompt_text IS NOT NULL').fetchone()[0])"
  ```

- [ ] `prompts` table grew by `M` rows:

  ```bash
  python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); \
    print('prompts total:', c.execute('SELECT COUNT(*) FROM prompts').fetchone()[0])"
  ```

- [ ] `tweets.pending` count dropped by `N`:

  ```bash
  python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); \
    print('pending tweets:', c.execute('SELECT COUNT(*) FROM tweets WHERE prompt_text IS NULL').fetchone()[0])"
  ```

- [ ] Sample new rows look sensible (not memes, not empty prompts):

  ```sql
  SELECT t.tweet_id, t.category, t.title, substr(t.prompt_text, 1, 80) AS preview, p.image_status
  FROM tweets t JOIN prompts p ON p.tweet_id = t.tweet_id
  ORDER BY t.rowid DESC
  LIMIT 5;
  ```

- [ ] No `prompts` row has `category = ''` or `category IS NULL` (NOT NULL contract — should never happen but worth checking after a fresh schema).

## Category-Suggestion Cleanup

> ⚠️ **Drift alert** — see `SKILL.md` Handoff Notes #4. The `category_suggestions` table is **not** populated by this skill today, even though the surrounding code suggests it should be. Cleanup below is defensive in case a future fix lands.

- [ ] If you implement the proposed fix (one extra `INSERT` in `tool_extract_prompts()`), expect a flood of `pending` rows. The cleanup is:

  ```sql
  -- Inspect pending suggestions
  SELECT suggested_name, COUNT(*) AS occurrences
  FROM category_suggestions
  WHERE status = 'pending'
  GROUP BY suggested_name
  ORDER BY occurrences DESC
  LIMIT 20;

  -- Approve the top ones (move to categories)
  BEGIN;
  INSERT OR IGNORE INTO categories (name, description, color, created_at)
    SELECT suggested_name, 'Auto-approved from suggestions', '#b2bec3', datetime('now')
    FROM category_suggestions
    WHERE status = 'pending' AND suggested_name = '<approved-name>';
  UPDATE category_suggestions
    SET status = 'approved', reviewed_at = datetime('now'), reviewed_by = 'operator'
    WHERE suggested_name = '<approved-name>' AND status = 'pending';
  COMMIT;

  -- Reject the rest
  UPDATE category_suggestions
  SET status = 'rejected', reviewed_at = datetime('now'), reviewed_by = 'operator'
  WHERE status = 'pending';
  ```

- [ ] **Alternative**: if you do not want a `category_suggestions` workflow, just leave the table empty. The `prompts` row is already correctly downgraded to `"other"`. The audit trail is the only thing missing.

## Hand Off To The Next Skill

- [ ] Trigger `score_prompts` (e.g. via the Agent: "给刚提取的 prompt 打分") so the new `prompts` rows get `quality_scores` populated. The `score_prompts` skill selects `WHERE quality_scores IS NULL AND prompt_text IS NOT NULL` (see `docs/11_ToolInterface.md` §3).
- [ ] Keep the first production run's `tweet_id` list around. When triaging noisy LLM extractions, you can `JOIN` against the Apify run page to see what the LLM was looking at.

## Escalation

| Symptom | Likely cause | Action |
|---|---|---|
| `错误: ... google.genai ... DefaultCredentialsError` | Vertex AI auth not set. | Run `gcloud auth application-default login` or set `GOOGLE_APPLICATION_CREDENTIALS`. |
| `错误: ... 429 ... RESOURCE_EXHAUSTED` | Vertex AI rate limit hit. | Wait 60s and retry with smaller `--batch`. The skill has no built-in retry on the batch path. |
| `错误: ... 403 ... PERMISSION_DENIED` | Service account lacks `aiplatform.endpoints.predict` permission. | Grant the role `roles/aiplatform.user` (or `roles/aiplatform.endpoints.predictUser`) on the project. |
| `错误: ... NotFound ... model gemini-3.5-flash` | The model is not enabled in the project / region. | Enable the Gemini API in the GCP console, or override `default_model` to a model that is available. |
| All rows skipped (S = N) | The LLM said `is_prompt=false` for every candidate. | This is *expected* if the candidates are "veo is great" hype tweets. Inspect a few to confirm. |
| All extracted prompts land as `category="other"` | `categories` table is empty (current state). | Either seed it (see Initialize section above) or accept the downgrade. |
| `category_suggestions` stays at 0 rows | Drift — see `SKILL.md` Handoff Notes #4. | Expected for now. Implement the proposed fix if you need the audit trail. |
| After running, `prompts.image_status` is `'pending'` for rows that already had an image | `INSERT OR REPLACE` resets the column. | Re-run `generate_images` on those specific rows, or skip the `INSERT OR REPLACE` for already-published rows. |
| Wrapper exits with code `2` | Project root mis-located. | Pass `--project-root <absolute-path-to-16_NewCrawler>`. |
| `错误: sqlite3.OperationalError: no such table: tweets` | DB not initialized. | Run `python -m src.main init-db` first. |
| `错误: sqlite3.OperationalError: database is locked` | Two skill instances writing at once. | The DB has `check_same_thread=False` but SQLite serializes writes. Run one skill at a time, or migrate to a real DBMS. |

## V3.3 Migration Checklist

When the project migrates to the V3.3 single-table architecture (see `docs/11_ToolInterface.md` "V3.3 目标版"):

- [ ] `tweets` and `prompts` collapse into a single `prompts` table with `has_raw_tweet`, `has_prompt`, `has_cover_image` boolean flags.
- [ ] The `tweets UPDATE` portion of this skill becomes a no-op (or a flag-flip on the `prompts` row).
- [ ] The `prompts INSERT` becomes a `UPDATE prompts SET prompt_text=?, category=?, title=?, notes=?, has_prompt=1, image_status='pending' WHERE tweet_id=?`.
- [ ] The `WHERE prompt_text IS NULL` selector becomes `WHERE has_raw_tweet=1 AND has_prompt=0`.
- [ ] The `category_suggestions` drift should be resolved during the migration (either fix the INSERT or remove the table).
- [ ] `image_status` column may be renamed to `has_cover_image` (boolean).
- [ ] Re-run the full smoke test against the new schema.
