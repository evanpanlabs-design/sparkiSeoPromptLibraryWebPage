# Sparki-Veo-Station Prompts Index

All LLM prompts used across the Sparki V3.2 project, organized by subsystem.

---

## Directory Structure

```
prompts/
├── extraction/              # Worker: Tweet → Prompt extraction
│   └── 01_extraction_system.md
├── scoring/                 # Worker: Prompt quality scoring
│   └── 01_scoring_system.md
├── agent_nodes/             # V3.2 Active Node prompts
│   └── 01_think_node.md    # (think, plan, observe nodes)
├── agent_templates/         # Legacy react/prompt.py templates
│   └── 01_templates.md
├── image_generation/        # Cover image generation
│   └── 01_cover_image.md
└── skill_descriptions/     # Skill tool schemas (LLM tool selection)
    └── 01_core_tools.md
```

---

## Quick Reference

| # | Prompt | File | Purpose |
|---|---|---|---|
| 1 | Extraction System | `extraction/01_extraction_system.md` | First-pass: is this tweet a Veo prompt? |
| 2 | Recheck | `extraction/01_extraction_system.md` | Second-pass for tweets with "prompt:" markers |
| 3 | Restructured | `extraction/01_extraction_system.md` | Repair for JSON/placeholder extraction errors |
| 4 | Scoring | `scoring/01_scoring_system.md` | Score prompt across 4 dimensions |
| 5 | think_node | `agent_nodes/01_think_node.md` | Intent classification + thought generation |
| 6 | plan_node | `agent_nodes/01_think_node.md` | Tool selection based on thought |
| 7 | observe_node | `agent_nodes/01_think_node.md` | Evaluate result, decide continue/stop |
| 8 | THINK template | `agent_templates/01_templates.md` | Legacy template (react/prompt.py) |
| 9 | PLAN template | `agent_templates/01_templates.md` | Legacy template |
| 10 | OBSERVE template | `agent_templates/01_templates.md` | Legacy template |
| 11 | FINAL REPLY template | `agent_templates/01_templates.md` | Legacy template |
| 12 | Cover Image | `image_generation/01_cover_image.md` | Generate cover image for prompt |
| 13 | Skill descriptions | `skill_descriptions/01_core_tools.md` | 18 skill tool schemas for LLM |

---

## Model Usage

| Component | Model | Config |
|---|---|---|
| Extraction (extractor.py) | `gemini-3.5-flash` | `configs/llm.yaml` |
| Scoring (scorer.py) | `gemini-3.5-flash` | `configs/llm.yaml` |
| Agent nodes (think/plan/observe) | `gemini-3.5-flash` | `configs/agent.yaml` |
| Image generation | `gemini-3.1-flash-image-preview` | `configs/gemini.yaml` |
| Embedding search | `gemini-embedding-exp-03-07` | `configs/agent.yaml` |

---

## Prompt Flow Summary

**Pipeline mode (MULTI_STEP):**
```
User: "跑一遍全程"
  → think_node: classify intent = MULTI_STEP
  → plan_node: selects crawl_tweets (rule-based, no LLM)
  → act_node: executes crawl_tweets
  → observe_node: rule-based → extract_prompts
  → act_node: executes extract_prompts (LLM: extraction system prompt)
  → observe_node: rule-based → score_prompts
  → act_node: executes score_prompts (LLM: scoring prompt)
  → observe_node: rule-based → generate_images
  → act_node: executes generate_images (LLM: cover image prompt)
  → observe_node: rule-based → sync_images → build_html → publish
  → observe_node: continue: false → final_reply_node
```

**Agent mode (single tool):**
```
User: "pool status"
  → think_node: classify intent = STATUS_QUERY
  → plan_node: selects pool_status tool (LLM call)
  → act_node: executes pool_status → return result
  → observe_node: continue: false → final_reply_node
```