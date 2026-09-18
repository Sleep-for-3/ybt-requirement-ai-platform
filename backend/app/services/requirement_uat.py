"""Reviewed manual UAT cases over fixed requirement rules; never execute SQL."""
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Project, Requirement, RequirementRevision, UatCase, UatSuite, WorkflowInstance, ReviewTask
from app.models.requirement import RequirementUatLink
from app.services.requirement_scope import content_digest
from app.services.requirement_revisions import load_revision
from app.services.requirement_paths import path_issues
from app.services.requirement_policy_comparison import comparison_issues
from app.services.requirement_script_basis import script_basis_changes


def suite_cases(db, suite_id):
    return list(db.scalars(select(UatCase).where(UatCase.uat_suite_id == suite_id)
        .order_by(UatCase.display_order, UatCase.id)))


def case_snapshot(cases):
    return [{key: deepcopy(getattr(case, key)) for key in ("project_id", "case_code", "case_name",
        "description", "case_category", "precondition_json", "input_requirement_json",
        "expected_result_json", "execution_mode", "severity", "enabled", "display_order")} for case in cases]


def validate_link(db, link, *, current=True):
    revision = db.get(RequirementRevision, link.revision_id)
    requirement = db.get(Requirement, link.requirement_id)
    if (revision is None or requirement is None or revision.project_id != link.project_id
            or revision.requirement_id != link.requirement_id or requirement.project_id != link.project_id):
        raise HTTPException(409, "需求测试依据不可用")
    if revision.content_hash != link.content_hash or content_digest(revision.content_json) != link.content_hash:
        raise HTTPException(409, "需求测试依据完整性检查失败")
    cases = suite_cases(db, link.suite_id)
    if not cases or content_digest(case_snapshot(cases)) != link.cases_hash:
        raise HTTPException(409, "测试项已变化，不能沿用原审核")
    if any(c.project_id != link.project_id or c.execution_mode != "manual" for c in cases):
        raise HTTPException(409, "需求派生测试项只能人工执行")
    if current and (requirement.content_version != revision.content_version
            or script_basis_changes(db, link.project_id, revision.content_json)):
        raise HTTPException(409, "需求或依据已变化，请复核并从新修订建立测试项")
    return revision


def create_requirement_suite(db, requirement, version, actor_id):
    revision = load_revision(db, requirement.project_id, requirement.id, version)
    existing = db.scalar(select(RequirementUatLink).where(RequirementUatLink.revision_id == revision.id))
    if existing:
        return existing
    content = revision.content_json
    if requirement.content_version != version:
        raise HTTPException(409, "只能从当前需求版本建立测试项")
    if not content.get("script_basis") or path_issues(content) or comparison_issues(content):
        raise HTTPException(409, "请先确认完整加工路径和制度对照")
    if content["script_basis"].get("gaps"):
        from app.services.requirement_policy_comparison import LEGACY_PENDING
        if any(g != LEGACY_PENDING for g in content["script_basis"]["gaps"]):
            raise HTTPException(409, "脚本依据仍有未核验缺口")
    if script_basis_changes(db, requirement.project_id, content):
        raise HTTPException(409, "固定依据已变化，请先复核需求")
    rule_fields = {}
    for record in content["fields"]:
        for rule_id in record["confirmed_path"]["rule_ids"]:
            rule_fields.setdefault(rule_id, []).append(record["field"]["id"])
    rules = [r for r in content["script_basis"]["rules"] if r["rule_id"] in rule_fields]
    if not rules:
        raise HTTPException(409, "缺少已确认字段规则")
    project = db.get(Project, requirement.project_id)
    try:
        with db.begin_nested():
            suite = UatSuite(project_id=project.id, institution_id=project.institution_id,
                suite_name=f"需求 #{requirement.id} 内容 v{version} 规则验收", suite_type="requirement_rules",
                description=f"固定需求 {requirement.name}；人工测试，待审核。", enabled=True,
                is_system=False, created_by=actor_id)
            db.add(suite); db.flush()
            for index, rule in enumerate(rules, 1):
                decisions = [deepcopy(d) for d in content["policy_comparisons"]["decisions"].values()
                    if rule["rule_id"] in d["rule_ids"]]
                evidence = {"requirement_id": requirement.id, "revision_id": revision.id,
                    "content_version": version, "content_hash": revision.content_hash,
                    "rule_id": rule["rule_id"], "script_version_id": rule["script_version_id"],
                    "statement_id": rule["statement_id"], "source_line_start": rule["source_line_start"],
                    "source_line_end": rule["source_line_end"], "field_ids": sorted(rule_fields[rule["rule_id"]])}
                expected = {key: deepcopy(rule.get(key)) for key in ("source", "target", "transformation_expression",
                    "join_condition", "filter_condition", "aggregation_rule", "code_mapping_rule")}
                expected["assertion"] = "以脱敏样本逐项核对固定来源、加工表达式、筛选和输出，记录预期值、实际值及验证证据。"
                expected["policy_confirmations"] = decisions
                expected["requirement_evidence"] = evidence
                db.add(UatCase(project_id=project.id, uat_suite_id=suite.id, case_code=f"REQ-{requirement.id}-{index}",
                    case_name=f"{rule['target'].get('table_name')}.{rule['target'].get('column_name')} · {rule['rule_id']}"[:255],
                    description=rule.get("transformation_expression"), case_category="requirement_rule",
                    execution_mode="manual", severity="high", enabled=True, display_order=index,
                    precondition_json={"requirement_evidence": evidence, "review_required": True},
                    input_requirement_json={"sample_policy": "仅使用授权脱敏样本；不自动连接银行数据库", "rule": deepcopy(rule)},
                    expected_result_json=expected))
            db.flush()
            link = RequirementUatLink(project_id=project.id, requirement_id=requirement.id,
                revision_id=revision.id, suite_id=suite.id, created_by=actor_id,
                content_hash=revision.content_hash, cases_hash=content_digest(case_snapshot(suite_cases(db, suite.id))), status="draft")
            db.add(link); db.flush()
    except IntegrityError:
        link = db.scalar(select(RequirementUatLink).where(RequirementUatLink.revision_id == revision.id))
        if link is None:
            raise
    return link


