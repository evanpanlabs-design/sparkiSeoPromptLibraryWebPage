# Database Schema — `prompt_embeddings` & `prompts.embedding_*`

This skill reads two embedding storage sites and one status column. **Only one
of the storage sites is actually populated by the current code path.** See
Handoff Notes in `SKILL.md` for the full drift list.

---

## `prompt_embeddings` (side table — *the one that is actually read*)

Created in `_migrate_v3_tables()` at `src/memory/schema.py:220-233`.

| Column        | Type      | Constraint                       | Notes |
|---------------|-----------|----------------------------------|-------|
| `id`          | INTEGER   | PRIMARY KEY AUTOINCREMENT        | local surrogate |
| `prompt_id`   | INTEGER   | NOT NULL, FK → `prompts(id)`     | indexed via `idx_prompt_emb_prompt_id` |
| `embedding`   | BLOB      | NOT NULL                         | stored as **JSON-encoded UTF-8 bytes** (e.g. `[0.012, -0.034, ...]`) — not raw float32. See drift #4. |
| `model`       | TEXT      | NOT NULL                         | embedding model name, e.g. `gemini-embedding-2` |
| `created_at`  | TEXT      | NOT NULL                         | ISO 8601 UTC |

```sql
CREATE TABLE IF NOT EXISTS prompt_embeddings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id  INTEGER NOT NULL REFERENCES prompts(id),
    embedding  BLOB NOT NULL,
    model      TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prompt_emb_prompt_id
    ON prompt_embeddings(prompt_id);
```

### How rows get in

`src/agent/memory/embedding.py:108-148` → `embed_pending_prompts(conn)`. This
function is **not exposed as a V3.2 tool** — call it manually from a Python
REPL. See `handoff_checklist.md` for the snippet.

### How rows get out

`src/agent/memory/embedding.py:61-105` → `search_prompts(conn, query, top_k)`:

```sql
SELECT pe.prompt_id, pe.embedding, p.title, p.prompt_text,
       p.quality_scores, p.image_status
FROM prompt_embeddings pe
JOIN prompts p ON p.id = pe.prompt_id
```

The deserializer handles both shapes:

```python
if isinstance(raw_emb, bytes):
    stored_vec = json.loads(raw_emb.decode("utf-8"))
else:
    stored_vec = json.loads(raw_emb)
```

---

## `prompts.embedding_vector` (column on the main table — *not actually used*)

Defined at `src/memory/schema.py:97` as part of the `prompts` table CREATE
statement (it has no separate migration):

```sql
embedding_vector  BLOB,
```

**No code path in the V3.2 codebase writes to this column.** The constant in
`src/agent/memory/embedding.py:137` updates `embedding_status = 'embedded'`
but not `embedding_vector = ?`. Therefore:

```sql
SELECT id, embedding_vector FROM prompts;   -- every row returns NULL
```

The wiki (`docs/11_ToolInterface.md` §9) implies that this column is the
search target. **It is not.** The wiki's "JOIN `prompts`" should be read as
"join for display fields only — the vector lives in `prompt_embeddings`."

V3.3 migration target: this column is **not** in the V3.3 column list, so
it will be dropped on the V3.2 → V3.3 migration. Confirm before then.

---

## `prompts.embedding_status` (column on the main table)

Added in `_migrate_v3_prompts_cols()` at `src/memory/schema.py:258-264`:

```sql
ALTER TABLE prompts ADD COLUMN embedding_status TEXT DEFAULT 'pending'
    CHECK (embedding_status IN ('pending','embedded','failed'))
```

State machine (set by `embed_pending_prompts()` in `embedding.py:121-145`):

| Value       | Set when |
|-------------|----------|
| `pending`   | row was inserted by `extract_prompts`, no embedding attempted yet |
| `embedded`  | `embed_text()` returned a vector and an `INSERT INTO prompt_embeddings` succeeded |
| `failed`    | `embed_text()` raised an exception; row is **not** in `prompt_embeddings` |

The `tool_search_prompts` SQL does **not** filter on `embedding_status` —
it only JOINs on `prompts.id = pe.prompt_id`. So `embedding_status='failed'`
rows are correctly absent from the result set (because their
`prompt_embeddings` row is missing), and `embedding_status='pending'` rows
are also absent (same reason). The status column is therefore purely a
diagnostic / backfill-queue indicator today.

---

## Quick verification

```bash
# Schema
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); \
  print('prompt_embeddings:', [r for r in c.execute('PRAGMA table_info(prompt_embeddings)').fetchall()]); \
  print('prompts.embedding*:', [r for r in c.execute('PRAGMA table_info(prompts)').fetchall() if 'embed' in r[1]])"

# Counts
python -c "import sqlite3; c=sqlite3.connect('data/veo_prompts.db'); \
  print('prompt_embeddings rows:', c.execute('SELECT COUNT(*) FROM prompt_embeddings').fetchone()[0]); \
  print('prompts.embedding_status=embedded:', c.execute(\"SELECT COUNT(*) FROM prompts WHERE embedding_status='embedded'\").fetchone()[0]); \
  print('prompts.embedding_status=pending :', c.execute(\"SELECT COUNT(*) FROM prompts WHERE embedding_status='pending'\").fetchone()[0])"
```
