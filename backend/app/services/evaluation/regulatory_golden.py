"""独立于既有 benchmark 的银行监管业务黄金集与质量指标。

设计约束（《VNext 任务书》阶段1.1/1.2）：
- 黄金集数据放在 ``data/vnext_golden_set_v1.json``，代码只做加载/校验/计分，
  不在代码里硬编码任何"通过"结果，避免为凑分数改分母或写死答案；
- 每个指标同时输出分子、分母与比值；分母为 0 时比值必须是 ``None``，
  不得用 0 或 1 模糊代替"无样本"；
- 引用级（citation-level）判定与主张级（claim-level）判定严格分离，
  引用级结果永远不计入主张级支持数；
- 未提供观测结果（模型/检索实际输出）的用例只进入 ``not_run``，
  绝不当作通过；没有独立领域人员标注时 ``independent_labeled=0``，
  外部报告只能标记 UNVERIFIED。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

GOLDEN_SET_VERSION = "vnext-regulatory-golden-2026-10-21.v1"
DEFAULT_DATASET_PATH = Path(__file__).with_name("data") / "vnext_golden_set_v1.json"

FAMILIES = (
    "A_field_semantics",
    "B_multitable_join",
    "C_citation_evidence",
    "D_sql_semantics",
    "E_agent_decision",
    "F_full_delivery",
)
KINDS = ("field_retrieval", "citation", "document", "agent_decision", "delivery")
EXPECTATIONS = ("positive", "negative", "ambiguous")
DIFFICULTIES = ("easy", "medium", "hard")
ANNOTATION_STATUSES = ("draft", "in_review", "accepted", "disputed", "rejected")
MIN_CASES = 60
MIN_CASES_PER_FAMILY = 8


class GoldenSetError(ValueError):
    """黄金集数据不合法。消息必须指出具体 case 与字段，便于人工修数据。"""


@dataclass(frozen=True)
class GoldenAnnotation:
    """一条用例的标注元数据。

    独立标注不能只靠“填了一个 reviewer 字符串”来证明：
    - ``status`` 必须是 ``accepted``（``disputed``/``rejected`` 不算通过，``draft``/``in_review`` 未完成）；
    - 必须能证明独立性：``case_author`` 与 ``expected_author`` 都要记录，且 ``reviewer_id`` 不得是其中任一人；
    - 必须记录 ``reviewed_at``（ISO 日期）与 ``basis``（标注依据），否则视为“填了名字但没有依据”。
    历史数据只有顶层 ``reviewer_id`` 时按 ``draft`` 处理，不再自动算作已独立标注。
    """

    case_author: str | None = None
    expected_author: str | None = None
    reviewer_id: str | None = None
    reviewer_role: str | None = None
    reviewed_at: str | None = None
    basis: str | None = None
    status: str = "draft"
    dispute_note: str | None = None

    @property
    def independence_proven(self) -> bool:
        return bool(
            self.case_author
            and self.expected_author
            and self.reviewer_id
            and self.reviewer_id not in {self.case_author, self.expected_author}
        )

    @property
    def verified(self) -> bool:
        """只有 accepted + 独立性可证 + 有依据 + 有标注时间才计入独立标注。"""
        return bool(
            self.status == "accepted"
            and self.independence_proven
            and (self.reviewed_at or "").strip()
            and (self.basis or "").strip()
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_author": self.case_author,
            "expected_author": self.expected_author,
            "reviewer_id": self.reviewer_id,
            "reviewer_role": self.reviewer_role,
            "reviewed_at": self.reviewed_at,
            "basis": self.basis,
            "status": self.status,
            "dispute_note": self.dispute_note,
            "independence_proven": self.independence_proven,
            "verified": self.verified,
        }


def _parse_annotation(
    raw: Mapping[str, Any],
    case_id: str,
    legacy_reviewer: str | None,
    defaults: Mapping[str, Any] | None = None,
) -> GoldenAnnotation:
    payload = raw.get("annotation")
    if payload is None:
        payload = {}
    _require(isinstance(payload, Mapping), f"case {case_id} annotation 必须是对象")
    defaults = dict(defaults or {})

    def _text(key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            value = defaults.get(key)
        _require(value is None or isinstance(value, str), f"case {case_id} annotation.{key} 必须是字符串或 null")
        return (value or "").strip() or None

    reviewer = _text("reviewer_id") or (legacy_reviewer or "").strip() or None
    status = str(payload.get("status") or "draft")
    _require(status in ANNOTATION_STATUSES, f"case {case_id} annotation.status 非法: {status!r}")
    reviewed_at = _text("reviewed_at")
    if reviewed_at is not None:
        _require(
            _is_iso_date(reviewed_at),
            f"case {case_id} annotation.reviewed_at 必须是 YYYY-MM-DD，当前 {reviewed_at!r}",
        )
    if legacy_reviewer and not payload:
        # 历史数据：只有一个 reviewer 字符串，缺少作者/依据/时间，不能算独立标注。
        status = "draft"
    annotation = GoldenAnnotation(
        case_author=_text("case_author"),
        expected_author=_text("expected_author"),
        reviewer_id=reviewer,
        reviewer_role=_text("reviewer_role"),
        reviewed_at=reviewed_at,
        basis=_text("basis"),
        status=status,
        dispute_note=_text("dispute_note"),
    )
    if status == "accepted":
        _require(
            annotation.independence_proven,
            f"case {case_id} 标注为 accepted，但无法证明独立标注：需要 case_author/expected_author，"
            "且 reviewer_id 不能是作者本人",
        )
        _require(annotation.reviewed_at and annotation.basis, f"case {case_id} accepted 标注缺少 reviewed_at 或 basis")
    if status == "disputed":
        _require(bool(annotation.dispute_note), f"case {case_id} disputed 必须记录 dispute_note")
    return annotation


def _is_iso_date(value: str) -> bool:
    import datetime as _dt

    try:
        _dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    family: str
    title: str
    kind: str
    scenario: str
    expectation: str
    expected: Mapping[str, Any]
    notes: str = ""
    difficulty: str = "medium"
    reviewer_id: str | None = None
    label_source: str = "synthetic_designer"
    annotation: GoldenAnnotation = GoldenAnnotation()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GoldenSetError(message)


def parse_case(raw: Mapping[str, Any], index: int, defaults: Mapping[str, Any] | None = None) -> GoldenCase:
    case_id = str(raw.get("id") or "")
    _require(bool(case_id), f"case[{index}] 缺少 id")
    family = str(raw.get("family") or "")
    _require(family in FAMILIES, f"case {case_id} family 非法: {family!r}")
    kind = str(raw.get("kind") or "")
    _require(kind in KINDS, f"case {case_id} kind 非法: {kind!r}")
    expectation = str(raw.get("expectation") or "")
    _require(expectation in EXPECTATIONS, f"case {case_id} expectation 非法: {expectation!r}")
    expected = raw.get("expected")
    _require(isinstance(expected, Mapping), f"case {case_id} 缺少 expected 对象")
    difficulty = str(raw.get("difficulty") or "medium")
    _require(difficulty in DIFFICULTIES, f"case {case_id} difficulty 非法: {difficulty!r}")
    reviewer = raw.get("reviewer_id")
    _require(reviewer is None or isinstance(reviewer, str), f"case {case_id} reviewer_id 必须是字符串或 null")
    notes = str(raw.get("notes") or "")
    label_source = str(raw.get("label_source") or "synthetic_designer")
    annotation = _parse_annotation(raw, case_id, reviewer, defaults)
    return GoldenCase(
        case_id=case_id,
        family=family,
        title=str(raw.get("title") or ""),
        kind=kind,
        scenario=str(raw.get("scenario") or ""),
        expectation=expectation,
        expected=dict(expected),
        notes=notes,
        difficulty=difficulty,
        reviewer_id=reviewer if isinstance(reviewer, str) else None,
        label_source=label_source,
        annotation=annotation,
    )


def load_golden_set_with_meta(path: Path | str = DEFAULT_DATASET_PATH) -> tuple[list[GoldenCase], dict[str, Any]]:
    """加载黄金集，同时返回数据集级元数据（版本、标注政策、作者）。"""
    dataset_path = Path(path)
    _require(dataset_path.exists(), f"黄金集文件不存在: {dataset_path}")
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    _require(isinstance(payload, Mapping), "黄金集顶层必须是对象")
    _require(payload.get("version") == GOLDEN_SET_VERSION, f"黄金集版本不匹配: {payload.get('version')!r}")
    raw_cases = payload.get("cases")
    _require(isinstance(raw_cases, Sequence) and not isinstance(raw_cases, str), "cases 必须是数组")
    meta = payload.get("annotation")
    _require(meta is None or isinstance(meta, Mapping), "数据集 annotation 必须是对象")
    meta = dict(meta or {})
    defaults = meta.get("defaults")
    _require(defaults is None or isinstance(defaults, Mapping), "数据集 annotation.defaults 必须是对象")
    cases = [parse_case(raw, i, defaults) for i, raw in enumerate(raw_cases)]
    _require(len(cases) >= MIN_CASES, f"黄金集至少 {MIN_CASES} 例，当前 {len(cases)} 例")
    ids = [case.case_id for case in cases]
    _require(len(ids) == len(set(ids)), "黄金集 case id 重复")
    for family in FAMILIES:
        count = sum(1 for case in cases if case.family == family)
        _require(
            count >= MIN_CASES_PER_FAMILY,
            f"family {family} 至少 {MIN_CASES_PER_FAMILY} 例，当前 {count} 例",
        )
    for case in cases:
        if case.kind == "field_retrieval":
            correct = case.expected.get("correct_candidates")
            _require(
                isinstance(correct, list),
                f"case {case.case_id} field_retrieval 需要 correct_candidates 数组",
            )
            if case.expectation == "positive":
                _require(
                    bool(correct),
                    f"case {case.case_id} positive 用例需要非空 correct_candidates",
                )
            elif case.expectation == "negative":
                _require(
                    isinstance(case.expected.get("distractors"), list)
                    and bool(case.expected.get("distractors")),
                    f"case {case.case_id} negative 用例需要非空 distractors",
                )
        if case.kind == "citation":
            citations = case.expected.get("citations")
            _require(
                isinstance(citations, list) and citations,
                f"case {case.case_id} citation 需要非空 citations",
            )
            for item in citations:
                _require(
                    item.get("reference_verdict") in {"supported", "unsupported", "unknown"},
                    f"case {case.case_id} citation reference_verdict 非法",
                )
        if case.kind in {"agent_decision", "delivery"}:
            _require(
                bool(case.expected.get("expected_state")),
                f"case {case.case_id} 需要 expected_state",
            )
        if case.kind == "document":
            fields = case.expected.get("required_fields")
            _require(
                isinstance(fields, list) and fields,
                f"case {case.case_id} document 需要非空 required_fields",
            )
    return cases, meta


def load_golden_set(path: Path | str = DEFAULT_DATASET_PATH) -> list[GoldenCase]:
    """兼容入口：只要用例列表。"""
    cases, _ = load_golden_set_with_meta(path)
    return cases


def _truth_level(cases: Sequence[GoldenCase]) -> str:
    """标注真实性级别：没有一条被独立标注过就只能是 UNVERIFIED。"""
    if not cases:
        return "UNVERIFIED"
    verified = sum(1 for case in cases if case.annotation.verified)
    if verified == 0:
        return "UNVERIFIED"
    if verified == len(cases):
        return "VERIFIED"
    return "PARTIALLY_VERIFIED"


def dataset_summary(cases: Sequence[GoldenCase], meta: Mapping[str, Any] | None = None) -> dict[str, Any]:
    meta = dict(meta or {})
    by_family = {family: sum(1 for case in cases if case.family == family) for family in FAMILIES}
    by_kind = {kind: sum(1 for case in cases if case.kind == kind) for kind in KINDS}
    reviewer_ids = {case.annotation.reviewer_id for case in cases if case.annotation.reviewer_id}
    verified = sum(1 for case in cases if case.annotation.verified)
    status_counts = {status: 0 for status in ANNOTATION_STATUSES}
    for case in cases:
        status_counts[case.annotation.status] = status_counts.get(case.annotation.status, 0) + 1
    claimed_accepted = [case for case in cases if case.annotation.status == "accepted"]
    unproven = [case.case_id for case in claimed_accepted if not case.annotation.independence_proven]
    disputed = [case.case_id for case in cases if case.annotation.status == "disputed"]
    return {
        "version": GOLDEN_SET_VERSION,
        "dataset_version": meta.get("dataset_version") or GOLDEN_SET_VERSION,
        "case_count": len(cases),
        "by_family": by_family,
        "by_kind": by_kind,
        "reviewer_count": len(reviewer_ids),
        "independent_labeled": verified,
        "independent_labeled_ratio": _ratio(verified, len(cases), "independent_labeled_ratio"),
        "annotation_status_counts": status_counts,
        "accepted_without_provable_independence": unproven,
        "disputed_cases": disputed,
        "label_status": _truth_level(cases),
        "label_source": sorted({case.label_source for case in cases}),
        "annotation_policy": meta.get("annotation_policy") or {
            "independent_requires": ["case_author", "expected_author", "distinct reviewer_id", "reviewed_at", "basis"],
            "statuses": list(ANNOTATION_STATUSES),
        },
        "case_authors": sorted({case.annotation.case_author for case in cases if case.annotation.case_author}),
    }



def _ratio(numerator: int | float, denominator: int | float, name: str) -> dict[str, Any]:
    """返回 {numerator, denominator, ratio}；分母为 0 时 ratio 必须是 None。

    任务书要求所有比例 ≤1 且保留分子分母。若调用方传入了超过分母的分子，
    说明指标定义被写错（例如把引用级结果加进主张级计数），这里必须炸掉
    而不是静默截断。
    """
    if denominator is None or denominator <= 0:
        return {"numerator": float(numerator), "denominator": 0, "ratio": None, "metric": name}
    if numerator < 0:
        raise ValueError(f"{name}: numerator 不能为负")
    if numerator > denominator:
        raise ValueError(f"{name}: numerator({numerator}) 超过 denominator({denominator})，比例必须 ≤1")
    return {
        "numerator": float(numerator),
        "denominator": float(denominator),
        "ratio": round(float(numerator) / float(denominator), 6),
        "metric": name,
    }


def _as_observed(observations: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return observations or {}


def field_retrieval_metrics(
    cases: Sequence[GoldenCase],
    observed: Mapping[str, Any] | None,
    *,
    k: int = 5,
) -> dict[str, Any]:
    """字段召回：Recall@K / Top1 / Top3 / MRR / 预算截断率。

    observed[case_id] = {"ranked": [...候选 id 按排序...], "truncated": bool, "model_calls": int}
    """
    observed = _as_observed(observed)
    eligible = [case for case in cases if case.kind == "field_retrieval" and case.case_id in observed]
    if not eligible:
        return {"scored_cases": 0, "recall_at_k": _ratio(0, 0, f"recall@{k}"), "status": "not_run"}
    recall_hits = 0
    recall_total = 0
    top1_hits = 0
    top3_hits = 0
    reciprocal_ranks: list[float] = []
    truncated = 0
    model_calls = 0
    for case in eligible:
        ranked = [str(item) for item in observed[case.case_id].get("ranked", [])]
        correct = [str(item) for item in case.expected.get("correct_candidates", [])]
        recall_total += len(correct)
        recall_hits += sum(1 for item in correct if item in ranked[:k])
        hit_ranks = [ranked.index(item) + 1 for item in correct if item in ranked]
        if 1 in hit_ranks:
            top1_hits += 1
        if any(rank <= 3 for rank in hit_ranks):
            top3_hits += 1
        reciprocal_ranks.append(1.0 / min(hit_ranks) if hit_ranks else 0.0)
        if observed[case.case_id].get("truncated"):
            truncated += 1
        model_calls += int(observed[case.case_id].get("model_calls") or 0)
    return {
        "scored_cases": len(eligible),
        "recall_at_k": _ratio(recall_hits, recall_total, f"recall@{k}"),
        "top1_accuracy": _ratio(top1_hits, len(eligible), "top1_accuracy"),
        "top3_accuracy": _ratio(top3_hits, len(eligible), "top3_accuracy"),
        "mrr": _ratio(sum(reciprocal_ranks), len(eligible), "mrr"),
        "budget_truncation_rate": _ratio(truncated, len(eligible), "budget_truncation_rate"),
        "model_calls_total": model_calls,
        "status": "scored",
    }


def citation_metrics(
    cases: Sequence[GoldenCase],
    observed: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """引用可信度指标（引用级与主张级分离）。

    observed[case_id] = {
        "citations": [{"citation_id","verdict"}],           # verdict: supported|unsupported|unknown
        "claim_level": bool,                                 # 是否做了主张级判定
        "claims": [{"claim_id","verdict"}],                  # 仅 claim_level=True 才计数
        "judge_failed": bool,
    }
    """
    observed = _as_observed(observed)
    eligible = [
        case
        for case in cases
        if case.kind == "citation" and case.case_id in observed
    ]
    if not eligible:
        return {"scored_cases": 0, "status": "not_run"}
    true_positive = 0
    supported_total = 0
    predicted_supported = 0
    unsupported_caught = 0
    unsupported_total = 0
    judged = 0
    claim_judged_cases = 0
    claim_supported = 0
    claim_unsupported = 0
    claim_unknown = 0
    for case in eligible:
        item = observed[case.case_id]
        if item.get("judge_failed"):
            continue
        reference = {
            str(entry["citation_id"]): str(entry["reference_verdict"])
            for entry in case.expected.get("citations", [])
        }
        verdicts = {
            str(entry["citation_id"]): str(entry["verdict"])
            for entry in item.get("citations", [])
        }
        for citation_id, reference_verdict in reference.items():
            if reference_verdict == "unknown":
                continue
            judged += 1
            verdict = verdicts.get(citation_id, "unknown")
            if verdict == "supported":
                predicted_supported += 1
            if reference_verdict == "supported":
                supported_total += 1
                if verdict == "supported":
                    true_positive += 1
            elif reference_verdict == "unsupported":
                unsupported_total += 1
                if verdict == "unsupported":
                    unsupported_caught += 1
        if item.get("claim_level"):
            claim_judged_cases += 1
            for entry in item.get("claims", []):
                verdict = str(entry.get("verdict"))
                if verdict == "supported":
                    claim_supported += 1
                elif verdict == "unsupported":
                    claim_unsupported += 1
                else:
                    claim_unknown += 1
    false_supported = predicted_supported - true_positive
    return {
        "scored_cases": len(eligible),
        "citation_support_precision": _ratio(true_positive, predicted_supported, "citation_support_precision"),
        "citation_support_recall": _ratio(true_positive, supported_total, "citation_support_recall"),
        "false_supported_rate": _ratio(false_supported, judged, "false_supported_rate"),
        "unsupported_detection_rate": _ratio(unsupported_caught, unsupported_total, "unsupported_detection_rate"),
        "citation_coverage": _ratio(judged, sum(
            len(case.expected.get("citations", [])) for case in eligible
        ), "citation_coverage"),
        "claim_judged_cases": claim_judged_cases,
        "claim_supported": claim_supported,
        "claim_unsupported": claim_unsupported,
        "claim_unknown": claim_unknown,
        "claim_level_note": "claim_* 只统计 claim_level=True 的用例；引用级判定不计入主张级支持。",
        "status": "scored",
    }


def document_metrics(
    cases: Sequence[GoldenCase],
    observed: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """需求文档质量：必需字段覆盖率/已验证来源路径占比/依据可追溯率/无依据事实率/阻断准确性。

    observed[case_id] = {
        "required_fields_present": [...], "required_fields_total": int,
        "source_paths_verified": int, "source_paths_total": int,
        "claims_total": int, "claims_with_evidence": int,
        "unsupported_facts": int, "facts_total": int,
        "gate_state": "deliverable"|"blocked", "expected_gate": "deliverable"|"blocked",
    }
    """
    observed = _as_observed(observed)
    eligible = [
        case
        for case in cases
        if case.kind in {"document", "delivery"} and case.case_id in observed
    ]
    if not eligible:
        return {"scored_cases": 0, "status": "not_run"}
    present = 0
    required = 0
    verified = 0
    paths = 0
    traced = 0
    claims = 0
    unsupported_facts = 0
    facts = 0
    gate_correct = 0
    for case in eligible:
        item = observed[case.case_id]
        present += len(item.get("required_fields_present", []))
        required += int(item.get("required_fields_total") or len(case.expected.get("required_fields", [])))
        verified += int(item.get("source_paths_verified") or 0)
        paths += int(item.get("source_paths_total") or 0)
        traced += int(item.get("claims_with_evidence") or 0)
        claims += int(item.get("claims_total") or 0)
        unsupported_facts += int(item.get("unsupported_facts") or 0)
        facts += int(item.get("facts_total") or 0)
        expected_gate = case.expected.get("expected_state") or (
            "deliverable" if case.expectation == "positive" else "blocked"
        )
        if item.get("gate_state") == expected_gate:
            gate_correct += 1
    return {
        "scored_cases": len(eligible),
        "required_field_coverage": _ratio(present, required, "required_field_coverage"),
        "verified_source_path_ratio": _ratio(verified, paths, "verified_source_path_ratio"),
        "evidence_traceability_ratio": _ratio(traced, claims, "evidence_traceability_ratio"),
        "unsupported_fact_rate": _ratio(unsupported_facts, facts, "unsupported_fact_rate"),
        "delivery_gate_accuracy": _ratio(gate_correct, len(eligible), "delivery_gate_accuracy"),
        "status": "scored",
    }


def agent_decision_metrics(
    cases: Sequence[GoldenCase],
    observed: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Agent 决策：正确继续/阻塞/等待/驳回的准确率与错误放行率。"""
    observed = _as_observed(observed)
    eligible = [case for case in cases if case.kind == "agent_decision" and case.case_id in observed]
    if not eligible:
        return {"scored_cases": 0, "status": "not_run"}
    correct = 0
    wrong_release = 0
    wrong_block = 0
    for case in eligible:
        item = observed[case.case_id]
        expected_state = str(case.expected.get("expected_state") or "")
        actual = str(item.get("decision") or "")
        if actual == expected_state:
            correct += 1
        elif actual == "continue" and expected_state in {"blocked", "reject"}:
            wrong_release += 1
        elif actual in {"blocked", "reject"} and expected_state == "continue":
            wrong_block += 1
    return {
        "scored_cases": len(eligible),
        "decision_accuracy": _ratio(correct, len(eligible), "decision_accuracy"),
        "unsafe_release_rate": _ratio(wrong_release, len(eligible), "unsafe_release_rate"),
        "over_block_rate": _ratio(wrong_block, len(eligible), "over_block_rate"),
        "status": "scored",
    }


