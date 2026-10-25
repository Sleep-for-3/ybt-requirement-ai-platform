"""P0-B：候选正文语义支持校验（claim-support-v1）的定向测试。

覆盖需求单要求的 8 类反例，全部断言「不得被判为已支持」（conflict 或 unknown），
并覆盖向后兼容（旧候选无 claims 仍可读、标记未执行校验）与三态可见性。
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.services import requirement_claim_support as claim_support
from app.services import requirement_generation_worker as worker
from app.services.ai_skills.requirement_context import build_requirement_envelope, validate_requirement_output
from app.services.llm.execution_metadata import stable_hash
from app.services.requirement_candidate_contract import (
    CLAIM_SUPPORT_VERSION,
    CandidateClaim,
    ClaimSupport,
    RequirementCandidate,
    check_candidate_compliance,
    project_candidate_context,
)

PROJECT = SimpleNamespace(id=1, institution_id=2, confidentiality_level="internal")


def evidence_unit(unit_id=4, content="只报送正常贷款余额。", version="2026-v1",
                  title="贷款风险分类管理办法"):
    return {"unit_id": unit_id, "document_id": 1, "document_version_id": 5,
            "content_hash": f"hash-{unit_id}", "content": content, "title": title,
            "confidentiality_level": "internal", "source_category": "regulatory_formal",
            "regulatory_version": version, "lifecycle_status": "active",
            "locator": {"paragraph_index": 1}}


def rule(rule_id, **overrides):
    base = {"rule_id": rule_id, "script_version_id": 1, "statement_id": 1,
            "source_line_start": 1, "source_line_end": 1,
            "source": {"node_id": 1, "table_name": "loan", "column_name": "loan_bal"},
            "target": {"node_id": 2, "table_name": "report", "column_name": "amount"},
            "edge_type": "filter", "transformation_type": "direct",
            "transformation_expression": "a.loan_bal", "join_condition": "",
            "filter_condition": "", "aggregation_rule": "", "code_mapping_rule": "",
            "confidence_level": "high"}
    base.update(overrides)
    return base


RULES = [
    rule("script-edge-11", filter_condition="a.loan_status = 'NORMAL'"),
    rule("script-edge-12", join_condition="a.customer_id = b.customer_id and a.loan_id = b.loan_id"),
    rule("script-edge-13", aggregation_rule="sum(a.loan_bal) group by a.branch_no"),
]

METADATA = [{"id": 1, "database_name": "bank", "schema_name": "ods", "table_name": "loan",
             "assignment": "source", "architecture_revision_id": 1,
             "columns": [
                 {"id": 1, "name": "loan_status", "data_type": "varchar", "comment": "贷款状态"},
                 {"id": 2, "name": "loan_bal", "data_type": "decimal", "comment": "贷款余额"},
                 {"id": 3, "name": "customer_id", "data_type": "varchar", "comment": "客户号"},
                 {"id": 4, "name": "loan_id", "data_type": "varchar", "comment": "借据号"},
                 {"id": 5, "name": "branch_no", "data_type": "varchar", "comment": "机构号"}]}]


def frozen_input(**overrides):
    payload = {
        "policy_version": "requirement-input-v1", "project_id": 1, "requirement_id": 1,
        "content_version": 1, "content_hash": "content-hash", "scope_version": 1,
        "requirement": {"name": "贷款余额报送", "objective": "按监管口径报送贷款余额",
                        "background": "", "effective_date": "2026-09-30",
                        "inclusion": "正常类贷款", "exclusion": "", "target_table_id": 2,
                        "scenario_id": 1},
        "scenario": {"id": 1, "name": "监管报送"}, "field_ids": [3],
        "sections": ["business", "lineage"], "allowed": {"document_ids": []},
        "fields": [{"target": {"id": 3}, "authored": {}}],
        "physical_sources": [{"kind": "source", "table_id": 2, "field_id": 3,
                              "table_code": "loan", "table_name": "贷款", "field_code": "loan_bal",
                              "field_name": "贷款余额", "field_type": "decimal",
                              "table_version": 1, "field_version": 1}],
        "evidence": [evidence_unit()], "limitations": [],
        "pinned_versions": {"贷款风险分类管理办法": "2026-v1"},
        "script_basis": {"policy_version": "requirement-script-basis-v1", "versions": {},
                         "statements": [], "targets": [], "rules": deepcopy(RULES),
                         "metadata": deepcopy(METADATA), "gaps": [], "confirmation": {},
                         "template": {}, "preview_hash": "preview"},
    }
    payload.update(overrides)
    return payload


def context(**overrides):
    return project_candidate_context(frozen_input(**overrides), 3, "business")


def claim(claim_id="C1", text="仅报送正常贷款余额。", kind="filter", support=None,
          section="business"):
    return {"claim_id": claim_id, "section": section, "text": text,
            "assertion_kind": kind, "support": support if support is not None else [support_item()]}


def support_item(source="evidence", ref_id="4", status="supported", **extra):
    payload = {"source": source, "ref_id": ref_id, "status": status,
               "method": "deterministic_fact_match", "method_version": CLAIM_SUPPORT_VERSION}
    payload.update(extra)
    return payload


def candidate(*claims, content="仅报送正常贷款余额。", evidence_ids=(4,), rule_ids=(), **extra):
    payload = {"final_content": content, "evidence_unit_ids": list(evidence_ids),
               "script_rule_ids": list(rule_ids), "claims": list(claims)}
    payload.update(extra)
    return RequirementCandidate.model_validate(payload).model_dump()


def report_of(*claims, ctx=None, **extra):
    return claim_support.evaluate_claim_support(ctx or context(), candidate(*claims, **extra))


def assert_not_supported(report):
    assert report.status != "supported"
    assert report.status in {"conflict", "unknown"}
    assert report.violations, "不得在存在未支持主张时返回空违规列表"


# --------------------------------------------------------------------------- #
# 8 类反例：每一个都不得被判为已支持
# --------------------------------------------------------------------------- #
def test_negation_flip_of_pinned_normal_loans_is_conflict():
    """反例1：证据「只报送正常贷款余额」，正文反转成「逾期 / 无需筛选正常」。"""
    report = report_of(claim(text="报送所有逾期贷款余额，无需筛选正常状态。"))
    assert_not_supported(report)
    assert report.status == "conflict"
    assert any("filter_negation_flip" in item for item in report.evaluations[0].codes)


def test_missing_filter_condition_is_conflict():
    """反例2：引用的规则过滤 loan_status，正文完全没提该列（漏过滤）。"""
    report = report_of(claim(text="报送贷款余额。", support=[support_item("script_rule", "script-edge-11")]),
                       rule_ids=("script-edge-11",))
    assert_not_supported(report)
    assert report.status == "conflict"
    assert "filter_column_missing" in report.evaluations[0].codes


def test_single_key_replacing_composite_join_is_conflict():
    """反例3：复合关联键 customer_id + loan_id，正文只提一个键。"""
    report = report_of(claim(text="按 customer_id 关联客户台账与贷款台账。", kind="join_key",
                             support=[support_item("script_rule", "script-edge-12")]),
                       rule_ids=("script-edge-12",))
    assert_not_supported(report)
    assert report.status == "conflict"
    assert "join_composite_key_collapsed" in report.evaluations[0].codes


def test_wrong_aggregation_function_is_conflict():
    """反例4a：固定聚合规则是 sum，正文声称「平均」。"""
    report = report_of(claim(text="按 branch_no 统计平均贷款余额。", kind="aggregation",
                             support=[support_item("script_rule", "script-edge-13")]),
                       rule_ids=("script-edge-13",))
    assert_not_supported(report)
    assert report.status == "conflict"
    assert "aggregation_function_mismatch" in report.evaluations[0].codes


def test_unattested_as_of_date_is_unknown_not_supported():
    """反例4b：正文声称 2025-06-30 时点，规则/证据里都没有该时点。"""
    report = report_of(claim(text="统计 2025-06-30 时点贷款余额。", kind="as_of_date"))
    assert_not_supported(report)
    assert report.status == "unknown"
    assert "as_of_date_unattested" in report.evaluations[0].codes


def test_legal_ids_with_unrelated_text_is_unknown():
    """反例5：evidence/rule id 都合法，正文与固定事实无任何可核验关联。"""
    report = report_of(claim(text="报送口径按监管要求执行。"))
    assert_not_supported(report)
    assert report.status == "unknown"
    assert "claim_unverifiable_tokens" in report.evaluations[0].codes


def test_evidence_version_mismatch_is_conflict():
    """反例6a：主张声明的证据版本与证据实际版本不一致。"""
    report = report_of(claim(support=[support_item(ref_version="2025-v1")]))
    assert_not_supported(report)
    assert report.status == "conflict"
    assert "evidence_version_mismatch" in report.evaluations[0].codes


def test_pinned_evidence_without_version_is_conflict():
    """反例6b：证据被钉扎版本，但证据自身缺该版本。"""
    ctx = context(evidence=[evidence_unit(version="")])
    report = report_of(claim(), ctx=ctx)
    assert_not_supported(report)
    assert "pinned_version_missing" in report.evaluations[0].codes


def test_missing_evidence_reference_is_conflict():
    """反例7：支持项引用的证据不存在于冻结输入（候选自己引用的 evidence id 仍合法）。"""
    report = report_of(claim(support=[support_item(ref_id="999")]))
    assert_not_supported(report)
    assert report.status == "conflict"
    assert "evidence_reference_out_of_scope" in report.evaluations[0].codes


def test_missing_rule_reference_is_conflict():
    """反例7b：支持项引用的脚本规则不存在。"""
    report = report_of(claim(support=[support_item("script_rule", "script-edge-999999")]))
    assert_not_supported(report)
    assert "rule_reference_out_of_scope" in report.evaluations[0].codes


def test_physical_field_outside_scope_is_conflict():
    """反例7c：支持项引用的物理字段不在冻结输入。"""
    report = report_of(claim(kind="null_handling",
                             support=[support_item("physical_field", "source:2:999")]))
    assert_not_supported(report)
    assert "physical_reference_out_of_scope" in report.evaluations[0].codes


def test_unverifiable_assertion_kind_is_unknown():
    """反例8a：claim 声明 other，校验器没有可核验口径。"""
    report = report_of(claim(text="报送口径需结合最新监管要求。", kind="other"))
    assert_not_supported(report)
    assert report.status == "unknown"
    assert "assertion_not_verifiable" in report.evaluations[0].codes


def test_evaluator_exception_degrades_to_unknown(monkeypatch):
    """反例8b：校验器自身不可用（内部异常），必须 unknown 且不能被静默放行。

    分层口径：校验器不可用属于"无法判定"，不阻断生成，但必须进入 advisory 违规
    并写成候选缺口，由送审前的人工确认挡住——否则模型如实说"没有证据"
    反而比虚构证据更难通过。
    """

    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated evaluator failure")

    monkeypatch.setattr(claim_support, "_evaluate", boom)
    ctx = context()
    payload = candidate(claim())
    report = claim_support.evaluate_claim_support(ctx, payload)
    assert report.status == "unknown"
    assert "evaluator_unavailable" in report.violations[0]
    assert report.advisory_violations and not report.blocking_violations
    # 生成期不阻断（合规校验只看确定性冲突）
    assert check_candidate_compliance(ctx, payload) == []


def test_malformed_claims_never_certify():
    """反例8c：claims 结构损坏（不是数组 / 缺字段）时不得被当成已校验。"""
    ctx = context()
    broken = claim_support.evaluate_claim_support(
        ctx, {"final_content": "仅报送正常贷款余额。", "claims": "C1"})
    assert broken.status == "unknown" and broken.violations
    empty = claim_support.evaluate_claim_support(
        ctx, {"final_content": "仅报送正常贷款余额。", "claims": [{"claim_id": "C1"}]})
    assert empty.status == "unknown" and empty.violations
    # 结构损坏是"无法判定"，不阻断生成；阻断发生在送审（候选缺口）与人工确认
    assert check_candidate_compliance(ctx, {"final_content": "仅报送正常贷款余额。",
                                            "claims": [{"claim_id": "C1"}]}) == []
    assert empty.advisory_violations and not empty.blocking_violations


def test_claim_section_mismatch_is_conflict():
    """章节不一致：business 候选里登记了 lineage 主张。"""
    report = report_of(claim(section="lineage"))
    assert_not_supported(report)
    assert "claim_section_mismatch" in report.evaluations[0].codes


# --------------------------------------------------------------------------- #
# 向后兼容：旧候选无 claims 仍可读，并标记「未执行主张校验」
# --------------------------------------------------------------------------- #
def test_legacy_candidate_without_claims_is_readable_and_not_evaluated():
    ctx = context()
    legacy = RequirementCandidate.model_validate(
        {"final_content": "报送正常贷款余额", "evidence_unit_ids": [4]})
    assert legacy.claims == []
    assert legacy.claim_support_version == CLAIM_SUPPORT_VERSION
    payload = legacy.model_dump()
    report = claim_support.evaluate_claim_support(ctx, payload)
    assert report.status == "not_evaluated"
    assert report.evaluated is False
    assert report.violations == []
    assert check_candidate_compliance(ctx, payload) == []
    # 旧候选不做语义追改：即使正文口径存疑，缺失 claims 也不新增违规。
    unclaimed = RequirementCandidate.model_validate(
        {"final_content": "报送所有逾期贷款余额，无需筛选正常状态。", "evidence_unit_ids": [4]})
    assert check_candidate_compliance(ctx, unclaimed.model_dump()) == []


def test_claim_support_schema_keeps_extra_forbid_and_defaults():
    with pytest.raises(ValidationError):
        ClaimSupport(source="evidence", ref_id="4", injected="x")
    assert ClaimSupport(source="evidence", ref_id="4").status == "unknown"
    assert CandidateClaim(claim_id="C1", section="business", text="正文", assertion_kind="filter").support == []
    with pytest.raises(ValidationError):
        RequirementCandidate(final_content="正文", unexpected_claim="x")
    with pytest.raises(ValidationError):
        RequirementCandidate(final_content="正文", claims=[{"claim_id": "C1", "section": "business",
                                                            "text": "t", "assertion_kind": "nope"}])


# --------------------------------------------------------------------------- #
# 三态在报告与 violations 里可见
# --------------------------------------------------------------------------- #
def test_supported_claim_is_supported():
    report = report_of(claim())
    assert report.status == "supported"
    assert report.supported_count == 1
    assert report.violations == []
    assert check_candidate_compliance(context(), candidate(claim())) == []


def test_report_exposes_supported_conflict_and_unknown_states():
    report = report_of(
        claim("C1", text="仅报送正常贷款余额。"),
        claim("C2", text="报送所有逾期贷款余额，无需筛选正常状态。"),
        claim("C3", text="报送口径需结合最新监管要求。", kind="other"),
    )
    assert report.status == "conflict"
    assert (report.supported_count, report.conflict_count, report.unknown_count) == (1, 1, 1)
    assert {item.status for item in report.evaluations} == {"supported", "conflict", "unknown"}
    assert any("冲突" in item for item in report.violations)
    assert any("须人工确认" in item for item in report.violations)
    assert {"C2", "C3"} <= {item.split("主张 ")[1].split("：")[0] for item in report.manual_review}
    violations = check_candidate_compliance(context(), candidate(
        claim("C1", text="仅报送正常贷款余额。"),
        claim("C2", text="报送所有逾期贷款余额，无需筛选正常状态。")))
    assert any("冲突" in item for item in violations)


def test_unknown_claim_support_version_is_refused():
    report = report_of(claim(), claim_support_version="claim-support-v0")
    assert report.status == "unknown"
    assert report.evaluations == []
    assert any("evaluator_version_mismatch" in item for item in report.violations)


# --------------------------------------------------------------------------- #
# 两条生成路径都必须经过公共检查
# --------------------------------------------------------------------------- #
def _runtime():
    return SimpleNamespace(system_prompt="需求字段候选", config={"requirement_max_input_bytes": 64000},
                           provider_type="fake", model_name="fake-model", version="v1")


def _patch_generation(monkeypatch, output):
    monkeypatch.setattr(worker, "generate_if_bound", lambda *a, **k: None)
    monkeypatch.setattr(worker, "get_prompt_runtime", lambda *a, **k: _runtime())
    monkeypatch.setattr(worker, "prepare_model_input",
                        lambda runtime, prompt, levels, **kwargs: prompt)

    async def fake_chat(*args, **kwargs):
        return deepcopy(output), {"execution_kind": "test", "execution_mode": "test"}

    monkeypatch.setattr(worker, "execute_runtime_chat", fake_chat)


def test_generation_path_blocks_conflicting_claim(monkeypatch):
    bad = {"final_content": "报送所有逾期贷款余额，无需筛选正常状态。", "evidence_unit_ids": [4],
           "claims": [claim(text="报送所有逾期贷款余额，无需筛选正常状态。")]}
    _patch_generation(monkeypatch, bad)
    row = SimpleNamespace(id=7, project_id=1, input_json=frozen_input())
    item = SimpleNamespace(id=1, field_id=3, section="business")
    with pytest.raises(HTTPException) as caught:
        worker.generate_candidate(None, row, item, SimpleNamespace(id=1, confidentiality_level="internal"))
    assert caught.value.status_code == 422
    assert "冲突" in str(caught.value.detail)


def test_generation_path_emits_claim_support_report(monkeypatch):
    good = {"final_content": "仅报送正常贷款余额。", "evidence_unit_ids": [4],
            "claims": [claim()]}
    _patch_generation(monkeypatch, good)
    row = SimpleNamespace(id=7, project_id=1, input_json=frozen_input())
    item = SimpleNamespace(id=1, field_id=3, section="business")
    sealed = worker.generate_candidate(None, row, item,
                                       SimpleNamespace(id=1, confidentiality_level="internal"))
    assert sealed["claim_support"]["status"] == "supported"
    assert sealed["claim_support"]["version"] == CLAIM_SUPPORT_VERSION


def test_skill_bound_path_cannot_bypass_claim_check(monkeypatch):
    conflicting = candidate(claim(text="报送所有逾期贷款余额，无需筛选正常状态。"))
    monkeypatch.setattr(worker, "generate_if_bound", lambda *a, **k: deepcopy(conflicting))
    row = SimpleNamespace(id=7, project_id=1, input_json=frozen_input())
    item = SimpleNamespace(id=1, field_id=3, section="business")
    with pytest.raises(HTTPException) as caught:
        worker.generate_candidate(None, row, item, SimpleNamespace(id=1, confidentiality_level="internal"))
    assert caught.value.status_code == 422
    assert "冲突" in str(caught.value.detail)


def test_seal_candidate_marks_legacy_candidate_as_not_evaluated():
    ctx = context()
    legacy = {"final_content": "报送正常贷款余额", "evidence_unit_ids": [4], "gaps": []}
    sealed = worker.seal_candidate(ctx, legacy)
    assert sealed["claim_support"]["status"] == "not_evaluated"
    assert any("未执行语义支持校验" in gap for gap in sealed["gaps"])


def test_skill_envelope_validation_rejects_conflicting_claim():
    """Skill 发布/运行复用同一 check_candidate_compliance，故冲突主张同样被拒。"""
    facts = frozen_input()
    row = SimpleNamespace(id=7, project_id=1, input_json=facts, input_hash=stable_hash(facts))
    item = SimpleNamespace(input_id=7, field_id=3, section="business")
    envelope = build_requirement_envelope(PROJECT, row, item)
    good = RequirementCandidate(final_content="仅报送正常贷款余额", evidence_unit_ids=[4],
                                claims=[CandidateClaim(claim_id="C1", section="business",
                                                       text="仅报送正常贷款余额。",
                                                       assertion_kind="filter",
                                                       support=[ClaimSupport.model_validate(support_item())])])
    validate_requirement_output(good, envelope)
    bad = good.model_copy(deep=True)
    bad.claims[0].text = "报送所有逾期贷款余额，无需筛选正常状态。"
    with pytest.raises(ValueError, match="候选正文主张与固定事实冲突"):
        validate_requirement_output(bad, envelope)

def test_seal_candidate_turns_unverifiable_claims_into_gaps_not_blockers():
    """真实观测（2026-10-24）：模型如实登记"没有证据"的主张，若在生成期整条阻断，
    等于逼它虚构证据。分层口径：只有确定性冲突阻断，无法判定写成候选缺口。"""

    from app.services.requirement_generation_worker import seal_candidate

    ctx = context()
    # 统计时点没有可核验的证据原文 → unknown（无法判定），不是冲突
    payload = candidate(claim(text="按 2025-06-30 统计时点取数。", kind="as_of_date"))
    sealed = seal_candidate(ctx, payload)
    support = sealed["claim_support"]
    assert support["blocking_violations"] == []
    assert support["advisory_violations"]
    assert any("无法确定性校验" in gap for gap in sealed["gaps"])


def test_mapping_sources_are_citable_as_physical_support():
    """需求字段已固定的集市映射可用于核对溯源引用，未映射的仍被拒（真实事故：T_8_1 重跑被误判越界）。"""
    mapping_sources = [{"kind": "mart", "table_id": 39, "field_id": 385, "table_code": "HYF_LN_DUEBILL_INFO",
                        "table_name": "信贷借据信息表", "field_code": "LOAN_BAL", "field_name": "借款余额",
                        "field_type": None, "table_version": "v1", "field_version": "v1",
                        "source": "field_mapping"}]
    ctx = context(mapping_sources=mapping_sources)
    report = report_of(
        claim(text="借款余额取自信贷借据信息表的借款余额字段。", kind="other",
              support=[support_item(source="physical_field", ref_id="385", status="supported")]),
        ctx=ctx,
    )
    assert not any("不在固定输入范围内" in item for item in report.violations), report.violations

    out_of_scope = report_of(
        claim(claim_id="C2", text="借款余额取自另一张未映射的集市表。", kind="other",
              support=[support_item(source="physical_field", ref_id="999", status="supported")]),
        ctx=ctx,
    )
    assert any("不在固定输入范围内" in item for item in out_of_scope.violations)
