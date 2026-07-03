"""Gemini image generation client with multi-model fallback."""

import os
import random
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from threading import Lock

from PIL import Image

from google import genai
from google.genai.types import GenerateContentConfig, Modality

from src.exceptions import ImageGenError, RateLimitError


MODELS = [
    "gemini-2.5-flash-image",
    "gemini-3-pro-image-preview",
    "gemini-3.1-flash-image-preview",
]


class GeminiImageClient:
    """Gemini image generation client with multi-model fallback and Vertex AI mode."""

    def __init__(
        self,
        project: str = "sparki-op",
        location: str = "global",
        gcs_bucket: str = "sparki-op-test",
        max_retries_per_model: int = 3,
        retry_delay_base: int = 5,
        models: list[str] | None = None,
    ):
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project)
        os.environ.setdefault("GOOGLE_CLOUD_LOCATION", location)
        os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
        self._client = genai.Client()
        self._gcs_bucket = gcs_bucket
        self._max_retries = max_retries_per_model
        self._retry_delay_base = retry_delay_base
        self._models = models or list(MODELS)

    def generate(
        self,
        prompt_text: str,
        category: str,
        title: str,
        tweet_id: str = "",
    ) -> tuple[bytes, str, str]:
        """Generate a cover image with multi-model fallback.

        Returns:
            tuple[image_bytes, model_used, gcs_url]
            Raises ImageGenError if all models fail.
        """
        from src.image_gen.style import build_image_prompt
        image_prompt = build_image_prompt(prompt_text, category, title)

        last_error = None
        for model_name in self._models:
            for attempt in range(self._max_retries):
                try:
                    response = self._client.models.generate_content(
                        model=model_name,
                        contents=image_prompt,
                        config=GenerateContentConfig(
                            response_modalities=[Modality.TEXT, Modality.IMAGE],
                        ),
                    )
                    image_bytes = self._extract_image_bytes(response)
                    if image_bytes is None:
                        raise ImageGenError(f"No image in response from {model_name}")
                    gcs_url = self._upload_image_bytes(
                        image_bytes, category, tweet_id or prompt_text[:20]
                    )
                    return image_bytes, model_name, gcs_url
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str:
                        if attempt < self._max_retries - 1:
                            wait = (attempt + 1) * self._retry_delay_base + random.uniform(0, 3)
                            _time.sleep(wait)
                            continue
                        # Exhausted retries on this model — wait before next model
                        _time.sleep(self._retry_delay_base + random.uniform(0, 5))
                    break
        raise ImageGenError(f"All models exhausted: {last_error}")

    def _extract_image_bytes(self, response) -> bytes | None:
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                return part.inline_data.data
        return None

    def _upload_image_bytes(
        self,
        image_bytes: bytes,
        category: str,
        tweet_id: str,
    ) -> str:
        from src.image_gen.gcs import upload_bytes_to_gcs
        now_dt = datetime.now(timezone.utc)
        yyyy_mm = now_dt.strftime("%Y-%m")
        gcs_blob = f"prompts/{category}/{yyyy_mm}/{tweet_id}.png"
        return upload_bytes_to_gcs(image_bytes, gcs_blob, self._gcs_bucket)

    def generate_batch(
        self,
        items: list[dict],
        concurrency: int = 3,
    ) -> list[dict]:
        """Generate cover images concurrently.

        Args:
            items: list of dicts with keys: tweet_id, prompt_text, category, title
            concurrency: max concurrent Gemini calls

        Returns:
            list of dicts with keys: tweet_id, image_bytes, model_used, gcs_url, error
        """
        results = []
        done = 0
        failed = 0
        total = len(items)
        lock = Lock()

        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            futures = {}
            for item in items:
                fut = ex.submit(self._generate_one, item)
                futures[fut] = item["tweet_id"]

            for fut in as_completed(futures):
                tid = futures[fut]
                try:
                    result = fut.result()
                except Exception as e:
                    result = {"tweet_id": tid, "error": str(e)}
                with lock:
                    done += 1
                    if result.get("error"):
                        failed += 1
                    if done % max(1, total // 20) == 0 or done == total:
                        print(f"  [image_gen] {done}/{total} done, {failed} failed")
                results.append(result)

        return results

    def _generate_one(self, item: dict) -> dict:
        tweet_id = item.get("tweet_id", "")
        try:
            image_bytes, model_used, gcs_url = self.generate(
                prompt_text=item["prompt_text"],
                category=item["category"],
                title=item["title"],
                tweet_id=tweet_id,
            )
            print(f"  [image] OK  {tweet_id}  model={model_used}")
            return {
                "tweet_id": tweet_id,
                "image_bytes": image_bytes,
                "model_used": model_used,
                "gcs_url": gcs_url,
                "error": None,
            }
        except Exception as e:
            print(f"  [image] FAIL {tweet_id}  {type(e).__name__}: {str(e)[:120]}")
            return {
                "tweet_id": tweet_id,
                "image_bytes": None,
                "model_used": None,
                "gcs_url": None,
                "error": str(e),
            }