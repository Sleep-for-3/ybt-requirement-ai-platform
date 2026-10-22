"""VNext2 P0-B: 引用可信性（A 版本一致性 / B 冲突证据 / C 复合主张覆盖）。

三个真实缺陷的回归：

* **C08** 引用只覆盖复合结论的部分条件时，不得因为“某条引用 supported”就让整段结论
  ``verified``——复合结论必须拆成原子主张，覆盖率按主张算；
* **C09** 同一条主张的两份有效来源互相矛盾时，不得“排序靠前者胜出”静默合并，必须把冲突
  记录在案并把涉及引用降级为 ``unknown``；
* **C10** 需求快照已固定来源版本时，引用另一版本必须由**确定性规则**判 ``unsupported``，
  不能指望 LLM 从两条版本号里猜出哪个才是交付依据。

模型网关全部替换为本地假实现（``get_runtime_llm_service``），不产生任何真实调用。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.settings import get_settings
from app.services.llm.base import ModelCallMetadata
from app.services.rag import citation_validator, citation_trust
from app.services.rag.citation_support import parse_judge_conflicts, parse_judge_verdicts, split_claims_all
from app.services.rag.citation_validator import check_citation_support


class _FixedJudge:
    """固定裁判回复；记录调用次数，便于断言“没有额外模型调用”。"""

    last_call = ModelCallMetadata(provider="mock", model="judge-model")

    def __init__(self, payload):
        self.payload = payload
        self.calls: list[str] = []

    async def chat_json(self, system_prompt, user_prompt):
        self.calls.append(user_prompt)
        return self.payload

    async def embed_texts(self, texts):
        return [[0.0] for _ in texts]


def _install(monkeypatch, judge):
    monkeypatch.setattr(
        "app.services.llm.prompt_runtime.get_runtime_llm_service",
        lambda *_args, **_kwargs: judge,
    )
    return judge


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        "sqlite:///" + (tmp_path / "trust.db").as_posix(),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def _enable_judge(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "citation_support_check", "judge", raising=False)
    yield


def _citation(citation_id: str, *, unit_id: int, quoted: str, version: str | None = None,
              source_name: str | None = None) -> dict:
    citation = {
        "citation_id": citation_id,
        "knowledge_unit_id": unit_id,
        "label": f"知识单元 {unit_id}",
        "quoted_content": quoted,
    }
    if version is not None:
        citation["version"] = version
    if source_name is not None:
        citation["source_name"] = source_name
    return citation


# ------------------------------------------------------------------ 确定性规则：单元行为


def test_version_normalisation_handles_v_prefix_years_and_labels():
    assert citation_trust.normalize_version("v2") == ("2",)
    assert citation_trust.normalize_version("V2.1") == ("2", "1")
    assert citation_trust.normalize_version("2024 旧版") == ("2024",)
    assert citation_trust.normalize_version("第 3 版") == ("3",)
    assert citation_trust.normalize_version("") is None
    assert citation_trust.normalize_version("现行有效") is None


def test_base_source_title_strips_version_annotations():
    assert citation_trust.base_source_title("一表通管理办法（2024年版）") == "一表通管理办法"
    assert citation_trust.base_source_title("一表通管理办法 v2") == "一表通管理办法 v2"
    assert citation_trust.base_source_title("") == ""


def test_version_violation_is_detected_only_against_a_pinned_source():
    citations = [
        _citation("c1", unit_id=1, quoted="表内贷款余额按月末统计", version="v2"),
        _citation("c2", unit_id=2, quoted="表外担保按月末统计", version="v1"),
    ]
    violations = citation_trust.version_violations(citations, {"一表通管理办法": "v1"})
    # 没有 source_name 时无法与固定版本条目对应，不能凭空判违规。
    assert violations == []

    citations[0]["source_name"] = "一表通管理办法（v2）"
    citations[1]["source_name"] = "一表通管理办法（v1）"
    violations = citation_trust.version_violations(citations, {"一表通管理办法": "v1"})
    assert [item["citation_id"] for item in violations] == ["c1"]
    assert violations[0]["reason"] == "version_mismatch"
    assert violations[0]["pinned_version"] == "1"
    assert violations[0]["cited_version"] == "2"


def test_conflicts_need_two_known_citation_ids():
    conflicts = citation_trust.normalize_conflicts(
        {"conflicts": [
            {"claim_id": "claim-1", "citation_ids": ["c1"], "conflict_type": "版本"},
            {"claim_id": "claim-1", "citation_ids": ["c1", "ghost"], "conflict_type": "版本"},
            {"claim_id": "claim-1", "citation_ids": ["c1", "c2"], "conflict_type": "版本差异"},
        ]},
        {"c1", "c2"},
    )
    assert len(conflicts) == 1
    # 只有一个合法 id 的“冲突”无法确认对立面是谁，宁可丢弃也不凭空降级一条好引用。
    assert conflicts[0]["citation_ids"] == ["c1", "c2"]
    assert conflicts[0]["conflict_type"] == "version"


def test_downgrading_conflicting_verdicts_keeps_evidence_but_not_confidence():
    verdicts = [
        {"citation_id": "c1", "verdict": "supported", "reason": "一致"},
        {"citation_id": "c2", "verdict": "unsupported", "reason": "口径不同"},
        {"citation_id": "c3", "verdict": "supported", "reason": "无关引用"},
    ]
    conflicts = [{"claim_id": "claim-1", "citation_ids": ["c1", "c2"],
                  "conflict_type": "contradiction", "reason": "统计时点不同"}]
    downgraded = citation_trust.downgrade_conflicting_verdicts(verdicts, conflicts)
    by_id = {item["citation_id"]: item for item in downgraded}
    assert by_id["c1"]["verdict"] == "unknown"
    assert by_id["c1"]["reason"].startswith("conflicting_evidence:")
    assert by_id["c2"]["verdict"] == "unknown"
    assert by_id["c3"]["verdict"] == "supported"


def test_judge_payload_with_two_lists_is_split_by_dimension():
    payload = {
        "verdicts": [{"citation_id": "c1", "verdict": "supported", "supported_claim_ids": ["claim-1"]}],
        "claims": [{"claim_id": "claim-2", "verdict": "unknown", "reason": "证据不足"}],
        "conflicts": [{"claim_id": "claim-1", "citation_ids": ["c1", "c2"],
                       "conflict_type": "scope"}],
    }
    verdicts = parse_judge_verdicts(payload)
    dimensions = sorted(item["dimension"] for item in verdicts)
    assert dimensions == ["citation", "claim"]
    assert [item["citation_ids"] for item in parse_judge_conflicts(payload)] == [["c1", "c2"]]


def test_compound_regulatory_conclusion_is_split_into_atomic_claims():
    answer = "报送范围包括：表内贷款、表外担保、贴现。报送时点为月末。"
    claims = split_claims_all(answer)
    assert len(claims) == 4
    assert claims[0].endswith("表内贷款。")
    assert claims[-1] == "报送时点为月末。"
    # 没有枚举的普通句子保持原样，不被拆碎。
    assert split_claims_all("余额以合同为准。") == ["余额以合同为准。"]


# ------------------------------------------------------------------ 集成：C08 / C09 / C10


def test_c08_partial_condition_coverage_cannot_be_verified(db, monkeypatch):
    """复合结论只被引用覆盖一部分时，只能部分支持。"""
    judge = _install(monkeypatch, _FixedJudge({
        "verdicts": [
            {"citation_id": "c1", "verdict": "supported", "reason": "覆盖表内贷款"},
            {"citation_id": "c2", "verdict": "unknown", "reason": "仅提及贴现"},
        ],
        "claims": [
            {"claim_id": "claim-1", "verdict": "supported", "reason": "与引文一致"},
            {"claim_id": "claim-2", "verdict": "unknown", "reason": "引文未涉及"},
            {"claim_id": "claim-3", "verdict": "unknown", "reason": "引文未涉及"},
        ],
    }))
    citations = [
        _citation("c1", unit_id=1, quoted="表内贷款余额含贴现。"),
        _citation("c2", unit_id=2, quoted="本段只讨论贴现。"),
    ]
    support = asyncio.run(check_citation_support(
        db, citations,
        answer="报送范围包括：表内贷款、表外担保、贴现。",
        project_id=1,
    ))
    assert support["claims_total"] == 3
    assert support["claim_judgement"] == "claim_level"
    assert support["claims_judged"] == 3
    assert support["claims_supported"] == 1
    assert support["claims_unknown"] == 2
    # 关键：一条引用 supported + 三条主张里只支持一条 → 绝不 verified。
    assert support["verification"] != "verified"
    assert support["verification"] == "partially_supported"
    assert judge.calls


def test_c08_citation_only_judge_still_cannot_verify_the_whole_answer(db, monkeypatch):
    """即使裁判只给引用级判定，整体结论也不得被判 verified。"""
    _install(monkeypatch, _FixedJudge({
        "verdicts": [
            {"citation_id": "c1", "verdict": "supported", "reason": "一致"},
            {"citation_id": "c2", "verdict": "unknown", "reason": "证据不足"},
        ],
    }))
    citations = [
        _citation("c1", unit_id=1, quoted="表内贷款余额按月末统计。"),
        _citation("c2", unit_id=2, quoted="培训材料提及类似口径。"),
    ]
    support = asyncio.run(check_citation_support(
        db, citations, answer="表内贷款余额按月末统计。", project_id=1,
    ))
    assert support["claim_judgement"] == "citation_level"
    assert support["claims_judged"] == 0
    assert support["verification"] != "verified"


def test_c09_conflicting_sources_are_exposed_not_merged(db, monkeypatch):
    """同一主张两份互相矛盾的有效来源：都保留，但都不足以确认口径。"""
    _install(monkeypatch, _FixedJudge({
        "verdicts": [
            {"citation_id": "c1", "verdict": "supported", "reason": "制度A支持月末"},
            {"citation_id": "c2", "verdict": "unsupported", "reason": "制度B要求季末"},
        ],
        "claims": [{"claim_id": "claim-1", "verdict": "supported", "reason": "按制度A"}],
        "conflicts": [{
            "claim_id": "claim-1",
            "citation_ids": ["c1", "c2"],
            "conflict_type": "scope",
            "reason": "统计时点规定不同",
        }],
    }))
    citations = [
        _citation("c1", unit_id=1, quoted="统计时点为月末。", version="v1",
                  source_name="一表通管理办法（v1）"),
        _citation("c2", unit_id=2, quoted="统计时点为季末。", version="v2",
                  source_name="一表通管理办法（v2）"),
    ]
    support = asyncio.run(check_citation_support(
        db, citations,
        answer="统计时点为月末。",
        project_id=1,
        pinned_versions={"一表通管理办法": "v1"},
    ))
    assert support["conflict_count"] == 1
    assert support["conflicts"][0]["conflict_type"] == "scope"
    # 冲突证据必须两份都在，且都降级为 unknown（不能“排序靠前者胜出”）。
    by_id = {item["citation_id"]: item for item in support["verdicts"]}
    assert set(by_id) == {"c1", "c2"}
    assert by_id["c1"]["verdict"] == "unknown"
    assert by_id["c1"]["reason"].startswith("conflicting_evidence:")
    # c2 的版本与快照固定版本不一致，确定性规则直接判 unsupported。
    assert by_id["c2"]["verdict"] in {"unknown", "unsupported"}
    assert any(item.startswith("version_mismatch:") for item in support["trust_blockers"])
    assert support["verification"] != "verified"


def test_c04_version_conflict_is_adjudicated_by_the_pinned_version(db, monkeypatch):
    """版本冲突若能被快照固定版本裁决，就只淘汰落后版本，不得把新版正确证据一起降级。"""
    _install(monkeypatch, _FixedJudge({
        "verdicts": [
            {"citation_id": "c1", "verdict": "supported", "reason": "旧版口径"},
            {"citation_id": "c2", "verdict": "supported", "reason": "新版口径"},
        ],
        "claims": [{"claim_id": "claim-1", "verdict": "supported", "reason": "按现行制度"}],
        "conflicts": [{
            "claim_id": "claim-1",
            "citation_ids": ["c1", "c2"],
            "conflict_type": "version",
            "reason": "新旧制度口径不同",
        }],
    }))
    citations = [
        _citation("c1", unit_id=1, quoted="统计时点为月末。", version="2023",
                  source_name="一表通管理办法（2023）"),
        _citation("c2", unit_id=2, quoted="统计时点为月末。", version="2026",
                  source_name="一表通管理办法（2026）"),
    ]
    support = asyncio.run(check_citation_support(
        db, citations,
        answer="统计时点为月末。",
        project_id=1,
        pinned_versions={"一表通管理办法": "2026"},
    ))
    by_id = {item["citation_id"]: item for item in support["verdicts"]}
    assert by_id["c1"]["verdict"] == "unsupported"  # 落后版本由确定性规则淘汰
    assert by_id["c2"]["verdict"] == "supported"    # 固定版本那一份仍然可用
    assert [item["citation_ids"] for item in support["resolved_conflicts"]] == [["c1", "c2"]]
    assert support["resolved_conflicts"][0]["resolution"] == "pinned_version"
    assert not any(
        str(item).startswith("conflicting_evidence:") for item in support["trust_blockers"]
    )


def test_version_conflict_without_a_pinned_basis_stays_unresolved(db, monkeypatch):
    """没有固定版本可依据时，版本冲突仍然是“无法确认”，两份证据都要降级。"""
    _install(monkeypatch, _FixedJudge({
        "verdicts": [
            {"citation_id": "c1", "verdict": "supported", "reason": "旧版"},
            {"citation_id": "c2", "verdict": "supported", "reason": "新版"},
        ],
        "claims": [{"claim_id": "claim-1", "verdict": "supported", "reason": "口径一致"}],
        "conflicts": [{
            "claim_id": "claim-1",
            "citation_ids": ["c1", "c2"],
            "conflict_type": "version",
            "reason": "版本不同",
        }],
    }))
    citations = [
        _citation("c1", unit_id=1, quoted="统计时点为月末。", version="2023",
                  source_name="一表通管理办法（2023）"),
        _citation("c2", unit_id=2, quoted="统计时点为月末。", version="2026",
                  source_name="一表通管理办法（2026）"),
    ]
    support = asyncio.run(check_citation_support(
        db, citations, answer="统计时点为月末。", project_id=1,
    ))
    by_id = {item["citation_id"]: item for item in support["verdicts"]}
    assert {by_id["c1"]["verdict"], by_id["c2"]["verdict"]} == {"unknown"}
    assert support["resolved_conflicts"] == []
    assert any(
        str(item).startswith("conflicting_evidence:") for item in support["trust_blockers"]
    )


def test_c10_pinned_version_mismatch_is_deterministic_not_model_guessed(db, monkeypatch):
    """模型说 supported 也没用：引用版本与快照固定版本不一致时由程序判 unsupported。"""
    judge = _install(monkeypatch, _FixedJudge({
        "verdicts": [{"citation_id": "c1", "verdict": "supported", "reason": "内容看起来一致"}],
        "claims": [{"claim_id": "claim-1", "verdict": "supported", "reason": "内容一致"}],
    }))
    citations = [_citation("c1", unit_id=7, quoted="表内贷款按月末统计。", version="v2",
                           source_name="一表通管理办法（v2）")]
    support = asyncio.run(check_citation_support(
        db, citations,
        answer="表内贷款按月末统计。",
        project_id=1,
        pinned_versions={"一表通管理办法": "v1"},
    ))
    assert support["version_violations"]
    assert support["version_violations"][0]["citation_id"] == "c1"
    assert support["verdicts"][0]["verdict"] == "unsupported"
    assert support["verdicts"][0]["deterministic"] is True
    assert support["verdicts"][0]["pinned_version"] == "1"
    assert support["verdicts"][0]["cited_version"] == "2"
    assert support["verification"] == "unsupported"
    assert judge.calls  # 仍然调用模型，但结果被确定性规则覆盖


def test_matching_pinned_version_is_not_flagged(db, monkeypatch):
    _install(monkeypatch, _FixedJudge({
        "verdicts": [{"citation_id": "c1", "verdict": "supported", "reason": "一致"}],
        "claims": [{"claim_id": "claim-1", "verdict": "supported", "reason": "一致"}],
    }))
    citations = [_citation("c1", unit_id=7, quoted="表内贷款按月末统计。", version="v1",
                           source_name="一表通管理办法（v1）")]
    support = asyncio.run(check_citation_support(
        db, citations,
        answer="表内贷款按月末统计。",
        project_id=1,
        pinned_versions={"一表通管理办法": "v1"},
    ))
    assert support["version_violations"] == []
    assert support["verdicts"][0]["verdict"] == "supported"


def test_claim_only_verdicts_are_never_paired_with_citations_by_position(db, monkeypatch):
    """裁判只回主张、不回引用时，引用一律 unknown，不能被按位置“配上”判定。"""
    _install(monkeypatch, _FixedJudge({
        "claims": [{"claim_id": "claim-1", "verdict": "supported", "reason": "一致"}],
    }))
    citations = [
        _citation("c1", unit_id=1, quoted="表内贷款余额按月末统计。"),
        _citation("c2", unit_id=2, quoted="无关材料。"),
    ]
    support = asyncio.run(check_citation_support(
        db, citations, answer="表内贷款余额按月末统计。", project_id=1,
    ))
    for verdict in support["verdicts"]:
        assert verdict["verdict"] == "unknown"
        assert verdict["reason"] == "judge_returned_no_verdict"
    assert support["claim_judgement"] == "claim_level"
    assert support["unkeyed_verdict_count"] == 0


def test_conflicts_with_unknown_citation_ids_do_not_break_the_result(db, monkeypatch):
    _install(monkeypatch, _FixedJudge({
        "verdicts": [{"citation_id": "c1", "verdict": "supported", "reason": "一致"}],
        "conflicts": [{"claim_id": "claim-1", "citation_ids": ["c1", "ghost"],
                       "conflict_type": "contradiction"}],
    }))
    citations = [_citation("c1", unit_id=1, quoted="表内贷款按月末统计。")]
    support = asyncio.run(check_citation_support(
        db, citations, answer="表内贷款按月末统计。", project_id=1,
    ))
    assert support["conflict_count"] == 0
    assert support["verdicts"][0]["verdict"] == "supported"


def test_pinned_versions_are_sent_to_the_judge_once(db, monkeypatch):
    judge = _install(monkeypatch, _FixedJudge({
        "verdicts": [{"citation_id": "c1", "verdict": "supported", "reason": "一致"}],
    }))
    citations = [_citation("c1", unit_id=1, quoted="表内贷款按月末统计。")]
    asyncio.run(check_citation_support(
        db, citations,
        answer="表内贷款按月末统计。",
        project_id=1,
        pinned_versions={"一表通管理办法": "v1"},
    ))
    request = json.loads(judge.calls[0])
    assert request["pinned_versions"] == {"一表通管理办法": "v1"}


def test_switch_off_path_is_unchanged(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "citation_support_check", "off", raising=False)
    support = asyncio.run(check_citation_support(
        db, [_citation("c1", unit_id=1, quoted="表内贷款按月末统计。")],
        answer="表内贷款按月末统计。",
        pinned_versions={"一表通管理办法": "v1"},
    ))
    assert support["enabled"] is False
    assert support["verdicts"] == []
    assert support["trust_blockers"] == []
