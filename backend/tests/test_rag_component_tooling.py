"""Acceptance tooling must not manufacture business approval or lose versions."""
import importlib.util
from pathlib import Path

import pytest
from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from app.services.knowledge_ingestion.parsers import _expanded_matrix
from app.services.rag.citation_trust import normalize_version
from app.services.knowledge_version_scope import matches_version_pins

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_script(name):
    import sys
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_review():
    return load_script("rag_gold_review")


def test_numeric_prefix_keeps_distinct_frozen_revisions():
    assert normalize_version("P0-V1") != normalize_version("P0-V2")
    assert normalize_version("2026-P0-V1") != normalize_version("2026-P0-V2")
    assert not matches_version_pins("policy.md", "P0-V2", {"policy.md": "P0-V1"})
    assert matches_version_pins("policy.md", "P0-V1", {"policy.md": "P0-V1"})


def test_matrix_computes_openpyxl_bounds_once_and_preserves_merged_values(monkeypatch):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["field", "meaning"])
    sheet.append(["F250007", "01"])
    sheet.append([None, "02"])
    sheet.merge_cells("A2:A3")
    original = Worksheet.max_column.fget
    calls = []
    def measured(instance):
        calls.append(instance)
        return original(instance)
    monkeypatch.setattr(Worksheet, "max_column", property(measured))
    assert _expanded_matrix(sheet) == [["field", "meaning"], ["F250007", "01"], ["F250007", "02"]]
    assert len(calls) == 1


def test_review_export_never_treats_old_numeric_ids_as_current_gold():
    review = load_review()
    dataset = {"dataset_version": "d", "cases": [{"case_id": "c", "query": "query", "split": "holdout",
        "provenance": [], "annotations": [{"expected": {"required_units": [10]}}]}]}
    manifest = {"corpus_hash": "h", "code_hash": "c", "corpus": [
        {"unit_id": 10, "document_id": 1, "content": "unrelated"}]}
    result = review.export_review(dataset, manifest, [])
    assert result["cases"][0]["proposed_relevant_ids"] == []
    assert result["cases"][0]["review_status"] == "needs_business_review"
    assert result["summary"]["human_approved"] == 0


def test_review_import_rejects_unapproved_or_document_contaminated_split():
    review = load_review()
    dataset = {"dataset_version": "d", "cases": [
        {"case_id": "a", "split": "tuning"}, {"case_id": "b", "split": "holdout"}], "blockers": []}
    manifest = {"corpus_hash": "h", "corpus": [{"unit_id": 1, "document_id": 7}, {"unit_id": 2, "document_id": 7}]}
    pack = {"dataset_version": "d", "corpus_hash": "h", "cases": [
        {"case_id": name, "review_status": "approved", "gold": {"reviewer": "actual reviewer",
         "corpus_hash": "h", "must_refuse": False, "relevant_ids": [index], "roles": {"rule": [index]}}}
        for name, index in (("a", 1), ("b", 2))]}
    with pytest.raises(ValueError, match="share source documents"):
        review.import_review(dataset, manifest, pack)
    for row in pack["cases"]:
        row["gold"]["relevant_ids"] = []
    with pytest.raises(ValueError, match="share source documents"):
        review.import_review(dataset, manifest, pack)
    pack["cases"][0]["review_status"] = "needs_business_review"
    with pytest.raises(ValueError, match="Incomplete human review"):
        review.import_review(dataset, manifest, pack)


def test_upload_resume_uses_revision_and_hash_when_job_filename_is_redacted(monkeypatch):
    from hashlib import sha256
    from types import SimpleNamespace
    component = load_script("rag_component_acceptance")
    source = b"exact source"
    versions = [{"id": identity, "regulatory_version": "ARCHIVE-1", "file_hash": sha256(source).hexdigest(),
                 "lifecycle_status": status} for identity, status in ((2, "pending_review"), (1, "active"))]
    def get(url, **kwargs):
        if url == "/api/jobs":
            return [{"id": 1, "job_type": "knowledge_ingestion", "status": "completed",
                     "payload_summary_json": {"file_name": "corpus_[账号].xlsx", "regulatory_version": "ARCHIVE-1"}}]
        return versions
    def post(*args, **kwargs):
        raise AssertionError("A resumed upload must neither upload nor activate a duplicate")
    monkeypatch.setattr(component, "checked", lambda response: response)
    monkeypatch.setattr(component, "wait_job", lambda *a: {"id": 1, "result_summary_json": {"document_id": 1}})
    result = component.upload(SimpleNamespace(get=get, post=post), 1, "corpus_20251103171632.xlsx",
                              source, version="ARCHIVE-1")
    assert result["version_id"] == 1
