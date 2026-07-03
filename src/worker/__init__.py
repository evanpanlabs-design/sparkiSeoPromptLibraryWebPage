"""Worker module — Prompt extraction, deduplication, and quality scoring.

This module implements the Worker component of the Sparki pipeline, responsible for:
1. Extracting prompts from tweets via LLM (extractor.py)
2. Deduplicating extracted prompts via text similarity (dedup.py)
3. Scoring prompt quality across multiple dimensions (scorer.py)
"""

from src.worker.extractor import PromptExtractor, ExtractionResult
from src.worker.dedup import PromptDeduplicator
from src.worker.scorer import QualityScorer

__all__ = [
    "PromptExtractor",
    "ExtractionResult",
    "PromptDeduplicator",
    "QualityScorer",
]