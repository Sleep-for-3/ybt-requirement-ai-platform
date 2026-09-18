import asyncio
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from fastapi import UploadFile

from app.core.settings import get_settings
from app.models import (KnowledgeDocumentVersion, KnowledgeUnit, Project, TargetField,
                        TemplateApplication, TemplateDocument, TemplateParseResult, TemplateVersion)
from app.services.knowledge_ingestion.ingestion_service import (activate_knowledge_version,
    ingest_knowledge_document, review_knowledge_version)
from app.services.retrieval.hybrid_retriever import HybridRetriever
from app.services.storage import get_storage_service
from app.services.template_service import (activate_template_version, apply_template,
    review_template_version, template_version_diff)


def _project(db):
    item = Project(name="治理测试", bank_name="测试银行")
    db.add(item); db.commit(); db.refresh(item)
    return item


def test_template_draft_review_activation_diff_and_apply_audit(db_session):
    project = _project(db_session)
    document = TemplateDocument(project_id=project.id, file_name="监管模板.xlsx", file_type="xlsx",
        storage_path="safe-key", sheet_names_json=["A"], parse_status="success", template_code="YBT",
        display_name="一表通")
    db_session.add(document); db_session.flush()
    base = [{"sheet_name":"A","table_code":"T1","table_name":"表一","rows":[
        {"field_code":"F1","field_name":"字段一","field_type":"VARCHAR","required_flag":False},
        {"field_code":"F3","field_name":"待删除字段","field_type":"VARCHAR","required_flag":False}]}]
    changed = [{"sheet_name":"A","table_code":"T1","table_name":"表一","rows":[
        {"field_code":"F1","field_name":"字段一新","field_type":"INTEGER","required_flag":True},
        {"field_code":"F2","field_name":"字段二","field_type":"VARCHAR","required_flag":False}]}]
    first = TemplateVersion(template_document_id=document.id, project_id=project.id, version_no=1,
        regulatory_version="2025批次", template_code="YBT", status="active", file_name="v1.xlsx",
        file_type="xlsx", storage_path="v1", file_hash="a"*64, sheet_names_json=["A"],
        parsed_snapshot_json=base, parse_status="success")
    second = TemplateVersion(template_document_id=document.id, project_id=project.id, version_no=2,
        regulatory_version="2026批次", template_code="YBT", status="pending_review", file_name="v2.xlsx",
        file_type="xlsx", storage_path="v2", file_hash="b"*64, sheet_names_json=["A"],
        parsed_snapshot_json=changed, parse_status="success")
    db_session.add_all([first, second]); db_session.flush(); document.current_version_id=first.id
    db_session.add(TemplateParseResult(template_document_id=document.id, template_version_id=second.id,
        project_id=project.id, sheet_name="A", table_code="T1", table_name="表一", field_count=2,
        raw_header_json=[], parsed_rows_json=changed[0]["rows"], warnings_json=[])); db_session.commit()
    assert document.current_version_id == first.id  # upload did not replace active
    diff = template_version_diff(db_session, second.id)
    assert diff["summary"] == {"added": 1, "removed": 1, "modified": 1}
    review_template_version(db_session, second.id, "reviewer")
    activate_template_version(db_session, second.id)
    assert document.current_version_id == second.id and first.status == "superseded"
    summary = apply_template(db_session, document.id, applied_by="operator")
    assert summary.template_version_id == second.id and summary.application_id
    assert summary.created_fields == 2 and summary.change_set
    audit = db_session.get(TemplateApplication, summary.application_id)
    assert audit.template_version_id == second.id and audit.before_snapshot_json == []


