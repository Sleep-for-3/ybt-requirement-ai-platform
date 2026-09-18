"""Focused regressions for the resources/data answer and preview boundary."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models import Project, KnowledgeDocument, KnowledgeDocumentVersion
from app.services.knowledge_evidence import mode_knowledge_types, REGULATORY_TYPES, DATA_FIELD_TYPES
from app.services.rag import grounded_answer_service as grounded
from app.services.rag import document_preview_service as preview
from app.services.rag import data_field_answer_service as fields
from app.services.knowledge_ingestion.parsers import parse_document
from app.services.auth.dependencies import Principal
from resources_data_fixtures import seed_resources, sample_files


@pytest.fixture
def resources(db_session):
    return seed_resources(db_session)


def test_mode_allowlists_never_fall_back_to_unfiltered():
    assert set(mode_knowledge_types("regulatory", [])) == REGULATORY_TYPES
    assert set(mode_knowledge_types("data_field", [])) == DATA_FIELD_TYPES
    for mode, forbidden in [("regulatory", "sql_evidence"), ("data_field", "regulatory_policy")]:
        selected = mode_knowledge_types(mode, [forbidden])
        assert selected and forbidden not in selected


def test_same_bank_name_does_not_authorize_original(db_session, monkeypatch):
    owner = Project(name="owner", bank_name="same descriptive label")
    other = Project(name="other", bank_name="same descriptive label")
    db_session.add_all([owner, other]); db_session.flush()
    doc = KnowledgeDocument(project_id=owner.id, file_name="policy.txt", file_type="txt",
        source_type="manual_note", storage_path="synthetic-object", knowledge_scope="institution",
        institution_name=owner.bank_name, document_status="indexed", confidentiality_level="internal")
    db_session.add(doc); db_session.flush()
    version = KnowledgeDocumentVersion(project_id=owner.id, document_id=doc.id, version_no=1,
        file_name="policy.txt", storage_path="synthetic-object", file_hash="a" * 64)
    db_session.add(version); db_session.commit()
    monkeypatch.setattr(preview.PermissionService, "require_project_permission", lambda *args: other)
    with pytest.raises(HTTPException) as failure:
        preview.authorized_version(db_session, None, other.id, doc.id)
    assert failure.value.status_code == 404
    assert failure.value.detail == "Resource not found"


@pytest.mark.parametrize("claim", ["Invented.column", "Known.table [99999]", "Known.table.column"])
def test_invented_claim_is_not_grounded(db_session, monkeypatch, claim):
    item = dict(knowledge_unit_id=1, content="Known.table", confidentiality_level="internal", rerank_score=1)
    monkeypatch.setattr(grounded.HybridRetriever, "search", lambda *a, **k: (SimpleNamespace(id=1), [item]))
    monkeypatch.setattr(grounded, "document_citation", lambda *a: {"knowledge_unit_id": 1})
    monkeypatch.setattr(grounded, "validate_citations", lambda *a, **k: None)
    monkeypatch.setattr(grounded, "get_prompt_runtime", lambda *a: None)
    monkeypatch.setattr(grounded, "evidence_runtime", lambda runtime: runtime)
    monkeypatch.setattr(grounded, "prepare_model_input", lambda *a, **k: "synthetic evidence")
    async def invented(*a, **k):
        return {"answer": claim, "confidence_level": "high", "supported_claims": [claim]}
    monkeypatch.setattr(grounded, "execute_runtime_chat", invented)
    answer = asyncio.run(grounded.grounded_answer(db_session, 1, "question"))
    assert answer["answer_status"] == "needs_confirmation"
    assert answer["confidence_level"] == "low"
    assert not answer["supported_claims"]
    assert answer["unsupported_claims"] and answer["open_questions"]


def test_technical_identifiers_use_exact_tokens():
    assert grounded._invented_qualified_identifiers("Known.table", "Unknown.table") == ["Known.table"]
    assert grounded._invented_qualified_identifiers("KNOWN.table", "known.TABLE") == []


def test_real_catalog_source_mapping_and_edges_are_bounded_candidates(db_session, resources):
    _, sections, citations = fields.collect_field_evidence(
        db_session, resources.project.id, "CERT_TYPE", resources.target.id, resources.scenario.id)
    assert {c["citation_type"] for c in citations} >= {"catalog_column", "mapping", "lineage_edge"}
    assert any(c.get("source_field_id") == resources.source.id for c in citations)
    assert any(c.get("mapping_id") == resources.mapping.id for c in citations)
    assert all(c["project_id"] == resources.project.id for c in citations)
    assert len(citations) <= 44 and len({c["citation_id"] for c in citations}) == len(citations)
    assert sections["join_conditions"] and sections["transformations"] and sections["code_mappings"]
    assert all(p["status"] == "candidate" for p in sections["source_paths"] if p.get("source_field_id") or p.get("catalog_column_id"))
    _, foreign, foreign_citations = fields.collect_field_evidence(db_session, resources.other.id, "CERT_TYPE")
    assert not foreign_citations and not foreign["source_paths"]


@pytest.mark.parametrize("failure", ["invented", "missing_citation", "provider", "empty"])
def test_field_model_contract(db_session, resources, monkeypatch, failure):
    async def reply(*args, **kwargs):
        if failure == "provider":
            raise RuntimeError("internal exception must stay private")
        if failure == "empty":
            return {"claims": []}
        return {"claims": [{"citation_id": "missing" if failure == "missing_citation" else f"catalog_column-{resources.column.id}", "text": "INVENTED.TABLE"}]}
    monkeypatch.setattr(fields, "execute_runtime_chat", reply)
    result = asyncio.run(fields.data_field_answer(db_session, resources.project.id, "CERT_TYPE",
        target_field_id=resources.target.id, scenario_id=resources.scenario.id, retrieval_mode="keyword_only"))
    assert result["citations"] and result["sections"]["source_paths"]
    assert result["answer_status"] == ("degraded" if failure == "provider" else "needs_confirmation")
    assert "INVENTED.TABLE" not in result["answer"]
    assert "internal exception" not in str(result)
    if failure in {"invented", "missing_citation"}:
        assert result["unsupported_claims"] and result["sections"]["gaps"]


def test_empty_field_evidence_never_invokes_model(db_session, resources, monkeypatch):
    async def unexpected(*args, **kwargs):
        pytest.fail("No-evidence answer must not call the model")
    monkeypatch.setattr(fields, "execute_runtime_chat", unexpected)
    result = asyncio.run(fields.data_field_answer(db_session, resources.other.id, "ZXQ_999", retrieval_mode="keyword_only"))
    assert not result["citations"]
    assert result["answer_status"] == "needs_confirmation" and result["open_questions"]


def test_actual_retrieval_mode_isolation_and_legacy(db_session, resources):
    from app.api.knowledge_rag import AskRequest, ask
    principal = Principal(None, "synthetic", None, True)
    for mode, allowed in [("regulatory", REGULATORY_TYPES), ("data_field", DATA_FIELD_TYPES), (None, REGULATORY_TYPES | DATA_FIELD_TYPES)]:
        result = asyncio.run(ask(resources.project.id, AskRequest(query="客户证件类型 CERT_TYPE", answer_mode=mode, retrieval_mode="keyword_only"), principal, db_session))
        doc_citations = [c for c in result["citations"] if c["citation_type"] == "knowledge_document"]
        assert doc_citations
        assert all(c["source_type"] in allowed for c in doc_citations)
        assert {"answer", "confidence_level", "citations", "supported_claims", "unsupported_claims", "open_questions", "retrieval_log_id", "answer_status"} <= result.keys()
    with pytest.raises(HTTPException):
        asyncio.run(ask(resources.other.id, AskRequest(query="test", target_field_id=resources.target.id), principal, db_session))


def test_original_versions_and_headers(db_session, resources, monkeypatch):
    principal = Principal(None, "synthetic", None, True)
    doc = resources.documents["policy.docx"]
    old = preview.authorized_version(db_session, principal, resources.project.id, doc.id)[1]
    second = KnowledgeDocumentVersion(project_id=resources.project.id, document_id=doc.id, version_no=2,
        file_name="第二版.docx", storage_path=old.storage_path, file_hash="b" * 64, parse_status="indexed")
    db_session.add(second); doc.current_version_no = 2; db_session.commit()
    assert preview.authorized_version(db_session, principal, resources.project.id, doc.id)[1].id == second.id
    assert preview.authorized_version(db_session, principal, resources.project.id, doc.id, old.id)[1].id == old.id
    monkeypatch.setattr(preview, "get_storage_service", lambda: SimpleNamespace(read=lambda key: resources.files[key]))
    response = preview.original_content(second)
    assert response.body == resources.files[old.storage_path]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert response.headers["content-disposition"].startswith("inline")
    assert "storage_path" not in str(preview.preview_document(db_session, doc, old))
    for version_id in (999999, preview.authorized_version(db_session, principal, resources.project.id, resources.documents["policy.pdf"].id)[1].id):
        with pytest.raises(HTTPException):
            preview.authorized_version(db_session, principal, resources.project.id, doc.id, version_id)
    doc.document_status = "archived"; db_session.commit()
    with pytest.raises(HTTPException):
        preview.authorized_version(db_session, principal, resources.project.id, doc.id, old.id)


@pytest.mark.parametrize("scope,level,allowed", [("project","internal",False),("institution","internal",False),("global","restricted",False),("global","internal",True)])
def test_preview_cross_project_scope(db_session, resources, scope, level, allowed):
    principal = Principal(None, "synthetic", None, True)
    doc = resources.documents["policy.pdf"]
    doc.knowledge_scope = scope; doc.confidentiality_level = level
    doc.institution_name = resources.project.bank_name; db_session.commit()
    if allowed:
        assert preview.authorized_version(db_session, principal, resources.other.id, doc.id)[0].id == doc.id
    else:
        with pytest.raises(HTTPException) as exc:
            preview.authorized_version(db_session, principal, resources.other.id, doc.id)
        assert exc.value.status_code == 404
    # A principal with no membership cannot use any scope via a forbidden project.
    with pytest.raises(HTTPException):
        preview.authorized_version(db_session, Principal(99999, "no-membership", None), resources.project.id, doc.id)


@pytest.mark.parametrize("name", ["regulatory.xlsx", "policy.docx", "policy.pdf", "dictionary.txt", "notes.md", "transform.sql"])
def test_six_formats_have_locators(name):
    data, kind = sample_files()[name]
    units, _ = parse_document(name, data, kind)
    assert units and all(u.metadata.get("locator") for u in units)
    if name.endswith(".pdf"):
        assert all(u.metadata["locator"]["page_no"] == 1 for u in units)
    if name.endswith(".xlsx"):
        assert units[0].metadata["locator"]["cell_range"] == "A2:B2"
    if name.endswith((".txt", ".md", ".sql")):
        assert all(u.metadata["locator"]["line_start"] >= 1 for u in units)


def test_scan_pdf_warns_without_fake_coordinates():
    data, kind = sample_files()["scan.pdf"]
    units, warnings = parse_document("scan.pdf", data, kind)
    assert not units and any("OCR" in warning for warning in warnings)


def test_protected_preview_and_entity_api(db_session, resources, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.database import get_db
    from app.models import User, ProjectMembership
    from app.services.auth.dependencies import get_current_principal
    user=User(username="resource-test-reader",display_name="Synthetic reader")
    db_session.add(user);db_session.flush()
    db_session.add(ProjectMembership(project_id=resources.project.id,user_id=user.id,project_role="technical_analyst",status="active"))
    db_session.commit()
    principal=Principal(user.id,user.username,user.display_name)
    previous=dict(app.dependency_overrides)
    app.dependency_overrides[get_db]=lambda:db_session
    app.dependency_overrides[get_current_principal]=lambda:principal
    monkeypatch.setattr(preview,"get_storage_service",lambda:SimpleNamespace(read=lambda key:resources.files[key]))
    try:
        with TestClient(app) as client:
            doc=resources.documents["regulatory.xlsx"]
            response=client.get(f"/api/knowledge/documents/{doc.id}/preview?project_id={resources.project.id}")
            assert response.status_code==200
            assert response.json()["sheets"][0]["rows"][1][0]=="客户证件类型报送范围"
            for suffix in ("preview","content"):
                response=client.get(f"/api/knowledge/documents/{doc.id}/{suffix}?project_id={resources.other.id}")
                assert response.status_code==404
                assert not any(key in response.text for key in ("storage_path","fixture/","policy.pdf"))
            response=client.get(f"/api/projects/{resources.project.id}/knowledge/evidence/catalog_column/{resources.column.id}")
            assert response.status_code==200 and response.json()["fields"]["column_name"]=="CERT_TYPE"
            response=client.get(f"/api/projects/{resources.other.id}/knowledge/evidence/catalog_column/{resources.column.id}")
            assert response.status_code==404
    finally:
        app.dependency_overrides.clear();app.dependency_overrides.update(previous)