def evaluate_golden_set(
    cases: Sequence[GoldenCase],
    observations: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """汇总评测；observations 未覆盖的用例进入 not_run（不伪造通过）。

    每个指标都带 ``truth_level``：只有被独立标注（见 :class:`GoldenAnnotation`）的用例才可能
    是 ``VERIFIED``；本轮 60 例无独立银行专家标注，因此对外只能报 ``UNVERIFIED``。
    覆盖率按 kind 给出 scored/not_run，避免“只跑了引用 10 例”被误解为整套 60 例通过。
    """
    observations = observations or {}
    kind_to_metric = {
        "field_retrieval": "field_retrieval",
        "citation": "citation",
        "document": "document",
        "delivery": "document",
        "agent_decision": "agent_decision",
    }

    def _scored_cases(metric_key: str) -> list[GoldenCase]:
        bundles = {
            "field_retrieval": observations.get("field_retrieval") or {},
            "citation": observations.get("citation") or {},
            "document": {**(observations.get("document") or {}), **(observations.get("delivery") or {})},
            "agent_decision": observations.get("agent_decision") or {},
        }
        observed_ids = set(bundles.get(metric_key) or {})
        wanted = {"document", "delivery"} if metric_key == "document" else {metric_key}
        return [
            case
            for case in cases
            if case.kind in wanted and case.case_id in observed_ids
        ]

    metrics = {
        "field_retrieval": field_retrieval_metrics(cases, observations.get("field_retrieval")),
        "citation": citation_metrics(cases, observations.get("citation")),
        "document": document_metrics(cases, observations.get("document")),
        "agent_decision": agent_decision_metrics(cases, observations.get("agent_decision")),
    }
    for metric_key, payload in metrics.items():
        payload["truth_level"] = _truth_level(_scored_cases(metric_key))
        if payload.get("status") == "not_run":
            payload["scored_cases"] = 0

    ranked_ids = {
        case_id
        for kind_map in observations.values()
        for case_id in (kind_map or {})
    }
    coverage: dict[str, Any] = {}
    for kind in KINDS:
        of_kind = [case for case in cases if case.kind == kind]
        scored = [case for case in of_kind if case.case_id in ranked_ids]
        coverage[kind] = {
            "cases": len(of_kind),
            "scored": len(scored),
            "not_run": len(of_kind) - len(scored),
            "truth_level": _truth_level(scored),
        }
    return {
        "dataset": dataset_summary(cases, meta),
        "coverage": coverage,
        "metrics": metrics,
        "not_run_case_ids": [
            case.case_id for case in cases if case.case_id not in ranked_ids
        ],
    }