def test_governed_knowledge_renamed_version_waits_and_failed_parse_keeps_active(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear(); get_storage_service.cache_clear()
    project = _project(db_session)
    first = asyncio.run(ingest_knowledge_document(db_session, project.id,
        UploadFile(file=BytesIO("客户证件类型当前规则".encode()), filename="原文件.txt"),
        "regulatory_policy"))
    active_id = first.current_version_id
    assert active_id and db_session.get(KnowledgeDocumentVersion, active_id).lifecycle_status == "active"
    same = asyncio.run(ingest_knowledge_document(db_session, project.id,
        UploadFile(file=BytesIO("客户证件类型候选新规则".encode()), filename="已改名文件.txt"),
        "regulatory_policy", document_id=first.id, source_category="regulatory_formal",
        regulatory_version="2026", internal_revision="R2"))
    candidate = db_session.query(KnowledgeDocumentVersion).filter_by(document_id=first.id, version_no=2).one()
    assert same.id == first.id and first.current_version_id == active_id
    assert candidate.lifecycle_status == "pending_review"
    assert db_session.query(KnowledgeUnit).filter_by(document_version_id=active_id, enabled=True).count() > 0
    assert db_session.query(KnowledgeUnit).filter_by(document_version_id=candidate.id, enabled=True).count() == 0

    from app.services.knowledge_ingestion import ingestion_service
    monkeypatch.setattr(ingestion_service, "parse_document", lambda *args: (_ for _ in ()).throw(ValueError("private path")))
    with pytest.raises(ValueError):
        asyncio.run(ingest_knowledge_document(db_session, project.id,
            UploadFile(file=BytesIO(b"broken"), filename="第三版.txt"), "regulatory_policy",
            document_id=first.id, source_category="regulatory_formal"))
    db_session.refresh(first)
    failed = db_session.query(KnowledgeDocumentVersion).filter_by(document_id=first.id, version_no=3).one()
    assert first.current_version_id == active_id and failed.parse_status == "failed"
    assert "private path" not in (failed.error_message or "")

    review_knowledge_version(db_session, candidate.id, "reviewer")
    activate_knowledge_version(db_session, candidate.id)
    db_session.refresh(first)
    assert first.current_version_id == candidate.id
    assert db_session.query(KnowledgeUnit).filter_by(document_version_id=active_id, enabled=True).count() == 0


def test_current_regulatory_authority_sorts_before_business_material(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path)); get_settings.cache_clear(); get_storage_service.cache_clear()
    project = _project(db_session)
    business = asyncio.run(ingest_knowledge_document(db_session, project.id,
        UploadFile(file=BytesIO("证件类型报送规则业务备注".encode()), filename="备注.txt"), "manual_note"))
    official = asyncio.run(ingest_knowledge_document(db_session, project.id,
        UploadFile(file=BytesIO("证件类型报送规则监管原文".encode()), filename="正式文件.txt"), "regulatory_policy"))
    business.source_category = "business_material"; official.source_category = "regulatory_formal"; db_session.commit()
    _, items = HybridRetriever(db_session).search(project.id, "证件类型报送规则", retrieval_mode="keyword_only")
    assert items and items[0]["document_id"] == official.id
    assert items[0]["authority_rank"] > items[-1]["authority_rank"]


def test_default_retrieval_excludes_noncurrent_invalid_versions_and_history_is_explicit(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path)); get_settings.cache_clear(); get_storage_service.cache_clear()
    project = _project(db_session)
    document = asyncio.run(ingest_knowledge_document(db_session, project.id,
        UploadFile(file=BytesIO("证件类型旧口径".encode()), filename="旧名.txt"), "regulatory_policy"))
    old_id = document.current_version_id
    asyncio.run(ingest_knowledge_document(db_session, project.id,
        UploadFile(file=BytesIO("证件类型当前新口径".encode()), filename="改名后的新版本.txt"), "regulatory_policy",
        document_id=document.id, source_category="regulatory_formal", regulatory_version="2026", internal_revision="R2"))
    candidate = db_session.query(KnowledgeDocumentVersion).filter_by(document_id=document.id, version_no=2).one()
    _, before = HybridRetriever(db_session).search(project.id, "证件类型口径", retrieval_mode="keyword_only")
    assert {item["document_version_id"] for item in before} == {old_id}
    review_knowledge_version(db_session, candidate.id, "reviewer"); activate_knowledge_version(db_session, candidate.id)
    _, current = HybridRetriever(db_session).search(project.id, "证件类型口径", retrieval_mode="keyword_only")
    assert {item["document_version_id"] for item in current} == {candidate.id}
    _, history = HybridRetriever(db_session).search(project.id, "证件类型口径", retrieval_mode="keyword_only", include_history=True)
    assert {item["document_version_id"] for item in history} == {old_id, candidate.id}
    assert any(item["historical"] for item in history if item["document_version_id"] == old_id)
    candidate.expires_at = datetime.now(timezone.utc) - timedelta(days=1); db_session.commit()
    assert not HybridRetriever(db_session).search(project.id, "证件类型口径", retrieval_mode="keyword_only")[1]
    candidate.expires_at = None; candidate.lifecycle_status = "withdrawn"; db_session.commit()
    assert not HybridRetriever(db_session).search(project.id, "证件类型口径", retrieval_mode="keyword_only")[1]


def test_conflicting_authoritative_evidence_is_reported():
    from app.services.rag.grounded_answer_service import _evidence_conflicts
    conflicts = _evidence_conflicts([
        {"knowledge_unit_id": 1, "authority_rank": 6, "content_hash": "a", "metadata_json": {"conflict_key": "CERT_TYPE"}},
        {"knowledge_unit_id": 2, "authority_rank": 5, "content_hash": "b", "metadata_json": {"conflict_key": "CERT_TYPE"}},
    ])
    assert conflicts == [{"topic": "CERT_TYPE", "message": "多份当前高权威资料口径不一致，需要人工确认。",
        "citation_ids": ["knowledge-unit-1", "knowledge-unit-2"]}]
