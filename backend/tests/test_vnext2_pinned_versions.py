"""C10: the frozen requirement version decides which regulation version is authoritative.

Product gap this closes (recorded in ``docs/vnext2/p0b-citation-trust.md``): the citation
judge understood ``pinned_versions`` since P0-B, but **no product caller supplied them**.
A requirement frozen against 制度 v1 was therefore judged against whatever the knowledge
base serves today, so a later v2 could silently replace the historical basis, or a correct
v1 citation could look inconsistent.

These tests pin the contract:
* pins are derived only from the frozen ``RequirementRevision`` (with digest integrity);
* a citation to another version is deterministically downgraded, not judged as supported;
* without pins the previous behaviour is unchanged;
* the ask API refuses half-specified pinning and refuses a revision with no pins instead of
  pretending the answer was anchored.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.settings import get_settings
from app.models import (
    Institution,
    Project,
    ProjectMembership,
    Requirement,
    RequirementRevision,
    User,
)
from app.services.auth.dependencies import Principal
from app.services.llm.base import ModelCallMetadata
from app.services.rag.citation_trust import normalize_version
from app.services.rag.citation_validator import VERIFIED, check_citation_support
from app.services.requirement_pins import (
    pinned_versions_for_revision,
    pinned_versions_from_content,
    revision_has_version_pins,
)
from app.services.requirement_scope import content_digest

PINNED_TITLE = "个人贷款统计制度"
PINNED_VERSION = "2026-v1"


class _SupportingJudge:
    """A judge that says every citation is supported; records the request it received."""

    last_call = ModelCallMetadata(provider="mock", model="judge-model")

    def __init__(self):
        self.requests: list[str] = []

    async def chat_json(self, system_prompt, user_prompt):
        self.requests.append(user_prompt)
        return {
            "verdicts": [
                {"citation_id": "knowledge-unit-7", "verdict": "supported", "reason": "条款一致"}
            ],
            "claims": [],
            "conflicts": [],
        }

    async def embed_texts(self, texts):
        return [[0.0] for _ in texts]


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        "sqlite:///" + (tmp_path / "pins.db").as_posix(),
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
def _judge_on(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "citation_support_check", "judge", raising=False)
    monkeypatch.setattr(settings, "ragas_judge_enabled", False, raising=False)


def _install_gateway(monkeypatch, service):
    monkeypatch.setattr(
        "app.services.llm.prompt_runtime.get_runtime_llm_service", lambda *a, **k: service
    )


def _citation(*, version=None, source_name=f"{PINNED_TITLE}（2026-v2）"):
    citation = {
        "citation_id": "knowledge-unit-7",
        "knowledge_unit_id": 7,
        "label": "个人贷款统计制度",
        "source_name": source_name,
        "quoted_content": "个人贷款余额按合同口径统计。",
    }
    if version is not None:
        citation["version"] = version
    return citation


def _seed(db, *, evidence=None):
    institution = Institution(institution_code="PIN-BANK", institution_name="钉扎测试银行")
    db.add(institution)
    db.flush()
    user = User(
        username="pin-owner",
        display_name="钉扎负责人",
        password_hash="x" * 60,
        status="active",
    )
    db.add(user)
    db.flush()
    project = Project(
        name="C10 版本钉扎项目", institution_id=institution.id, project_owner_id=user.id
    )
    db.add(project)
    db.flush()
    db.add(
        ProjectMembership(
            project_id=project.id,
            user_id=user.id,
            project_role="project_manager",
            status="active",
        )
    )
    requirement = Requirement(
        project_id=project.id,
        name="个人贷款余额报送需求",
        version=1,
        content_version=1,
        scope_json={"target_table_id": 1, "field_ids": [1], "scenario_id": None},
        # Requirement 只记录 project 级归属，没有 created_by 列
    )
    db.add(requirement)
    db.flush()
    frozen = {
        "requirement": {"name": requirement.name},
        "fields": [
            {
                "field_id": 1,
                "evidence": evidence
                if evidence is not None
                else [{"title": PINNED_TITLE, "regulatory_version": PINNED_VERSION}],
            }
        ],
    }
    revision = RequirementRevision(
        project_id=project.id,
        requirement_id=requirement.id,
        content_version=1,
        scope_version=1,
        content_json=frozen,
        content_hash=content_digest(frozen),
        status="draft",
        created_by=user.id,
    )
    db.add(revision)
    db.commit()
    return project, requirement, revision, user


# --------------------------------------------------------------------------- pin extraction


def test_pins_are_read_from_the_frozen_revision(db):
    _, requirement, _, _ = _seed(db)
    assert pinned_versions_for_revision(db, requirement.project_id, requirement.id, 1) == {
        PINNED_TITLE: PINNED_VERSION
    }
    assert revision_has_version_pins(db, requirement.project_id, requirement.id) == [1]


def test_placeholder_versions_never_become_pins():
    content = {
        "fields": [
            {
                "evidence": [
                    {"title": "制度A", "regulatory_version": "2026-v1"},
                    {"title": "制度B", "regulatory_version": "  "},
                    {"title": "制度C", "regulatory_version": "未标注"},
                    {"regulatory_version": "2026-v3"},
                ]
            }
        ]
    }
    assert pinned_versions_from_content(content) == {"制度A": "2026-v1"}


def test_conflicting_versions_for_one_title_are_flagged_not_silently_overwritten():
    content = {
        "fields": [
            {
                "evidence": [
                    {"title": "制度A", "regulatory_version": "2026-v1"},
                    {"title": "制度A", "regulatory_version": "2026-v2"},
                ]
            }
        ]
    }
    pins = pinned_versions_from_content(content)
    assert pins["制度A"] == "2026-v1"
    assert pins["_conflicting:制度A"] == "1"


def test_missing_or_tampered_revisions_fail_closed(db):
    _, requirement, revision, _ = _seed(db)
    with pytest.raises(HTTPException) as missing:
        pinned_versions_for_revision(db, requirement.project_id, requirement.id, 99)
    assert missing.value.status_code == 404

    tampered = dict(revision.content_json)
    tampered["fields"] = [
        {"field_id": 1, "evidence": [{"title": "被改写的制度", "regulatory_version": "2026-v9"}]}
    ]
    revision.content_json = tampered
    db.commit()
    with pytest.raises(HTTPException) as broken:
        pinned_versions_for_revision(db, requirement.project_id, requirement.id, 1)
    assert broken.value.status_code == 409
    assert "完整性" in broken.value.detail


# --------------------------------------------------------------------------- deterministic downgrade


def test_citation_to_another_version_is_downgraded_even_if_the_judge_says_supported(db, monkeypatch):
    judge = _SupportingJudge()
    _install_gateway(monkeypatch, judge)
    _, requirement, _, _ = _seed(db)
    pins = pinned_versions_for_revision(db, requirement.project_id, requirement.id, 1)

    result = asyncio.run(
        check_citation_support(
            db,
            [_citation(version="2026-v2")],
            answer="个人贷款余额按合同口径统计。",
            project_id=requirement.project_id,
            pinned_versions=pins,
        )
    )

    assert result["pinned_versions"] == pins
    assert result["version_violations"], "v2 引用相对于固定的 v1 必须被确定性判为违规"
    violation = result["version_violations"][0]
    assert violation["citation_id"] == "knowledge-unit-7"
    assert violation["pinned_version"] == ".".join(normalize_version(PINNED_VERSION))
    assert violation["cited_version"] == ".".join(normalize_version("2026-v2"))
    assert result["verdicts"][0]["verdict"] == "unsupported"
    assert any(item.startswith("version_mismatch:") for item in result["trust_blockers"])
    assert result["verification"] != VERIFIED
    # 钉扎确实随请求交给了裁判，而不是只在本地过滤。
    assert PINNED_TITLE in judge.requests[0]


def test_the_pinned_version_itself_stays_supported(db, monkeypatch):
    _install_gateway(monkeypatch, _SupportingJudge())
    _, requirement, _, _ = _seed(db)
    pins = pinned_versions_for_revision(db, requirement.project_id, requirement.id, 1)

    result = asyncio.run(
        check_citation_support(
            db,
            [_citation(version=PINNED_VERSION, source_name=PINNED_TITLE)],
            answer="个人贷款余额按合同口径统计。",
            project_id=requirement.project_id,
            pinned_versions=pins,
        )
    )
    assert result["version_violations"] == []
    assert result["verdicts"][0]["verdict"] == "supported"


def test_without_pins_the_previous_behaviour_is_unchanged(db, monkeypatch):
    _install_gateway(monkeypatch, _SupportingJudge())
    _, requirement, _, _ = _seed(db)

    result = asyncio.run(
        check_citation_support(
            db,
            [_citation(version="2026-v2")],
            answer="个人贷款余额按合同口径统计。",
            project_id=requirement.project_id,
        )
    )
    assert result["pinned_versions"] == {}
    assert result["version_violations"] == []
    assert result["verdicts"][0]["verdict"] == "supported"


# --------------------------------------------------------------------------- API wiring


def _ask(db, project, requirement, *, content_version, monkeypatch, captured):
    from app.api import knowledge_rag

    async def fake_grounded_answer(_db, project_id, query, **filters):
        captured.update(filters)
        return {
            "answer": "个人贷款余额按合同口径统计。",
            "confidence_level": "medium",
            "citations": [],
            "supported_claims": [],
            "unsupported_claims": [],
            "open_questions": [],
            "retrieval_log_id": 1,
            "answer_status": "grounded",
            "trustworthiness": {},
            "index_freshness": {},
            "conflicts": [],
            "execution_metadata": {},
        }

    monkeypatch.setattr(knowledge_rag, "grounded_answer", fake_grounded_answer)
    principal = Principal(user_id=project.project_owner_id, username="pin-owner", display_name=None)
    payload = knowledge_rag.AskRequest(
        query="个人贷款余额怎么统计？",
        requirement_id=requirement.id,
        requirement_content_version=content_version,
    )
    return asyncio.run(knowledge_rag.ask(project.id, payload, principal, db))


def test_ask_passes_frozen_pins_into_the_answer_service(db, monkeypatch):
    project, requirement, _, _ = _seed(db)
    captured: dict = {}
    result = _ask(db, project, requirement, content_version=1, monkeypatch=monkeypatch, captured=captured)

    assert captured["pinned_versions"] == {PINNED_TITLE: PINNED_VERSION}
    assert result["version_pin"] == {
        "requirement_id": requirement.id,
        "content_version": 1,
        "source": "frozen_revision",
        "pinned_count": 1,
        # 明细必须回显，否则前端只能说“已固定”而说不出固定的是哪个版本。
        "pinned_versions": {PINNED_TITLE: PINNED_VERSION},
    }


def test_ask_requires_both_requirement_fields(db, monkeypatch):
    from app.api import knowledge_rag

    project, requirement, _, _ = _seed(db)
    principal = Principal(user_id=project.project_owner_id, username="pin-owner", display_name=None)
    payload = knowledge_rag.AskRequest(query="个人贷款余额怎么统计？", requirement_id=requirement.id)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(knowledge_rag.ask(project.id, payload, principal, db))
    assert exc.value.status_code == 400


def test_ask_refuses_a_revision_without_any_version_pins(db, monkeypatch):
    project, requirement, _, _ = _seed(db, evidence=[{"title": "无版本制度"}])
    captured: dict = {}
    with pytest.raises(HTTPException) as exc:
        _ask(db, project, requirement, content_version=1, monkeypatch=monkeypatch, captured=captured)
    assert exc.value.status_code == 422
    assert "未固定任何制度版本" in exc.value.detail
    assert captured == {}, "没有钉扎时不得继续调用生成，避免把未固定版本冒充为已固定"
