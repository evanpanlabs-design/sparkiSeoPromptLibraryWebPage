---
name: search-prompts
description: Semantic search over extracted Veo prompts using Gemini embeddings. Embeds the user's natural-language query and returns the top-k most similar prompts from the `prompt_embeddings` table, joined with `prompts` for display. Use when the operator wants to find prompts by meaning (e.g. "cinematic drone shot", "cozy rainy cafe interior", "neon city at night") instead of by category or keyword, after prompts have been scored, and when the `prompt_embeddings` table is populated. Do NOT use for exact-match keyword search, for unscored prompts, or before backfilling embeddings — and be aware that the underlying embedding module is currently a stub: until Code-4 ships the real `search_prompts` implementation, the tool returns the placeholder string "Embedding搜索暂不可用（等待Code-4实现），请稍后再试。" rather than actual results.
---

# Search Prompts (V3.2 — Semantic Search)

## What It Does

Embeds a natural-language query with the Gemini embeddings API, then loads every row of the `prompt_embeddings` table, computes cosine similarity against the query vector, and returns the top-k matches joined with their `prompts` row.

The current code at `src/agent/memory/embedding.py` (`search_prompts`) is **fully implemented** (lines 61-105) — it calls `embed_text()`, fetches all rows from `prompt_embeddings JOIN prompts`, and sorts by `cosine_similarity`. However, the *wrapper* at `src/agent/skills/core_tools.py:465-518` (`tool_search_prompts`) wraps the import in `try/except (ImportError, AttributeError)` (line 513). On a fresh checkout where the embedding module fails to import (missing `google-genai`, missing `GOOGLE_APPLICATION_CREDENTIALS`, transient Vertex AI outage during the lazy client init, or a real regression), the wrapper short-circuits to the **stub message**:

```
Embedding搜索暂不可用（等待Code-4实现），请稍后再试。
```

When that stub is returned, the CLI wrapper below exits with code `1` so the operator can distinguish "no results" from "feature unavailable".

This skill does **not** generate embeddings in bulk, score prompts, or extract prompts — those are `embed_pending_prompts` (in `embedding.py:108`, not exposed as a V3.2 tool), `score_prompts`, and `extract_prompts` respectively.

## When To Use

- Run **after** `extract_prompts` has populated the `prompts` table **and** the `prompt_embeddings` table is non-empty.
- Use when the user says: "搜索 prompt", "找一下 …", "我想要 cinematic drone shot 类的 prompt", or invokes the ReAct agent's `tool_search_prompts` skill.
- Use for content-ops retrieval — "which of my prompts best matches a new brief?" — not for system monitoring (use `pool_status`).

## When NOT To Use

- For exact keyword / category filtering → query `prompts` directly with SQL, or use `pool_status`.
- For unscored prompts — embedding similarity is still meaningful, but `min_score` filtering on `quality_scores` is irrelevant.
- Before backfilling embeddings — `prompt_embeddings` rows are produced by `embedding.embed_pending_prompts(conn)`, which is **not** wired into any V3.2 tool yet. See `references/handoff_checklist.md` for the manual backfill script.
- For batch reranking of the whole library — `search_prompts()` reads every embedding row on each call. With >10k prompts this becomes O(N) per query; switch to a vector index then.

## Required Context

- Project root: `16_NewCrawler`
- Tool implementation: `src/agent/skills/core_tools.py:465-518` (`tool_search_prompts`)
- Embedding module: `src/agent/memory/embedding.py:61-105` (`search_prompts`), `:108-148` (`embed_pending_prompts`)
- Schema: `src/memory/schema.py:80-100` (prompts table incl. `embedding_vector`, `embedding_status`), `:220-233` (prompt_embeddings table)
- Wiki contract: `docs/11_ToolInterface.md` §9 (search_prompts)
- V3.3 migration target: `prompts` collapses to a single table with `has_raw_tweet`, `has_prompt`, `has_cover_image` flags — the `prompt_embeddings` table may be merged in or kept as a side table. See Handoff Notes.

