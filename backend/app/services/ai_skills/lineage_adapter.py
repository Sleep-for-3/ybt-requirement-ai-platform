"""Authorized fixed-revision facts for the first Skill business adapter."""
from collections import defaultdict, deque
import re

from fastapi import HTTPException
from sqlalchemy import select

from app.models import KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit, LineageRevision, Project
from app.schemas.ai_skill import EvidenceSource, SkillEvidence, SkillGap, SkillInputEnvelope, SkillScope
from app.schemas.ai_skill_control import SkillContent
from app.services.ai_skills import runtime
from app.services.ai_skills.lineage_context import auxiliary_context
from app.services.knowledge_eligibility import governed_document_visible, governed_unit_predicates
from app.services.knowledge_evidence import document_citation, mode_knowledge_types
from app.services.lineage.revisions import LineageRevisionService
from app.services.llm.execution_metadata import stable_hash
from app.services.requirement_policy_comparison import NORMATIVE_CATEGORIES
from app.services.retrieval import HybridRetriever

SUPPORTED_PROVIDERS = {"lineage_edge_facts", "script_evidence", "asset_identity", "regulatory_clauses", "bounded_lineage_paths",
                       "field_constraints", "quality_profile", "script_diff", "prior_human_decisions"}


def bounded_paths(edges, selected, depth, max_paths):
    incoming, outgoing = defaultdict(list), defaultdict(list)
    for edge in edges:
        incoming[str(edge.get("target_node_key"))].append(edge)
        outgoing[str(edge.get("source_node_key"))].append(edge)
    paths, gaps = [], []
    for direction, root, adjacency, next_key in (
        ("upstream", str(selected.get("source_node_key")), incoming, "source_node_key"),
        ("downstream", str(selected.get("target_node_key")), outgoing, "target_node_key"),
    ):
        queue = deque([(root, [root], [])])
        while queue:
            node, nodes, trail = queue.popleft()
            candidates = adjacency[node]
            if not candidates or len(trail) >= depth:
                paths.append({"direction": direction, "nodes": nodes, "edges": trail, "depth": len(trail), "complete": not candidates})
                if candidates:
                    gaps.append(SkillGap(code="path_depth_boundary", message="路径达到配置深度，边界外未纳入本次解释"))
            else:
                for edge in candidates:
                    target = str(edge.get(next_key))
                    if target in nodes:
                        gaps.append(SkillGap(code="lineage_cycle", message="固定版本存在循环，路径不作无限展开"))
                        continue
                    queue.append((target, [*nodes, target], [*trail, edge]))
            if len(paths) + len(queue) > max_paths:
                raise HTTPException(409, detail={"error_code": "path_scope_exceeded", "gaps": [{"code": "path_scope_exceeded", "message": "路径数超过配置，请显式缩小范围"}]})
    return paths, gaps


