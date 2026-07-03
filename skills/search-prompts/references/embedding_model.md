# Embedding Model — Gemini `gemini-embedding-2`

> **Source of truth**: the constant lives in
> `src/agent/memory/embedding.py:12` — `EMBEDDING_MODEL = "gemini-embedding-2"`.
> It is **not** in any YAML config. See the Handoff Notes in `SKILL.md`
> for the `configs/agent.yaml` drift.

---

## Model identity

| Field | Value |
|---|---|
| Model name (constant) | `gemini-embedding-2` |
| Provider | Google Vertex AI (not the public Gemini API) |
| Project | `sparki-op` (from `configs/llm.yaml:11`) |
| Location | `global` (from `configs/llm.yaml:12`) |
| Task type used | `RETRIEVAL_DOCUMENT` (see drift note below) |
| Auth | Vertex AI ADC: `GOOGLE_APPLICATION_CREDENTIALS` env var **or** `gcloud auth application-default login` |

> If the model string is wrong, Gemini will return `404 NOT_FOUND` with a
> `ListModels` hint listing the actual model id (e.g. `text-embedding-005`,
> `gemini-embedding-exp-03-07`, `embedding-001`). Replace the constant
> accordingly.

---

## Where it is configured

**It is not.** The literal string `gemini-embedding-2` is hard-coded in
`embedding.py:12`. To change it:

1. Edit `src/agent/memory/embedding.py:12` directly. **All callers go
   through this constant** — `embed_text`, `embed_pending_prompts`, and
   `search_prompts` all import the module-level name.
2. If you want config-driven selection, add a `configs/agent.yaml` reader
   that loads `embedding.model` and bind it to a module attribute at
   import time. (Do this once the `configs/agent.yaml` file actually
   exists; today `CLAUDE.md` lists it but it does not exist on disk.)

There is no environment-variable override path. `EMBEDDING_MODEL` is a
module-level constant, not a function argument.

---

## How the embedding is generated

```python
# src/agent/memory/embedding.py:37-48
def embed_text(text: str) -> list[float]:
    from google.genai.types import EmbedContentConfig
    client = _get_embed_client()
    resp = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=[text],
        config=EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
    )
    return resp.embeddings[0].values
```

| Step | Notes |
|---|---|
| `_get_embed_client()` | Lazy-init singleton, line 28-34. Calls `genai.Client(vertexai=True, project="sparki-op", location="global")`. Cached for the process lifetime. |
| `client.models.embed_content(...)` | Vertex AI SDK call. One text per request (no batching). |
| `task_type` | Hard-coded to `RETRIEVAL_DOCUMENT`. **Drift**: the *query* side (search) should use `RETRIEVAL_QUERY` per Gemini docs, but `embed_text` is shared between the two. Switching it is a one-line change but it changes the geometry — re-embed everything after. |
| `resp.embeddings[0].values` | New SDK format (post-`google-generativeai` rename to `google-genai`). Older code uses `resp.results[0].values` — that path will raise `AttributeError` and trigger the stub message in the wrapper. |

---

## Output shape

- A Python `list[float]`. Length depends on the model:
  - `gemini-embedding-2` (if it is the successor to `text-embedding-005`): expected **768** or **3072** floats.
  - Verify with: `python -c "from src.agent.memory.embedding import embed_text; print(len(embed_text('hello')))"`.

- Stored in `prompt_embeddings.embedding` as a **JSON-encoded UTF-8 byte
  string** (not raw float32 BLOB). See `database_schema.md` and Handoff
  Notes drift #4 in `SKILL.md`.

---

## How to backfill embeddings

`embed_pending_prompts()` is the only function that writes embeddings, and
it is **not** exposed as a V3.2 tool. Manual backfill:

```python
# From project root, in a Python REPL
from src.memory.schema import _conn
from src.agent.memory.embedding import embed_pending_prompts

conn = _conn()
n = embed_pending_prompts(conn)
print(f"embedded {n} prompts")
```

Side effects per row:
- `INSERT INTO prompt_embeddings (prompt_id, embedding, model, created_at) VALUES (?, ?, ?, ?)`
- `UPDATE prompts SET embedding_status = 'embedded' WHERE id = ?`

If `embed_text()` raises, the row's `embedding_status` is set to `'failed'`
instead, and no `prompt_embeddings` row is written. The function
continues to the next prompt — there is no batch-level retry.

---

## Smoke test

```bash
# Confirm the model name is reachable
python -c "
from src.agent.memory.embedding import _get_embed_client, EMBEDDING_MODEL
c = _get_embed_client()
print('client:', c)
print('model:', EMBEDDING_MODEL)
resp = c.models.embed_content(model=EMBEDDING_MODEL, contents=['hello world'])
print('dim:', len(resp.embeddings[0].values))
"
```

Expected: prints `client: <google.genai.client.Client object>`, the model
name, and the vector dimension. If the model id is wrong, the call
returns `404 NOT_FOUND` and the SDK raises.

---

## Switching models (operational runbook)

1. **Pick a new model** (e.g. `text-embedding-005`, `gemini-embedding-exp-03-07`).
2. **Edit the constant** in `embedding.py:12`.
3. **Drop the old vectors**:
   ```sql
   DELETE FROM prompt_embeddings;
   UPDATE prompts SET embedding_status = 'pending';
   ```
4. **Re-run the backfill** (snippet above).
5. **Update the wiki** at `docs/11_ToolInterface.md` §9 if the new model
   changes the dim or the task type.
