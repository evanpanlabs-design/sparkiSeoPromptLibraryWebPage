"""Quality scoring for extracted prompts.

The QualityScorer class scores prompts across 4 dimensions using LLM analysis:
  - specificity: Detail level of visual description
  - visual_detail: Camera, lighting, composition terms
  - novelty: Uniqueness/rarity of structure
  - generatable: Can this directly drive generation?

Overall is a weighted average using weights from quality.yaml.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from src.types.prompt import ExtractedPrompt, QualityScores
from src.types.config import QualityConfig, QualityWeights, QualityThresholds
from src.exceptions import LLMError, LLMParseError


class LLMClientLike:
    """Interface for LLM client. Actual implementation in src.llm.client."""

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> str:
        """Send a completion request and return raw response text."""
        raise NotImplementedError


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


class QualityScorer:
    """Scores prompt quality across multiple dimensions."""

    def __init__(
        self,
        llm_client: LLMClientLike,
        quality_config: QualityConfig,
        default_model: str = "gemini-3.5-flash",
    ):
        """Initialize with LLM client and quality configuration."""
        self.llm = llm_client
        self.config = quality_config
        self.default_model = default_model
        self._weights = quality_config.weights
        self._thresholds = quality_config.thresholds

    def _call_llm(self, prompt_text: str) -> Optional[dict]:
        """Make an LLM call to score a prompt."""
        try:
            raw = self.llm.complete(
                prompt=f"Prompt to score:\n{prompt_text}",
                system=SCORING_SYSTEM_PROMPT,
                model=self.default_model,
                temperature=0.0,
                max_tokens=300,
            )
            return _parse_json_response(raw)
        except Exception as e:
            raise LLMError(f"Scoring LLM call failed: {e}") from e

    def score(self, prompt: ExtractedPrompt) -> QualityScores:
        """
        Score a prompt across 4 dimensions using LLM analysis.
        Returns QualityScores dataclass with all dimensions and overall.
        """
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

        return QualityScores(
            specificity=specificity,
            visual_detail=visual_detail,
            novelty=novelty,
            generatable=generatable,
            overall=round(overall, 4),
        )

    def should_generate_image(self, scores: QualityScores) -> bool:
        """Return True if overall score >= min_overall threshold."""
        return scores.overall >= self._thresholds.min_overall


def score_prompt(
    prompt: ExtractedPrompt,
    llm_client: LLMClientLike,
    quality_config: QualityConfig,
    model: str = "gemini-3.5-flash",
) -> QualityScores:
    """Convenience function to score a single prompt."""
    scorer = QualityScorer(llm_client, quality_config, model)
    return scorer.score(prompt)