"""Blob storage for the live pipeline: tracking chunks (``frames``) and the workers' checkpoints (``checkpoints``).

Two implementations of one small interface: :class:`MemoryBlobs` for tests and a laptop, :class:`AzureBlobs` on Blob Storage with the identity the
service runs as (no keys). Names are plain paths (``<match>/00042.json.gz``).
"""

from __future__ import annotations

import hashlib
import hmac
import threading
from typing import Any, Protocol


class Blobs(Protocol):
    def put(self, name: str, data: bytes) -> None: ...
    def get(self, name: str) -> bytes | None: ...
    def exists(self, name: str) -> bool: ...


class MemoryBlobs:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: dict[str, bytes] = {}
        self.puts: list[str] = []  # what was written, in order (tests assert on it)

    def put(self, name: str, data: bytes) -> None:
        with self._lock:
            self._data[name] = data
            self.puts.append(name)

    def get(self, name: str) -> bytes | None:
        with self._lock:
            return self._data.get(name)

    def exists(self, name: str) -> bool:
        with self._lock:
            return name in self._data


class AzureBlobs:
    """One container of an Azure Storage account, through ``azure-storage-blob`` and an identity."""

    def __init__(self, account: str, container: str, credential: Any = None) -> None:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        service = BlobServiceClient(f"https://{account}.blob.core.windows.net", credential=credential or DefaultAzureCredential())
        self._c = service.get_container_client(container)

    def put(self, name: str, data: bytes) -> None:
        self._c.upload_blob(name, data, overwrite=True)

    def get(self, name: str) -> bytes | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return self._c.download_blob(name).readall()
        except ResourceNotFoundError:
            return None

    def exists(self, name: str) -> bool:
        return self._c.get_blob_client(name).exists()


def sign(data: bytes, key: bytes) -> bytes:
    """``data`` with an HMAC-SHA256 in front. Checkpoints are pickles; a pickle is only ever loaded if it carries a valid signature,
    so whoever can write to the storage account but does not hold the key cannot make a worker run their code."""
    return hmac.new(key, data, hashlib.sha256).digest() + data


def unsign(blob: bytes | None, key: bytes) -> bytes | None:
    if not blob or len(blob) < 32:
        return None
    mac, data = blob[:32], blob[32:]
    return data if hmac.compare_digest(mac, hmac.new(key, data, hashlib.sha256).digest()) else None
