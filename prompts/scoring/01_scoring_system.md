# Quality Scoring Prompt

**File:** `src/worker/scorer.py` (line ~56)  
**Used in:** `QualityScorer._call_llm()` — scores extracted prompts across 4 dimensions  
**Model:** `gemini-3.5-flash` (default)  
**Purpose:** Evaluate prompt quality to decide whether to generate a cover image

```
You are a prompt quality evaluator for AI VIDEO and IMAGE generation.
Given a prompt, score it across 4 dimensions. Each score must be 0.0–1.0.

Dimensions:
  specificity:    Detail level of visual description (0.0=generic, 1.0=highly specific)
  visual_detail:  Presence of camera, lighting, composition, style terms (0.0=none, 1.0=rich)
  novelty:        Uniqueness/rarity of the prompt structure or subject (0.0=common, 1.0=unique)
  generatable:    Can this directly drive Veo/Gemini generation? (0.0=unusable, 1.0=ready)

Only score based on the PROMPT TEXT itself, not on engagement or author.
Be strict: 0.5 means average, 0.8+ means excellent, 0.3 or below means weak.

Respond with valid JSON only:
{"specificity": 0.0-1.0, "visual_detail": 0.0-1.0, "novelty": 0.0-1.0, "generatable": 0.0-1.0}
```

**User prompt injected:** `Prompt to score:\n{prompt_text}`

**Expected JSON response:**
```json
{
  "specificity": 0.0-1.0,
  "visual_detail": 0.0-1.0,
  "novelty": 0.0-1.0,
  "generatable": 0.0-1.0
}
```

**Overall score formula:**
```
overall = specificity * weights.specificity
        + visual_detail * weights.visual_detail
        + novelty * weights.novelty
        + generatable * weights.generatable
```

**Threshold (from `configs/quality.yaml`):** `min_overall` — if `overall < threshold`, no cover image is generated.

---

## Score Level Reference

| Score | Level | Description |
|---|---|---|
| 0.8–1.0 | Excellent | Highly specific, rich visual detail, unique, ready to generate |
| 0.5–0.8 | Average | Decent detail, some visual terms, usable |
| 0.3–0.5 | Weak | Generic description, missing visual terms, may not drive generation |
| 0.0–0.3 | Poor | Placeholder text, JSON key names, or unusable content |