def policy_clauses(db, project, context, scope, limit):
    query = " ".join(str(context[side].get(key) or "") for side in ("source", "target") for key in ("business_name", "technical_name"))
    if not query.strip():
        return [], [], [SkillGap(code="missing_basis", message="缺少制度检索目标")]
    try:
        # A failed retrieval must not poison the transaction holding run facts.
        with db.begin_nested():
            _, retrieved = HybridRetriever(db).search(project.id, query, top_k=limit,
                knowledge_types=mode_knowledge_types("regulatory", None), retrieval_mode="keyword_only", commit=False)
    except Exception:
        return [], [], [SkillGap(code="policy_retrieval_failed", message="制度检索失败，本次不能确认制度要求"),
                        SkillGap(code="missing_basis", message="缺少可验证制度依据，脚本现状不能作为监管要求")]
    evidence, citations, gaps = [], [], []
    for item in retrieved:
        # First adapter only admits project-owned clauses. Shared clauses need
        # an explicit institution-ID authority mapping before a later rollout.
        row = db.execute(select(KnowledgeUnit, KnowledgeDocument, KnowledgeDocumentVersion)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeUnit.document_id)
            .join(KnowledgeDocumentVersion, KnowledgeDocumentVersion.id == KnowledgeUnit.document_version_id)
            .where(KnowledgeUnit.id == item["knowledge_unit_id"], KnowledgeUnit.project_id == project.id,
                   KnowledgeDocument.project_id == project.id, KnowledgeDocumentVersion.project_id == project.id,
                   KnowledgeDocumentVersion.document_id == KnowledgeUnit.document_id,
                   *governed_unit_predicates(project.id))).first()
        if row is None:
            continue
        unit, document, version = row
        if (document.source_category not in NORMATIVE_CATEGORIES or version.lifecycle_status != "active"
                or not governed_document_visible(document, version, project.id, project.bank_name)):
            continue
        clause = str((unit.metadata_json or {}).get("clause_no") or unit.source_heading or "")
        if not clause or not re.search(r"第[^\s]{1,20}条|\b\d+(?:\.\d+)+\b", clause):
            gaps.append(SkillGap(code="clause_locator_missing", message="已检索文档缺少明确条款定位，未提升为制度要求"))
            continue
        evidence_id = f"knowledge:{version.id}:unit:{unit.id}"
        source = EvidenceSource(source_type="knowledge_clause", source_id=str(unit.id), source_version=str(version.id),
                                locator=f"knowledge-unit-{unit.id}", scope=scope)
        evidence.append(SkillEvidence(id=evidence_id, kind="policy_clause", source=source,
                        value={"clause": clause, "text": unit.content, "document_version_id": version.id,
                               "effective_at": str(version.effective_at) if version.effective_at else None},
                        confidentiality=unit.confidentiality_level))
        # Citation identity comes from the authorized row, never search metadata.
        citation = document_citation({"knowledge_unit_id": unit.id, "document_id": document.id,
            "document_version_id": version.id, "content": unit.content, "content_hash": unit.content_hash,
            "source_file_name": document.file_name, "source_page_no": unit.source_page_no,
            "source_heading": clause, "knowledge_type": unit.knowledge_type,
            "source_category": document.source_category, "lifecycle_status": version.lifecycle_status}, project.id)
        citations.append({**citation, "citation_id": evidence_id, "source_heading": clause, "quoted_content": unit.content})
    if not evidence:
        gaps.append(SkillGap(code="missing_basis", message="没有当前项目可用的有效制度条款，脚本事实不是监管要求"))
    return evidence, citations, gaps


def build_envelope(db, project, request, context, definition, version):
    scope = SkillScope(scope_type="task", institution_id=project.institution_id, project_id=project.id, invocation_key="lineage_graph")
    policy = SkillContent.model_validate(version.content_json).context_policy
    if request.revision_id is None:
        raise HTTPException(409, detail={"error_code": "fixed_revision_required", "gaps": [{"code": "fixed_revision_required", "message": "请选择固定血缘版本后运行 Skill"}]})
    revision = db.scalar(select(LineageRevision).where(LineageRevision.id == request.revision_id, LineageRevision.project_id == project.id))
    if revision is None:
        raise HTTPException(404, "Resource not found")
    nodes, edges = LineageRevisionService(db).members(revision)
    raw_edge = context["edge"]
    facts, gaps = [], []
    def fact(kind, locator, value):
        digest = stable_hash(locator)
        facts.append(SkillEvidence(id=f"revision:{revision.id}:{digest[:24]}", kind=kind, value=value,
            source=EvidenceSource(source_type="lineage_revision", source_id=str(revision.id),
                                  source_version=f"{revision.id}:{revision.graph_hash}", locator=digest, scope=scope),
            confidentiality=project.confidentiality_level or "internal"))
    # Raw snapshot values are never passed through legacy _text()/length slices.
    fact("lineage_edge", "edge:" + str(request.edge_id), raw_edge)
    selected_nodes = {str(raw_edge.get("source_node_key")), str(raw_edge.get("target_node_key"))}
    for node in nodes:
        if str(node.get("node_key")) in selected_nodes:
            fact("asset_identity", str(node["node_key"]), node)
    fact("script_manifest", "script_manifest", revision.source_manifest_json)
    for warning in revision.warnings_json or []:
        gaps.append(SkillGap(code="parse_gap", message=str(warning)))
    if "bounded_lineage_paths" in policy.providers:
        paths, path_gaps = bounded_paths(edges, raw_edge, policy.max_depth, policy.max_paths)
        fact("bounded_paths", "bounded_paths", paths)
        gaps.extend(path_gaps)
    for provider in sorted(set(policy.providers) - SUPPORTED_PROVIDERS):
        gaps.append(SkillGap(code="provider_not_available", message=f"上下文来源 {provider} 尚未接入本适配器"))
    extra_facts, extra_gaps = auxiliary_context(db, project, revision, nodes, raw_edge, scope, policy.providers)
    facts.extend(extra_facts)
    gaps.extend(extra_gaps)
    # Policy validity and missing-basis checks are mandatory, not configurable.
    evidence, citations, policy_gaps = policy_clauses(db, project, context, scope, policy.max_policy_clauses)
    gaps.extend(policy_gaps)
    return SkillInputEnvelope(skill_key=definition.skill_key, task_key=definition.task_key, scope=scope,
        subject_ref=f"revision:{revision.id}:edge:{stable_hash(str(request.edge_id))[:24]}", facts=facts,
        policy_evidence=evidence, gaps=gaps, max_input_bytes=policy.max_input_bytes), citations


