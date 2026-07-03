# Scoring Prompts (LLM System Prompts)

The `score_prompts` skill uses **one** LLM system prompt — defined inline in `src/worker/scorer.py`. There is no recheck / repair pass (unlike `extract_prompts`); scoring is single-shot with a deterministic all-zeros fallback on parse failure.

---

## 1. `SCORING_SYSTEM_PROMPT` (the only prompt)

**File:** `src/worker/scorer.py:56-69`
**Used in:** `QualityScorer._call_llm()` — invoked from `QualityScorer.score()` at line 102
**Model:** `gemini-3.5-flash` (default at `scorer.py:79`; the tool wrapper does not override it, see `core_tools.py:309`)
**Purpose:** Score a single prompt across 4 dimensions, JSON-only response.

**Full text (verbatim, line refs preserved):**

```python
# scorer.py:56-69
SCORING_SYSTEM_PROMPT = (
    "You are a prompt quality evaluator for AI VIDEO and IMAGE generation.\n"
    "Given a prompt, score it across 4 dimensions. Each score must be 0.0–1.0.\n\n"
    "Dimensions:\n"
    "  specificity:    Detail level of visual description (0.0=generic, 1.0=highly specific)\n"
    "  visual_detail:  Presence of camera, lighting, composition, style terms (0.0=none, 1.0=rich)\n"
    "  novelty:        Uniqueness/rarity of the prompt structure or subject (0.0=common, 1.0=unique)\n"
    "  generatable:    Can this directly drive Veo/Gemini generation? (0.0=unusable, 1.0=ready)\n\n"
    "Only score based on the PROMPT TEXT itself, not on engagement or author.\n"
    "Be strict: 0.5 means average, 0.8+ means excellent, 0.3 or below means weak.\n\n"
    'Respond with valid JSON only: '
    '{"specificity": 0.0-1.0, "visual_detail": 0.0-1.0, '
    '"novelty": 0.0-1.0, "generatable": 0.0-1.0}'
)
```

**User prompt injected** (`scorer.py:92`):

```python
prompt=f"Prompt to score:\n{prompt_text}"
```

So a full LLM call looks like:

```
SYSTEM:  <SCORING_SYSTEM_PROMPT>
USER:    Prompt to score:
         <prompt_text from the prompts.prompt_text column>
```

**Generation params** (`scorer.py:91-97`):
- `model="gemini-3.5-flash"`
- `temperature=0.0`
- `max_tokens=300`

**Expected JSON response:**
```json
{"specificity": 0.0-1.0, "visual_detail": 0.0-1.0, "novelty": 0.0-1.0, "generatable": 0.0-1.0}
```

Note: the system prompt does **not** ask the LLM to return an `overall` field. `overall` is computed client-side via the weighted average formula at `scorer.py:124-129`.

---

## 2. JSON parsing helper

**File:** `src/worker/scorer.py:38-53` (`_parse_json_response`)

The LLM sometimes wraps its response in a markdown code fence (` ```json ... ``` `). The parser strips those before passing to `json.loads`. If parsing still fails, the function returns `None`, which triggers the all-zeros fallback at `scorer.py:111-117`.

```python
# scorer.py:38-53
def _parse_json_response(raw: str) -> Optional[dict]:
    """Parse JSON from LLM response, handling markdown code blocks."""
    try:
        text = raw.strip()
        if text.startswith("```"):
            text = text[3:]
            if text.startswith("json"):
                text = text[3:]
            text = text.strip().strip("```").strip()
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace >= first_brace:
            text = text[first_brace : last_brace + 1]
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
```

The parser is **silent on failure** — a `None` return is the only signal. There is no logging, no retry, no flag. A high volume of `0,0,0,0,0.0` rows in the DB is the only externally visible symptom of a parse storm (see SKILL.md drift #5).

---

## 3. The all-zeros fallback (silent, see drift #5)

**File:** `src/worker/scorer.py:107-117`

```python
# scorer.py:107-117
result = self._call_llm(prompt.prompt_text)

if result is None:
    # Fallback: all zeros if LLM fails
    return QualityScores(
        specificity=0.0,
        visual_detail=0.0,
        novelty=0.0,
        generatable=0.0,
        overall=0.0,
    )
