import hashlib
from pathlib import Path

from app.services.storage.base import StoredObject


class S3CompatibleStorageService:
    def __init__(self, client, bucket: str):
        self.client = client
        self.bucket = bucket

    def save(self, data: bytes, *, file_name: str, project_id: int | None = None) -> StoredObject:
        self.scan(data, file_name)
        digest = hashlib.sha256(data).hexdigest()
        key = f"projects/{project_id or 0}/{digest[:2]}/{digest}{Path(file_name).suffix.lower()}"
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ServerSideEncryption="AES256")
        return StoredObject(key, len(data), digest)

    def read(self, storage_key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=storage_key)["Body"].read()

    def delete(self, storage_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=storage_key)

    def is_ready(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False

    def scan(self, data: bytes, file_name: str) -> None:
        if data[:2] == b"MZ" or data.startswith(b"\x7fELF"):
            raise ValueError("Executable files are not allowed")
