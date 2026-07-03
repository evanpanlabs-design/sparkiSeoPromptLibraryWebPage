"""Rate-limit-safe image generator — parallel + retry-safe batch mode.

Used by tool_generate_images to safely generate images for the prompt pool
without hitting Vertex AI rate limits.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock

from src.image_gen.client import GeminiImageClient


class RateLimitSafeGenerator:
    """Thread-safe image generator with 2s interval, per-thread retry, and batch parallelism.

    Uses a ThreadPoolExecutor to run multiple generation tasks in parallel,
    with each thread enforcing its own 2s interval. Each task has its own
    retry with exponential backoff for rate-limit errors.
    """

    def __init__(
        self,
        interval: float = 2.0,
        project: str = "sparki-op",
        location: str = "global",
        gcs_bucket: str = "sparki-op-test",
        max_workers: int = 3,
        max_retries: int = 3,
        retry_delay_base: float = 2.0,
    ):
        self.interval = interval
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.retry_delay_base = retry_delay_base
        self._client = GeminiImageClient(
            project=project,
            location=location,
            gcs_bucket=gcs_bucket,
        )

    def _generate_one(self, item: dict) -> dict:
        """Generate a single image with per-task retry and rate-limit interval.

        Returns dict with keys: prompt_id, gcs_url, error, model_used.
        """
        prompt_id = item["prompt_id"]
        prompt_text = item["prompt_text"]
        category = item["category"]

        # Rate-limit enforcement per call (including retries)
        time.sleep(self.interval)

        last_error = None
        for attempt in range(self.max_retries):
            try:
                # title is passed as "" — build_image_prompt no longer uses it
                # to avoid text/label artifacts appearing in the cover image.
                image_bytes, model, gcs_url = self._client.generate(
                    prompt_text=prompt_text,
                    category=category,
                    title="",
                    tweet_id=str(prompt_id),
                )
                return {
                    "prompt_id": prompt_id,
                    "gcs_url": gcs_url,
                    "error": None,
                    "model_used": model,
                }
            except Exception as e:
                last_error = e
                err_str = str(e)
                # Rate-limit: wait then retry
                if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str:
                    if attempt < self.max_retries - 1:
                        delay = self.retry_delay_base * (2 ** attempt)
                        time.sleep(delay)
                        continue
                # Other error: no retry
                break

        return {
            "prompt_id": prompt_id,
            "gcs_url": None,
            "error": str(last_error) if last_error else "unknown",
            "model_used": None,
        }

    def generate_batch(self, items: list[dict]) -> list[dict]:
        """Generate cover images in parallel with retry.
    
        Args:
            items: list of dicts with keys: prompt_id, prompt_text, category

        Returns:
            list of result dicts (same order as input), each with:
                prompt_id, gcs_url, error, model_used
        """
        results = []
        lock = Lock()
        done = 0
        total = len(items)

        def worker(item: dict) -> dict:
            return self._generate_one(item)

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {ex.submit(worker, item): item for item in items}
            for fut in as_completed(futures):
                result = fut.result()
                results.append(result)
                with lock:
                    done += 1
                    ok = sum(1 for r in results if r.get("gcs_url"))
                    print(f"  [image_gen] {done}/{total} done, {ok} OK, {done - ok} failed")

        return results

    # Legacy single-shot method — kept for backwards compatibility
    def generate(self, prompt: str, category: str, prompt_id: int | str) -> str | None:
        """Generate a single cover image. Returns GCS URL or None."""
        result = self._generate_one({
            "prompt_id": str(prompt_id),
            "prompt_text": prompt,
            "category": category,
        })
        return result.get("gcs_url")