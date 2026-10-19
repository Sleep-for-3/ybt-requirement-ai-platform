import pytest

from app.services.agent.tools.evidence import clause_parentage, inscribed_clause_locator, policy_clause_evidence
from app.schemas.ai_skill import SkillScope


BASE_HIT = {
    "knowledge_unit_id": 11,
    "document_version_id": 7,
    "content_hash": "c" * 64,
    "title": "第五条 客户身份资料保存",
    "content": "第五条 客户身份资料应当自业务关系结束当年计起至少保存5年。",
    "source_category": "internal_policy",
    "source_heading": "第二章 客户身份资料保存",
}


def _hit(**overrides):
    hit = dict(BASE_HIT)
    hit.update(overrides)
    return hit


def _scope() -> SkillScope:
    return SkillScope(scope_type="project", institution_id=1, project_id=1)


def test_clause_parentage_reads_chapter_recorded_at_ingestion() -> None:
    locator = {"chapter_no": "第二章", "chapter_heading": "客户身份资料保存", "clause_no": "第五条"}

    assert clause_parentage({"locator": locator}) == ("第二章", "客户身份资料保存", "第五条")


def test_clause_parentage_never_invents_a_chapter_for_a_unit_that_has_none() -> None:
    # A unit whose chapter was never recorded reports no chapter.  Deriving one from a
    # neighbouring heading would attach a citation to a chapter nobody verified.
    assert clause_parentage({"locator": {"clause_no": "第五条"}}) == (None, None, "第五条")
    assert clause_parentage({"locator": "table:1:row:2"}) == (None, None, None)
    assert clause_parentage({}) == (None, None, None)


def test_clause_parentage_falls_back_to_the_recorded_heading_for_the_chapter_title() -> None:
    hit = {"locator": {"chapter_no": "第二章"}, "source_heading": "第二章 客户身份资料保存"}

    assert clause_parentage(hit) == ("第二章", "第二章 客户身份资料保存", None)


@pytest.mark.parametrize("value", ["", "   ", None, 5, ["第二章"]])
def test_clause_parentage_ignores_non_text_locator_values(value) -> None:
    assert clause_parentage({"locator": {"chapter_no": value, "clause_no": value}}) == (None, None, None)


def test_evidence_carries_chapter_parentage_onto_the_cited_clause() -> None:
    hit = _hit(locator={"block_id": "knowledge-unit-11", "chapter_no": "第二章",
                        "chapter_heading": "客户身份资料保存", "clause_no": "第五条"})

    item, gap = policy_clause_evidence(hit, scope=_scope(), confidentiality="internal")

    assert gap is None and item is not None
    assert item.value["clause_no"] == "第五条"
    assert item.value["chapter_no"] == "第二章"
    assert item.value["chapter_heading"] == "客户身份资料保存"
    assert item.source.locator == "第五条"


def test_a_file_name_citation_never_acquires_a_chapter_by_adjacency() -> None:
    # The locator is a container (a bare document name), so the unit is not a citable
    # clause at all -- and must not inherit the chapter metadata sitting beside it.
    hit = _hit(locator={"block_id": "knowledge-unit-11", "chapter_no": "第二章"},
               title="客户身份识别管理办法.docx", content="附件目录")

    item, gap = policy_clause_evidence(hit, scope=_scope(), confidentiality="internal")

    assert item is None and gap is not None
    assert gap.code == "clause_locator_missing"


def test_an_inscribed_clause_number_keeps_its_recorded_chapter() -> None:
    # ``locator`` is a container here, so the clause number is recovered from the text
    # the unit owns; because it *is* a clause, the recorded chapter still applies.
    hit = _hit(locator={"block_id": "knowledge-unit-11", "chapter_no": "第二章",
                        "chapter_heading": "客户身份资料保存", "clause_no": "第五条"})

    assert inscribed_clause_locator(hit) == "第五条"
    item, gap = policy_clause_evidence(hit, scope=_scope(), confidentiality="internal")

    assert gap is None and item is not None
    assert item.source.locator == "第五条"
    assert item.value["chapter_no"] == "第二章"


def test_a_clause_without_recorded_parentage_reports_blank_not_guessed() -> None:
    hit = _hit(locator={"block_id": "knowledge-unit-11", "clause_no": "第五条"})

    item, gap = policy_clause_evidence(hit, scope=_scope(), confidentiality="internal")

    assert gap is None and item is not None
    assert item.value["chapter_no"] is None
    assert item.value["chapter_heading"] is None
    assert item.value["clause_no"] == "第五条"


def _policy_docx() -> bytes:
    """A two-chapter policy document: one heading with headings, one heading without."""
    from io import BytesIO

    from docx import Document

    document = Document()
    document.add_heading("第二章 口径管理", level=1)
    document.add_paragraph("第五条 口径变更应当留存审批记录。")
    document.add_paragraph("第六条 口径口径应当每月核对一次。")
    document.add_heading("第三章 报送管理", level=1)
    document.add_paragraph("第七条 月度报送应当在次月十日前完成。")
    document.add_heading("附录", level=1)
    document.add_paragraph("本附录未编号，不是条款。")
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_ingestion_records_the_chapter_a_clause_belongs_to() -> None:
    # The acceptance criterion: after splitting one policy document, ``第五条`` must
    # resolve to ``第二章 口径管理`` -- read back from what ingestion actually stored,
    # not from the parser's in-memory draft.
    from app.services.knowledge_ingestion.parsers import parse_document

    units, _warnings = parse_document("policy.docx", _policy_docx(), "regulatory_policy")
    by_clause = {unit.metadata.get("clause_no"): unit for unit in units if unit.metadata.get("clause_no")}

    assert set(by_clause) == {"第五条", "第六条", "第七条"}
    assert by_clause["第五条"].metadata["locator"]["chapter_no"] == "第二章"
    assert by_clause["第六条"].metadata["locator"]["chapter_no"] == "第二章"
    assert by_clause["第七条"].metadata["locator"]["chapter_no"] == "第三章"


def test_a_heading_without_a_chapter_number_is_not_a_citable_clause() -> None:
    from app.services.knowledge_ingestion.parsers import parse_document

    units, _warnings = parse_document("policy.docx", _policy_docx(), "regulatory_policy")
    headings = [unit for unit in units if unit.title in {"第二章 口径管理", "第三章 报送管理", "附录"
                                                     } and unit.content in {"第二章 口径管理", "第三章 报送管理", "附录"}]

    # Chapter headings state where clauses live; emitting them as policy_clause units
    # made every heading an uncitable unit that could never be cited.
    assert headings == []


def test_a_clause_outside_a_numbered_chapter_reports_no_chapter() -> None:
    from app.services.knowledge_ingestion.parsers import parse_document

    units, _warnings = parse_document("policy.docx", _policy_docx(), "regulatory_policy")
    unnumbered = [unit for unit in units if unit.content.startswith("本附录未编号")]

    assert len(unnumbered) == 1
    assert unnumbered[0].metadata.get("chapter_no") is None
    assert unnumbered[0].metadata.get("clause_no") is None
