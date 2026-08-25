"""
Dual-backend storage abstraction: local filesystem (dev) or GCS (Cloud Run).

Backend is selected automatically:
- If K_SERVICE env var is set (Cloud Run), uses GCS.
- Otherwise, uses local disk under outputs/.
- STORAGE_BACKEND=local|gcs env var overrides auto-detection.

All blob_path values mirror the current local path structure:
  storyboard/{job_id}/{filename}.png
  audio/{job_id}/{filename}.wav
  video/{job_id}/{filename}.mp4
  jobs/{job_id}/manifest.json
  _assets/explainer_voice/{step_id}.wav
  _assets/demo_walkthrough/{job_id}.wav
  _meta/golden_job_id.txt
"""

import os
from abc import ABC, abstractmethod
from pathlib import Path

from loguru import logger


class StorageBackend(ABC):
    """Abstract storage interface."""

    @abstractmethod
    async def save_file(self, data: bytes, blob_path: str, content_type: str = "application/octet-stream") -> str:
        """Save bytes to storage. Returns a servable URL."""
        ...

    @abstractmethod
    async def read_file(self, blob_path: str) -> bytes | None:
        """Read bytes from storage. Returns None if not found."""
        ...

    @abstractmethod
    async def exists(self, blob_path: str) -> bool:
        """Check if a blob exists."""
        ...

    @abstractmethod
    def get_serving_url(self, blob_path: str) -> str:
        """Get a URL that can serve this file to the frontend."""
        ...


class LocalStorageBackend(StorageBackend):
    """Filesystem-backed storage (development). Files stored under outputs/."""

    def __init__(self, base_dir: str = "outputs"):
        self._base = Path(base_dir)
        self._base.mkdir(exist_ok=True)

    def _resolve(self, blob_path: str) -> Path:
        return self._base / blob_path

    async def save_file(self, data: bytes, blob_path: str, content_type: str = "application/octet-stream") -> str:
        path = self._resolve(blob_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"/static/{blob_path}"

    async def read_file(self, blob_path: str) -> bytes | None:
        path = self._resolve(blob_path)
        if not path.exists():
            return None
        return path.read_bytes()

    async def exists(self, blob_path: str) -> bool:
        return self._resolve(blob_path).exists()

    def get_serving_url(self, blob_path: str) -> str:
        return f"/static/{blob_path}"

    def local_path(self, blob_path: str) -> str:
        """Get the local filesystem path (needed for ffmpeg and wave operations)."""
        path = self._resolve(blob_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)


class GCSStorageBackend(StorageBackend):
    """Google Cloud Storage backend (production/Cloud Run)."""

    def __init__(self, bucket_name: str):
        from google.cloud import storage as gcs_lib
        self._client = gcs_lib.Client()
        self._bucket = self._client.bucket(bucket_name)
        self._bucket_name = bucket_name
        logger.info("GCS storage backend initialized: gs://{}", bucket_name)

    async def save_file(self, data: bytes, blob_path: str, content_type: str = "application/octet-stream") -> str:
        import asyncio
        blob = self._bucket.blob(blob_path)
        await asyncio.to_thread(blob.upload_from_string, data, content_type=content_type)
        return self.get_serving_url(blob_path)

    async def read_file(self, blob_path: str) -> bytes | None:
        import asyncio
        blob = self._bucket.blob(blob_path)
        if not await asyncio.to_thread(blob.exists):
            return None
        return await asyncio.to_thread(blob.download_as_bytes)

    async def exists(self, blob_path: str) -> bool:
        import asyncio
        blob = self._bucket.blob(blob_path)
        return await asyncio.to_thread(blob.exists)

    def get_serving_url(self, blob_path: str) -> str:
        """Return a direct GCS public URL for the asset.

        Uses the public storage.googleapis.com URL pattern. This requires the
        bucket to have uniform public read access (allUsers: objectViewer).
        For a hackathon demo bucket serving only generated media, this is
        appropriate and avoids the complexity/overhead of signed URLs.
        """
        return f"https://storage.googleapis.com/{self._bucket_name}/{blob_path}"

    def local_path(self, blob_path: str) -> str:
        """
        For GCS mode, download blob to a local temp location for ffmpeg/wave ops.
        Or provide a writable local path that will be uploaded after use.
        """
        # Use a local staging area for files that need filesystem access (ffmpeg, wave)
        staging = Path("/tmp/studioz_staging") / blob_path
        staging.parent.mkdir(parents=True, exist_ok=True)
        # If file exists in GCS, download it
        blob = self._bucket.blob(blob_path)
        if blob.exists():
            blob.download_to_filename(str(staging))
        return str(staging)

    async def upload_local_file(self, local_path: str, blob_path: str, content_type: str = "application/octet-stream") -> str:
        """Upload a file from local disk to GCS (for ffmpeg output, etc.)."""
        import asyncio
        blob = self._bucket.blob(blob_path)
        await asyncio.to_thread(blob.upload_from_filename, local_path, content_type=content_type)
        return self.get_serving_url(blob_path)


# ============================================================
# Module-level singleton — initialized once on import
# ============================================================

def _create_backend() -> StorageBackend:
    from studioz.config import settings

    if settings.storage_backend == "gcs":
        if not settings.gcs_bucket:
            raise ValueError(
                "STORAGE_BACKEND=gcs but GCS_BUCKET is not set. "
                "Set the GCS_BUCKET environment variable."
            )
        return GCSStorageBackend(settings.gcs_bucket)
    else:
        return LocalStorageBackend("outputs")


storage = _create_backend()


# Convenience: check if we're using GCS
def is_gcs() -> bool:
    return isinstance(storage, GCSStorageBackend)
