"""Sparki image generation module.

Provides Gemini-based cover image generation with multi-model fallback,
category-based style keywords, and GCS upload support.
"""

from src.image_gen.client import GeminiImageClient
from src.image_gen.style import build_image_prompt
from src.image_gen.gcs import upload_to_gcs

__all__ = [
    "GeminiImageClient",
    "build_image_prompt",
    "upload_to_gcs",
]