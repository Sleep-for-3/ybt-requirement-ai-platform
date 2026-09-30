"""Bounded literal decomposition and authority-preserving reciprocal-rank fusion."""
import re
import time

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, or_

from app.models import RetrievalLog, TargetField, ProductScenario, KnowledgeUnit, KnowledgeDocument, KnowledgeDocumentVersion
from app.services.auth.permission_service import PermissionService
from app.services.knowledge_eligibility import governed_unit_predicates, governed_document_visible
from app.services.rag.data_field_answer_service import project_entity
from .hybrid_retriever import HybridRetriever

PLAN_VERSION = "literal-clauses-rrf-1"
MAX_SUBQUERIES = 3
RRF_K = 60


class PlannedSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    target_field_id: int | None = Field(default=None, gt=0, strict=True)
    scenario_id: int | None = Field(default=None, gt=0, strict=True)
    knowledge_types: list[str] = Field(default_factory=list, max_length=20)
    top_k: int = Field(default=20, ge=1, le=50, strict=True)

    @field_validator("query")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("查询不能为空")
        return value.strip()


def query_plan(query):
    # Preserve identifiers and quoted expressions; never infer missing context.
    if any(mark in query for mark in ('"', "'", "`", "“", "”", "‘", "’")):
        clauses, notice = [], "包含引号，仅检索完整问题以保留原始表达式。"
    else:
        clauses = list(dict.fromkeys(part.strip() for part in re.split(r"[；;？?\n]+", query) if part.strip()))
        notice = ""
        if len(clauses) > MAX_SUBQUERIES:
            clauses, notice = [], "分句超过三项，仅检索完整问题；未截断原问题。"
        elif len(clauses) < 2:
            clauses = []
    return {"version": PLAN_VERSION, "queries": [query] + [part for part in clauses if part != query],
            "notice": notice, "execution_kind": "deterministic", "retrieval_mode": "keyword_only",
            "max_passes": 1 + MAX_SUBQUERIES, "rrf_k": RRF_K}


def fuse_rounds(rounds, top_k):
    merged = {}
    for round_no, items in enumerate(rounds, 1):
        seen = set()
        for rank, item in enumerate(items, 1):
            identity = item["knowledge_unit_id"]
            if identity in seen:
                continue
            seen.add(identity)
            if identity not in merged:
                merged[identity] = {**item, "fusion_score": 0.0, "retrieval_rounds": []}
            candidate = merged[identity]
            if any(candidate.get(key) != item.get(key) for key in ("content_hash", "document_version_id", "content")):
                raise HTTPException(409, "检索期间资料发生变化，请重新检索")
            candidate["fusion_score"] += 1 / (RRF_K + rank)
            candidate["retrieval_rounds"].append({"round": round_no, "rank": rank})
    items = sorted(merged.values(), key=lambda item: (-item["authority_rank"], -item["fusion_score"], item["knowledge_unit_id"]))
    return [{**item, "fusion_score": round(item["fusion_score"], 8)} for item in items[:top_k]]


def planned_search(db, principal, project_id, payload):
    if principal.user_id is None:
        raise HTTPException(401, "Authenticated user required")
    permissions = PermissionService(db, principal)
    permissions.require_project_permission(project_id, "knowledge.search")
    project_entity(db, TargetField, payload.target_field_id, project_id)
    project_entity(db, ProductScenario, payload.scenario_id, project_id)
    plan = query_plan(payload.query)
    started = time.perf_counter()
    rounds, log_ids = [], []
    for query in plan["queries"]:
        permissions.require_project_permission(project_id, "knowledge.search")
        log, items = HybridRetriever(db).search(project_id, query,
            target_field_id=payload.target_field_id, scenario_id=payload.scenario_id,
            knowledge_types=payload.knowledge_types, top_k=payload.top_k,
            retrieval_mode="keyword_only", include_history=False, commit=False,
            created_by=principal.username)
        rounds.append(items)
        log_ids.append(log.id)
    db.expire_all()
    project = permissions.require_project_permission(project_id, "knowledge.search")
    items = fuse_rounds(rounds, payload.top_k)
    if items:
        current_query = select(KnowledgeUnit, KnowledgeDocument, KnowledgeDocumentVersion).join(
            KnowledgeDocument, KnowledgeDocument.id == KnowledgeUnit.document_id).join(
            KnowledgeDocumentVersion, KnowledgeDocumentVersion.id == KnowledgeUnit.document_version_id).where(
            KnowledgeUnit.id.in_([item["knowledge_unit_id"] for item in items]),
            *governed_unit_predicates(project_id),
            KnowledgeDocumentVersion.document_id == KnowledgeDocument.id,
            KnowledgeDocumentVersion.project_id == KnowledgeUnit.project_id,
            KnowledgeDocument.project_id == KnowledgeUnit.project_id)
        if payload.scenario_id:
            current_query = current_query.where(or_(KnowledgeUnit.scenario_id.is_(None), KnowledgeUnit.scenario_id == payload.scenario_id))
        if payload.knowledge_types:
            current_query = current_query.where(KnowledgeUnit.knowledge_type.in_(payload.knowledge_types))
        current = {unit.id: unit for unit, document, version in db.execute(current_query)
                   if governed_document_visible(document, version, project_id, project.bank_name)}
        for item in items:
            unit = current.get(item["knowledge_unit_id"])
            if unit is None or (unit.content_hash, unit.document_version_id, unit.content) != (
                    item["content_hash"], item["document_version_id"], item["content"]):
                raise HTTPException(409, "检索期间资料失效或发生变化，请重新检索")
    log = RetrievalLog(project_id=project_id, query_text=payload.query, query_type="planned_keyword",
        target_field_id=payload.target_field_id, scenario_id=payload.scenario_id,
        filters_json={"plan": plan, "child_log_ids": log_ids, "knowledge_types": payload.knowledge_types,
                      "top_k": payload.top_k, "include_history": False},
        retrieval_strategy=PLAN_VERSION, keyword_result_count=len({item["knowledge_unit_id"] for rows in rounds for item in rows}),
        vector_result_count=0, final_result_count=len(items), result_ids_json=[item["knowledge_unit_id"] for item in items],
        latency_ms=int((time.perf_counter() - started) * 1000), created_by=principal.username)
    db.add(log); db.flush()
    return {"retrieval_log_id": log.id, "retrieval_mode": "keyword_only", "query_plan": plan,
            "rounds": [{"query": query, "retrieval_log_id": log_id, "result_count": len(rows)}
                       for query, log_id, rows in zip(plan["queries"], log_ids, rounds)],
            "items": items, "requires_human_confirmation": True}
