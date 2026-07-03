# Handoff Checklist — `search-prompts`

A copy-pasteable runbook to install, configure, smoke-test, and backfill the
semantic search skill on a fresh machine.

---

## 1. Install

```bash
# From the 16_NewCrawler project root
pip install -r requirements.txt
pip install google-genai    # required by src/agent/memory/embedding.py
pip install python-dotenv   # optional — for loading .env in the wrapper
```

`google-genai` is the only hard requirement for the embedding module.
`python-dotenv` is optional; the wrapper falls through to reading shell
env vars if it is not installed.

---

## 2. Configure

### 2a. Vertex AI auth (required)

Pick **one**:

```bash
# Option 1: service-account JSON
export GOOGLE_APPLICATION_CREDENTIALS="/abs/path/to/service-account.json"

# Option 2: gcloud user credentials
gcloud auth application-default login
```

The lazy client in `src/agent/memory/embedding.py:28-34` reads
`GOOGLE_APPLICATION_CREDENTIALS` at first call.

### 2b. Project / Location (already set)

`src/agent/memory/embedding.py:15-25` reads `configs/llm.yaml`:

```yaml
llm:
  gemini:
    project: "sparki-op"
    location: "global"
```

If you fork to a different GCP project, edit this YAML.

### 2c. Embedding model (drift — no config file)

The model is hard-coded in `src/agent/memory/embedding.py:12`:

```python
EMBEDDING_MODEL = "gemini-embedding-2"
```

`configs/agent.yaml` is **referenced** in `CLAUDE.md` and
`docs/11_ToolInterface.md` §9, but **does not exist on disk** (verified by
`ls configs/`). To make it config-driven, create `configs/agent.yaml` and
add a reader; or just edit the constant.

### 2d. `.env.example` (recommended)

```bash
# .env
GOOGLE_APPLICATION_CREDENTIALS=/abs/path/to/sa.json
```

The wrapper calls `load_dotenv(root / ".env")` if `python-dotenv` is
installed; otherwise it relies on the shell.

---

## 3. Smoke test

### 3a. Wrapper `--help`

```bash
python skills/search-prompts/scripts/search_prompts.py --help
echo "exit=$?"   # expect 0
```

### 3b. Bad project root (verify error handling)

```bash
python skills/search-prompts/scripts/search_prompts.py --project-root /nonexistent
echo "exit=$?"   # expect 2
```

### 3c. Dry-run (no API call, just shape)

```bash
python skills/search-prompts/scripts/search_prompts.py \
  --query "cinematic drone shot" --dry-run
echo "exit=$?"   # expect 0
```

Expected: prints the payload, DB path, `prompt_embeddings` row count, and
`prompts.embedding_status` counts. **No embedding API call is made.**

### 3d. Real call (likely returns stub today)

```bash
python skills/search-prompts/scripts/search_prompts.py \
  --query "cinematic drone shot"
echo "exit=$?"
```

Likely outcomes:
- `1` + `Embedding搜索暂不可用（等待Code-4实现），请稍后再试。`
  → embedding module failed to import. See step 4.
- `1` + `未找到相关Prompt（关键词: cinematic drone shot）`
  → import succeeded but `prompt_embeddings` is empty. See step 5.
- `0` + `找到 N 条相关Prompt（按相关性排序）: ...`
  → success. Requires both an importable module *and* a backfilled DB.

---

## 4. Diagnose the "stub" state

If step 3d returns the stub message, isolate where the import fails:

```bash
# 1. Can the module be imported at all?
python -c "from src.agent.memory.embedding import search_prompts; print('ok')"
```

If this raises, common causes:

| Error | Fix |
|---|---|
| `ModuleNotFoundError: google.genai` | `pip install google-genai` |
| `ModuleNotFoundError: yaml` | `pip install pyyaml` (used by `_load_gemini_config`) |
| `DefaultCredentialsError` | `gcloud auth application-default login` |
| `AttributeError: ... has no attribute 'embeddings'` | Stale `__pycache__` — `rm -rf src/agent/memory/__pycache__` |

```bash
# 2. Can the client be constructed?
python -c "from src.agent.memory.embedding import _get_embed_client; print(_get_embed_client())"
```

```bash
# 3. Can a single embedding be generated?
python -c "from src.agent.memory.embedding import embed_text; print(len(embed_text('hello world')))"
```

If step 3 returns a vector dimension, the import path is healthy — the
stub must be coming from something else (e.g. transient Vertex AI outage
during a concurrent call). Re-run step 3d.

---

## 5. Backfill the `prompt_embeddings` table

This is the missing piece of the V3.2 pipeline. There is **no tool wrapper**
for `embed_pending_prompts()` — you have to call it manually.

### 5a. Confirm the schema is ready

```bash
python -m src.main init-db
```

This creates `prompt_embeddings` and the `prompts.embedding_status` column
on first run. Idempotent — safe to re-run.

### 5b. Confirm the target rows

```bash
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); \
  print('pending rows:', c.execute(\"SELECT COUNT(*) FROM prompts WHERE embedding_status='pending'\").fetchone()[0])"
```

### 5c. Run the backfill

```bash
python -c "
from src.memory.schema import _conn
from src.agent.memory.embedding import embed_pending_prompts

conn = _conn()
n = embed_pending_prompts(conn)
print(f'embedded {n} prompts')
"
```

Notes:
- The function is **sequential** (no `concurrency=` kwarg). For 100+ rows
  expect several minutes.
- The function commits at the end (`embedding.py:147`). On a per-row
  failure it sets `embedding_status='failed'` and continues.
- Vertex AI 429s will surface as `failed` rows; re-run after waiting.

### 5d. Re-run the real call

```bash
python skills/search-prompts/scripts/search_prompts.py \
  --query "cinematic drone shot" --top-k 5
echo "exit=$?"   # expect 0
```

### 5e. (Optional) Re-embed after a model change

```bash
# Wipe the old vectors
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); \
  c.execute('DELETE FROM prompt_embeddings'); \
  c.execute(\"UPDATE prompts SET embedding_status='pending'\"); \
  c.commit(); print('cleared')"

# Edit src/agent/memory/embedding.py:12 to the new model
# Re-run step 5c
```

---

## 6. Verify a known-good result

Pick a query and confirm the top-1 row makes sense:

```bash
python skills/search-prompts/scripts/search_prompts.py \
  --query "neon city at night" --top-k 3 --min-score 0.0
```

If the top result is obviously unrelated (e.g. a "fitness app demo"
prompt ranked above a "neon city" prompt), the most likely cause is
that `task_type` should be `RETRIEVAL_QUERY` for the query path —
see `embedding_model.md` and Handoff Notes "Other things to know"
in `SKILL.md`.

---

## 7. (Future) Add a `tool_embed_pending_prompts` to V3.2

To stop relying on the manual REPL, register a new tool in
`src/agent/skills/core_tools.py` and add a keyword trigger in
`src/agent/nodes/plan_node.py`. Sketch:

```python
def tool_embed_pending_prompts(args: dict) -> str:
    from src.memory.schema import _conn
    from src.agent.memory.embedding import embed_pending_prompts
    conn = _conn()
    batch = args.get("batch", 50)
    # Note: the current `embed_pending_prompts(conn)` has no batch limit;
    # wrap with a SELECT ... LIMIT batch if needed.
    n = embed_pending_prompts(conn)
    return f"嵌入完成: {n} 条 prompt 已生成 embedding"
```

After adding, update the `extract-prompts → score-prompts` pipeline to
chain an `embed_pending_prompts` step between scoring and search (or
before `generate_images`, since both can run in parallel).
