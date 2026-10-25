"""项目级的"需求交付状态"：每条需求是否冻结、最近产物、仍打开的缺口。

为什么单独做：工作台只在单条需求里告诉用户"冻结没冻结"（round 20）与"与上一份快照差在哪"
（round 19/21）。项目负责人要回答的是"这个项目里哪些需求已经冻结、可以导出"，只能在十几条
需求之间反复点开。这里把同一批事实聚合成一行一条，判据与工作台完全一致：
`content_hash` 相同即已冻结在最近快照，绝不用版本号推断。
"""

from datetime import datetime, timezone
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    ScriptFile,
    ScriptFileVersion,
    TargetField,
    Requirement,
    RequirementArtifactAttestation,
    RequirementDelivery,
    RequirementGenerationInput,
    RequirementGenerationItem,
    RequirementFormalDelivery,
    RequirementRenderArtifact,
    TargetTable,
    User,
)
from app.services.requirement_scope import caliber_digest, content_digest, document_content

def _text(value: Any) -> str:
    """只有真正的字符串才算有内容：``None``/数字/列表一律当作"没填"。"""

    return value.strip() if isinstance(value, str) else ""


# v7：判断"被判不通过"从"同一个 artifact_id"改成"同一份 content_hash"。
# 只换版式重新导出会生成新 id，但正文没变，红牌必须继续压着。
STATUS_VERSION = "requirement-delivery-status-v7"
CLOSED_GAP_STATUSES = ("resolved", "rejected", "closed")
DEFAULT_LIMIT = 200


def _open_gaps(content: dict[str, Any]) -> tuple[int, int]:
    gaps = content.get("gaps") or []
    open_count = 0
    field_ids: set[Any] = set()
    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        if str(gap.get("status") or "open") in CLOSED_GAP_STATUSES:
            continue
        open_count += 1
        if gap.get("field_id"):
            field_ids.add(gap["field_id"])
    return open_count, len(field_ids)


GAP_BREAKDOWN_VERSION = "requirement-gap-breakdown-v1"
# 类别名只取消息里"："之前的部分（"未核验上游元数据：SAFE_INSTANCE_GB.HYF_…" 这种
# 尾巴带具体对象名，按整条消息归并会得到上百个单例，看不出"主要卡在哪一类"）。
_GAP_CATEGORY_LIMIT = 40


def _gap_category(message: str) -> str:
    text = (message or "").strip()
    if not text:
        return "未说明的缺口"
    head = text.split("：")[0].split(":")[0].strip() or text
    return head[:_GAP_CATEGORY_LIMIT]


