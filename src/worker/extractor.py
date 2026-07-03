"""Prompt extraction via LLM — single-tweet extraction with validation and repair.

The PromptExtractor class handles:
  - First-pass LLM classification (is_prompt?, category, title, prompt_text)
  - Recheck for tweets containing prompt indicators (e.g., "prompt:", "见评论")
  - Validation & repair for JSON key extraction errors and placeholder text
  - Structured prompt extraction (JSON/shot-list/"Prompt:" markers)
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.types.prompt import ExtractedPrompt, QualityScores
from src.types.tweet import Tweet, AuthorRef
from src.types.category import CategorySuggestion, CategorySuggestionStatus
from src.exceptions import LLMError, LLMParseError


# Keywords that suggest a prompt is embedded in the tweet text
PROMPT_INDICATORS = [
    "prompt:", "\nPrompt ", "\"prompt\":", "prompt_details",
    "见评论", "评论区", "prompt in", "prompt below",
]

# Required content filter — tweet text MUST contain "veo" (case-insensitive)
# and be at least 15 words. The LLM does the real is_prompt classification.
_REQUIRED_TWEET_KEYWORDS = ["veo"]  # case-insensitive
_MIN_CONTENT_WORDS = 15  # tweet text must have at least this many words

# Keywords that appear INSIDE a JSON structure, meaning the LLM likely
# extracted a JSON key name (like "title") instead of the actual prompt content.
_JSON_INDICATORS = {
    "\"style\":", "\"scenes\":", "\"camera\":", "\"mood\":", "\"aspect_ratio\":",
    "\"scene_number\":", "\"description\":", "\"audio\":", "\"background_music\":"
}

# Text fragments that indicate the LLM extracted a placeholder, not real content.
_PLACEHOLDER_INDICATORS = {
    "...", "[the full prompt text]", "see comments", "见评论",
    "prompt below", "in reply"
}


@dataclass
class ExtractionResult:
    """Result of a single-tweet extraction attempt."""
    is_prompt: bool
    category: str | None = None
    title: str | None = None
    prompt_text: str | None = None
    notes: str = ""
    is_recheck: bool = False
    repair_attempted: bool = False
    is_structured: bool = False
    structured_format: str | None = None


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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _should_recheck(text: str) -> bool:
    """Return True if tweet text contains prompt indicators that warrant a second review."""
    t = text.lower()
    return any(kw in t for kw in PROMPT_INDICATORS)


_MIN_CONTENT_WORDS = 15  # tweet text must have at least this many words


def _content_filter(text: str) -> bool:
    """Return True if tweet text contains BOTH required keywords (Veo + prompt).

    This is a fast gate applied BEFORE LLM extraction to reject tweets that are
    clearly not about Veo video generation prompts AND content shorter than 15 words.
    """
    t = text.lower()
    if not all(kw in t for kw in _REQUIRED_TWEET_KEYWORDS):
        return False
    # Reject trivially short content (e.g. "Nano Banana")
    word_count = len(text.split())
    if word_count < _MIN_CONTENT_WORDS:
        return False
    return True


def _looks_like_json_extraction(prompt_text: str) -> bool:
    """True if prompt_text looks like a JSON key name, not actual content."""
    if not prompt_text:
        return False
    t = prompt_text.strip()
    return any(t.startswith(k) or t.startswith(k.replace("\"", ""))
               for k in _JSON_INDICATORS)


def _looks_like_placeholder(prompt_text: str) -> bool:
    """True if prompt_text is clearly a placeholder, not real extracted content."""
    if not prompt_text:
        return True
    t = prompt_text.strip().lower()
    if len(t) < 15:
        return True
    KNOWN_PLACEHOLDERS = {
        "...", "...", "[the full prompt text]", "[full prompt text]",
        "see comments", "见评论", "prompt below", "in reply",
        "see reply", "prompt in comments",
    }
    if t in KNOWN_PLACEHOLDERS or any(t.startswith(p) for p in KNOWN_PLACEHOLDERS):
        return True
    short_phrases = {"full prompt text", "see below", "as above", "see link"}
    if t in short_phrases:
        return True
    return False


def _parse_json_response(raw: str) -> Optional[dict]:
    """Parse JSON from LLM response, handling markdown code blocks."""
    try:
        text = raw.strip()
        # Strip markdown code blocks if present
        if text.startswith("```"):
            text = text[3:]
            if text.startswith("json"):
                text = text[3:]
            text = text.strip().strip("```").strip()
        # Find JSON bounds
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace >= first_brace:
            text = text[first_brace : last_brace + 1]
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


_SYSTEM_PROMPT_CONTENT = (
    "You are a prompt extraction specialist for AI VIDEO GENERATION.\n"
    "Your task is to identify Veo/Gemini video generation prompts and classify them by the VISUAL CONTENT they describe.\n\n"
    "== STRICT CRITERIA ==\n"
    "Only mark is_prompt=true when ALL of these are true:\n"
    "  1. The prompt describes visual content that can be DIRECTLY generated by Veo/Gemini\n"
    "  2. The prompt contains enough detail to GUIDE actual generation (subject, action, setting, style, lighting, camera, etc.)\n"
    "  3. The output is a VIDEO or ANIMATED IMAGE, not plain text, code, or a static image alone\n\n"
    "Mark is_prompt=false for:\n"
    "  - Code generation, CLI tools, software architecture prompts\n"
    "  - Plain text assistants, writing tasks, brainstorming prompts\n"
    "  - Non-visual analysis tasks (code review, debugging, documentation)\n"
    "  - Discussion posts about Veo WITHOUT a usable prompt inside\n"
    "  - Vague references ('prompt in comments', 'see below', 'veo is great')\n"
    "  - Single words, emoji-only, or reaction text\n"
    "  - Memes/jokes without actual generation content\n"
    "  - Prompts that describe HOW an AI model works (latent space, encoding, temporal coherence, physics simulation, rendering pipeline, model architecture)\n"
    "  - Prompts that generate diagrams, infographics, explainers, or step-by-step overviews of AI processes\n"
    "  - Prompts that ask for flowcharts, architecture diagrams, or technical breakdowns\n\n"
    "== CATEGORY RULE: Describe WHAT IS GENERATED, not the prompt type ==\n"
    "Classify by VISUAL CONTENT: what the viewer would SEE in the generated video.\n"
    "Use free-form labels. Here are examples of GOOD category labels:\n\n"
    "  - 'cinematic-scene'        -- film-like shot with dramatic lighting, camera movement\n"
    "  - 'product-showcase'       -- product rotating/displayed in studio or lifestyle setting\n"
    "  - 'character-portrait'     -- person or character face/body, portrait-style\n"
    "  - '3d-render'              -- 3D animated object, environment, architectural viz\n"
    "  - 'animation-clip'         -- cartoon style, motion graphics, stylized animation\n"
    "  - 'nature-scene'           -- landscape, animals, plants, outdoor environments\n"
    "  - 'urban-scene'            -- city streets, buildings, traffic, architecture\n"
    "  - 'food-beverage'          -- food styling, cooking, drink cinematography\n"
    "  - 'fashion-apparel'        -- clothing model, fabric detail, runway style\n"
    "  - 'sports-action'          -- athletic movement, game footage simulation\n"
    "  - 'sci-fi-fantasy'         -- futuristic, space, CG environments\n"
    "  - 'historical-period'       -- period drama, vintage aesthetics\n"
    "  - 'abstract-motion'        -- artistic particles, shaders, generative visuals\n"
    "  - 'tutorial-demo'          -- screen recording style, product demo, how-to\n"
    "  - 'social-media-content'   -- vertical video, reel-style, phone-native framing\n"
    "  - 'music-visualizer'       -- audio-reactive visual, album art motion\n"
    "  - 'other'                  -- only when nothing above fits\n\n"
    "== FEW-SHOT EXAMPLES ==\n\n"
    'Example 1 (PASS, cinematic-scene):\n'
    '{"is_prompt": true, "category": "cinematic-scene", "title": "Desert Lone Traveler", "prompt_text": "A lone traveler walks across vast red sand dunes at golden hour. Wide tracking shot, warm desert sun behind, long shadow stretching. Cinematic color grade."}\n\n'
    'Example 2 (PASS, product-showcase):\n'
    '{"is_prompt": true, "category": "product-showcase", "title": "Floating Sneaker", "prompt_text": "A sneaker slowly rotates in mid-air against a dark gradient background. Clean studio lighting from above, subtle reflection on the rubber sole."}\n\n'
    'Example 3 (PASS, character-portrait):\n'
    '{"is_prompt": true, "category": "character-portrait", "title": "Cyberpunk Portrait", "prompt_text": "Close-up portrait of a young woman with neon-lit cybernetic implants. Rain-soaked street reflections on her visor. Teal and magenta neon lighting."}\n\n'
    'Example 4 (PASS, animation-clip):\n'
    '{"is_prompt": true, "category": "animation-clip", "title": "Dancing Blob Character", "prompt_text": "A friendly amorphous blob character bounces and morphs through a pastel landscape. Hand-drawn animation style with fluid squash-and-stretch motion."}\n\n'
    'Example 5 (PASS, 3d-render):\n'
    '{"is_prompt": true, "category": "3d-render", "title": "Isometric City Block", "prompt_text": "An isometric low-poly 3D render of a bustling city block with tiny cars, trees and pedestrians. Soft shadows, warm afternoon light."}\n\n'
    'Example 6 (PASS, nature-scene):\n'
    '{"is_prompt": true, "category": "nature-scene", "title": "Tidal Pool Close-up", "prompt_text": "A macro shot of a tidal pool on volcanic rock. Tiny crabs and anemones visible underwater. Crystal clear water, sunlight refracting through surface."}\n\n'
    'Example 7 (PASS, social-media-content):\n'
    '{"is_prompt": true, "category": "social-media-content", "title": "Fitness App Promo", "prompt_text": "A young woman in athletic wear demonstrates a bicep curl on a smartphone screen. Vertical 9:16 format, bright fitness studio background, energetic music cue."}\n\n'
    'Example 8 (PASS, sci-fi-fantasy):\n'
    '{"is_prompt": true, "category": "sci-fi-fantasy", "title": "Alien Marketplace", "prompt_text": "A crowded alien marketplace on a ring-shaped space station. Strange foods, exotic vendors, zero gravity water droplets floating. Concept film style."}\n\n'
    'Example 9 (FAIL, discussion):\n'
    '{"is_prompt": false, "category": null, "title": null, "prompt_text": null, "notes": "Discussion about Veo pricing, no actual prompt inside."}\n\n'
    'Example 10 (FAIL, vague):\n'
    '{"is_prompt": false, "category": null, "title": null, "prompt_text": null, "notes": "Just says prompt in comments without providing the actual prompt text."}\n\n'
    'Example 11 (PASS, food-beverage):\n'
    '{"is_prompt": true, "category": "food-beverage", "title": "Coffee Pour", "prompt_text": "Slow-motion pour of dark espresso into a white ceramic cup. Thick crema forming on top. Warm bokeh background of a cafe counter."}\n\n'
    'Example 12 (PASS, abstract-motion):\n'
    '{"is_prompt": true, "category": "abstract-motion", "title": "Particle Storm", "prompt_text": "Millions of glowing particles stream and swirl in a dark void. Audio-reactive waves, iridescent color shifts, deep space ambience."}\n\n'
    "== OUTPUT FORMAT ==\n"
    'Respond with valid JSON only, no markdown, no explanation:\n'
    '{"is_prompt": true or false, '
    '"category": "<free-form label describing visual content>", '
    '"title": "short descriptive title" or null, '
    '"prompt_text": "full prompt text" or null, '
    '"notes": "optional note" or null}.\n'
    "Use 'other' for category only when truly nothing fits. "
    "Be CREATIVE and SPECIFIC with category -- err toward descriptive over generic."
)


class PromptExtractor:
    """Extracts prompts from tweets using an LLM client."""

    def __init__(
        self,
        llm_client: LLMClientLike,
        categories: list[str],
        default_model: str = "gemini-3.5-flash",
    ):
        """Initialize with LLM client and active category list."""
        self.llm = llm_client
        self.categories = categories
        self.default_model = default_model
        self._system_prompt = _SYSTEM_PROMPT_CONTENT

    def _call_llm(self, text: str, system: str | None = None, model: str | None = None) -> Optional[dict]:
        """Make an LLM call and parse JSON response."""
        system = system or self._system_prompt
        model = model or self.default_model
        try:
            raw = self.llm.complete(
                prompt=f"Tweet:\n{text}",
                system=system,
                model=model,
                temperature=0.0,
                max_tokens=500,
            )
            return _parse_json_response(raw)
        except Exception as e:
            raise LLMError(f"LLM call failed: {e}") from e

    def _call_llm_raw(self, text: str, system: str, model: str | None = None) -> Optional[dict]:
        """Make an LLM call with a custom system prompt."""
        return self._call_llm(text, system=system, model=model)

    def extract(self, tweet: Tweet) -> ExtractionResult:
        """
        Single-tweet extraction.
        Returns ExtractionResult with is_prompt, category, title, prompt_text, notes.
        Handles first-pass LLM classification, content gate, and validation/repair.
        """
        # Fast content gate: tweet text MUST contain both "veo" and "prompt"
        if not _content_filter(tweet.text):
            return ExtractionResult(is_prompt=False)

        text = tweet.text
        result = self._call_llm(text)

        # If LLM said not a prompt, check if recheck is warranted
        if result is None or not result.get("is_prompt", False):
            if _should_recheck(text):
                result = self._recheck(tweet)
            if result is None or not result.get("is_prompt", False):
                return ExtractionResult(is_prompt=False)

        # Post-extraction validation & repair
        result = self._validate_and_repair(result, tweet)
        if result is None or not result.get("is_prompt", False):
            return ExtractionResult(is_prompt=False)

        is_structured = result.get("is_structured", False)
        structured_format = result.get("structured_format", None) if is_structured else None

        return ExtractionResult(
            is_prompt=True,
            category=result.get("category", "other"),
            title=result.get("title", ""),
            prompt_text=result.get("prompt_text", ""),
            notes=result.get("notes", ""),
            is_recheck=result.get("is_recheck", False),
            repair_attempted=result.get("repair_attempted", False),
            is_structured=is_structured,
            structured_format=structured_format,
        )

    def _recheck(self, tweet: Tweet) -> Optional[dict]:
        """Second-pass review for tweets with prompt indicators."""
        RECHECK_PROMPT = (
            "You are a Veo video generation prompt reviewer.\n"
            "A tweet was initially flagged as not containing a prompt.\n"
            "However, the tweet text contains keywords that suggest a prompt may be present.\n\n"
            "IMPORTANT: Be STRICT. Only return JSON if the tweet ITSELF contains a complete,\n"
            "directly usable prompt for Veo/Gemini video generation.\n"
            "If the tweet only says 'prompt in comments', 'see reply', 'prompt below',\n"
            "or references a prompt elsewhere without giving the content — return null.\n\n"
            '{"is_prompt": true/false, "category": "...", "title": "...", '
            '"prompt_text": "...", "notes": "..."} or null.'
        )
        result = self._call_llm_raw(tweet.text, system=RECHECK_PROMPT)
        if result and result.get("is_prompt"):
            result["is_recheck"] = True
        return result

    def _reextract_structured(self, tweet: Tweet) -> Optional[dict]:
        """
        For tweets where the LLM misinterpreted a JSON structure as a prompt title,
        OR the tweet contains a "Prompt:"-style literal prompt marker.
        """
        RESTRUCTURED_PROMPT = (
            "You are a video prompt extraction specialist.\n"
            "A tweet may contain a STUCTURED prompt in JSON, YAML, shot-list, or scene-breakdown format.\n"
            "OR it may contain a literal prompt prefixed with 'Prompt:' or 'Prompt:-'.\n"
            "Your job is to find it and extract the FULL content.\n\n"
            "Rules:\n"
            "  - If the tweet contains a structured prompt (JSON/shot list/scene format),\n"
            "    extract the FULL raw structured text as prompt_text — do NOT summarize or reformat.\n"
            "  - If the tweet contains a 'Prompt:' or 'Prompt:-' marker followed by prompt content,\n"
            "    extract EVERYTHING after that marker as the full prompt_text.\n"
            "  - The 'title' field should be a SHORT label (e.g. 'Luxury Chronograph Watch',\n"
            "    'Cinematic Mountain Product Shot'), NOT a description or quote.\n"
            "  - The 'prompt_text' field must contain the ACTUAL prompt content from the tweet.\n"
            "  - If there is no structured prompt and no 'Prompt:' marker, return null.\n\n"
            '{"is_prompt": true/false, "category": "...", "title": "...", '
            '"prompt_text": "...full prompt text...", "notes": "...", '
            '"is_structured": true/false, "structured_format": "json|shot_list|prompt_marker"} '
            "or null."
        )
        result = self._call_llm_raw(tweet.text, system=RESTRUCTURED_PROMPT)
        if result and result.get("is_prompt"):
            result["repair_attempted"] = True
            # Detect structured format
            if result.get("is_structured"):
                text_lower = tweet.text.lower()
                if '{"' in tweet.text or '"style":' in tweet.text:
                    result["structured_format"] = "json"
                elif any(kw in text_lower for kw in ["shot", "scene ", "take ", "frame "]):
                    result["structured_format"] = "shot_list"
                else:
                    result["structured_format"] = "prompt_marker"
        return result

    def _validate_and_repair(self, result: Optional[dict], tweet: Tweet) -> Optional[dict]:
        """
        Post-extraction check: if prompt_text looks like a JSON key name or a placeholder,
        attempt one re-extraction pass with a specialized prompt.
        Also strips common markdown/code prefixes (e.g. 'Prompts:' in the text).
        """
        if result is None:
            return None

        prompt_text = result.get("prompt_text", "")

        # Strip common prefixes that are NOT part of the actual prompt
        # e.g. "Prompts: A cinematic shot of..." → "A cinematic shot of..."
        # e.g. "Prompt: ..." → "..."
        prefixes_to_strip = [
            r"^Prompts?:\s*",
            r"^Prompt:\s*",
            r"^Prompt:\s*",
            r"^Veo:\s*",
            r"^Video Prompt:\s*",
        ]
        for pattern in prefixes_to_strip:
            prompt_text = re.sub(pattern, "", prompt_text, flags=re.IGNORECASE).strip()
        if prompt_text != result.get("prompt_text", ""):
            result = dict(result)  # copy to avoid mutating shared dict
            result["prompt_text"] = prompt_text

        # Case 1: prompt_text looks like a JSON key name → re-extract with structured-aware prompt
        if _looks_like_json_extraction(prompt_text):
            repaired = self._reextract_structured(tweet)
            if repaired and repaired.get("is_prompt", False):
                if not repaired.get("category") or repaired["category"] == "other":
                    repaired["category"] = result.get("category", "other")
                repaired["repair_attempted"] = True
                return repaired

        # Case 2: prompt_text is too short / placeholder → re-extract via structured repair
        if _looks_like_placeholder(prompt_text):
            repaired = self._reextract_structured(tweet)
            if repaired and repaired.get("is_prompt", False):
                if not repaired.get("prompt_text") or _looks_like_placeholder(repaired["prompt_text"]):
                    repaired = None
            if repaired is None:
                # Last resort: raw recheck
                repaired = self._recheck(tweet)
            if repaired and repaired.get("is_prompt", False):
                repaired["repair_attempted"] = True
                result = repaired

        # Case 3: prompt_text too short (兜底) — runs AFTER repair attempts as final gate.
        # This fires even when Case 2 returned a repaired result.
        # Prevents trivial prompts like "Football Magic" or "show me a fitness app demo"
        # from passing through after repair/recheck.
        MIN_PROMPT_WORDS = 25
        if result and result.get("is_prompt") and prompt_text:
            words_in_prompt = len(prompt_text.split())
            if words_in_prompt < MIN_PROMPT_WORDS:
                result = dict(result)
                result["is_prompt"] = False
                result["notes"] = (
                    f"{result.get('notes', '')} "
                    f"[rejected: prompt_text only {words_in_prompt} words, "
                    f"minimum {MIN_PROMPT_WORDS} required]."
                ).strip()

        return result

    def extract_batch(
        self,
        tweets: list[Tweet],
        concurrency: int = 15,
        max_retries: int = 3,
        base_delay: float = 2.0,
    ) -> list[ExtractionResult]:
        """
        Concurrent extraction with ThreadPoolExecutor + as_completed.
        Returns list of ExtractionResult in the same order as tweets input.
        Retries LLM errors (rate limit, transient) with exponential backoff.
        """
        def _extract_with_retry(tweet: Tweet) -> tuple[int, ExtractionResult]:
            """Returns (attempt_count, result). attempt_count > 1 means retry succeeded."""
            last_error = None
            for attempt in range(max_retries):
                try:
                    result = self.extract(tweet)
                    return attempt + 1, result
                except LLMError as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        time.sleep(delay)
                except Exception as e:
                    last_error = e
                    break
            return max_retries, ExtractionResult(is_prompt=False)

        results: list[ExtractionResult] = [ExtractionResult(is_prompt=False)] * len(tweets)
        done_count = 0

        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            futures = {}
            for i, tweet in enumerate(tweets):
                fut = ex.submit(_extract_with_retry, tweet)
                futures[fut] = i

            for fut in as_completed(futures):
                i = futures[fut]
                try:
                    _, results[i] = fut.result()
                except Exception:
                    results[i] = ExtractionResult(is_prompt=False)
                done_count += 1

        return results


def build_extracted_prompt(
    tweet: Tweet,
    result: ExtractionResult,
    known_categories: set[str],
) -> tuple[ExtractedPrompt, list[CategorySuggestion]]:
    """
    Convert an ExtractionResult + Tweet into an ExtractedPrompt.

    Returns (ExtractedPrompt, list[CategorySuggestion]).
    CategorySuggestions are created for new categories not in known_categories.
    """
    category = result.category or "other"
    is_new_category = category not in known_categories

    suggestions: list[CategorySuggestion] = []
    if is_new_category and result.is_prompt:
        suggestions.append(CategorySuggestion(
            id=None,
            suggested_name=category,
            reason=f"LLM classified a tweet as '{category}' but this category is not in DB",
            suggested_by="gemini-3.5-flash",
            sample_prompt_text=result.prompt_text[:200] if result.prompt_text else "",
            status=CategorySuggestionStatus.PENDING,
            created_at=_utc_now(),
        ))

    prompt = ExtractedPrompt(
        tweet_id=tweet.tweet_id,
        url=tweet.url,
        category=category if not is_new_category else "other",
        title=result.title or "",
        prompt_text=result.prompt_text or "",
        notes=result.notes,
        author=tweet.author,
        likes_count=tweet.favorite_count,
        retweet_count=tweet.retweet_count,
        reply_count=tweet.reply_count,
        view_count=tweet.view_count,
        extracted_at=_utc_now(),
        quality_scores=None,
        needs_image=True,
        is_structured=result.is_structured,
        structured_format=result.structured_format,
        is_recheck=result.is_recheck,
        repair_attempted=result.repair_attempted,
    )
    return prompt, suggestions