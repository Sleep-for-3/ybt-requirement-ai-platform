"""Read-only prose candidates from a single immutable requirement revision."""
from copy import deepcopy

from fastapi import HTTPException
from pydantic import Field

from app.schemas.ai_skill import ContractModel, SkillInputEnvelope, SkillScope, SkillEvidence, EvidenceSource, SkillGap
from app.services.auth.permission_service import PermissionService
from app.services.requirement_revisions import load_revision

TASK = "requirement_document_assistance"
LEVELS = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}


class DocumentParagraph(ContractModel):
    text: str = Field(min_length=1, max_length=10000)
    fact_ids: list[str] = Field(min_length=1, max_length=100)


class DocumentCandidate(ContractModel):
    background: list[DocumentParagraph] = Field(default_factory=list, max_length=20)
    business_description: list[DocumentParagraph] = Field(default_factory=list, max_length=20)
    difference_analysis: list[DocumentParagraph] = Field(default_factory=list, max_length=20)
    missing_information: list[DocumentParagraph] = Field(default_factory=list, max_length=20)


def validate_document_output(candidate, envelope):
    allowed = {item.id for item in envelope.facts}
    for section in candidate.model_dump().values():
        for paragraph in section:
            if not paragraph["text"].strip() or not set(paragraph["fact_ids"]) <= allowed:
                raise ValueError("document paragraph references outside fixed revision")


def build_document_envelope(db, principal, project_id, requirement_id, content_version):
    permissions = PermissionService(db, principal)
    project = permissions.require_project_permission(project_id, "project.view")
    permissions.require_project_permission(project_id, "knowledge.search")
    if project.institution_id is None:
        raise HTTPException(409, "请先将项目关联到有效机构并配置文档辅助 Skill")
    revision = load_revision(db, project_id, requirement_id, content_version)
    content = revision.content_json
    snapshot = (content.get("script_basis") or {}).get("policy_snapshot") or {}
    from app.services.knowledge_eligibility import validate_frozen_requirement_evidence
    validate_frozen_requirement_evidence(db, project_id, snapshot)
    levels = [project.confidentiality_level or "internal"]
    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"confidentiality", "confidentiality_level"} and item:
                    levels.append(item if isinstance(item, str) else "restricted")
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    collect(content)
    from app.models import KnowledgeUnit
    for saved in snapshot.get("evidence", []):
        unit = db.get(KnowledgeUnit, saved["unit_id"])
        if unit:
            levels.append(unit.confidentiality_level or "internal")
    level = max((item if item in LEVELS else "restricted" for item in levels), key=LEVELS.get)
    scope = SkillScope(scope_type="task", institution_id=project.institution_id, project_id=project_id, invocation_key="requirement_document")
    facts = []
    for key in ("requirement", "fields", "script_basis", "policy_comparisons", "gaps"):
        if key in content:
            facts.append(SkillEvidence(id=f"revision:{revision.id}:{key}", kind="requirement_revision_section",
                value=deepcopy(content[key]), confidentiality=level,
                source=EvidenceSource(source_type="requirement_revision", source_id=str(revision.id),
                    source_version=revision.content_hash, locator=key, scope=scope)))
    envelope = SkillInputEnvelope(skill_key=TASK, task_key=TASK, scope=scope,
        subject_ref=f"requirement:{requirement_id}:v{content_version}", facts=facts,
        gaps=[SkillGap(code="draft_only", message="仅辅助整理固定修订，历史制度及人工判断不等于当前合规结论；候选不自动写回正文。")])
    return revision, envelope


async def assist_document(db, principal, project_id, requirement_id, content_version):
    from app.services.ai_skills import runtime
    runtime.require_user(db, principal)
    revision, envelope = build_document_envelope(db, principal, project_id, requirement_id, content_version)
    resolved = runtime.resolve_skill(db, principal, TASK, envelope.scope)
    if resolved is None:
        raise HTTPException(409, "请先测试、审批并固定采用文档辅助 Skill")
    definition, version, binding = resolved
    # Full frozen revisions can contain historical asset classifications. Until
    # every historical source has a current external-release projection, keep
    # this adapter local-only instead of inferring permission to send it out.
    from app.models import ModelProfile
    if not db.get(ModelProfile, version.content_json["model_profile_id"]).local_only:
        raise HTTPException(409, "固定修订文档辅助当前仅支持本地模型配置")
    identities = (version.id, binding.id, binding.lock_version, envelope.context_hash())
    result = await runtime.execute_resolved(db, envelope, definition, version, binding)
    db.flush(); db.expire_all()
    revision, current = build_document_envelope(db, principal, project_id, requirement_id, content_version)
    latest = runtime.resolve_skill(db, principal, TASK, current.scope)
    if latest is None or (latest[1].id, latest[2].id, latest[2].lock_version, current.context_hash()) != identities:
        raise HTTPException(409, "文档辅助权限、依据或绑定已变化，请重新生成")
    return {"content_version": content_version, "content_hash": revision.content_hash,
            "status": "candidate_only", **result}