## Preconditions

1. **Database initialized**: `python -m src.main init-db` — creates `prompts`, `prompt_embeddings`, and the `prompts.embedding_status` / `prompts.embedding_vector` columns.
2. **Vertex AI auth**: `_get_embed_client()` calls `genai.Client(vertexai=True, project="sparki-op", location="global")` (singleton at `embedding.py:28-34`). Set `GOOGLE_APPLICATION_CREDENTIALS` or `gcloud auth application-default login`.
3. **Embedding model `gemini-embedding-2`** is the constant in `embedding.py:12` — there is no `configs/agent.yaml` (the file is referenced in `CLAUDE.md` and the wiki, but **does not exist on disk**). See Handoff Notes for the drift.
4. **`prompts.embedding_status = 'embedded'`** for rows you expect to retrieve, **or** `prompt_embeddings` rows for that `prompt_id` must exist. The `tool_search_prompts` SQL JOINs `prompt_embeddings` to `prompts` — prompts with no embedding row are invisible to the search.
5. **`google-genai` SDK installed** (`pip install google-genai`). The `try/except (ImportError, AttributeError)` in `tool_search_prompts` will return the stub message if the import fails.

## Inputs

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `query` | `str` | `""` (treated as no-op by the underlying `search_prompts`) | Natural-language search string. Required for a useful result. |
| `top_k` | `int` | `5` | Number of top-similarity results to return. |
| `min_score` | `float` | `None` | Cosine-similarity floor (0-1). Rows below the floor are dropped by the wrapper, not by `search_prompts`. |

The CLI wrapper (`scripts/search_prompts.py`) additionally accepts `--project-root` and `--dry-run` (see Validation below).

## Outputs

- **Success string** (printed to stdout, in Chinese):
  ```
  找到 N 条相关Prompt（按相关性排序）:
    1. [0.68] {prompt_text 前200字符截断}...
    2. [0.61] {prompt_text}...
    ...
  ```
  Truncation tries newline boundaries first, then word boundaries, then a 200-char hard cut (`core_tools.py:486-510`).

- **Empty-result string**:
  ```
  未找到相关Prompt（关键词: {query}）
  ```
  Returned when `_search()` returns `[]` — e.g. the `prompt_embeddings` table is empty.

- **Stub-state string** (the one this skill is most likely to return today):
  ```
  Embedding搜索暂不可用（等待Code-4实现），请稍后再试。
  ```
  Returned when `from src.agent.memory.embedding import search_prompts` raises `ImportError` or `AttributeError`. The CLI wrapper translates this to **exit code 1**.

- **Generic failure string**:
  ```
  错误: {ExceptionType}: {message}
  ```
  Returned by the outermost `except Exception` (line 516-517). Exit code 1.

- **No side effects** on the database — the tool is read-only.

## Data Contract

The skill reads two tables.

### `prompt_embeddings` — JOIN target

| Field | Source | Notes |
|---|---|---|
| `id` | `INTEGER PK AUTOINCREMENT` | local surrogate |
| `prompt_id` | FK → `prompts.id` | indexed via `idx_prompt_emb_prompt_id` |
| `embedding` | `BLOB NOT NULL` | **stored as JSON-encoded UTF-8 bytes** today (see drift note in `embedding.py:88-93` — `json.loads(raw_emb.decode("utf-8"))` is the deserializer). The wiki says BLOB; the code stores it as TEXT-as-JSON. |
| `model` | `TEXT NOT NULL` | e.g. `gemini-embedding-2` |
| `created_at` | `TEXT NOT NULL` | ISO 8601 UTC |

### `prompts` — display fields