def gap_breakdown(
    content: dict[str, Any],
    *,
    field_limit: int = 12,
    category_limit: int = 8,
) -> dict[str, Any]:
    """把"打开缺口"从数字拆成可派工的两维：按字段、按类别。

    与 `_open_gaps` 完全同口径（字段级/范围级都算打开、`CLOSED_GAP_STATUSES` 不计），
    否则看板上的"打开缺口 N 条"和弹层里的明细会对不上——这类不一致比不显示更糟。
    """
    gaps = content.get("gaps") or []
    field_by_id: dict[Any, dict[str, Any]] = {}
    for item in content.get("fields") or []:
        if not isinstance(item, dict):
            continue
        field = item.get("field")
        if isinstance(field, dict) and field.get("id") is not None:
            field_by_id[field["id"]] = field

    by_field: dict[Any, int] = {}
    by_category: dict[str, int] = {}
    open_count = 0
    field_gap_count = 0
    scope_gap_count = 0
    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        if str(gap.get("status") or "open") in CLOSED_GAP_STATUSES:
            continue
        open_count += 1
        gap_field_id = gap.get("field_id")
        if gap_field_id:
            by_field[gap_field_id] = by_field.get(gap_field_id, 0) + 1
            field_gap_count += 1
        else:
            scope_gap_count += 1
        category = _gap_category(str(gap.get("message") or ""))
        by_category[category] = by_category.get(category, 0) + 1

    field_items = []
    for field_id, count in sorted(by_field.items(), key=lambda pair: (-pair[1], str(pair[0])))[:field_limit]:
        field = field_by_id.get(field_id) or {}
        field_items.append({
            "field_id": field_id,
            "field_code": field.get("field_code"),
            "field_name": field.get("field_name"),
            "count": count,
        })
    ranked_categories = sorted(by_category.items(), key=lambda pair: (-pair[1], pair[0]))
    category_items = [
        {"category": label, "count": count, "aggregated": False}
        for label, count in ranked_categories[:category_limit]
    ]
    # 真实数据里 406 条缺口会归出 219 个不同前缀（不同脚本/表名各占一类）。
    # 只给前 8 类会让"还有 211 类不知道是什么"，所以把尾巴折成一条并保留条数。
    if len(ranked_categories) > category_limit:
        rest_count = sum(count for _, count in ranked_categories[category_limit:])
        rest_kinds = len(ranked_categories) - category_limit
        category_items.append({
            "category": f"其他 {rest_kinds} 类（见工作台明细）",
            "count": rest_count,
            "aggregated": True,
        })
    target_table = content.get("target_table") or {}
    scenario = content.get("scenario") or {}
    return {
        "breakdown_version": GAP_BREAKDOWN_VERSION,
        # 深链需要"这张需求在哪张表、哪个场景"：看板只能拿到 requirement_id，
        # 而工作台按 tableId + scenarioId + requirementId 才能还原同一条需求。
        "target_table_id": target_table.get("id"),
        "target_table_code": target_table.get("table_code"),
        "scenario_id": scenario.get("id"),
        "open_gap_count": open_count,
        "field_gap_count": field_gap_count,
        "scope_gap_count": scope_gap_count,
        "field_count": len(by_field),
        "category_count": len(by_category),
        "fields": field_items,
        "categories": category_items,
        "truncated_fields": len(by_field) > len(field_items),
        "truncated_categories": len(by_category) > category_limit,
    }


READINESS_LABELS = {
    "delivered": "已正式交付",
    "metadata_stale": "仅引用元数据更新",
    "delivered_stale": "已交付，内容已改",
    "exportable": "可直接重新导出",
    "frozen": "已冻结，尚未导出",
    "stale": "有未冻结改动",
    "no_snapshot": "无快照",
    "human_rejected": "人工核对不通过",
}


def _script_binding(content: dict[str, Any], row: Any, fields_by_table: dict[int, list[Any]]) -> dict[str, Any] | None:
    """脚本没产出哪些监管字段。

    只对“有脚本依据”的需求回答：手工建的需求没有 field_bindings，说“脚本没产出”是错的，
    必须返回 None 让界面显示“不适用”，而不是 0。
    """
    basis = content.get("script_basis") or {}
    bindings = ((basis.get("confirmation") or {}).get("field_bindings") or {})
    if not bindings:
        return None
    table_id = (row.scope_json or {}).get("target_table_id")
    table_fields = fields_by_table.get(table_id) or []
    if not table_fields:
        return None
    scope_ids = {int(value) for value in ((row.scope_json or {}).get("field_ids") or []) if isinstance(value, int) or str(value).isdigit()}
    unbound = [
        {"field_id": field_row.id, "field_code": field_row.field_code, "field_name": field_row.field_name}
        for field_row in table_fields
        if field_row.id not in scope_ids
    ]
    return {
        "table_field_count": len(table_fields),
        "bound_field_count": len(scope_ids & {field_row.id for field_row in table_fields}),
        "unbound_count": len(unbound),
        "unbound": unbound[:200],
    }


