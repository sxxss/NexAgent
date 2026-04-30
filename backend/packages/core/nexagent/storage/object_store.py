"""Object-store adapter for production knowledge files.

The production path uses MinIO. A local filesystem implementation is kept as a
development/test fallback and always marks itself as degraded in diagnostics.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path

from nexagent.config import get_config


@dataclass
class ObjectWriteResult:
    uri: str
    bucket: str
    object_name: str
    degraded: bool = False


class ObjectStore:
    def put_bytes(self, bucket: str, object_name: str, data: bytes, content_type: str = "application/octet-stream") -> ObjectWriteResult:
        raise NotImplementedError

    def get_bytes(self, uri: str) -> bytes:
        raise NotImplementedError

    def delete(self, uri: str) -> None:
        raise NotImplementedError

    def status(self) -> dict:
        raise NotImplementedError


class MinioObjectStore(ObjectStore):
    def __init__(self) -> None:
        cfg = get_config().knowledge
        try:
            from minio import Minio
        except ImportError as exc:
            raise RuntimeError("minio package is not installed") from exc
        self._client = Minio(
            cfg.object_store_endpoint,
            access_key=cfg.object_store_access_key,
            secret_key=cfg.object_store_secret_key,
            secure=cfg.object_store_secure,
        )

    def put_bytes(self, bucket: str, object_name: str, data: bytes, content_type: str = "application/octet-stream") -> ObjectWriteResult:
        self._ensure_bucket(bucket)
        self._client.put_object(bucket, object_name, io.BytesIO(data), length=len(data), content_type=content_type)
        return ObjectWriteResult(uri=f"minio://{bucket}/{object_name}", bucket=bucket, object_name=object_name)

    def get_bytes(self, uri: str) -> bytes:
        bucket, object_name = _parse_object_uri(uri)
        response = self._client.get_object(bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def delete(self, uri: str) -> None:
        bucket, object_name = _parse_object_uri(uri)
        self._client.remove_object(bucket, object_name)

    def status(self) -> dict:
        try:
            self._client.list_buckets()
            return {"status": "ok", "provider": "minio"}
        except Exception as exc:
            return {"status": "unavailable", "provider": "minio", "reason": str(exc)}

    def _ensure_bucket(self, bucket: str) -> None:
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)


class LocalObjectStore(ObjectStore):
    def __init__(self) -> None:
        root = Path(os.environ.get("NEXAGENT_DATA_DIR", str(Path.home() / ".nexagent"))) / "object-store"
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, bucket: str, object_name: str, data: bytes, content_type: str = "application/octet-stream") -> ObjectWriteResult:
        path = self.root / bucket / object_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return ObjectWriteResult(uri=f"local-object://{bucket}/{object_name}", bucket=bucket, object_name=object_name, degraded=True)

    def get_bytes(self, uri: str) -> bytes:
        bucket, object_name = _parse_object_uri(uri)
        return (self.root / bucket / object_name).read_bytes()

    def delete(self, uri: str) -> None:
        bucket, object_name = _parse_object_uri(uri)
        path = self.root / bucket / object_name
        if path.exists():
            path.unlink()

    def status(self) -> dict:
        return {
            "status": "degraded",
            "provider": "local",
            "reason": "MinIO is unavailable or disabled; local object-store fallback is active.",
            "root": str(self.root),
        }


def get_object_store() -> ObjectStore:
    if os.environ.get("NEXAGENT_OBJECT_STORE", "minio").lower() == "local":
        return LocalObjectStore()
    try:
        store = MinioObjectStore()
        status = store.status()
        if status.get("status") == "ok":
            return store
    except Exception:
        pass
    return LocalObjectStore()


def _parse_object_uri(uri: str) -> tuple[str, str]:
    value = str(uri or "")
    for prefix in ("minio://", "local-object://"):
        if value.startswith(prefix):
            rest = value[len(prefix):]
            bucket, _, object_name = rest.partition("/")
            if bucket and object_name:
                return bucket, object_name
    raise ValueError(f"Invalid object-store URI: {uri}")