| Field | Source | Notes |
|---|---|---|
| `id` | `INTEGER PK` | joined on `prompts.id = pe.prompt_id` |
| `title` | `TEXT NOT NULL` | from extract_prompts |
| `prompt_text` | `TEXT NOT NULL` | the actual prompt |
| `quality_scores` | `TEXT` | CSV `spec,vis,nov,gen,overall` — not used in display |
| `image_status` | `TEXT` | not used in display |
| `embedding_vector` | `BLOB` | **separate** copy of the embedding on the `prompts` row, *not* the same column as `prompt_embeddings.embedding`. **Not read by the tool** — the wiki is misleading here. See Handoff Notes. |
| `embedding_status` | `TEXT DEFAULT 'pending'` | `'pending' \| 'embedded' \| 'failed'`. Set by `embed_pending_prompts` after a successful vector store. |

## Procedure

1. **Open DB connection** via `src.memory.schema._conn()`.
2. **Lazy-init Vertex AI client** via `_get_embed_client()` (singleton). On failure, the import in the wrapper raises and we hit the stub branch.
3. **Embed the query**: `query_vec = embed_text(query)` (calls `client.models.embed_content(model="gemini-embedding-2", contents=[query], config=EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"))`).
4. **Fetch all rows**:
   ```sql
   SELECT pe.prompt_id, pe.embedding, p.title, p.prompt_text,
          p.quality_scores, p.image_status
   FROM prompt_embeddings pe
   JOIN prompts p ON p.id = pe.prompt_id
   ```
5. **Decode each row's `embedding`** with `json.loads()` (handles both `bytes` and `str` for safety).
6. **Score** with `cosine_similarity(query_vec, stored_vec)`.
7. **Sort descending by score** and slice `[:top_k]`.
8. **Format in the wrapper** (not the embedding module): apply `min_score` filter, truncate each `prompt_text` to 200 chars, prepend the count header.

## Validation

```bash
# 1. --help must exit 0
python skills/search-prompts/scripts/search_prompts.py --help
echo "exit=$?"   # expect 0

# 2. Bad project root
python skills/search-prompts/scripts/search_prompts.py --project-root /nonexistent
echo "exit=$?"   # expect 2

# 3. Real call (likely returns the stub message today)
python skills/search-prompts/scripts/search_prompts.py --query "cinematic drone shot"
echo "exit=$?"   # expect 1 if stub, 0 if results, 1 if "错误:" string

# 4. PRAGMA check
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); \
  print('prompt_embeddings:', [r for r in c.execute('PRAGMA table_info(prompt_embeddings)').fetchall()]); \
  print('prompts.embedding*:', [r for r in c.execute('PRAGMA table_info(prompts)').fetchall() if 'embed' in r[1]])"

# 5. Counts
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); \
  print('prompt_embeddings rows:', c.execute('SELECT COUNT(*) FROM prompt_embeddings').fetchone()[0]); \
  print('prompts.embedding_status=embedded:', c.execute(\"SELECT COUNT(*) FROM prompts WHERE embedding_status='embedded'\").fetchone()[0])"
```

The wrapper exits with code:
- `0` on a successful search (results returned) or on `--help` or on a successful `--dry-run`.
- `1` if the tool returned a stub message, an empty-result, or a `错误:` string.
- `2` if the project root cannot be located (`src/agent/skills/core_tools.py` missing).

## Failure Handling