def _readiness(
    frozen: bool,
    stale: bool,
    artifact_count: int,
    formal_current: bool = False,
    formal_present: bool = False,
    meta_only: bool = False,
    human_rejected: bool = False,
) -> str:
    """把冻结态、正式交付与"有没有产出过文件"合成一个可排序的就绪度。

    项目负责人看的是"这条需求现在是什么交付状态"，所以在这里就定死：
    正式交付且内容一致 = delivered（最高）；已冻结且有产物 = exportable；已冻结但没导出过 = frozen；
    有改动 = stale；没快照 = no_snapshot。

    formal_current 只在"正式交付的 content_hash 等于当前内容 hash"时为真 —— 正式交付之后又改过内容，
    就不能再叫"已正式交付"，否则看板会把"交付完又改了"的需求说成已完成；此时用 delivered_stale，
    既不冒充已完成，也不至于让人以为从没交付过。
    """
    if human_rejected:
        # 最近一份产物被人判"不通过"：这比"已正式交付"更需要注意，必须先解决。
        # 但只在该产物仍是最新产物的前提下成立——重新导出后新的产物没被否过，
        # 老产物的否决意见就不该继续压着这条需求（历史仍然留痕在审计里）。
        return "human_rejected"
    if formal_current:
        return "delivered"
    if formal_present:
        # 正式交付过、但内容后来又改了：不能再叫"已交付"（旧正式文件不代表现在的内容），
        # 也不该显示"无快照"（那会让人以为什么都没交过）。
        return "delivered_stale"
    if frozen:
        return "exportable" if artifact_count else "frozen"
    if meta_only:
        # 内容 hash 变了但口径 hash 没变：只是模板带过来的表级引用元数据更新。
        # 它需要重新冻结，但不需要改正文——排在“正文真改了”之后、无快照之前。
        return "metadata_stale"
    return "stale" if stale else "no_snapshot"


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _actor(users: dict[int, Any], user_id: int | None) -> dict[str, Any] | None:
    """把 created_by 变成一个可读的操作人。

    只回传 id 与显示名：看板要回答“是谁做的”，不需要邮箱、角色等账号信息。
    查不到用户（已删号）时 name 为 None，前端必须显示“未知用户”而不是编一个名字。
    """
    if not user_id:
        return None
    user = users.get(user_id)
    name = getattr(user, "display_name", None) or getattr(user, "username", None)
    return {"id": user_id, "name": name}


