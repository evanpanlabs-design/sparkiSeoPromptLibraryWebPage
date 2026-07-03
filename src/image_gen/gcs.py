"""GCS upload helpers for image generation outputs."""

from google.cloud import storage


def upload_to_gcs(local_path: str, dest_blob: str, bucket: str) -> str:
    """Upload a local file to GCS.

    Args:
        local_path: Path to the local image file.
        dest_blob: GCS blob path (e.g., "prompts/cinematic/2026-05/1/1.png").
        bucket: GCS bucket name.

    Returns:
        gs:// URL (e.g., "gs://sparki-op-test/prompts/cinematic/2026-05/1/1.png").
    """
    client = storage.Client()
    bucket_obj = client.bucket(bucket)
    blob = bucket_obj.blob(dest_blob)
    blob.upload_from_filename(local_path, content_type="image/png")
    return f"gs://{bucket}/{dest_blob}"


def upload_bytes_to_gcs(image_bytes: bytes, dest_blob: str, bucket: str) -> str:
    """Upload raw image bytes to GCS.

    Args:
        image_bytes: Raw PNG image bytes.
        dest_blob: GCS blob path.
        bucket: GCS bucket name.

    Returns:
        gs:// URL.
    """
    client = storage.Client()
    bucket_obj = client.bucket(bucket)
    blob = bucket_obj.blob(dest_blob)
    blob.upload_from_string(image_bytes, content_type="image/png")
    return f"gs://{bucket}/{dest_blob}"