def link_view(db, link):
    revision = db.get(RequirementRevision, link.revision_id)
    instance = db.scalar(select(WorkflowInstance).where(WorkflowInstance.project_id == link.project_id,
        WorkflowInstance.target_type == "requirement_uat_link", WorkflowInstance.target_id == link.id)
        .order_by(WorkflowInstance.id.desc()))
    tasks = list(db.scalars(select(ReviewTask).where(ReviewTask.workflow_instance_id == instance.id)
        .order_by(ReviewTask.id))) if instance else []
    issue = None
    try:
        validate_link(db, link)
    except HTTPException as exc:
        issue = exc.detail
    return {"id": link.id, "requirement_id": link.requirement_id, "suite_id": link.suite_id,
        "content_version": revision.content_version if revision else None, "status": link.status,
        "content_hash": link.content_hash, "pending_review": bool(issue), "issue": issue,
        "tasks": [{"id": t.id, "step_key": t.step_key, "status": t.status} for t in tasks]}


def validate_suite_execution(db, suite_id):
    link = db.scalar(select(RequirementUatLink).where(RequirementUatLink.suite_id == suite_id))
    if link:
        validate_link(db, link)
        if link.status != "approved":
            raise HTTPException(409, "需求规则测试项尚未审核通过")
    return link


def review_snapshot(db, link):
    revision = validate_link(db, link, current=False)
    return {"requirement_id": link.requirement_id, "content_version": revision.content_version,
        "content_hash": link.content_hash, "cases_hash": link.cases_hash, "cases": case_snapshot(suite_cases(db, link.suite_id))}


def validate_decision(db, link, actor_id, decision):
    if actor_id == link.created_by:
        raise HTTPException(409, "测试项发起人不能审核自己的测试项")
    if decision == "approved":
        validate_link(db, link)


def validate_manual_evidence(db, case, payload):
    link = validate_suite_execution(db, case.uat_suite_id)
    if link:
        if not payload.actual_result_json or not payload.evidence_json:
            raise HTTPException(422, "需求规则验收必须记录预期样本值、实际值和验证证据")
        if not str(payload.evidence_json.get("verification") or "").strip():
            raise HTTPException(422, "请填写可核验的验证证据说明")
        for key in ("expected_value", "actual_value", "conclusion"):
            if key not in payload.actual_result_json or not str(payload.actual_result_json[key]).strip():
                raise HTTPException(422, "请填写样本预期值、实际值和核验结论")
        return deepcopy(case.expected_result_json["requirement_evidence"])
    return None