async def explain_if_bound(db, principal, project_id, request, context, deterministic):
    if principal is None or principal.user_id is None or principal.is_legacy_system:
        return None
    project = db.get(Project, project_id)
    if project is None or project.institution_id is None:
        return None
    scope = SkillScope(scope_type="task", institution_id=project.institution_id, project_id=project.id, invocation_key="lineage_graph")
    resolved = runtime.resolve_skill(db, principal, "lineage_edge_explanation", scope)
    if resolved is None:
        return None
    definition, version, binding = resolved
    envelope, citations = build_envelope(db, project, request, context, definition, version)
    result = await runtime.execute_resolved(db, envelope, definition, version, binding)
    metadata = result["execution_metadata"]
    claims = result["claims"]
    comparisons = result["policy_comparisons"]
    has_conflict = any(item["status"] in {"conflict", "missing_implementation"} for item in comparisons)
    degraded = metadata["execution_kind"] == "degraded"
    response = {"edge_id": str(request.edge_id), "revision_id": request.revision_id,
        "facts": [{"id": f.id, "kind": f.kind, "label": f.kind, "value": f.value} for f in envelope.facts],
        "status": "degraded" if degraded else "ready", "deterministic": deterministic,
        "ai": None if degraded else {"business_summary": "；".join(c["text"] for c in claims) or "模型未提供可采纳声明，请查看脚本事实和缺口。",
            "plain_language_steps": [{"text": c["text"], "fact_ids": c["fact_ids"]} for c in claims],
            "regulatory_interpretation": "模型发现候选制度差异，需人工逐条核验" if has_conflict else "制度要求仍需人工逐条对照确认" if citations else "缺少制度依据，脚本现状不能作为监管要求",
            "regulatory_status": "conflict" if has_conflict else "needs_confirmation" if citations else "missing_basis", "regulatory_evidence_ids": [c["citation_id"] for c in citations],
            "risks": [], "open_questions": [g["message"] for g in result["gaps"]], "confidence_level": "low", "unsupported_claim_count": len(metadata["rejected_claims"])},
        "regulatory_evidence": citations, "execution_metadata": metadata,
        "model": {"provider": metadata["provider_type"], "model": metadata["model_name"], "prompt_key": metadata["prompt_key"], "prompt_version": version.version_no},
        "skill_result": result, "regression_input": envelope.model_dump(mode="json"),
        "human_confirmation": {"status": "pending", "note": "本次 AI 候选不改变已有人工确认"},
        "message": "模型输出不可用，已保留事实和缺口" if degraded else None,
        "disclaimer": "固定版本事实、制度条款、AI 候选和人工确认分层展示；AI 不改变正式需求。"}
    db.commit()
    return response
