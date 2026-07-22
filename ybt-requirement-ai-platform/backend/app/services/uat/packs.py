from __future__ import annotations

from io import BytesIO
from pathlib import PurePosixPath
import mimetypes
import zipfile

from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.models import Project, StoredFile, UatPack, UatPackItem
from app.services.storage import get_storage_service


ALLOWED_EXTENSIONS = {".xlsx", ".sql", ".sh", ".md", ".json"}
REQUIRED_MATERIAL_TYPES = {"target_template", "delivery_template", "historical_business_caliber", "historical_technical_lineage", "regulatory_qa", "data_dictionary", "source_sql", "uat_instruction"}
EXECUTABLE_EXTENSIONS = {".exe", ".dll", ".com", ".bat", ".cmd", ".ps1", ".msi", ".scr", ".jar"}


def create_uat_pack(db: Session, project: Project, pack_name: str, uploads: list[tuple[str, bytes]], created_by: int | None) -> UatPack:
    entries: list[tuple[str, bytes]] = []
    settings = Settings()
    for file_name, data in uploads:
        if len(data) > settings.max_upload_bytes:
            raise ValueError("Uploaded UAT file exceeds the compressed upload limit")
        if PurePosixPath(file_name).suffix.lower() == ".zip":
            entries.extend(_read_zip(data, settings))
        else:
            entries.append((_safe_relative_path(file_name), data))
    if not entries:
        raise ValueError("UAT pack contains no supported files")
    if len(entries) > settings.uat_zip_max_file_count:
        raise ValueError("UAT pack contains too many files")
    if len({name.casefold() for name, _ in entries}) != len(entries):
        raise ValueError("UAT pack contains duplicate file paths")
    storage = get_storage_service()
    for name, data in entries:
        _validate_entry(name, data, settings)
        storage.scan(data, name)
    pack = UatPack(institution_id=project.institution_id, project_id=project.id, pack_name=pack_name[:255], status="uploaded", manifest_json={}, validation_json={}, created_by=created_by)
    db.add(pack); db.flush()
    manifest = []
    for relative_path, data in entries:
        original_name = PurePosixPath(relative_path).name
        saved = storage.save(data, file_name=original_name, project_id=project.id)
        stored = StoredFile(institution_id=project.institution_id or 0, project_id=project.id, storage_key=saved.storage_key, original_file_name=original_name, content_type=mimetypes.guess_type(original_name)[0] or "application/octet-stream", byte_size=saved.byte_size, content_hash=saved.content_hash, classification="internal", created_by=created_by or 0, enabled=True)
        db.add(stored); db.flush()
        material_type = classify_material(relative_path)
        item = UatPackItem(project_id=project.id, uat_pack_id=pack.id, stored_file_id=stored.id, relative_path=relative_path, original_file_name=original_name, material_type=material_type, content_hash=saved.content_hash, byte_size=saved.byte_size)
        db.add(item); db.flush()
        manifest.append({"item_id": item.id, "relative_path": relative_path, "material_type": material_type, "content_hash": saved.content_hash, "byte_size": saved.byte_size})
    pack.manifest_json = {"file_count": len(manifest), "total_bytes": sum(item["byte_size"] for item in manifest), "items": manifest}
    db.commit()
    return pack


def validate_uat_pack(pack: UatPack, items: list[UatPackItem]) -> dict:
    present = {item.material_type for item in items}
    missing = sorted(REQUIRED_MATERIAL_TYPES - present)
    result = {"valid": not missing, "present_material_types": sorted(present), "missing_material_types": missing, "file_count": len(items), "blocking_reasons": [{"code": "missing_material", "material_type": item} for item in missing]}
    pack.validation_json = result
    pack.status = "valid" if result["valid"] else "invalid"
    return result


def classify_material(path: str) -> str:
    name = PurePosixPath(path).name.lower()
    if "一表通" in name and "目标" in name:
        return "target_template"
    if "正式交付" in name:
        return "delivery_template"
    if "历史业务" in name:
        return "historical_business_caliber"
    if "历史技术" in name:
        return "historical_technical_lineage"
    if "监管答疑" in name:
        return "regulatory_qa"
    if "数据字典" in name:
        return "data_dictionary"
    if name.endswith(".sql"):
        return "source_sql"
    if name.endswith(".sh"):
        return "shell_script"
    if "expected" in name:
        return "expected_output"
    if name.endswith(".md"):
        return "uat_instruction"
    return "other"


def _read_zip(data: bytes, settings: Settings) -> list[tuple[str, bytes]]:
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid UAT ZIP archive") from exc
    files = [item for item in archive.infolist() if not item.is_dir() and not item.filename.replace("\\", "/").startswith("__MACOSX/")]
    if len(files) > settings.uat_zip_max_file_count:
        raise ValueError("UAT ZIP contains too many files")
    if sum(item.file_size for item in files) > settings.uat_zip_max_total_bytes:
        raise ValueError("UAT ZIP extracted size exceeds the limit")
    result = []
    for info in files:
        path = _safe_relative_path(info.filename)
        if info.file_size > settings.uat_file_max_bytes:
            raise ValueError("A UAT ZIP member exceeds the per-file limit")
        content = archive.read(info)
        if len(content) != info.file_size:
            raise ValueError("UAT ZIP member size does not match its manifest")
        result.append((path, content))
    return result


def _safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} or ":" in part for part in path.parts):
        raise ValueError("Unsafe path in UAT pack")
    if any(part.lower() == ".git" for part in path.parts) or "hooks" in {part.lower() for part in path.parts}:
        raise ValueError("Git metadata and hooks are not allowed in UAT packs")
    return "/".join(path.parts)


def _validate_entry(name: str, data: bytes, settings: Settings) -> None:
    extension = PurePosixPath(name).suffix.lower()
    if extension in EXECUTABLE_EXTENSIONS or extension not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported UAT file extension: {extension or '[none]'}")
    if len(data) > settings.uat_file_max_bytes:
        raise ValueError("UAT file exceeds the per-file limit")
