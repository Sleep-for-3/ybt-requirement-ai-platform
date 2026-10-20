"""B包：引用支撑结果必须真正影响答案状态、可信度与界面（全部为合成材料）。

覆盖的缺陷（改前行为）：

* ``grounded_answer`` 只把 judge 结论**附加**到 ``citation_support``，于是引用被判定
  ``unsupported`` 时答案仍是 ``grounded`` + ``confidence_level="high"`` + 可信性 A/B；
* judge 超时/解析失败/漏判只表现成 ``unsupported_ratio == 0.0``，看起来“很干净”，
  缺少分母（原始主张数 / 已判断数 / unknown / 未判断数 / 覆盖率）；
* 重复 verdict、未知 citation id、无 id 的乱序输出会被静默丢弃或按位置错配，
  甚至重复计分；
* 超过单次判断上限时静默截断尾部，却仍声称全量通过。

合成材料说明：检索项、引用与模型回复均为合成数据，不含任何真实客户或行内资料；
``LLM_PROVIDER=mock``（``tests/conftest.py`` 强制），不发起任何外部模型调用。
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.settings import get_settings
from app.models import ModelProfile, Project, RagEvaluationCase, RagEvaluationResult, RagEvaluationRun
from app.services.evaluation import rag_evaluator
from app.services.llm.base import LLMProviderError, ModelCallMetadata
from app.services.rag import grounded_answer_service as grounded
from app.services.rag.citation_validator import check_citation_support

CALL_COUNT = {"value": 0}

SUPPORTED_ANSWER = "余额以合同为准。"
UNSUPPORTED_ANSWER = "利率以口头约定为准。"
FULL_ANSWER = f"{SUPPORTED_ANSWER}{UNSUPPORTED_ANSWER}"


class _ScriptedJudge:
    """按调用顺序返回固定 payload；记录每次调用实际收到的输入。"""

    last_call = ModelCallMetadata(provider="mock", model="judge-model")

    def __init__(self, payloads):
        # 单个 payload 也要包成列表：dict 直接 list() 会退化为取键（'verdicts'），
        # 得到一个永远不可解析的字符串回复，正是“解析失败”路径的意外触发。
        self.payloads = list(payloads) if isinstance(payloads, list) else [payloads]
        self.calls: list[dict] = []

    async def chat_json(self, system_prompt, user_prompt):
        CALL_COUNT["value"] += 1
        self.calls.append(json.loads(user_prompt))
        if not self.payloads:
            return {}
        if len(self.payloads) == 1:
            return self.payloads[0]
        return self.payloads.pop(0)

    async def embed_texts(self, texts):
        return [[0.0] for _ in texts]


class _EchoJudge:
    """把本次请求里的每条 claim/citation 都判为 supported（用于分批覆盖测试）。"""

    last_call = ModelCallMetadata(provider="mock", model="judge-model")

    def __init__(self):
        self.calls: list[dict] = []

    async def chat_json(self, system_prompt, user_prompt):
        CALL_COUNT["value"] += 1
        payload = json.loads(user_prompt)
        self.calls.append(payload)
        verdicts = [
            {"claim_id": item["claim_id"], "verdict": "supported", "reason": "引文支持"}
            for item in payload.get("claims") or []
        ]
        verdicts += [
            {
                "citation_id": item["citation_id"],
                "verdict": "supported",
                "reason": "引文支持",
            }
            for item in payload.get("citations") or []
        ]
        return {"verdicts": verdicts}

    async def embed_texts(self, texts):
        return [[0.0] for _ in texts]


class _FailingJudge:
    last_call = ModelCallMetadata(provider="mock", model="judge-model")

    async def chat_json(self, system_prompt, user_prompt):
        CALL_COUNT["value"] += 1
        raise LLMProviderError("judge unavailable", error_type="timeout")

    async def embed_texts(self, texts):
        raise LLMProviderError("judge unavailable", error_type="timeout")


def _install_gateway(monkeypatch, service):
    monkeypatch.setattr(
        "app.services.llm.prompt_runtime.get_runtime_llm_service", lambda *_a, **_k: service
    )


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        "sqlite:///" + (tmp_path / "overnight_citation.db").as_posix(),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    CALL_COUNT["value"] = 0
    settings = get_settings()
    monkeypatch.setattr(settings, "citation_support_check", "off", raising=False)
    monkeypatch.setattr(settings, "ragas_judge_enabled", False, raising=False)
    yield


def _citation(unit_id):
    return {
        "citation_id": f"knowledge-unit-{unit_id}",
        "knowledge_unit_id": unit_id,
        "label": f"合成知识单元 {unit_id}",
        "quoted_content": "余额以合同为准；利率以合同约定为准。",
        "locator": {"block_id": f"knowledge-unit-{unit_id}"},
    }


def _items(*unit_ids):
    return [
        {
            "knowledge_unit_id": unit_id,
            "content": "Synthetic.balance_table",
            "confidentiality_level": "internal",
            "rerank_score": 1.0,
            "authority_rank": 6,
        }
        for unit_id in unit_ids
    ]


def _run_grounded(db, monkeypatch, *, answer, supported_claims, judge, unit_ids=(1,)):
    """只替换模型边界与检索边界；判定/组装逻辑走真实代码。"""

    citations = {unit_id: _citation(unit_id) for unit_id in unit_ids}
    monkeypatch.setattr(
        grounded.HybridRetriever,
        "search",
        lambda *_a, **_k: (SimpleNamespace(id=1), _items(*unit_ids)),
    )
    monkeypatch.setattr(
        grounded,
        "document_citation",
        lambda item, _project_id: dict(citations[item["knowledge_unit_id"]]),
    )
    monkeypatch.setattr(grounded, "validate_citations", lambda *_a, **_k: None)
    monkeypatch.setattr(grounded, "get_prompt_runtime", lambda *_a, **_k: None)
    monkeypatch.setattr(grounded, "evidence_runtime", lambda runtime: runtime)
    monkeypatch.setattr(grounded, "prepare_model_input", lambda *_a, **_k: "synthetic evidence")

    async def execute(*_args, **_kwargs):
        return (
            {
                "answer": answer,
                "confidence_level": "high",
                "supported_claims": list(supported_claims),
                "unsupported_claims": [],
                "open_questions": [],
            },
            {},
        )

    monkeypatch.setattr(grounded, "execute_runtime_chat_with_metadata", execute)
    _install_gateway(monkeypatch, judge)
    return asyncio.run(grounded.grounded_answer(db, 1, "余额与利率的确定依据是什么？"))


# --------------------------------------------------------------------- 核心：unsupported 必须降级


def test_unsupported_key_claim_cannot_stay_grounded_high(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "citation_support_check", "judge", raising=False)
    judge = _ScriptedJudge(
        {
            "verdicts": [
                {"citation_id": "knowledge-unit-1", "verdict": "supported", "reason": "引文一致"},
                {"claim_id": "claim-1", "verdict": "supported", "reason": "引文一致"},
                {"claim_id": "claim-2", "verdict": "unsupported", "reason": "引文矛盾"},
            ]
        }
    )
    result = _run_grounded(
        db,
        monkeypatch,
        answer=FULL_ANSWER,
        supported_claims=[SUPPORTED_ANSWER, UNSUPPORTED_ANSWER],
        judge=judge,
        unit_ids=(1,),
    )
    support = result["citation_support"]

    # 引用 ID 合法（judged）不等于引用真正支撑主张：主张级判定必须独立生效。
    assert support["verification"] == "partially_supported"
    assert support["claims_supported"] == 1
    assert support["claims_unsupported"] == 1

    # 不得继续以 grounded / high 呈现为已证实。
    assert result["answer_status"] == "needs_confirmation"
    assert result["confidence_level"] == "low"
    assert result["trustworthiness"]["grade"] == "D"

    # 拆分“已支持部分 / 待核实部分”，并保留依据（引用不能被丢弃）。
    assert result["supported_claims"] == [SUPPORTED_ANSWER]
    assert UNSUPPORTED_ANSWER in result["unsupported_claims"]
    assert result["citations"] and result["citations"][0]["knowledge_unit_id"] == 1


def test_full_support_with_full_coverage_stays_grounded(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "citation_support_check", "judge", raising=False)
    judge = _ScriptedJudge(
        {
            "verdicts": [
                {"citation_id": "knowledge-unit-1", "verdict": "supported", "reason": "引文一致"},
                {"claim_id": "claim-1", "verdict": "supported", "reason": "引文一致"},
                {"claim_id": "claim-2", "verdict": "supported", "reason": "引文一致"},
            ]
        }
    )
    result = _run_grounded(
        db,
        monkeypatch,
        answer=FULL_ANSWER,
        supported_claims=[SUPPORTED_ANSWER, UNSUPPORTED_ANSWER],
        judge=judge,
    )
    support = result["citation_support"]
    assert support["verification"] == "verified"
    assert support["claim_coverage"] == 1.0
    assert support["claims_unjudged"] == 0
    assert result["answer_status"] == "grounded"
    assert result["confidence_level"] == "high"
    assert result["trustworthiness"]["grade"] in {"A", "B"}
    assert result["supported_claims"] == [SUPPORTED_ANSWER, UNSUPPORTED_ANSWER]


def test_unknown_claim_is_reported_as_partial_support_not_verified(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "citation_support_check", "judge", raising=False)
    judge = _ScriptedJudge(
        {
            "verdicts": [
                {"citation_id": "knowledge-unit-1", "verdict": "supported", "reason": "引文一致"},
                {"claim_id": "claim-1", "verdict": "supported", "reason": "引文一致"},
                {"claim_id": "claim-2", "verdict": "unknown", "reason": "证据不足"},
            ]
        }
    )
    result = _run_grounded(
        db,
        monkeypatch,
        answer=FULL_ANSWER,
        supported_claims=[SUPPORTED_ANSWER, UNSUPPORTED_ANSWER],
        judge=judge,
    )
    support = result["citation_support"]
    assert support["verification"] == "partially_supported"
    assert support["claims_unknown"] == 1
    assert result["answer_status"] == "needs_confirmation"
    assert result["confidence_level"] == "low"
    # 未知不是“无依据”，也不能冒充已证实：可信性最多 C。
    assert result["trustworthiness"]["grade"] == "C"
    assert result["unverified_claims"] == [UNSUPPORTED_ANSWER]


# --------------------------------------------------------------------- 降级/覆盖：不得换算成可靠


def test_judge_timeout_reports_degraded_with_denominators(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "citation_support_check", "judge", raising=False)
    result = _run_grounded(
        db,
        monkeypatch,
        answer=FULL_ANSWER,
        supported_claims=[SUPPORTED_ANSWER, UNSUPPORTED_ANSWER],
        judge=_FailingJudge(),
    )
    support = result["citation_support"]
    assert support["degraded"] is True
    assert support["degraded_reason"] == "timeout"
    assert support["verification"] == "degraded"
    # 关键：unsupported_ratio 为 0 不等于可靠，必须有分母与未判断数。
    assert support["unsupported_ratio"] == 0.0
    assert support["claims_total"] == 2
    assert support["claims_judged"] == 0
    assert support["claims_unjudged"] == 2
    assert support["claim_coverage"] == 0.0
    assert result["answer_status"] == "needs_confirmation"
    assert result["confidence_level"] == "low"
    assert result["trustworthiness"]["grade"] == "D"


def test_unparseable_judgement_is_unknown_not_a_clean_pass(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "citation_support_check", "judge", raising=False)
    result = _run_grounded(
        db,
        monkeypatch,
        answer=FULL_ANSWER,
        supported_claims=[SUPPORTED_ANSWER, UNSUPPORTED_ANSWER],
        judge=_ScriptedJudge("not json at all"),
    )
    support = result["citation_support"]
    assert support["verification"] == "unknown"
    assert support["claims_judged"] == 0
    assert support["claims_unjudged"] == 2
    assert support["unknown_count"] == 1  # 引用拿不到 verdict → unknown，而不是 supported
    assert result["answer_status"] == "needs_confirmation"


# --------------------------------------------------------------------- 重复/未知/乱序：不错配不重复计分


def test_duplicate_verdicts_are_counted_once_and_exposed(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "citation_support_check", "judge", raising=False)
    judge = _ScriptedJudge(
        {
            "verdicts": [
                {"citation_id": "knowledge-unit-1", "verdict": "supported", "reason": "首个"},
                {"citation_id": "knowledge-unit-1", "verdict": "unsupported", "reason": "重复"},
            ]
        }
    )
    _install_gateway(monkeypatch, judge)
    support = asyncio.run(
        check_citation_support(db, [_citation(1)], answer="余额以合同为准。", project_id=1)
    )
    # 直接驱动函数（不经过答案组装），断言计数语义。
    assert support["duplicate_verdict_ids"] == ["knowledge-unit-1"]
    assert support["supported_count"] == 1
    assert support["unsupported_count"] == 0
    assert support["judged_count"] == 1


def test_unknown_and_unkeyed_verdicts_are_dropped_not_misassigned(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "citation_support_check", "judge", raising=False)
    judge = _ScriptedJudge(
        {
            "verdicts": [
                {"citation_id": "knowledge-unit-99", "verdict": "supported", "reason": "越界"},
                {"verdict": "unsupported", "reason": "无 id 的乱序输出"},
                {"verdict": "supported", "reason": "无 id 的乱序输出"},
            ]
        }
    )
    _install_gateway(monkeypatch, judge)
    support = asyncio.run(
        check_citation_support(
            db,
            [_citation(1), _citation(2)],
            answer="余额以合同为准。",
            project_id=1,
        )
    )
    # 丢弃顺序：未带键的 verdict 先被识别，随后才是越界 id；两者都计数、都不参与计分。
    # 越界 id 被丢弃并计数；两条无 id 的 verdict 数量与待对应引用数量相等，
    # 因此按位置无歧义对齐（这是 A 包数据集明确要求的契约），不丢也不能乱猜。
    assert support["dropped_verdict_ids"] == ["knowledge-unit-99"]
    assert support["unkeyed_verdict_count"] == 2
    assert [item["verdict"] for item in support["verdicts"]] == ["unsupported", "supported"]
    assert support["judged_count"] == 2
    assert support["supported_count"] == 1
    assert support["unsupported_count"] == 1


# --------------------------------------------------------------------- 超上限：有界分批 / 显式未覆盖


def _claims_answer(count):
    return "".join(f"合成结论{index}。".replace("。", "") + "。" for index in range(1, count + 1))


def test_claims_beyond_one_call_are_batched_with_bounded_calls(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "citation_support_check", "judge", raising=False)
    judge = _EchoJudge()
    _install_gateway(monkeypatch, judge)
    answer = _claims_answer(25)
    support = asyncio.run(
        check_citation_support(db, [_citation(1)], answer=answer, project_id=1)
    )
    assert support["claims_total"] == 25
    assert support["claims_judged"] == 25
    assert support["claim_coverage"] == 1.0
    assert support["coverage_truncated"] is False
    assert support["batch_count"] == 2
    assert CALL_COUNT["value"] == 2
    # 第二批不再重复送引用，避免重复计分。
    assert judge.calls[1]["citations"] == []


def test_claims_beyond_the_batch_budget_are_explicitly_uncovered(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "citation_support_check", "judge", raising=False)
    judge = _EchoJudge()
    _install_gateway(monkeypatch, judge)
    answer = _claims_answer(70)
    support = asyncio.run(
        check_citation_support(db, [_citation(1)], answer=answer, project_id=1)
    )
    assert support["claims_total"] == 70
    assert support["claims_judged"] == 60
    assert support["claims_unjudged"] == 10
    assert support["claim_coverage"] == pytest.approx(0.8571, abs=1e-4)
    assert support["coverage_truncated"] is True
    assert support["batch_count"] == 3
    assert CALL_COUNT["value"] == 3
    # 未覆盖的尾部必须显式列出，不得静默截断后声称全量通过。
    assert len(support["uncovered_claims"]) == 10


# --------------------------------------------------------------------- 开关关闭：逐字兼容


def test_switch_off_adds_nothing_and_keeps_the_original_status(db, monkeypatch):
    def explode(*_args, **_kwargs):  # pragma: no cover - 关闭时绝不允许调用裁判
        raise AssertionError("citation_support_check=off 时不得调用裁判")

    monkeypatch.setattr("app.services.llm.prompt_runtime.get_runtime_llm_service", explode)
    result = _run_grounded(
        db,
        monkeypatch,
        answer=FULL_ANSWER,
        supported_claims=[SUPPORTED_ANSWER, UNSUPPORTED_ANSWER],
        judge=SimpleNamespace(),
    )
    assert "citation_support" not in result
    assert "unverified_claims" not in result
    assert result["answer_status"] == "grounded"
    assert result["confidence_level"] == "high"
    # 关闭时不得新增“已通过语义验证”的承诺，也不得凭空降低可信性。
    assert "support_verification" not in result["trustworthiness"]["dimensions"]
    assert CALL_COUNT["value"] == 0


# --------------------------------------------------------------------- 评测：接线而不破坏既有契约


def _profiles(db):
    profile = ModelProfile(
        profile_name="synthetic-profile",
        provider_type="mock",
        model_name="synthetic-model",
        enabled=True,
        local_only=True,
        supports_structured_output=True,
        max_context_tokens=8192,
        temperature=0.0,
        config_json={},
        created_by="b-package",
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def _seed_run(db):
    project = Project(name="B包合成评测项目")
    db.add(project)
    db.flush()
    case = RagEvaluationCase(
        project_id=project.id,
        case_name="synthetic-case",
        case_type="retrieval",
        query_text="问题-1",
        expected_knowledge_unit_ids_json=[1],
        expected_answer_keywords_json=["余额"],
        enabled=True,
    )
    run = RagEvaluationRun(
        project_id=project.id,
        run_name="b-citation",
        model_profile_id=None,
        retrieval_config_json={"retrieval_mode": "hybrid", "top_k": 10},
        status="pending",
        started_at=datetime.now(UTC),
        created_by="b-package",
    )
    db.add_all([case, run])
    db.commit()
    db.refresh(run)
    return project.id, run


def test_evaluator_records_citation_support_and_downgraded_status(db, monkeypatch):
    _profiles(db)
    project_id, run = _seed_run(db)
    from app.models import RetrievalLog

    async def fake_answer(db, project_id, query, **kwargs):
        log = RetrievalLog(
            project_id=project_id,
            query_text=query,
            query_type=kwargs["retrieval_mode"],
            filters_json={},
            retrieval_strategy=kwargs["retrieval_mode"],
            keyword_result_count=1,
            vector_result_count=1,
            final_result_count=1,
            result_ids_json=[1],
            latency_ms=5,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return {
            "retrieval_log_id": log.id,
            "answer": FULL_ANSWER,
            "citations": [{"knowledge_unit_id": 1, "quoted_content": "余额以合同为准"}],
            "supported_claims": [SUPPORTED_ANSWER],
            "unsupported_claims": [UNSUPPORTED_ANSWER],
            "open_questions": [],
            "answer_status": "needs_confirmation",
            "execution_metadata": {"execution_kind": "model"},
            "citation_support": {
                "enabled": True,
                "judged": True,
                "citation_count": 1,
                "judged_count": 1,
                "claims_total": 2,
                "claims_judged": 2,
                "claims_supported": 1,
                "claims_unsupported": 1,
                "claims_unknown": 0,
                "claims_unjudged": 0,
                "claim_coverage": 1.0,
                "coverage_truncated": False,
                "verification": "partially_supported",
            },
        }

    monkeypatch.setattr(rag_evaluator, "grounded_answer", fake_answer)
    completed = asyncio.run(rag_evaluator.run_evaluation(db, run))
    summary = completed.summary_metrics_json

    # 逐条元数据必须带上支撑校验结论（可序列化）。
    rows = list(
        db.scalars(
            select(RagEvaluationResult).where(
                RagEvaluationResult.evaluation_run_id == run.id
            )
        )
    )
    assert rows and rows[0].execution_metadata_json["answer_status"] == "needs_confirmation"
    assert rows[0].execution_metadata_json["citation_support"]["verification"] == (
        "partially_supported"
    )

    # 降级为待确认的样本不得计为“成功生成”，也不得进入回答正确率分母。
    assert summary["status_counts"]["needs_confirmation"] == 1
    assert summary["successful_query_count"] == 0
    assert summary["answer_correctness_denominator"] == 0
    # 汇总必须带分母，不允许只看“未发现不支持”。
    assert summary["citation_support_denominator"] == 1
    assert summary["citation_support_unsupported_count"] == 1
    assert summary["citation_support_claim_coverage"] == 1.0
