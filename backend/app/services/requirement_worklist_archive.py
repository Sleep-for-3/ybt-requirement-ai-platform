"""项目级待办派工清单的"按监管表分装"导出。

为什么按表分装：派工是按表派的——一张表通常交给一个人/一组人，而清单本身是 200+ 行平铺的。
把 233 行塞进一个 CSV，经办人拿到后要自己按"监管表编号"排序、自己切分；分装成"一张表一个文件"
加一份清单，才能直接分发。

两条硬约束（都是前面轮次踩出来的）：
1. **字节可复现**：同一份清单两次导出必须完全相同，所以 zip 条目时间固定、清单里不写生成时间
   （`snapshot_created` 那类"调用态"字段写进清单会让两次导出字节不同）。
2. **口径与清单一致**：CSV 的列、待办事项文案、计数全部来自服务端已经算好的 worklist，
   这里只做分组与序列化，不重算、不补充推断。
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from typing import Any

ARCHIVE_VERSION = "requirement-worklist-archive-v1"
MANIFEST_NAME = "manifest.json"
FIXED_ZIP_DATE = (2000, 1, 1, 0, 0, 0)
CSV_HEADER = (
    "监管表编号",
    "监管表名称",
    "需求",
    "字段编码",
    "字段名称",
    "待办事项",
    "打开缺口数",
    "待采纳候选数",
)
_UNSAFE_NAME = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff_-]+")
_FALLBACK_TABLE = "未登记监管表"


class WorklistArchiveError(RuntimeError):
    """导出失败时给出可读的 code/message。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _cell(value: Any) -> str:
    """CSV 单元格：全加引号、内部双写；`= + - @` 开头前置单引号防公式注入。"""
    raw = "" if value is None else str(value)
    guarded = f"'{raw}" if raw[:1] in ("=", "+", "-", "@") else raw
    return '"' + guarded.replace('"', '""') + '"'


def _table_csv(items: list[dict[str, Any]]) -> bytes:
    lines = [",".join(_cell(part) for part in CSV_HEADER)]
    for item in items:
        lines.append(
            ",".join(
                _cell(value)
                for value in (
                    item.get("target_table_code"),
                    item.get("target_table_name"),
                    item.get("requirement_name"),
                    item.get("field_code"),
                    item.get("field_name"),
                    "；".join(item.get("reason_labels") or []),
                    item.get("open_gap_count"),
                    item.get("pending_candidate_count"),
                )
            )
        )
    # BOM 让 Excel 正确识别 UTF-8；CRLF 是 Excel 的默认换行。
    return ("\ufeff" + "\r\n".join(lines) + "\r\n").encode("utf-8")


def _file_name(code: str) -> str:
    safe = _UNSAFE_NAME.sub("_", code.strip()) or _FALLBACK_TABLE
    return f"待办-{safe}.csv"


def _reason_totals(items: list[dict[str, Any]], reason_labels: dict[str, str]) -> dict[str, int]:
    totals = {key: 0 for key in reason_labels}
    for item in items:
        for reason in item.get("reasons") or []:
            if reason in totals:
                totals[reason] += 1
    return totals


def build_worklist_archive(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    """把 worklist payload 分装成 zip；返回 (bytes, manifest)。"""
    items = [item for item in (payload.get("items") or []) if isinstance(item, dict)]
    if not items:
        raise WorklistArchiveError("worklist_empty", "待办清单为空：没有可分装的字段。")

    labels = payload.get("reason_labels") or {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        code = str(item.get("target_table_code") or "").strip() or _FALLBACK_TABLE
        grouped.setdefault(code, []).append(item)

    buffer = io.BytesIO()
    tables: list[dict[str, Any]] = []
    overrides = sorted(grouped)
    used_names: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for code in overrides:
            rows = grouped[code]
            data = _table_csv(rows)
            name = _file_name(code)
            if name in used_names:
                name = name.replace(".csv", f"-{len(used_names) + 1}.csv")
            used_names.add(name)
            info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)
            tables.append(
                {
                    "target_table_code": code,
                    "target_table_name": rows[0].get("target_table_name"),
                    "file_name": name,
                    "item_count": len(rows),
                    "reason_totals": _reason_totals(rows, labels),
                    "file_sha256": hashlib.sha256(data).hexdigest(),
                }
            )

        manifest = {
            "archive_version": ARCHIVE_VERSION,
            "worklist_version": payload.get("worklist_version"),
            "project_id": payload.get("project_id"),
            "table_count": len(tables),
            "item_count": len(items),
            "reason_totals": _reason_totals(items, labels),
            "reason_labels": labels,
            "tables": tables,
            "note": (
                "按监管表分装的派工清单：一张表一个 CSV，清单里给出每份文件的 sha256 与待办原因计数。"
                "导出只读：不改内容、不冻结、不生成候选。清单里不写生成时间，"
                "同一份清单两次导出字节完全相同。"
            ),
        }
        info = zipfile.ZipInfo(MANIFEST_NAME, date_time=FIXED_ZIP_DATE)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = 0o600 << 16
        archive.writestr(info, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"))

    return buffer.getvalue(), manifest


def read_manifest(archive_bytes: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        return json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
