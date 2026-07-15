import hashlib
from pathlib import Path

from app.services.storage.base import StoredObject


class LocalStorageService:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, *, file_name: str, project_id: int | None = None) -> StoredObject:
        self.scan(data, file_name)
        suffix = Path(file_name).suffix.lower()
        digest = hashlib.sha256(data).hexdigest()
        storage_key = f"projects/{project_id or 0}/{digest[:2]}/{digest}{suffix}"
        target = self._resolve(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return StoredObject(storage_key=storage_key, byte_size=len(data), content_hash=digest)

    def read(self, storage_key: str) -> bytes:
        return self._resolve(storage_key).read_bytes()

    def delete(self, storage_key: str) -> None:
        target = self._resolve(storage_key)
        if target.exists():
            target.unlink()

    def is_ready(self) -> bool:
        return self.root.exists() and self.root.is_dir()

    def scan(self, data: bytes, file_name: str) -> None:
        # Seam reserved for ICAP/ClamAV adapters. Local MVP rejects executable signatures.
        if data[:2] == b"MZ" or data.startswith(b"\x7fELF"):
            raise ValueError("Executable files are not allowed")

    def _resolve(self, storage_key: str) -> Path:
        target = (self.root / storage_key).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError("Invalid storage key")
        return target