| Symptom | Likely cause | Action |
|---|---|---|
| `Embedding搜索暂不可用（等待Code-4实现），请稍后再试。` | `from src.agent.memory.embedding import search_prompts` failed at import or attribute access. | `pip install google-genai`; check `GOOGLE_APPLICATION_CREDENTIALS`; confirm the `embedding.py` file is not shadowed by a `__pycache__` stale copy. Exit code 1. |
| `未找到相关Prompt（关键词: ...）` | `prompt_embeddings` is empty. | Run the backfill workflow in `references/handoff_checklist.md` (call `embedding.embed_pending_prompts(conn)` from a one-shot Python). |
| `错误: ... 429 ... RESOURCE_EXHAUSTED` | Vertex AI rate limit on the embedding model. | Wait 60s and retry. The skill has no built-in retry. |
| `错误: ValueError: ... math domain ...` | `norm_a` or `norm_b` is 0 (all-zero vector). | Reject the row upstream in the loader. Today the cosine function returns `0.0` for zero norms (`embedding.py:51-58`), so this should not happen. |
| `错误: ... AttributeError: 'bytes' object has no attribute 'read' ...` | Stale Python bytecode for `embedding.py` after a partial edit. | `find . -name __pycache__ -prune -exec rm -rf {} +` (or the Windows equivalent `del /s /q __pycache__`). |
| All-zero scores | Embedding was stored as a wrong-length vector (e.g. JSON truncation) or the query text was empty. | Confirm `len(query_vec) == len(stored_vec)`; both should be the model's native dim (3072 for `gemini-embedding-2` if it is the v3.0 model, 768 for older). |
| `错误: sqlite3.OperationalError: no such table: prompt_embeddings` | `init-db` was not run after the V3 migration that adds the table. | `python -m src.main init-db` — the table is created in `_migrate_v3_tables()`. |

## Handoff Notes

Five **verified** drift points between the project wiki, the current code, and the live database. **Prioritize the code as the source of truth.**

1. **`configs/agent.yaml` does not exist on disk.**
   - `CLAUDE.md` (Configuration table) and `docs/11_ToolInterface.md` §9 both list `configs/agent.yaml` as the place to configure the embedding model.
   - `ls configs/` returns: `crawler.yaml`, `engagement.yaml`, `gemini.yaml`, `llm.yaml`, `quality.yaml`, `queries.yaml`. **No `agent.yaml`.**
   - The actual model is hard-coded in `src/agent/memory/embedding.py:12` as `EMBEDDING_MODEL = "gemini-embedding-2"`. There is no environment override path.
   - **Implication for the next operator**: if you want a different embedding model, edit the constant (or add a `configs/agent.yaml` reader); the wrapper will not pick it up from anywhere else.

2. **The wrapper returns a stub message on `ImportError`/`AttributeError` — and the message still says "等待Code-4实现" even though the code is now in `embedding.py`.**
   - `src/agent/skills/core_tools.py:513-514`:
     ```python
     except (ImportError, AttributeError):
         return "Embedding搜索暂不可用（等待Code-4实现），请稍后再试。"
     ```
   - `embedding.py` does have a real `search_prompts` (line 61) and `embed_pending_prompts` (line 108). The "Code-4" string is a stale TODO.
   - **Implication**: when you do see the stub message, do not assume the module is unimplemented. Run `python -c "from src.agent.memory.embedding import search_prompts; print('ok')"` to distinguish "module missing" from "import side-effect failing".

