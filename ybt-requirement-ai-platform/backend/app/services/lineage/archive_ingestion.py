from __future__ import annotations

import stat
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from app.services.lineage.ingestion import ALLOWED_SCRIPT_EXTENSIONS, validate_script_path


@dataclass(frozen=True)
class ArchivedScript:
    relative_path: str
    file_name: str
    content: bytes


def read_safe_script_archive(
    data: bytes,
    *,
    max_archive_bytes: int = 20 * 1024 * 1024,
    max_total_bytes: int = 100 * 1024 * 1024,
    max_file_count: int = 2000,
    max_file_bytes: int = 10 * 1024 * 1024,
    max_compression_ratio: int = 100,
) -> list[ArchivedScript]:
    if len(data) > max_archive_bytes:
        raise ValueError("ZIP archive is too large")
    try:
        archive = ZipFile(BytesIO(data))
    except BadZipFile as exc:
        raise ValueError("Invalid ZIP archive") from exc
    with archive:
        entries = [item for item in archive.infolist() if not item.is_dir()]
        if len(entries) > max_file_count:
            raise ValueError("ZIP archive contains too many files")
        if sum(item.file_size for item in entries) > max_total_bytes:
            raise ValueError("ZIP archive uncompressed size exceeds the limit")
        result: list[ArchivedScript] = []
        for item in entries:
            normalized = item.filename.replace("\\", "/")
            try:
                safe_path = validate_script_path(normalized)
            except ValueError as exc:
                raise ValueError(f"ZIP entry has an unsafe path: {item.filename}") from exc
            mode = item.external_attr >> 16
            if mode and stat.S_ISLNK(mode):
                raise ValueError(f"ZIP symbolic links are not allowed: {item.filename}")
            suffix = PurePosixPath(safe_path).suffix.lower()
            if suffix in {".zip", ".tar", ".gz", ".7z", ".rar"}:
                raise ValueError("Nested archives are not allowed")
            if suffix not in ALLOWED_SCRIPT_EXTENSIONS:
                continue
            if item.file_size > max_file_bytes:
                raise ValueError(f"ZIP entry exceeds the single-file limit: {item.filename}")
            compressed = max(item.compress_size, 1)
            if item.file_size / compressed > max_compression_ratio:
                raise ValueError(f"ZIP entry compression ratio exceeds the limit: {item.filename}")
            content = archive.read(item)
            if len(content) != item.file_size:
                raise ValueError(f"ZIP entry size changed while reading: {item.filename}")
            result.append(ArchivedScript(safe_path, PurePosixPath(safe_path).name, content))
        return result