def build_delivery_status(db: Session, project_id: int, *, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    requirements = list(db.scalars(
        select(Requirement).where(Requirement.project_id == project_id).order_by(Requirement.id)
    ))
    truncated = len(requirements) > limit
    requirements = requirements[:limit]

    table_ids = {
        (row.scope_json or {}).get("target_table_id")
        for row in requirements
        if (row.scope_json or {}).get("target_table_id")
    }
    tables = {}
    if table_ids:
        tables = {row.id: row for row in db.scalars(select(TargetTable).where(TargetTable.id.in_(table_ids)))}

    # 一次取回这些目标表的字段：用来回答“脚本没产出哪些监管字段”。
    # 逐需求再查一次会变成 N+1，而看板是只读的聚合接口。
    fields_by_table: dict[int, list[Any]] = {}
    if table_ids:
        for field_row in db.scalars(
            select(TargetField)
            .where(TargetField.target_table_id.in_(table_ids))
            .order_by(TargetField.id)
        ):
            fields_by_table.setdefault(field_row.target_table_id, []).append(field_row)

    # 已生成但还没采纳的候选：看板要能回答"这条需求还有多少正文等我采纳"，
    # 否则用户只能回工作台逐条翻。一次聚合查完，避免逐需求 N+1。
    pending_candidates: dict[int, int] = {}
    requirement_ids = [row.id for row in requirements]
    if requirement_ids:
        for requirement_id, count in db.execute(
            select(RequirementGenerationInput.requirement_id, func.count(RequirementGenerationItem.id))
            .join(RequirementGenerationItem, RequirementGenerationItem.input_id == RequirementGenerationInput.id)
            .where(
                RequirementGenerationInput.project_id == project_id,
                RequirementGenerationInput.requirement_id.in_(requirement_ids),
                RequirementGenerationItem.status == "completed",
                or_(
                    RequirementGenerationItem.decision.is_(None),
                    RequirementGenerationItem.decision == "pending",
                ),
            )
            .group_by(RequirementGenerationInput.requirement_id)
        ).all():
            pending_candidates[int(requirement_id)] = int(count)

    # 人工核对登记：按需求分组、按 id 倒序保留全部登记。
    #
    # 不能只留"最近一条"：判「不通过」的登记要一直管到**内容变了**为止。
    # 只比 artifact_id 的话，把同一份冻结内容换个版式重新导出就会产生一个 id 更大的新产物，
    # 那份"不通过"立刻失效——文档一个字没改，红牌却被洗掉了。所以下面按 content_hash 比。
    attestations_by_requirement: dict[int, list[Any]] = {}
    if requirement_ids:
        for attestation_row in db.scalars(
            select(RequirementArtifactAttestation)
            .where(
                RequirementArtifactAttestation.project_id == project_id,
                RequirementArtifactAttestation.requirement_id.in_(requirement_ids),
            )
            .order_by(RequirementArtifactAttestation.id.desc())
        ):
            attestations_by_requirement.setdefault(int(attestation_row.requirement_id), []).append(
                attestation_row
            )

    items: list[dict[str, Any]] = []
    # 先收集 (目标字典, 用户 id)，循环结束后一次性查用户表：10~200 条需求逐条查用户
    # 会把一个只读看板变成 N+1 次查询。
    actor_refs: list[tuple[dict[str, Any], int]] = []
    summary = {"frozen": 0, "stale": 0, "no_snapshot": 0, "with_artifacts": 0, "with_open_gaps": 0,
               "human_rejected": 0,
               "open_gap_count": 0, "open_gap_field_count": 0, "formal_delivered": 0,
               "exportable": 0, "frozen_pending_export": 0, "delivered": 0, "delivered_stale": 0,
               "caliber_changed": 0, "reference_meta_only": 0, "metadata_stale": 0,
               "with_pending_candidates": 0, "pending_candidate_total": 0}
    for row in requirements:
        # 与 /document、freeze_draft 用同一种编码：jsonable_encoder 会把时间转成 ISO 字符串，
        # 与 content_digest(default=str) 的结果不同。少这一步会出现"刚冻结却显示未冻结"的假状态。
        content = jsonable_encoder(document_content(db, row))
        current_hash = content_digest(content)
        # 口径身份：剔除表级引用元数据。冻结仍以 content_hash 为准，这里只用于解释
        # “看板说我有改动，到底改的是正文还是模板带过来的表级口径”。
        current_caliber = caliber_digest(content)
        deliveries = list(db.scalars(
            select(RequirementDelivery)
            .where(RequirementDelivery.project_id == project_id, RequirementDelivery.requirement_id == row.id)
            .order_by(RequirementDelivery.id.desc())
        ))
        artifacts = list(db.scalars(
            select(RequirementRenderArtifact)
            .where(RequirementRenderArtifact.project_id == project_id,
                   RequirementRenderArtifact.requirement_id == row.id)
            .order_by(RequirementRenderArtifact.id.desc())
        ))
        formal_rows = list(db.scalars(
            select(RequirementFormalDelivery)
            .where(RequirementFormalDelivery.project_id == project_id,
                   RequirementFormalDelivery.requirement_id == row.id)
            .order_by(RequirementFormalDelivery.version_no.desc(), RequirementFormalDelivery.id.desc())
        ))
        formal = formal_rows[0] if formal_rows else None
        latest = deliveries[0] if deliveries else None
        latest_caliber = caliber_digest(latest.content_json) if latest is not None else None
        latest_artifact = artifacts[0] if artifacts else None
        open_gap_count, open_gap_field_count = _open_gaps(content)
        script_binding = _script_binding(content, row, fields_by_table)
        frozen = latest is not None and latest.content_hash == current_hash
        stale = latest is not None and latest.content_hash != current_hash
        caliber_changed = bool(latest is not None and latest_caliber != current_caliber)
        # stale 但口径未变：只是模板带过来的表级引用元数据变了（主题/报送数据域）。
        reference_meta_only = bool(stale and not caliber_changed)
        table = tables.get((row.scope_json or {}).get("target_table_id"))
        attestations = attestations_by_requirement.get(row.id) or []
        attestation = attestations[0] if attestations else None
        attestation_on_latest = bool(
            attestation is not None
            and latest_artifact is not None
            and int(attestation.artifact_id) == int(latest_artifact.id)
        )
        artifacts_by_id = {int(entry.id): entry for entry in artifacts}
        rejection = next(
            (entry for entry in attestations if _text(entry.conclusion) == "rejected"),
            None,
        )
        rejection_artifact = artifacts_by_id.get(int(rejection.artifact_id)) if rejection is not None else None
        rejection_content_hash = getattr(rejection_artifact, "content_hash", None)
        rejection_on_latest = bool(
            rejection is not None
            and latest_artifact is not None
            and int(rejection.artifact_id) == int(latest_artifact.id)
        )
        # 只有"内容还是那份被否的内容"时才压住：新导出如果 content_hash 变了，说明正文真动过，
        # 红牌解除、交回人工复核；只换版式/渲染器则 content_hash 不变，红牌继续压着。
        rejection_matches_latest_content = bool(
            rejection_content_hash
            and latest_artifact is not None
            and rejection_content_hash == latest_artifact.content_hash
        )
        human_rejected = bool(rejection is not None and rejection_matches_latest_content)
        readiness = _readiness(
            frozen, stale, len(artifacts),
            bool(formal is not None and formal.content_hash == current_hash),
            bool(formal is not None),
            reference_meta_only,
            human_rejected,
        )
        item: dict[str, Any] = {
            "requirement_id": row.id,
            "name": row.name,
            "requirement_version": row.version,
            "content_version": row.content_version or 0,
            "target_table_code": getattr(table, "table_code", None),
            "target_table_name": getattr(table, "table_name", None),
            "field_count": len(content.get("fields") or []),
            "current_content_hash": current_hash,
            "current_caliber_hash": current_caliber,
            "latest_snapshot": None if latest is None else {
                "id": latest.id,
                "content_hash": latest.content_hash,
                "caliber_hash": latest_caliber,
                "requirement_version": latest.requirement_version,
                "created_at": _iso(latest.created_at),
                "actor": None,
            },
            "frozen": frozen,
            "stale": stale,
            "caliber_changed": caliber_changed,
            "reference_meta_only": reference_meta_only,
            "snapshot_count": len(deliveries),
            "artifact_count": len(artifacts),
            "last_artifact": None if latest_artifact is None else {
                "id": latest_artifact.id,
                "format": latest_artifact.format,
                "file_size": latest_artifact.file_size,
                "renderer_version": latest_artifact.renderer_version,
                "created_at": _iso(latest_artifact.created_at),
                "actor": None,
            },
            "formal_delivery": None if formal is None else {
                "id": formal.id,
                "version_no": formal.version_no,
                "content_version": formal.content_version,
                "content_hash": formal.content_hash,
                "file_hash": formal.file_hash,
                "matches_current_content": formal.content_hash == current_hash,
            },
            "formal_delivery_count": len(formal_rows),
            "readiness": readiness,
            # 最近一条人工核对登记：看板要能回答"这份产物是谁、什么时候、凭什么否掉的"。
            "latest_attestation": None if attestation is None else {
                "id": attestation.id,
                "artifact_id": attestation.artifact_id,
                "conclusion": attestation.conclusion,
                "scope_code": attestation.scope_code,
                "basis": attestation.basis,
                "created_at": _iso(attestation.created_at),
                "on_latest_artifact": attestation_on_latest,
                "actor": None,
            },
            "human_rejected": human_rejected,
            # 被否细节：哪份产物、谁、什么时候、凭什么否的，以及之后有没有出现过内容不同的新产物。
            "rejection": None if rejection is None else {
                "attestation_id": rejection.id,
                "artifact_id": rejection.artifact_id,
                "scope_code": rejection.scope_code,
                "basis": rejection.basis,
                "created_at": _iso(rejection.created_at),
                "content_hash": rejection_content_hash,
                "on_latest_artifact": rejection_on_latest,
                "same_content_as_latest": rejection_matches_latest_content,
                "superseded_by": None if rejection_on_latest or latest_artifact is None else {
                    "id": latest_artifact.id,
                    "format": latest_artifact.format,
                    "renderer_version": latest_artifact.renderer_version,
                    "created_at": _iso(latest_artifact.created_at),
                },
                "actor": None,
            },
            "open_gap_count": open_gap_count,
            "open_gap_field_count": open_gap_field_count,
            "script_binding": script_binding,
            "pending_candidate_count": pending_candidates.get(row.id, 0),
            # 目标表与场景 id 给深链用：看板点"去工作台采纳"必须能直接落到同一条需求，
            # 只带 requirement_id 会打开同表的另一条需求（T_8_1 就有三条）。
            "target_table_id": (row.scope_json or {}).get("target_table_id"),
            "scenario_id": (row.scope_json or {}).get("scenario_id"),
        }
        items.append(item)
        if latest is not None and latest.created_by:
            actor_refs.append((item["latest_snapshot"], latest.created_by))
        if latest_artifact is not None and latest_artifact.created_by:
            actor_refs.append((item["last_artifact"], latest_artifact.created_by))
        if attestation is not None and attestation.attested_by:
            actor_refs.append((item["latest_attestation"], attestation.attested_by))
        if rejection is not None and rejection.attested_by and item["rejection"] is not None:
            actor_refs.append((item["rejection"], rejection.attested_by))
        # “有未冻结改动”只统计正文真的改了的（口径变化）；仅引用元数据更新单独计数，
        # 否则头条上两个互斥口径会重复计算同一批行。
        summary["frozen" if frozen else "metadata_stale" if reference_meta_only else "stale" if stale else "no_snapshot"] += 1
        if caliber_changed:
            summary["caliber_changed"] += 1
        if reference_meta_only:
            summary["reference_meta_only"] += 1
        if artifacts:
            summary["with_artifacts"] += 1
        if formal_rows:
            summary["formal_delivered"] += 1
        if readiness == "delivered":
            summary["delivered"] += 1
        elif readiness == "delivered_stale":
            summary["delivered_stale"] += 1
        elif readiness == "exportable":
            summary["exportable"] += 1
        elif readiness == "frozen":
            summary["frozen_pending_export"] += 1
        elif readiness == "human_rejected":
            summary["human_rejected"] += 1
        if open_gap_count:
            summary["with_open_gaps"] += 1
        summary["open_gap_count"] += open_gap_count
        summary["open_gap_field_count"] += open_gap_field_count
        pending_count = pending_candidates.get(row.id, 0)
        if pending_count:
            summary["with_pending_candidates"] += 1
            summary["pending_candidate_total"] += pending_count

    actor_ids = {actor_id for _, actor_id in actor_refs}
    users: dict[int, Any] = {}
    if actor_ids:
        users = {row.id: row for row in db.scalars(select(User).where(User.id.in_(actor_ids)))}
    for target, actor_id in actor_refs:
        target["actor"] = _actor(users, actor_id)

    return {
        "status_version": STATUS_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requirement_count": len(items),
        "truncated": truncated,
        "summary": summary,
        "items": items,
    }


FRESHNESS_VERSION = "requirement-script-basis-freshness-v1"
FRESHNESS_STATES = ("aligned", "script_updated", "parse_changed", "version_missing")
FRESHNESS_LABELS = {
    "aligned": "已对齐",
    "script_updated": "脚本有更新",
    "parse_changed": "解析状态变了",
    "version_missing": "依据版本缺失",
}


def build_script_basis_freshness(db: Session, project_id: int, *, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """跑批脚本改了之后，已建需求用的还是哪一版脚本依据。

    为什么单独做：需求冻结的是「建需那一刻的脚本事实」（`script_basis.versions[*].id`）。
    脚本被重新导入后会产生新版本，但已冻结的需求不会自动跟着变——这是刻意的（证据可追溯），
    可也因此可能长期停留在旧脚本上而没人知道。看板要说清楚的是「哪几条需求的依据落后了」。

    为什么用版本号比较而不是重算 preview_hash：重算要逐需求加载上千条血缘边，
    对只读看板太重；而「同一脚本文件存在更高版本号」本身就是要人复核的强信号。
    真正判定"依据是否还等价"仍走 `GET …/script-basis-impact`（按预览哈希，逐条点开时用）。
    """

    requirements = list(db.scalars(
        select(Requirement).where(Requirement.project_id == project_id).order_by(Requirement.id).limit(limit)
    ))
    truncated = len(requirements) >= limit

    frozen_by_requirement: list[tuple[Any, dict[str, Any], list[dict[str, Any]]]] = []
    script_file_ids: set[int] = set()
    for row in requirements:
        content = jsonable_encoder(document_content(db, row))
        basis = content.get("script_basis") or {}
        versions = [item for item in (basis.get("versions") or []) if isinstance(item, dict)]
        frozen_by_requirement.append((row, content, versions))
        for version in versions:
            if version.get("script_file_id"):
                script_file_ids.add(int(version["script_file_id"]))

    version_ids = {
        int(version["id"])
        for _, _, versions in frozen_by_requirement
        for version in versions
        if version.get("id")
    }
    current_versions: dict[int, Any] = {}
    if version_ids:
        current_versions = {
            item.id: item for item in db.scalars(select(ScriptFileVersion).where(ScriptFileVersion.id.in_(version_ids)))
        }
    versions_by_file: dict[int, list[Any]] = {}
    if script_file_ids:
        for item in db.scalars(
            select(ScriptFileVersion)
            .where(ScriptFileVersion.script_file_id.in_(script_file_ids))
            .order_by(ScriptFileVersion.version_no)
        ):
            versions_by_file.setdefault(item.script_file_id, []).append(item)
    script_files = {}
    if script_file_ids:
        script_files = {
            item.id: item for item in db.scalars(select(ScriptFile).where(ScriptFile.id.in_(script_file_ids)))
        }

    items: list[dict[str, Any]] = []
    summary = {state: 0 for state in FRESHNESS_STATES}
    summary["no_basis"] = 0
    for row, content, versions in frozen_by_requirement:
        if not versions:
            summary["no_basis"] += 1
            continue
        details: list[dict[str, Any]] = []
        for frozen in versions:
            version_id = int(frozen.get("id") or 0)
            script_file_id = int(frozen.get("script_file_id") or 0)
            current = current_versions.get(version_id)
            latest_versions = versions_by_file.get(script_file_id) or []
            latest = latest_versions[-1] if latest_versions else None
            if current is None:
                state = "version_missing"
            elif latest is not None and latest.version_no > current.version_no:
                state = "script_updated"
            elif current.parse_status != (frozen.get("parse_status") or current.parse_status):
                state = "parse_changed"
            else:
                state = "aligned"
            script_file = script_files.get(script_file_id)
            details.append({
                "version_id": version_id,
                "script_file_id": script_file_id,
                "file_name": getattr(script_file, "file_name", None) or frozen.get("path"),
                "frozen_version_no": frozen.get("version_no"),
                "latest_version_no": getattr(latest, "version_no", None),
                "latest_version_id": getattr(latest, "id", None),
                "frozen_parse_status": frozen.get("parse_status"),
                "current_parse_status": getattr(current, "parse_status", None),
                "state": state,
            })
        states = {detail["state"] for detail in details}
        if "version_missing" in states:
            state = "version_missing"
        elif "script_updated" in states:
            state = "script_updated"
        elif "parse_changed" in states:
            state = "parse_changed"
        else:
            state = "aligned"
        summary[state] += 1
        items.append({
            "requirement_id": row.id,
            "name": row.name,
            "target_table_code": ((content.get("target_table") or {}).get("table_code")),
            "state": state,
            "frozen_version_count": len(details),
            "versions": details,
        })

    from app.services.requirement_script_basis_decision import decisions_for_project

    decisions = decisions_for_project(db, project_id)
    decided_requirements = 0
    for item in items:
        behind = [
            version
            for version in item.get("versions") or []
            if isinstance(version, dict) and version.get("state") != "aligned"
        ]
        decided = 0
        for version in item.get("versions") or []:
            if not isinstance(version, dict):
                continue
            key = (item["requirement_id"], version.get("script_file_id"), version.get("latest_version_id"))
            decision = decisions.get(key)
            version["decision"] = decision
            if decision is not None and version.get("state") != "aligned":
                decided += 1
        item["decided_version_count"] = decided
        # 只有"所有落后的版本都已登记决定"才算这条需求已被复核过：
        # 部分决定仍然需要人再看，否则会出现"处理了一条就当整条处理完"的假完成。
        item["fully_decided"] = bool(behind) and decided >= len(behind)
        if item.get("state") != "aligned" and item["fully_decided"]:
            decided_requirements += 1
    summary["decided_requirements"] = decided_requirements
    return {
        "freshness_version": FRESHNESS_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requirement_count": len(items),
        "truncated": truncated,
        "summary": summary,
        "items": items,
    }