3. **Two embedding storage sites; the tool only reads one.**
   - `prompts.embedding_vector` (BLOB, defined at `schema.py:97`) — populated by `embed_pending_prompts()` via `UPDATE prompts SET embedding_status = 'embedded' WHERE id = ?`. **The actual bytes live in `prompt_embeddings.embedding`, not on the `prompts` row.** The `prompts.embedding_vector` column is never written by the current code path.
   - `prompt_embeddings.embedding` (BLOB, defined at `schema.py:225`) — the column `search_prompts()` actually reads. Stored as JSON-encoded UTF-8 bytes (drift #4).
   - **Implication**: `SELECT p.embedding_vector FROM prompts` will return `NULL` for every row today, even when `embedding_status='embedded'`. The wiki's "JOIN `prompts`" is correct in the sense that `prompts` provides display fields, but the *vector* comes from the side table.

4. **The `embedding` column is stored as JSON-as-bytes, not as raw float32 BLOB.**
   - `embed_pending_prompts()` does `vec_json = json.dumps(vec)` and passes that to the `INSERT`. The column type is `BLOB` but the bytes are a UTF-8 JSON string.
   - `search_prompts()` deserializes with `json.loads(raw_emb.decode("utf-8"))` (line 91) or `json.loads(raw_emb)` for `str` (line 93).
   - This is 2-3x larger than a raw `numpy.float32` BLOB and slower to decode, but it is what the code does. A future migration could store the raw `struct.pack(f"{len(vec)}f", *vec)` bytes and skip the JSON round-trip.

5. **No V3.2 tool wraps `embed_pending_prompts()`.**
   - The function exists at `embedding.py:108-148` and the database columns (`prompts.embedding_status`, `prompt_embeddings.embedding`) are designed for it, but no `tool_embed_pending_prompts()` is registered in `core_tools.py` and no pipeline keyword triggers it.
   - **Implication for the next operator**: until somebody adds a tool, the only way to populate `prompt_embeddings` is a one-shot Python REPL:
     ```python
     from src.memory.schema import _conn
     from src.agent.memory.embedding import embed_pending_prompts
     conn = _conn()
     n = embed_pending_prompts(conn)
     print(f"embedded {n} prompts")
     ```
   - There is also no scheduled job — embeddings are computed only when an operator runs this manually.

### Other things the next operator should know

- **Live DB state at the time of writing** (will differ at your run time; verify with the PRAGMA commands in Validation):
  - `prompts` total: ~148 (from the extract-prompts skill's handoff).
  - `prompts.embedding_status` counts: all `pending` (no backfill has been run).
  - `prompt_embeddings` rows: `0`.
  - **Therefore every real call to this skill today will return the empty-result string or the stub message.** To get real results, run the backfill first.
- **The `cosine_similarity` function** (`embedding.py:51-58`) is a pure-Python loop. For 10k+ prompts it becomes a hot path; vectorize with `numpy` if you scale up.
- **The `search_prompts` query reads the full `prompt_embeddings` table on every call** (`embedding.py:74-81` — no `LIMIT` or `WHERE`). For a 100k-row library this is the bottleneck. Switch to a vector index (FAISS, sqlite-vss) before that scale.
- **V3.3 migration target** (per `docs/11_ToolInterface.md`): the V3.3 spec collapses `tweets` and `prompts` into a single `prompts` table with three flags (`has_raw_tweet`, `has_prompt`, `has_cover_image`). The `prompt_embeddings` table is *not* in the V3.3 collapse list, so it will likely remain a side table — but `prompts.embedding_vector` (drift #3) is not in the V3.3 column list either, so that column will be dropped. The `embedding_status` column is also not in the V3.3 list, so the backfill trigger will need to move to a different signal (e.g. a `prompts_embeddings` LEFT JOIN, or a `has_embedding` flag added to V3.3).
- **The `embed_text` call uses `task_type="RETRIEVAL_DOCUMENT"`** (line 45). For query embedding, the correct task type per Gemini docs is `"RETRIEVAL_QUERY"`. This is a *quality* drift: doc-side embeddings are tuned to be stored, query-side embeddings are tuned to match. Switching the task type in `embed_text` for the query path is a one-line fix; today both sides use the same function.
- **No retry / circuit-breaker on Vertex AI 429s.** The tool will surface the 429 as a `错误:` string; the wrapper exits 1. A future improvement would be a 3-retry loop with exponential backoff.
- **The wrapper's truncation logic** (`core_tools.py:486-510`) prefers newline → word boundary → 200-char hard cut. This is fine for English prompts but treats Chinese characters as a single unit per `len()` (which is code points, not display width). A 200-char Chinese truncation is roughly the right length.
- **The `from src.agent.memory.embedding import search_prompts as _search`** in the wrapper will be picked up by `__pycache__` even after edits. If you change `embedding.py` and the wrapper still returns the stub, `rm -rf src/agent/memory/__pycache__`.