```

This is the only failure path inside `score()`. The `LLMError` raised by `_call_llm()` (at `scorer.py:99-100`) is **not caught** — it propagates up to the `tool_score_prompts()` loop, which has no retry, and then to the `tool_score_prompts()` boundary, which converts it to a `错误: LLMError: ...` string.

So:
- LLM transport error (rate limit, network, auth) → `错误: LLMError: ...` (no DB write).
- LLM returned un-parseable text → silent `0,0,0,0,0.0` write (no log).

---

## 4. The `overall` formula (client-side, not in the LLM call)

**File:** `src/worker/scorer.py:119-137`

```python
# scorer.py:119-129
specificity = max(0.0, min(1.0, float(result.get("specificity", 0.0))))
visual_detail = max(0.0, min(1.0, float(result.get("visual_detail", 0.0))))
novelty = max(0.0, min(1.0, float(result.get("novelty", 0.0))))
generatable = max(0.0, min(1.0, float(result.get("generatable", 0.0))))

overall = (
    specificity * self._weights.specificity +
    visual_detail * self._weights.visual_detail +
    novelty * self._weights.novelty +
    generatable * self._weights.generatable
)
```

The default `self._weights` come from `QualityWeights()` in `src/types/config.py:120-125`:
```python
QualityWeights(specificity=0.25, visual_detail=0.30, novelty=0.20, generatable=0.25)
```
These mirror `configs/quality.yaml:3-6` exactly. Sum = `1.0`, so `overall` is bounded by `[0.0, 1.0]` automatically.

The 4 LLM-returned values are clamped to `[0.0, 1.0]` but **`overall` itself is not clamped**. With the default weights, the bound holds. If a future YAML change makes the weights sum to > 1.0, `overall` could exceed 1.0.

The `round(overall, 4)` at `scorer.py:136` means the CSV stores up to 4 decimal places (e.g. `0.6705`). The 4 base scores are **not** rounded.

---

## 5. The CSV builder (in the tool, not the scorer)

**File:** `src/agent/skills/core_tools.py:336-339`

```python
# core_tools.py:336-339
scores_json = (
    f"{scores.specificity},{scores.visual_detail},"
    f"{scores.novelty},{scores.generatable},{scores.overall}"
)
```

This is the exact string written into `prompts.quality_scores`. **Field order is fixed** — `spec,vis,nov,gen,overall`. See SKILL.md drift #4 for the downstream impact.

---

## 6. Score-level reference (from the wiki)

Reproduced from `prompts/scoring/01_scoring_system.md` (lines 49-56). The wiki is a slimmed-down version of the real prompt (the wiki only shows the dimensions, not the "Be strict" calibration line), but this table is consistent with the code:

| Score | Level | Description |
|---|---|---|
| 0.8–1.0 | Excellent | Highly specific, rich visual detail, unique, ready to generate |
| 0.5–0.8 | Average | Decent detail, some visual terms, usable |
| 0.3–0.5 | Weak | Generic description, missing visual terms, may not drive generation |
| 0.0–0.3 | Poor | Placeholder text, JSON key names, or unusable content |

The tool's default `min_score=0.4` falls in the "Weak" band — it's deliberately permissive, designed to keep ~half of extracted prompts in the pipeline for image generation. Raise it to `0.6` ("good_overall" in YAML) to filter down to the "Average" band only.

---

## 7. Things to tune (and where)

| Symptom | What to edit | Note |
|---|---|---|
| All scores are too generous (every prompt is "Excellent") | `SCORING_SYSTEM_PROMPT` line "Be strict: 0.5 means average, 0.8+ means excellent" | The calibration line is the main lever. The 4 dimension descriptions set the rubric. |
| `overall` is biased toward `visual_detail` | `src/types/config.py:120-125` (and `configs/quality.yaml:3-6` for documentation) | The tool reads the dataclass default, not the YAML — see SKILL.md drift #2. |
| Many rows are `0,0,0,0,0.0` | Add logging in `_call_llm()` and `score()`; or hard-code a retry. | The fallback is silent — see SKILL.md drift #5. |
| `temperature=0.0` isn't producing deterministic results | Switch to `gemini-2.5-flash-image` (or another model with stricter JSON mode), or wrap `_call_llm` in a retry loop. | The current model is `gemini-3.5-flash`. |
| You want to score a different field set | Extend `SCORING_SYSTEM_PROMPT` + `QualityScores` dataclass + `QualityWeights` + the CSV builder. | The CSV order is a hard contract — see SKILL.md drift #4. |
