"""Vertex AI Gemini client — same complete() interface as LLMClient."""

from typing import Optional

from google import genai
from google.genai.types import GenerateContentConfig, HttpOptions, ThinkingConfig


class GeminiClient:
    """Vertex AI Gemini text-generation client.

    Exposes the same complete() signature as LLMClient so it can
    drop into _get_llm_client() without changing PromptExtractor or
    any downstream code.

    Gemini 3.5 Flash is a thinking model — thinking tokens count against
    max_output_tokens but are not returned in resp.text. We disable
    thinking by default (thinking_budget=0) so the full token budget is
    available for the visible response.

    Usage:
        client = GeminiClient(project="sparki-op", location="global")
        text = client.complete("Hello", system="You are helpful.")
    """

    def __init__(
        self,
        project: str = "sparki-op",
        location: str = "global",
        default_model: str = "gemini-3.5-flash",
        timeout: int = 60,
    ):
        self.project = project
        self.location = location
        self.default_model = default_model
        self._client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
            http_options=HttpOptions(timeout=timeout * 1000),
        )

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> str:
        config = GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            thinking_config=ThinkingConfig(thinking_budget=0),
        )
        if system:
            config.system_instruction = system

        resp = self._client.models.generate_content(
            model=model or self.default_model,
            contents=prompt,
            config=config,
        )
        # Handle empty/blocked responses safely
        text = getattr(resp, "text", None) or ""
        # Strip after checking — avoid issues with None even if .text is str
        return text.strip() if text else ""
