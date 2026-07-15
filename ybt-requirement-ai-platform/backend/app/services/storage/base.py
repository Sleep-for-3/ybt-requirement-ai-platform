from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StoredObject:
    storage_key: str
    byte_size: int
    content_hash: str


class StorageService(Protocol):
    def save(self, data: bytes, *, file_name: str, project_id: int | None = None) -> StoredObject: ...
    def read(self, storage_key: str) -> bytes: ...
    def delete(self, storage_key: str) -> None: ...
    def is_ready(self) -> bool: ...
    def scan(self, data: bytes, file_name: str) -> None: ...
