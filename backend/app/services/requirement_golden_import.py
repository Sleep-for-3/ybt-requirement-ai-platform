"""把人工标注表（CSV）导入成金标数据集，并在导入阶段就拒绝不可验收的“业务”标注。

设计原则与 ``requirement_golden_metrics`` 保持一致：

* **合成用例可以进数据集，但不能进业务正确率**；
* 标了 ``quality=business`` 却缺标注人、标注时间或证据位置的行，导入即丢弃并记录原因，
  不允许它悄悄参与业务指标计算；
* 同一 ``case_id`` 重复出现视为标注冲突，丢弃并保留原因，不做“后者覆盖前者”。

这里只做确定性解析，不调用模型、不猜测缺失值。
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.services.requirement_golden_metrics import QUALITY_LEVELS, CaseLabel, dataset_sha256

IMPORT_VERSION = "requirement-golden-import-v1"

REQUIRED_COLUMNS = ("case_id", "field_code")
OPTIONAL_COLUMNS = (
    "expected_definition",
    "expected_processing_logic",
    "required_tokens",
    "quality",
    "case_family",
    "annotator",
    "reviewer",
    "annotated_at",
    "evidence_positions",
)
KNOWN_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

TOKEN_SEPARATOR = "|"
EVIDENCE_ENTRY_SEPARATOR = ";"
EVIDENCE_FIELD_SEPARATOR = "|"


class GoldenAnnotationError(ValueError):
    """标注表结构不可用（缺必需列等），无法导入。"""

    def __init__(self, message: str, *, issues: Iterable[str] = (), missing: Iterable[str] = ()):
        super().__init__(message)
        self.issues = list(issues)
        self.missing = list(missing)


def _split_tokens(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(TOKEN_SEPARATOR) if part.strip())


def _split_evidence(value: str) -> tuple[dict[str, Any], ...]:
    entries: list[dict[str, Any]] = []
    for chunk in value.split(EVIDENCE_ENTRY_SEPARATOR):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = [part.strip() for part in chunk.split(EVIDENCE_FIELD_SEPARATOR)]
        entry: dict[str, Any] = {"source": parts[0] if parts else ""}
        if len(parts) > 1:
            page = parts[1]
            entry["page"] = int(page) if page.isdigit() else page
        if len(parts) > 2:
            entry["locator"] = parts[2]
        entries.append(entry)
    return tuple(entries)


def rows_to_cases(rows: Iterable[Mapping[str, Any]], *, default_quality: str = "synthetic") -> dict[str, Any]:
    """把已解析的行转成用例；不可验收的行被丢弃并留下原因。"""

    if default_quality not in QUALITY_LEVELS:
        raise GoldenAnnotationError(f"默认质量级别不合法：{default_quality}")
    cases: list[dict[str, Any]] = []
    issues: list[str] = []
    dropped: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, row in enumerate(rows, start=2):  # 第 1 行是表头
        case_id = str(row.get("case_id") or "").strip()
        field_code = str(row.get("field_code") or "").strip()
        if not case_id:
            dropped.append({"row": index, "case_id": "", "reason": "缺少 case_id"})
            issues.append(f"第 {index} 行缺少 case_id，已丢弃")
            continue
        if not field_code:
            dropped.append({"row": index, "case_id": case_id, "reason": "缺少 field_code"})
            issues.append(f"{case_id} 缺少 field_code，已丢弃")
            continue
        if case_id in seen:
            dropped.append({"row": index, "case_id": case_id, "reason": "case_id 重复"})
            issues.append(f"{case_id} 在第 {index} 行重复出现，已丢弃（不做覆盖）")
            continue

        quality = str(row.get("quality") or default_quality).strip() or default_quality
        raw = {
            "case_id": case_id,
            "field_code": field_code,
            "expected_definition": str(row.get("expected_definition") or "").strip(),
            "expected_processing_logic": str(row.get("expected_processing_logic") or "").strip(),
            "required_tokens": _split_tokens(str(row.get("required_tokens") or "")),
            "annotator": str(row.get("annotator") or "").strip(),
            "reviewer": str(row.get("reviewer") or "").strip(),
            "annotated_at": str(row.get("annotated_at") or "").strip(),
            "evidence_positions": _split_evidence(str(row.get("evidence_positions") or "")),
            "quality": quality,
            "case_family": str(row.get("case_family") or "default").strip() or "default",
        }
        if quality not in QUALITY_LEVELS:
            issues.append(f"{case_id} 的 quality={quality} 不被识别，按 {default_quality} 处理")
            raw["quality"] = default_quality
            quality = default_quality

        label = CaseLabel.from_mapping(raw)
        problems = label.metadata_issues()
        if problems:
            reason = "；".join(problems)
            dropped.append({"row": index, "case_id": case_id, "reason": reason})
            issues.extend(problems)
            continue

        seen.add(case_id)
        cases.append({
            "case_id": label.case_id,
            "field_code": label.field_code,
            "expected_definition": label.expected_definition,
            "expected_processing_logic": label.expected_processing_logic,
            "required_tokens": list(label.required_tokens),
            "annotator": label.annotator,
            "reviewer": label.reviewer,
            "annotated_at": label.annotated_at,
            "evidence_positions": [dict(entry) for entry in label.evidence_positions],
            "quality": label.quality,
            "case_family": label.case_family,
        })

    return {"cases": cases, "issues": issues, "dropped": dropped}


def parse_annotation_csv(text: str, *, default_quality: str = "synthetic") -> dict[str, Any]:
    """解析标注 CSV；缺必需列时直接失败，不猜测列含义。"""

    payload = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(payload))
    header = [str(name or "").strip() for name in (reader.fieldnames or [])]
    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        raise GoldenAnnotationError(
            "标注表缺少必需列：" + "、".join(missing), missing=missing)
    unknown = [column for column in header if column and column not in KNOWN_COLUMNS]
    rows = []
    for row in reader:
        rows.append({str(key or "").strip(): value for key, value in row.items()})
    result = rows_to_cases(rows, default_quality=default_quality)
    result["unknown_columns"] = unknown
    result["import_version"] = IMPORT_VERSION
    return result


def build_dataset(text: str, *, dataset_version: str = "", notes: str = "",
                  default_quality: str = "synthetic") -> dict[str, Any]:
    """产出可直接交给 ``requirement_golden_metrics.evaluate`` 的数据集字典。"""

    parsed = parse_annotation_csv(text, default_quality=default_quality)
    version = dataset_version or f"annotation-{dataset_sha256(parsed['cases'])[:12]}"
    return {
        "import_version": IMPORT_VERSION,
        "dataset_version": version,
        "notes": notes,
        "cases": parsed["cases"],
        "results": [],
        "timings": [],
        "executed_families": [],
        "issues": parsed["issues"],
        "dropped": parsed["dropped"],
        "unknown_columns": parsed["unknown_columns"],
        "dataset_sha256": dataset_sha256(parsed["cases"]),
    }


def load_annotation_csv(path: str | Path, **kwargs: Any) -> dict[str, Any]:
    return build_dataset(Path(path).read_text(encoding="utf-8"), **kwargs)
