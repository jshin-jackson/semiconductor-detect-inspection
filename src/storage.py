"""
Storage client with automatic local filesystem fallback.

When MinIO is reachable, uses MinIO (S3-compatible object storage).
When MinIO is NOT reachable (e.g. CML sandbox without K8s services),
falls back to storing files in the local project filesystem under
data/local_storage/.  The API returns a local:// URI in that case.

This makes the AMP fully self-contained without any external dependencies.
"""

from __future__ import annotations

import io
import logging
import os
from typing import Any

logger = logging.getLogger("api.storage")


class StorageClient:
    """
    Unified storage client.

    Tries MinIO first; if unreachable, automatically switches to
    LocalStorageClient which stores files in data/local_storage/.
    """

    def __new__(cls, config: dict[str, Any]) -> "StorageClient":
        """Try MinIO; fall back to local storage on any connection error."""
        try:
            client = _MinIOClient(config)
            logger.info("Storage: MinIO connected  endpoint=%s", config["endpoint"])
            return client          # type: ignore[return-value]
        except Exception as e:
            logger.warning("Storage: MinIO NOT available (%s) — using local filesystem fallback.", e)
            return _LocalClient(config)   # type: ignore[return-value]


class _MinIOClient:
    """MinIO (S3-compatible) storage backend."""

    def __init__(self, config: dict[str, Any]) -> None:
        from minio import Minio
        from minio.error import S3Error
        import urllib3

        self._S3Error = S3Error
        self.bucket = config["bucket"]

        http_client = urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=5, read=10),
            retries=urllib3.Retry(total=1, raise_on_status=False),
        )
        self.client = Minio(
            endpoint=config["endpoint"],
            access_key=config["access_key"],
            secret_key=config["secret_key"],
            secure=config.get("secure", False),
            http_client=http_client,
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
        except self._S3Error as e:
            if e.code != "BucketAlreadyOwnedByYou":
                raise

    def upload_file(self, local_path: str, object_name: str) -> str:
        self.client.fput_object(self.bucket, object_name, local_path)
        return f"s3://{self.bucket}/{object_name}"

    def upload_bytes(self, data: bytes, object_name: str,
                     content_type: str = "application/octet-stream") -> str:
        buf = io.BytesIO(data)
        self.client.put_object(
            bucket_name=self.bucket,
            object_name=object_name,
            data=buf,
            length=len(data),
            content_type=content_type,
        )
        return f"s3://{self.bucket}/{object_name}"

    def download_file(self, object_name: str, local_path: str) -> None:
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        self.client.fget_object(self.bucket, object_name, local_path)

    def object_exists(self, object_name: str) -> bool:
        try:
            self.client.stat_object(self.bucket, object_name)
            return True
        except self._S3Error:
            return False

    def list_objects(self, prefix: str = "") -> list[str]:
        objects = self.client.list_objects(self.bucket, prefix=prefix, recursive=True)
        return [obj.object_name for obj in objects]


class _LocalClient:
    """
    Local filesystem fallback storage.

    Stores files under <project_root>/data/local_storage/<bucket>/.
    Returns local:// URIs so callers can detect which backend is in use.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.bucket = config["bucket"]
        # Resolve project root: two levels up from this file
        try:
            _here = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            _here = os.getcwd()
        self._base = os.path.join(
            os.path.dirname(_here), "data", "local_storage", self.bucket
        )
        os.makedirs(self._base, exist_ok=True)
        logger.info("Storage: local filesystem at %s", self._base)

    def _path(self, object_name: str) -> str:
        full = os.path.join(self._base, object_name.lstrip("/"))
        os.makedirs(os.path.dirname(full) or self._base, exist_ok=True)
        return full

    def upload_file(self, local_path: str, object_name: str) -> str:
        import shutil
        dest = self._path(object_name)
        shutil.copy2(local_path, dest)
        return f"local://{self.bucket}/{object_name}"

    def upload_bytes(self, data: bytes, object_name: str,
                     content_type: str = "application/octet-stream") -> str:
        dest = self._path(object_name)
        with open(dest, "wb") as f:
            f.write(data)
        return f"local://{self.bucket}/{object_name}"

    def download_file(self, object_name: str, local_path: str) -> None:
        import shutil
        src = self._path(object_name)
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        shutil.copy2(src, local_path)

    def object_exists(self, object_name: str) -> bool:
        return os.path.isfile(self._path(object_name))

    def list_objects(self, prefix: str = "") -> list[str]:
        base = os.path.join(self._base, prefix.lstrip("/"))
        result = []
        if not os.path.isdir(base):
            return result
        for root, _, files in os.walk(base):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, self._base)
                result.append(rel.replace(os.sep, "/"))
        return result
