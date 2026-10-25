"""批量导出归档：把多份已冻结产物打成一个可复核的 zip。

真实动机：项目里十几条需求，评审要一次性拿到"这一批"的交付文件，逐条点导出既慢又容易漏。
这里只做归档本身（纯函数、无数据库、无渲染），产物字节由调用方提供：
- 每个条目必须带"它是从哪份快照、哪条产物来的"（快照号、内容 hash、产物号、文件 hash），
  否则压缩包里的一堆同名文件无法回溯到具体版本；
- 压缩包字节必须可复现：zip 条目时间固定、不带"生成于"时间戳，同一批输入两次导出应当逐字节相同。
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO

ARCHIVE_VERSION = "requirement-batch-archive-v1"
MANIFEST_NAME = "manifest.json"
FIXED_ZIP_DATE = (2000, 1, 1, 0, 0, 0)

_MANIFEST_FIELDS = (
    "requirement_id",
    "name",
    "target_table_code",
    "snapshot_id",
    # 故意不写 snapshot_created：它记录的是"这一次调用新建了快照吗"，
    # 写进清单会让同一批内容两次导出得到不同字节（第一次 true、第二次 false），
    # 而审计要的是"这份文件来自哪份快照"，不是"这次调用做了什么"。
    # 新建条数通过响应头 X-Requirement-Batch-Snapshots-Created 给出。
    "content_hash",
    "artifact_id",
    "file_name",
    "file_sha256",
    "file_size",
    "renderer_version",
    "format",
    "layout",
)


class BatchArchiveError(RuntimeError):
    """归档参数不合法（调用方已经拿到产物，这里只是拒绝拼装）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _entry_file_name(entry: dict, used: set[str]) -> str:
    raw = str(entry.get("file_name") or "").strip()
    if not raw:
        raise BatchArchiveError("file_name_missing", "归档条目缺少文件名，无法保证可回溯")
    name = raw.replace("/", "-").replace("\\", "-")
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        stem, suffix = name, ""
    candidate = name
    index = 2
    while candidate in used:
        candidate = f"{stem}-{index}.{suffix}" if suffix else f"{stem}-{index}"
        index += 1
    used.add(candidate)
    return candidate


def build_archive(entries: list[dict], *, project_id: int) -> bytes:
    """把条目打成 zip；同一输入两次调用得到逐字节相同的压缩包。"""

    if not entries:
        raise BatchArchiveError("archive_empty", "没有可归档的产物")
    ordered = sorted(entries, key=lambda item: (int(item.get("requirement_id") or 0), str(item.get("file_name"))))
    used: set[str] = set()
    items: list[dict] = []
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for entry in ordered:
            payload = entry.get("payload")
            if not isinstance(payload, (bytes, bytearray)) or not payload:
                raise BatchArchiveError("payload_empty", "归档条目没有文件内容")
            file_name = _entry_file_name(entry, used)
            info = zipfile.ZipInfo(file_name, date_time=FIXED_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            archive.writestr(info, bytes(payload))
            items.append({key: entry.get(key) for key in _MANIFEST_FIELDS} | {"file_name": file_name})
        manifest = {
            "archive_version": ARCHIVE_VERSION,
            "project_id": project_id,
            "item_count": len(items),
            "items": items,
        }
        manifest_info = zipfile.ZipInfo(MANIFEST_NAME, date_time=FIXED_ZIP_DATE)
        manifest_info.compress_type = zipfile.ZIP_DEFLATED
        manifest_info.create_system = 3
        manifest_info.external_attr = 0o600 << 16
        archive.writestr(
            manifest_info,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
        )
    return buffer.getvalue()


def read_manifest(archive_bytes: bytes) -> dict:
    """测试与运维用：从压缩包里读回清单（不依赖文件名猜测）。"""

    with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
        return json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
