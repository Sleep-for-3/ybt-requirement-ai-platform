"""需求覆盖了监管表的哪些字段，没覆盖的又是什么性质。

为什么单做这一个视图：脚本自动建的需求只纳入"脚本里能对上号"的字段，比如 `T_1_3` 员工表有 248 个
监管字段，从脚本建出来的需求只覆盖 29 个。导出文档本身是完整的（模板里有的列都在），但**没进需求
范围的字段在文档里没有正文、没有证据**，而文档上不会写"这里少了 219 个字段"。评审拿着文档看，看不出
覆盖缺口。

所以这里只回答一件事：这张监管表一共多少字段、有多少进了本需求、没进的分别是什么情况——

- ``mapped``：模板里有集市映射（说明监管口径确实要求填这列），属于"应为但没为"；
- ``script_only``：脚本血缘里出现过但没有纳入需求，属于"有来源但没进范围"；
- ``unreferenced``：既没有集市映射、也没有脚本血缘，多数是系统字段或本需求不涉及的列。

三类的后续动作完全不同，混成一个"缺 219 个字段"没有可操作性。这个视图**不改需求、不补字段、不写任何
库**：补字段等于改需求范围，要走人工确认与重新生成，不能由一次只读核对替人决定。

口径边界：
- 只按 ``scope_json.field_ids`` 判断"进没进范围"，不看正文写没写——正文缺失另有缺口清单管；
- 集市映射看 ``MartToYbtMapping.target_field_id``；脚本血缘看 ``LineageNode.target_field_id``；
- 需求没绑定监管表时返回 ``table=None`` 与全 0 计数，不猜它属于哪张表。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MartToYbtMapping, Requirement, TargetField, TargetTable
from app.models.lineage import LineageNode

COVERAGE_VERSION = "requirement-field-coverage-v1"
DEFAULT_SAMPLE = 200

UNCOVERED_BUCKETS = ("mapped", "script_only", "unreferenced")
BUCKET_LABELS = {
    "mapped": "模板要求填，且有集市映射",
    "script_only": "脚本血缘里出现过，但没纳入需求",
    "unreferenced": "既无集市映射、也无脚本血缘",
}
BUCKET_HINTS = {
    "mapped": "这几列在模板里有对应集市字段，缺了文档就答不上模板问题——优先补。",
    "script_only": "脚本里取过这些列，说明有事实来源，只是建需时没纳入范围。",
    "unreferenced": "多半是系统字段或本需求不涉及的列，可以留空，但要让看文档的人知道。",
}


class CoverageError(Exception):
    """覆盖核对的前置条件不满足（目前只有需求不存在或不属于该项目）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _scope_ids(requirement: Requirement) -> set[int]:
    raw = (requirement.scope_json or {}).get("field_ids") or []
    ids: set[int] = set()
    for value in raw:
        if isinstance(value, int):
            ids.add(value)
        elif isinstance(value, str) and value.isdigit():
            ids.add(int(value))
    return ids


def _mapping_statuses(db: Session, field_ids: list[int]) -> dict[int, list[str]]:
    if not field_ids:
        return {}
    rows = db.execute(
        select(MartToYbtMapping.target_field_id, MartToYbtMapping.mapping_status).where(
            MartToYbtMapping.target_field_id.in_(field_ids)
        )
    ).all()
    statuses: dict[int, list[str]] = {}
    for field_id, status in rows:
        text = str(status or "").strip()
        if not text:
            continue
        bucket = statuses.setdefault(int(field_id), [])
        if text not in bucket:
            bucket.append(text)
    return statuses


def _lineage_field_ids(db: Session, project_id: int, field_ids: list[int]) -> set[int]:
    if not field_ids:
        return set()
    rows = db.scalars(
        select(LineageNode.target_field_id).where(
            LineageNode.project_id == project_id,
            LineageNode.target_field_id.in_(field_ids),
        )
    ).all()
    return {int(value) for value in rows if value is not None}


