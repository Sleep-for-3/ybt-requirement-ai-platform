"""The clause locator must accept the clause number a unit states itself.

A spreadsheet row or a bare file name is a *container* locator: it says where the
text was found, not which clause was cited.  A unit whose own heading or text opens
with ``第三条 …`` (or a dotted section number) does carry a citable clause number,
and rejecting it kept real internal-policy clauses out of every agent run.
"""

from __future__ import annotations

import pytest

from app.schemas.ai_skill import SkillScope
from app.services.agent.tools.evidence import (
    clause_locator,
    inscribed_clause_locator,
    policy_clause_evidence,
)

SCOPE = SkillScope(scope_type="project", institution_id=4, project_id=12)


def _hit(**overrides):
    hit = {
        "knowledge_unit_id": 6901,
        "document_version_id": 34,
        "chunk_id": 6901,
        "source_category": "internal_policy",
        "title": "第二章 口径管理",
        "content": "第五条 客户年龄、逾期天数等派生指标须由统一加工层产出，禁止报送系统自行计算。",
        "source_heading": "第二章 口径管理",
        "source_cell_range": None,
        "source_file_name": "银行监管数据报送管理办法-合成.docx",
        "content_hash": "abc",
    }
    hit.update(overrides)
    return hit


@pytest.mark.parametrize(
    ("heading", "content", "expected"),
    [
        ("第二章 口径管理", "第五条 派生指标须统一加工。", "第五条"),
        ("第二条 监管数据报送实行统一口径。", None, "第二条"),
        ("段落 2", "6.1 客户年龄按实足年龄计算。", "6.1"),
        ("段落 3", "第十三条 报送口径以监管答疑为准。", "第十三条"),
        (None, "客户年龄由出生日期计算。", None),
        ("A2:J2", "回复：年龄由出生日期与统计期末日相减得到。", None),
    ],
)
def test_inscribed_clause_locator(heading, content, expected):
    hit = _hit(source_heading=heading, title=heading, content=content)
    assert inscribed_clause_locator(hit) == expected


def test_cell_range_locator_alone_is_still_not_citable():
    hit = _hit(
        knowledge_unit_id=6881,
        source_category="regulatory_qa",
        title="客户年龄",
        content="回复：年龄由出生日期与统计期末日相减得到。",
        source_heading=None,
        source_cell_range="A2:J2",
        source_file_name="监管答疑-一表通口径-2026Q3.xlsx",
    )
    assert clause_locator(hit) == "A2:J2"
    evidence, gap = policy_clause_evidence(hit, scope=SCOPE, confidentiality="internal")
    assert evidence is None
    assert gap is not None and gap.code == "clause_locator_missing"


def test_internal_policy_clause_becomes_governed_evidence():
    evidence, gap = policy_clause_evidence(_hit(), scope=SCOPE, confidentiality="internal")
    assert gap is None
    assert evidence is not None
    assert evidence.kind == "policy_clause"
    assert evidence.source.source_type == "knowledge_clause"
    assert evidence.source.locator == "第五条"
    assert "第五条" in evidence.value["excerpt"]


def test_non_normative_source_is_never_policy_even_with_a_clause_number():
    hit = _hit(source_category="technical_evidence", content="第五条 技术实现按此执行。")
    evidence, gap = policy_clause_evidence(hit, scope=SCOPE, confidentiality="internal")
    assert evidence is None and gap is None
