# Image Generation Reference

This document covers the model, style-keyword system, rate-limit policy,
retry policy, and the GCS vs local-storage decision for cover images.

## Models

The image client (`src/image_gen/client.py:20-24`) tries models in order. The
first one that returns a valid image wins.

| Model | Notes |
|---|---|
| `gemini-2.5-flash-image` | Default. Cheapest, fastest. Used by the summary line ("模型: gemini-2.5-flash-image" — see SKILL.md drift #1). |
| `gemini-3-pro-image-preview` | Fallback. Higher quality, slower, more 429-prone. |
| `gemini-3.1-flash-image-preview` | Newer fallback. Behavior under rate limits is not yet stable. |

To change the active list, edit `client.py:20-24`. `configs/gemini.yaml` lists
the same three under `image_models:`, but the YAML is **not read at runtime**
by `RateLimitSafeGenerator` — it is documentation only. The yaml's
`generation.concurrency=3` and `retry_delay_base=5` are also not honored by
the tool path (`RateLimitSafeGenerator` hard-codes `interval=2.0`,
`max_retries=3`, `retry_delay_base=2.0`). They are honored by the legacy
`GeminiImageClient.generate_batch` (the path the ReAct skill does not take).

## Style keywords

`src/image_gen/style.py:build_image_prompt()` takes the raw `prompt_text`, the
`category` string, and a `title` (which is now ignored — see
`generator.py:64` hard-codes `title=""`). It selects **3 random** keywords
from the category's bucket in `_DEFAULT_STYLE_KEYWORDS` (or `"other"` if the
category is unknown) and injects them into the prompt template:

```
Generate a cover image for the following AI generation prompt.
The cover should visually represent this prompt in a compelling, marketable way.

IMPORTANT: Center the main subject/content in the middle of the image.
Do NOT place important elements near the top or bottom edges.
DO NOT include any text, words, numbers, labels, or watermarks in the image.
Style keywords: {3 random from category}

Prompt text: {prompt_text}
```

The 16 category buckets live in `style.py:48-211` (`cinematic-scene`,
`sci-fi-fantasy`, `product-showcase`, …). The `prompts.category` values
written by `extract_prompts` are LLM-suggested labels, and they are NOT in
this fixed list (the categories table is currently empty in the live DB —
see `extract-prompts` skill drift #4). When the category is not in the dict,
the generator falls back to the `"other"` bucket (4 generic keywords).

`configs/gemini.yaml:style:` lists a different set of category → keywords
mappings. That config is also not read at runtime.

## Rate-limit policy

`RateLimitSafeGenerator` (`src/image_gen/generator.py:15-119`):

- **Per-thread interval**: every `generate()` call sleeps `interval` seconds
  (default `2.0`) before firing. With `max_workers=3`, this gives roughly
  1 request / 0.67s of wall-clock.
- **Per-thread retry on 429**: `max_retries=3` (default), `retry_delay_base=2.0`
  → delays of `2s, 4s, 8s` between retries.
- **Exhaustion**: after 3 retries, the per-row result is `{gcs_url: None,
  error: <last exception>, model_used: None}`. The tool then UPDATEs
  `image_status='failed'`.

`GeminiImageClient` (`src/image_gen/client.py:48-93`):

- **Per-model retry**: `max_retries_per_model=3`, `retry_delay_base=5` →
  delays of `~5-8s, ~10-13s, ~15-18s` (adds `random.uniform(0, 3)` jitter).
- **Model fallback**: when retries on model N are exhausted, the client
  moves to model N+1 (with a `retry_delay_base + uniform(0, 5)` cooldown).
- **Hard fail**: when all 3 models exhaust, the client raises
  `ImageGenError(f"All models exhausted: {last_error}")` (`client.py:93`).
  The generator catches it, writes the error message into the result, and
  marks the row failed.

## GCS vs local storage (V3.2 vs V3.3)

**V3.2 (today)**: every successful generation is uploaded to GCS bucket
`sparki-op-test` at path `prompts/{category}/{yyyy-mm}/{tweet_id}.png`. The
GCS URL is stored in `prompts.image_gcs_url` (a `TEXT` column). A separate
`tool_sync_images` skill copies GCS → `outputs/images/{cat}/{yyyy-mm}/` and
`outputs/generated_images/` for `build_html` to reference.

**V3.3 (target)**: the image is written directly to
`outputs/generated_images/{id}.png` and the path is stored in a new
`prompts.image_local_path` column. `sync_images` is removed. The GCS bucket
becomes optional (archive only).

The migration is a pending PR. See `docs/11_ToolInterface.md` §"V3.3 目标版"
and SKILL.md drift #2 for the field-by-field mapping.

## Decision: which path to run on

- **Run the V3.2 GCS path** if `image_gcs_url` is the source of truth for
  `build_html` and you do not want to touch the V3.3 schema migration.
- **Run the V3.3 local path** if you have applied the `image_local_path`
  column migration AND `build_html` reads from `outputs/generated_images/`.
  Today this is a no-op (the column does not exist).

## Re-running failed rows

`tool_retry_failed(args: dict)` (`core_tools.py:615+`) is the dedicated
recovery path:

1. SELECT `image_status='failed' LIMIT batch`.
2. UPDATE → `image_status='pending'`.
3. For each row, call the same `RateLimitSafeGenerator.generate_batch`.
4. UPDATE → `'done'` / `'failed'` per the result.

Pair it with `--max-workers 1` and `--batch 1` to ride out a Vertex AI rate
storm. The wrapper is at `scripts/...` (one-shot if it ever ships).
