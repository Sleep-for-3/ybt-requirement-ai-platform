"""Subject resolution V2: resolve / ambiguous / not_found — never a silent default."""
from __future__ import annotations

import pytest

from app.models import Institution, Project, ScriptFile, TargetField, TargetTable, User
from app.services.agent import subject as subject_module
from app.services.agent.subject import (
    STATUS_AMBIGUOUS,
    STATUS_NOT_FOUND,
    STATUS_RESOLVED,
    objective_tokens,
    resolve_subject_v2,
    subject_candidates,
)


@pytest.fixture()
def project_scope(db_session):
    institution = Institution(institution_code="subject-bank", institution_name="主体识别银行",
                              institution_type="bank", status="active")
    db_session.add(institution)
    db_session.flush()
    project = Project(name="主体识别项目", institution_id=institution.id, project_status="active")
    db_session.add(project)
    db_session.flush()
    table = TargetTable(project_id=project.id, table_code="YBT_LOAN", table_name="贷款报送表")
    db_session.add(table)
    db_session.flush()
    fields = {}
    for code, name in (("FT_BAL", "福费廷余额"), ("ACCT_BAL", "账户余额"),
                       ("LOAN_BAL", "贷款余额"), ("CREDIT_BAL", "授信余额")):
        field = TargetField(project_id=project.id, target_table_id=table.id,
                            field_code=code, field_name=name)
        db_session.add(field)
        fields[code] = field
    db_session.flush()
    return {"db": db_session, "project": project, "table": table, "fields": fields}


def test_tokens_include_cjk_ngrams_and_codes():
    tokens = objective_tokens("分析二级市场福费廷报送需求 FT_BAL")
    assert "FT_BAL" in tokens
    assert "福费廷" in tokens
    assert "分析" in tokens


def test_a_clearly_named_field_is_resolved(project_scope):
    resolution = resolve_subject_v2(project_scope["db"], project_scope["project"],
                                    "分析二级市场福费廷余额字段的监管口径")
    assert resolution.status == STATUS_RESOLVED
    assert resolution.subject["target_field_code"] == "FT_BAL"
    assert resolution.subject["target_field_id"] == project_scope["fields"]["FT_BAL"].id
    assert resolution.confidence > 0.5


def test_objective_naming_the_family_still_resolves_a_single_candidate(project_scope):
    resolution = resolve_subject_v2(project_scope["db"], project_scope["project"],
                                    "分析二级市场福费廷报送需求")
    assert resolution.status == STATUS_RESOLVED
    assert resolution.subject["target_field_code"] == "FT_BAL"


def test_several_balance_fields_are_ambiguous_and_are_not_guessed(project_scope):
    resolution = resolve_subject_v2(project_scope["db"], project_scope["project"], "分析余额字段")
    assert resolution.status == STATUS_AMBIGUOUS
    assert resolution.subject == {}, "an ambiguous subject must never be auto-selected"
    codes = {candidate.target_field_code for candidate in resolution.candidates}
    assert {"ACCT_BAL", "LOAN_BAL", "CREDIT_BAL"} <= codes
    assert resolution.requirement, "the agent must tell the human what it needs"
    assert resolution.confidence < 0.95


def test_an_unrelated_objective_is_not_found(project_scope):
    resolution = resolve_subject_v2(project_scope["db"], project_scope["project"],
                                    "统计本周系统运行日志的告警数量")
    assert resolution.status == STATUS_NOT_FOUND
    assert resolution.subject == {}
    assert resolution.candidates == ()
    assert "第一个字段" in resolution.requirement


def test_the_first_project_field_is_never_used_as_a_default(db_session):
    institution = Institution(institution_code="no-match-bank", institution_name="无匹配银行",
                              institution_type="bank", status="active")
    db_session.add(institution)
    db_session.flush()
    project = Project(name="无匹配项目", institution_id=institution.id, project_status="active")
    db_session.add(project)
    db_session.flush()
    table = TargetTable(project_id=project.id, table_code="ZZ_T", table_name="无关表")
    db_session.add(table)
    db_session.flush()
    db_session.add(TargetField(project_id=project.id, target_table_id=table.id,
                               field_code="ZZ_001", field_name="完全不相关字段"))
    db_session.flush()
    resolution = resolve_subject_v2(db_session, project, "分析二级市场福费廷报送需求")
    assert resolution.status == STATUS_NOT_FOUND
    assert resolution.subject == {}


def test_an_exact_code_in_the_objective_wins(project_scope):
    resolution = resolve_subject_v2(project_scope["db"], project_scope["project"],
                                    "请分析 LOAN_BAL 的口径与实现差异")
    assert resolution.status == STATUS_RESOLVED
    assert resolution.subject["target_field_code"] == "LOAN_BAL"
    assert resolution.confidence >= 0.9


def test_a_script_target_is_a_candidate_even_without_a_name_match(project_scope):
    db = project_scope["db"]
    db.add(ScriptFile(project_id=project_scope["project"].id, file_name="credit_bal.sql",
                      relative_path="scripts/credit_bal.sql", file_type="sql",
                      logical_target_name="CREDIT_BAL"))
    db.flush()
    resolution = resolve_subject_v2(db, project_scope["project"], "分析信贷口径实现")
    assert any(candidate.matched_on == "script_target" for candidate in resolution.candidates)


def test_candidates_are_ranked_and_bounded(project_scope):
    candidates = subject_candidates(project_scope["db"], project_scope["project"], "分析余额")
    assert len(candidates) <= subject_module.MAX_CANDIDATES
    scores = [candidate.score for candidate in candidates]
    assert scores == sorted(scores, reverse=True)
    assert all("score" in candidate.as_dict() for candidate in candidates)


def test_resolution_payload_is_json_safe(project_scope):
    payload = resolve_subject_v2(project_scope["db"], project_scope["project"], "分析余额字段").as_dict()
    assert payload["status"] == STATUS_AMBIGUOUS
    assert isinstance(payload["candidates"], list) and payload["candidates"]
    assert set(payload["candidates"][0]) == {"target_field_id", "target_field_code", "target_field_name",
                                             "target_table_id", "score", "matched_on", "matched_token"}
