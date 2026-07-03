"""OpenAI-compatible LLM client for Sparki."""

import os
import json
import time
from typing import Optional, Any
import json
import time
from typing import Optional
from dataclasses import dataclass

import requests

from src.exceptions import LLMError, LLMParseError


@dataclass
class LLMResponse:
    raw: str
    model: str
    usage: dict | None = None


class LLMClient:
    """OpenAI-compatible REST client using requests.

    Handles:
      - Chat Completions API (POST /chat/completions)
      - JSON parsing with fallback extraction
      - Rate limit detection and optional retry
      - Configurable model, temperature, max_tokens
    """

    def __init__(
        self,
        api_base: str | None = None,
        api_key: str | None = None,
        default_model: str = "MiniMax-M2.7",
        timeout: int = 60,
    ):
        self.api_base = api_base or os.environ.get(
            "OPENAI_API_BASE", "https://api.minimaxi.com/v1"
        ).rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.default_model = default_model
        self.timeout = timeout

        if not self.api_key:
            raise LLMError("OPENAI_API_KEY not set")

    def _post(self, payload: dict, model: str | None = None) -> dict:
        """Send a POST request to the chat completions endpoint."""
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload["model"] = model or self.default_model

        resp = requests.post(
            url, headers=headers, json=payload, timeout=self.timeout
        )

        if resp.status_code == 429:
            raise LLMError("Rate limited by LLM API", is_retryable=True)
        if resp.status_code != 200:
            raise LLMError(f"LLM API error {resp.status_code}: {resp.text[:500]}")

        return resp.json()

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> str:
        """Send a completion request. Returns raw response text."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        data = self._post(payload, model=model)
        return data["choices"][0]["message"]["content"]

    def complete_json(
        self,
        prompt: str,
        system: str | None,
        pydantic_model: Any,
        model: str | None = None,
    ) -> Any:
        """Send a completion and parse response into a Pydantic model."""
        raw = self.complete(prompt, system=system, model=model, temperature=0.0, max_tokens=500)
        parsed = self._extract_json(raw)
        if parsed is None:
            raise LLMParseError(f"Failed to parse JSON from: {raw[:200]}")
        try:
            return pydantic_model(**parsed)
        except Exception as e:
            raise LLMParseError(f"Failed to validate JSON: {e}") from e

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """Extract JSON object from LLM response text (handles markdown, truncation)."""
        text = text.strip()
        # Strip markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        # Find JSON bounds
        first = text.find("{")
        last = text.rfind("}")
        if first != -1 and last != -1 and last >= first:
            try:
                return json.loads(text[first : last + 1])
            except json.JSONDecodeError:
                pass
        # Try as bare JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None