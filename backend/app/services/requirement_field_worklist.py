"""项目级"待办派工清单"：把每条需求里还没做完的事按字段归并成一张可派工的表。

为什么单独做一个聚合而不是只看缺口条数：一个字段"做没做完"实际由几件互相独立的事决定——
业务口径正文是否为空、有没有固定的集市映射、有没有仍打开的字段级缺口、有没有已生成但未采纳的候选。
工作台里这四项分散在不同页签，项目负责人要派工只能逐条需求点开数；而项目看板此前只给出汇总计数，
看得到数字、派不出任务。这里只做**只读归并**：不改内容、不生成候选、不关缺口、不冻结。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Requirement,
    RequirementArtifactAttestation,
    RequirementGenerationInput,
    RequirementGenerationItem,
    RequirementRenderArtifact,
    TargetTable,
)
from app.services.requirement_delivery_status import CLOSED_GAP_STATUSES
from app.services.requirement_field_dispatch import dispatches_for_project
from app.services.requirement_rejection_followup import build_rejection_followup
from app.services.requirement_scope import document_content

WORKLIST_VERSION = "requirement-field-worklist-v3"
DEFAULT_LIMIT = 3000

# 每一项都对应"这个字段还没做完"的一个可核实原因；顺序即派工优先级（先补口径，再补来源）。
REASONS: tuple[tuple[str, str], ...] = (
    ("business_definition_missing", "缺少业务口径正文"),
    ("mart_mapping_missing", "没有固定集市映射"),
    ("open_gap", "仍有未关闭的字段级缺口"),
    ("pending_candidate", "有已生成但未采纳的候选"),
    ("artifact_rejected", "所在产物被人工核对判不通过"),
)

REASON_LABELS = dict(REASONS)

# "处置"和"缺口"是两件独立的事：登记处置不会关闭缺口。所以要把两者放在一起看，
# 否则会出现"已登记处置、却还有未关闭缺口"而没人发现的情况。
GAP_CONSISTENCY_STATES: tuple[tuple[str, str], ...] = (
    ("no_dispatch", "未登记处置"),
    ("in_progress", "处置中，缺口未清"),
    ("done_with_gaps", "已登记处置，但缺口仍未关闭"),
    ("done_clear", "已登记处置，且无未关闭缺口"),
)

GAP_CONSISTENCY_LABELS = dict(GAP_CONSISTENCY_STATES)


def _gap_consistency(dispatch: dict | None, gap_count: int) -> dict[str, Any]:
    """按（处置状态，未关闭缺口数）给四态之一，并写明为什么是这个状态。"""

    if not dispatch:
        state = "no_dispatch"
        detail = (
            f"还没有登记处置，但有 {gap_count} 条未关闭缺口" if gap_count else "还没有登记处置，也没有未关闭缺口"
        )
    elif _text(dispatch.get("status")) == "done":
        if gap_count:
            state = "done_with_gaps"
            detail = f"处置登记为「已处置，待复核」，但这个字段仍有 {gap_count} 条未关闭缺口——处置登记不会关闭缺口"
        else:
            state = "done_clear"
            detail = "处置登记为「已处置，待复核」，且没有未关闭的字段级缺口"
    else:
        state = "in_progress"
        label = dispatch.get("status_label") or dispatch.get("status") or "处理中"
        detail = f"处置登记为「{label}」，仍有 {gap_count} 条未关闭缺口" if gap_count else f"处置登记为「{label}」，没有未关闭缺口"
    return {
        "state": state,
        "label": GAP_CONSISTENCY_LABELS[state],
        "detail": detail,
        "open_gap_count": gap_count,
    }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)


def _dispatch_text(dispatch: dict | None) -> str:
    """派工单上只显示"谁·到哪一步"，不带评价——状态不等于缺口关闭。"""

    if not dispatch:
        return "未登记处置"
    owner = _text(dispatch.get("owner")) or "未填责任人"
    label = dispatch.get("status_label") or dispatch.get("status") or ""
    return f"{owner} · {label}"

def _has_business(record: dict[str, Any]) -> bool:
    business = record.get("business") or {}
    return bool(_text(business.get("business_definition")) or _text(business.get("final_content")))


def _has_mart(record: dict[str, Any]) -> bool:
    return bool(record.get("mart_mappings") or record.get("source_mappings"))


def _open_field_gap_counts(content: dict[str, Any]) -> dict[int, int]:
    counts: dict[int, int] = defaultdict(int)
    for gap in content.get("gaps") or []:
        if not isinstance(gap, dict):
            continue
        field_id = gap.get("field_id")
        status = _text(gap.get("status")).lower()
        if not isinstance(field_id, int) or isinstance(field_id, bool):
            continue
        if status in CLOSED_GAP_STATUSES:
            continue
        counts[field_id] += 1
    return dict(counts)


def _rejected_artifacts(
    db: Session, project_id: int, requirement_ids: list[int]
) -> dict[int, dict[str, Any]]:
    """哪些需求的"最新产物"被人判了「不通过」。

    只认登记落在最新产物上的那一条：重新导出后新产物没被否过，就不该继续压着整份文档。
    历史登记不覆盖、不删除，但也不替新产物背锅。
    """

    if not requirement_ids:
        return {}
    artifacts_by_requirement: dict[int, list[Any]] = {}
    for artifact_row in db.scalars(
        select(RequirementRenderArtifact)
        .where(
            RequirementRenderArtifact.project_id == project_id,
            RequirementRenderArtifact.requirement_id.in_(requirement_ids),
        )
        .order_by(RequirementRenderArtifact.id.desc())
    ):
        artifacts_by_requirement.setdefault(int(artifact_row.requirement_id), []).append(artifact_row)
    latest_attestation: dict[int, Any] = {}
    for attestation_row in db.scalars(
        select(RequirementArtifactAttestation)
        .where(
            RequirementArtifactAttestation.project_id == project_id,
            RequirementArtifactAttestation.requirement_id.in_(requirement_ids),
        )
        .order_by(RequirementArtifactAttestation.id.desc())
    ):
        if _text(attestation_row.conclusion) != "rejected":
            continue
        latest_attestation.setdefault(int(attestation_row.requirement_id), attestation_row)
    rejected: dict[int, dict[str, Any]] = {}
    for requirement_id, artifacts in artifacts_by_requirement.items():
        artifact_row = artifacts[0] if artifacts else None
        attestation_row = latest_attestation.get(requirement_id)
        if attestation_row is None or artifact_row is None:
            continue
        # 判「不通过」的那份产物可能已经不是最新的（重新导出过）。只要最新产物的内容
        # 与它相同，就是同一份正文换了个壳，红牌继续压着；内容真变了才解除。
        rejected_artifact = next(
            (entry for entry in artifacts if int(entry.id) == int(attestation_row.artifact_id)),
            None,
        )
        if rejected_artifact is None:
            continue
        if _text(rejected_artifact.content_hash) != _text(artifact_row.content_hash):
            continue
        rejected[requirement_id] = {
            "artifact_id": int(artifact_row.id),
            "file_name": artifact_row.file_name,
            "artifact_format": artifact_row.format,
            "renderer_version": artifact_row.renderer_version,
            "attestation_id": int(attestation_row.id),
            "conclusion": "rejected",
            "conclusion_label": "人工核对不通过",
            "basis": _text(attestation_row.basis),
            "scope_code": attestation_row.scope_code,
            "created_at": _iso(attestation_row.created_at),
            "content_hash": _text(rejected_artifact.content_hash),
            "on_latest_artifact": int(attestation_row.artifact_id) == int(artifact_row.id),
            "later_artifact_count": len(
                [entry for entry in artifacts if int(entry.id) > int(attestation_row.artifact_id)]
            ),
        }
    return rejected


def _pending_candidate_counts(db: Session, project_id: int) -> dict[tuple[int, int], int]:
    """按 (requirement_id, field_id) 统计"已生成但未采纳"的候选条数。"""
    statement = (
        select(
            RequirementGenerationInput.requirement_id,
            RequirementGenerationItem.field_id,
            func.count(RequirementGenerationItem.id),
        )
        .join(RequirementGenerationItem, RequirementGenerationItem.input_id == RequirementGenerationInput.id)
        .where(
            RequirementGenerationInput.project_id == project_id,
            RequirementGenerationItem.status == "completed",
            or_(
                RequirementGenerationItem.decision.is_(None),
                RequirementGenerationItem.decision == "pending",
            ),
        )
        .group_by(RequirementGenerationInput.requirement_id, RequirementGenerationItem.field_id)
    )
    return {
        (int(requirement_id), int(field_id)): int(count)
        for requirement_id, field_id, count in db.execute(statement)
    }


def build_field_worklist(db: Session, project_id: int, *, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """返回按字段归并的待办清单。

    `total` 是满足"至少有一项待办"的字段总数，`returned` 是本次返回条数——
    两者分开是为了在截断时也不把"少了"说成"没了"。
    """
    requirements = list(
        db.scalars(
            select(Requirement).where(Requirement.project_id == project_id).order_by(Requirement.id)
        )
    )
    table_cache: dict[int, Any] = {}
    pending = _pending_candidate_counts(db, project_id)
    rejected_map = _rejected_artifacts(db, project_id, [row.id for row in requirements])
    rejected_field_counts: dict[int, int] = defaultdict(int)
    rejected_gap_counts: dict[int, int] = defaultdict(int)
    rejected_pending_counts: dict[int, int] = defaultdict(int)

    dispatches = dispatches_for_project(db, project_id)
    items: list[dict[str, Any]] = []
    reason_totals: dict[str, int] = {key: 0 for key, _ in REASONS}
    gap_consistency_totals: dict[str, int] = {key: 0 for key, _ in GAP_CONSISTENCY_STATES}
    requirements_with_work = 0

    for requirement in requirements:
        content = jsonable_encoder(document_content(db, requirement))
        record_list = content.get("fields") or []
        gap_counts = _open_field_gap_counts(content)
        table_id = (content.get("target_table") or {}).get("id")
        if isinstance(table_id, int) and table_id not in table_cache:
            table_cache[table_id] = db.get(TargetTable, table_id)
        table = table_cache.get(table_id) if isinstance(table_id, int) else None
        table_code = getattr(table, "table_code", None) or (content.get("target_table") or {}).get("table_code")
        table_name = getattr(table, "table_name", None) or (content.get("target_table") or {}).get("table_name")
        # 派工单要能直接落到"那一条需求的那一个字段"：工作台按 tableId + scenarioId + requirementId
        # 三者还原需求（同表可能有多条需求），只给 requirementId 会打开另一条需求的同名字段。
        scenario_id = (content.get("scenario") or {}).get("id")
        if not isinstance(scenario_id, int) or isinstance(scenario_id, bool):
            scenario_id = None

        rejected = rejected_map.get(requirement.id)
        requirement_has_work = False
        for record in record_list:
            if not isinstance(record, dict):
                continue
            field = record.get("field") or {}
            field_id = field.get("id")
            reasons: list[str] = []
            if not _has_business(record):
                reasons.append("business_definition_missing")
            if not _has_mart(record):
                reasons.append("mart_mapping_missing")
            gap_count = gap_counts.get(field_id, 0) if isinstance(field_id, int) else 0
            if gap_count:
                reasons.append("open_gap")
            pending_count = pending.get((requirement.id, field_id), 0) if isinstance(field_id, int) else 0
            if pending_count:
                reasons.append("pending_candidate")
            if rejected:
                # 整份文档被否，受影响的是它里面每个字段——这里逐字段列出来，
                # 否则"被否了一份"就只剩一个数字，没有可派的字段。
                reasons.append("artifact_rejected")
                rejected_field_counts[requirement.id] += 1
                rejected_gap_counts[requirement.id] += gap_count
                rejected_pending_counts[requirement.id] += pending_count
            if not reasons:
                continue
            requirement_has_work = True
            for reason in reasons:
                reason_totals[reason] += 1
            dispatch = dispatches.get((requirement.id, field_id)) if isinstance(field_id, int) else None
            consistency = _gap_consistency(dispatch, gap_count)
            gap_consistency_totals[consistency["state"]] += 1
            items.append(
                {
                    "requirement_id": requirement.id,
                    "requirement_name": requirement.name,
                    "target_table_id": table_id if isinstance(table_id, int) else None,
                    "scenario_id": scenario_id,
                    "target_table_code": table_code,
                    "target_table_name": table_name,
                    "field_id": field_id,
                    "field_code": _text(field.get("field_code")) or None,
                    "field_name": _text(field.get("field_name")) or None,
                    "reasons": reasons,
                    "reason_labels": [REASON_LABELS[reason] for reason in reasons],
                    "open_gap_count": gap_count,
                    "pending_candidate_count": pending_count,
                    "primary_reason": reasons[0],
                    "dispatch": dispatch,
                    "dispatch_text": _dispatch_text(dispatch),
                    "gap_consistency": _gap_consistency(dispatch, gap_count),
                    "artifact_rejected": rejected,
                }
            )
        if requirement_has_work:
            requirements_with_work += 1

    # 派工顺序：待办项多的字段优先，再按监管表/字段代码稳定排序，便于两次导出对得上。
    items.sort(
        key=lambda item: (
            -len(item["reasons"]),
            str(item.get("target_table_code") or ""),
            str(item.get("field_code") or ""),
            item["requirement_id"],
            int(item.get("field_id") or 0),
        )
    )
    returned = items[:limit]
    rejected_requirements: list[dict[str, Any]] = []
    for requirement in requirements:
        rejected = rejected_map.get(requirement.id)
        if not rejected:
            continue
        content = jsonable_encoder(document_content(db, requirement))
        table_id = (content.get("target_table") or {}).get("id")
        rejected_requirements.append(
            {
                "requirement_id": requirement.id,
                "requirement_name": requirement.name,
                "target_table_id": table_id if isinstance(table_id, int) else None,
                "target_table_code": (content.get("target_table") or {}).get("table_code"),
                "field_count": rejected_field_counts.get(requirement.id, 0),
                "open_gap_count": rejected_gap_counts.get(requirement.id, 0),
                "pending_candidate_count": rejected_pending_counts.get(requirement.id, 0),
                **rejected,
            }
        )
    return {
        "worklist_version": WORKLIST_VERSION,
        "project_id": project_id,
        "requirement_count": len(requirements),
        "requirements_with_work": requirements_with_work,
        "reason_labels": REASON_LABELS,
        "reason_totals": reason_totals,
        "gap_consistency_labels": GAP_CONSISTENCY_LABELS,
        "gap_consistency_totals": gap_consistency_totals,
        "rejected_requirement_count": len(rejected_requirements),
        "rejected_requirements": rejected_requirements,
        # 被否之后的跟随核对：重新导出的那份内容到底变了没有（只描述事实，不做判定）。
        "rejection_followup": build_rejection_followup(db, project_id),
        "field_count": len(items),
        "returned": len(returned),
        "truncated": len(returned) < len(items),
        "items": returned,
        "note": (
            "这份清单只是把四处已有的待办归并到字段维度：业务口径正文是否为空、有没有固定集市映射、"
            "有没有仍打开的字段级缺口、有没有已生成但未采纳的候选；"
            "最新产物被人判「不通过」的文档，它里面的字段也会一并列进来。它不判断口径对错，"
            "也不改变任何内容——补齐仍在工作台完成。处置登记不会让被否的产物重新变成可交付。"
        ),
    }
