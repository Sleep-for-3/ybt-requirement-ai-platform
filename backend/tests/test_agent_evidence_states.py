"""Answer/evidence binding regression (nightly task, package B).

Pins the five adversarial cases from the task book and keeps the four evidence
states apart: retrieved -> selected into context -> cited by the answer ->
(when the judge ran) supporting the claim. Also pins formal policy vs
institution question vs reference material, so a suggestion cannot be promoted
to a formal conclusion.
"""

from app.services.agent.tools.builtin import (
    _citation_summary,
    _classification_result,
    _evidence_source_kind,
)
from app.services.rag.grounded_answer_service import (
    _evidence_conflicts,
    _invented_qualified_identifiers,
)


def _citation(**overrides):
    base = {
        "knowledge_unit_id": 1,
        "citation_id": "knowledge-unit-1",
        "label": "一表通制度问答",
        "quoted_content": "合作方式码值：01 营销获客；02 联合贷款。",
        "source_type": "regulatory_qa",
        "source_category": "regulatory_formal",
        "document_id": 6,
        "document_version_id": 2,
        "source_sheet_name": "转1104问答",
        "source_cell_range": "A237:AF237",
        "locator": {"sheet_name": "转1104问答", "cell_range": "A237:AF237"},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------- case 1
def test_case1_classification_missing_when_only_related_material():
    """问「合作机构类型」，只有合作方式/报送义务材料：不得冒充分类口径。"""

    citation = _citation(quoted_content="合作方式按 01-10 报送，具体口径见附件。")
    result = _classification_result("合作机构类型有哪些？", [citation])
    assert result == {"status": "missing", "items": [], "coverage": "missing"}


def test_case1_classification_missing_when_only_obligation_material():
    citation = _citation(quoted_content="合作机构应在协议签订后 5 个工作日内报送合作信息。")
    result = _classification_result("合作机构类型有哪些？", [citation])
    assert result["status"] == "missing"
    assert result["items"] == []


# ---------------------------------------------------------------- case 2
def test_case2_partial_coverage_when_source_list_is_truncated():
    """同一份分类资料只给出一段且以「等/详见」收尾：列已知条目并标覆盖不全。"""

    citation = _citation(quoted_content=(
        "合作方式码值：\n01 营销获客\n02 联合贷款\n等，详见附件。"
    ))
    result = _classification_result("合作方式有哪些码值？", [citation])
    assert result["status"] == "listed"
    assert result["coverage"] == "partial"
    assert [item["code"] for item in result["items"]] == ["01", "02"]


def test_case2_complete_coverage_when_list_is_not_truncated():
    citation = _citation(quoted_content="合作方式码值：\n01 营销获客\n02 联合贷款\n")
    result = _classification_result("合作方式有哪些码值？", [citation])
    assert result["status"] == "listed"
    assert result["coverage"] == "complete"


# ---------------------------------------------------------------- case 3
def test_case3_conflicting_code_sets_keep_both_sides():
    """两个有效来源给同一数据项不同码值：保留双方，不擅自择一。"""

    base = "表号（主）：6.25；数据项编码：F250007；数据项名称：合作方式；具体问题描述："

    def row(unit_id, content, rank=5):
        return {"knowledge_unit_id": unit_id, "authority_rank": rank, "content": content,
                "content_hash": f"hash-{unit_id}"}

    old = row(1, base + "值域为（00,01,02,03,04,05,06,07,08）")
    new = row(2, base + "反馈意见：建议合作方式的码值修改为：01 营销获客。02 联合贷款。"
                       "03 支付结算。09 部分风险评价。")
    conflicts = _evidence_conflicts([old, new])
    assert conflicts
    assert set(conflicts[0]["citation_ids"]) == {"knowledge-unit-1", "knowledge-unit-2"}


# ---------------------------------------------------------------- case 4
def test_case4_invented_qualified_identifier_is_flagged():
    """模型给出证据里没有的「表.字段」限定标识：必须进入未支持主张，不能当依据。"""

    answer = "应在 LOAN_DTL.BALANCE_AMT 字段填报。"
    evidence = "合作方式码值：01 营销获客。"
    invented = _invented_qualified_identifiers(answer, evidence)
    assert "LOAN_DTL.BALANCE_AMT" in invented


def test_case4_supported_qualified_identifier_is_not_flagged():
    answer = "应在 LOAN_DTL.BALANCE_AMT 字段填报。"
    evidence = "字段 LOAN_DTL.BALANCE_AMT 对应贷款余额。"
    assert _invented_qualified_identifiers(answer, evidence) == []


# ---------------------------------------------------------------- case 5
def test_case5_citation_keeps_version_and_locator_identity():
    """旧任务引用必须能定位到当时版本与单元格，而不是当前版本。"""

    summary = _citation_summary(_citation())
    assert summary["document_id"] == 6
    assert summary["document_version_id"] == 2
    assert summary["knowledge_unit_id"] == 1
    assert summary["locator"]["sheet_name"] == "转1104问答"
    assert summary["locator"]["cell_range"] == "A237:AF237"


# ------------------------------------------------------- four-state identity
def test_usage_distinguishes_cited_from_context_only():
    context_only = _citation(usage="context_only")
    cited = _citation(usage="cited")
    assert _citation_summary(context_only)["usage"] == "context_only"
    assert _citation_summary(cited)["usage"] == "cited"


def test_source_kind_separates_formal_question_and_material():
    assert _evidence_source_kind({"source_type": "regulatory_policy"}) == "formal_feedback"
    assert _evidence_source_kind({"source_category": "regulatory_formal"}) == "formal_feedback"
    assert _evidence_source_kind({"source_type": "regulatory_qa"}) == "institution_question"
    assert _evidence_source_kind({"source_type": "business_research"}) == "reference_material"
    assert _evidence_source_kind({"source_type": "manual_note"}) == "reference_material"


def test_citation_summary_carries_source_kind():
    question = _citation_summary(_citation())
    assert question["source_kind"] == "institution_question"
    formal = _citation_summary(_citation(source_type="regulatory_policy"))
    assert formal["source_kind"] == "formal_feedback"
