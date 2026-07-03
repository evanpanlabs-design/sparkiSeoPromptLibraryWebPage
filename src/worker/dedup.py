"""Prompt deduplication via text similarity.

The PromptDeduplicator class uses:
  - Jaccard similarity on character trigrams as a fast-path
  - Cosine similarity on embedding vectors (when available)

A prompt is considered a duplicate if similarity >= threshold (default 0.85).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class DedupResult:
    """Result of a deduplication check."""
    is_duplicate: bool
    similar_prompt_id: int | None = None
    similarity_score: float = 0.0


class PromptDeduplicator:
    """Deduplicates prompts using text similarity."""

    def __init__(self, threshold: float = 0.85):
        """Initialize with similarity threshold (0.0–1.0)."""
        self.threshold = threshold
        self._corpus: list[tuple[int, str]] = []  # (prompt_id, text)
        self._trigram_sets: dict[int, frozenset[str]] = {}

    def _get_trigrams(self, text: str) -> frozenset[str]:
        """Return frozenset of character trigrams from text."""
        t = text.lower().strip()
        if len(t) < 3:
            return frozenset()
        return frozenset(t[i:i+3] for i in range(len(t) - 2))

    def _jaccard_similarity(self, text1: str, text2: str) -> float:
        """Compute Jaccard similarity between two texts using trigrams."""
        trigrams1 = self._get_trigrams(text1)
        trigrams2 = self._get_trigrams(text2)
        if not trigrams1 or not trigrams2:
            return 0.0
        intersection = len(trigrams1 & trigrams2)
        union = len(trigrams1 | trigrams2)
        return intersection / union if union > 0 else 0.0

    def is_duplicate(self, new_prompt: str, prompt_id: int | None = None) -> DedupResult:
        """
        Check if new_prompt is a near-duplicate of any prompt already in the corpus.

        Uses trigram Jaccard as fast path. If similarity >= threshold,
        marks as duplicate.
        """
        if not self._corpus:
            return DedupResult(is_duplicate=False)

        for existing_id, existing_text in self._corpus:
            # Skip comparing against itself during updates
            if prompt_id is not None and existing_id == prompt_id:
                continue
            sim = self._jaccard_similarity(new_prompt, existing_text)
            if sim >= self.threshold:
                return DedupResult(
                    is_duplicate=True,
                    similar_prompt_id=existing_id,
                    similarity_score=sim,
                )
        return DedupResult(is_duplicate=False, similarity_score=0.0)

    def add_to_corpus(self, prompt_id: int, text: str) -> None:
        """Add a prompt to the dedup corpus (in-memory)."""
        self._corpus.append((prompt_id, text))
        self._trigram_sets[prompt_id] = self._get_trigrams(text)

    def remove_from_corpus(self, prompt_id: int) -> None:
        """Remove a prompt from the dedup corpus."""
        self._corpus = [(pid, txt) for pid, txt in self._corpus if pid != prompt_id]
        self._trigram_sets.pop(prompt_id, None)

    def clear(self) -> None:
        """Clear the entire dedup corpus."""
        self._corpus.clear()
        self._trigram_sets.clear()

    @property
    def corpus_size(self) -> int:
        """Return number of prompts in the dedup corpus."""
        return len(self._corpus)