def build_field_coverage(
    db: Session,
    project_id: int,
    requirement_id: int,
    *,
    sample: int = DEFAULT_SAMPLE,
) -> dict[str, Any]:
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or int(requirement.project_id) != int(project_id):
        raise CoverageError("requirement_not_found", "需求不存在或不属于这个项目。")

    scope_ids = _scope_ids(requirement)
    table_id = (requirement.scope_json or {}).get("target_table_id")
    table = db.get(TargetTable, int(table_id)) if table_id else None

    if table is None:
        return {
            "coverage_version": COVERAGE_VERSION,
            "requirement_id": requirement.id,
            "requirement_name": requirement.name,
            "table": None,
            "counts": {
                "table_fields": 0,
                "covered": 0,
                "uncovered": 0,
                "outside_scope": len(scope_ids),
                "buckets": {name: 0 for name in UNCOVERED_BUCKETS},
            },
            "bucket_labels": dict(BUCKET_LABELS),
            "bucket_hints": dict(BUCKET_HINTS),
            "uncovered": [],
            "outside_scope_fields": [],
            "note": "这条需求没有绑定监管表，无法核对字段覆盖；先在工作台绑定监管表再来看。",
        }

    table_fields = list(
        db.scalars(
            select(TargetField)
            .where(TargetField.target_table_id == table.id)
            .order_by(TargetField.field_code)
        ).all()
    )
    table_field_ids = {int(row.id) for row in table_fields}
    covered = [row for row in table_fields if int(row.id) in scope_ids]
    uncovered = [row for row in table_fields if int(row.id) not in scope_ids]

    uncovered_ids = [int(row.id) for row in uncovered]
    statuses = _mapping_statuses(db, uncovered_ids)
    lineage_ids = _lineage_field_ids(db, project_id, uncovered_ids)

    bucket_counts = {name: 0 for name in UNCOVERED_BUCKETS}
    samples: list[dict[str, Any]] = []
    for row in uncovered:
        field_id = int(row.id)
        mapped = statuses.get(field_id) or []
        if mapped:
            bucket = "mapped"
        elif field_id in lineage_ids:
            bucket = "script_only"
        else:
            bucket = "unreferenced"
        bucket_counts[bucket] += 1
        if len(samples) < max(0, int(sample)):
            samples.append(
                {
                    "field_id": field_id,
                    "field_code": row.field_code,
                    "field_name": row.field_name,
                    "required_flag": bool(row.required_flag),
                    "bucket": bucket,
                    "bucket_label": BUCKET_LABELS[bucket],
                    "mapping_statuses": mapped,
                    "in_script_lineage": field_id in lineage_ids,
                }
            )

    outside_ids = sorted(scope_ids - table_field_ids)
    outside_fields: list[dict[str, Any]] = []
    if outside_ids:
        outside_fields = [
            {"field_id": row.id, "field_code": row.field_code, "field_name": row.field_name}
            for row in db.scalars(select(TargetField).where(TargetField.id.in_(outside_ids))).all()
        ]

    note = (
        f"这张监管表共 {len(table_fields)} 个字段，本需求覆盖 {len(covered)} 个，"
        f"另有 {len(uncovered)} 个没进需求范围（其中 {bucket_counts['mapped']} 个有集市映射）。"
        "覆盖核对只列事实：不改需求、不补字段，也不代表没覆盖的字段不需要填报。"
    )

    return {
        "coverage_version": COVERAGE_VERSION,
        "requirement_id": requirement.id,
        "requirement_name": requirement.name,
        "table": {
            "id": table.id,
            "table_code": table.table_code,
            "table_name": table.table_name,
            "reporting_domain_name": table.reporting_domain_name,
        },
        "counts": {
            "table_fields": len(table_fields),
            "covered": len(covered),
            "uncovered": len(uncovered),
            "outside_scope": len(outside_fields),
            "buckets": bucket_counts,
        },
        "bucket_labels": dict(BUCKET_LABELS),
        "bucket_hints": dict(BUCKET_HINTS),
        "uncovered": samples,
        "outside_scope_fields": outside_fields,
        "note": note,
    }
