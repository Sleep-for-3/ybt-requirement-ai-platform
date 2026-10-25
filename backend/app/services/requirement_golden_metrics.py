"""业务金标与人工耗时基线（P0-A）。

本模块只做两件事：把"正确率"与"人工成本"算成可复算的数，并且拒绝把没有
独立标注的数据说成业务验收。

必须区分的三件事（混在一起就是自欺）：

* ``synthetic_consistency``——与合成期望的一致率，只能证明代码没坏；
* ``business_accuracy``——有独立标注人与证据位置的真实业务正确率，缺标注一律 N/A；
* ``manual_effort``——每字段人工有效处理时间，必须扣除审批等待与系统等待。

任何分母为 0 的指标输出 ``None``（JSON null / 文本 N/A），绝不写成 0 或 100%。
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

METRIC_VERSION = "requirement-golden-v1"

TIMING_PHASES = ("reading", "editing", "verifying", "approval_wait", "system_wait")
WAIT_PHASES = ("approval_wait", "system_wait")
QUALITY_LEVELS = ("synthetic", "business")


def dataset_sha256(cases: Iterable[Mapping[str, Any]]) -> str:
    payload = json.dumps(list(cases), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize(text: str | None) -> str:
    return " ".join((text or "").split())


@dataclass(frozen=True)
class CaseLabel:
    """一个字段级金标用例。``quality="business"`` 才可能进入业务正确率。"""

    case_id: str
    field_code: str
    expected_definition: str = ""
    expected_processing_logic: str = ""
    required_tokens: tuple[str, ...] = ()
    annotator: str = ""
    reviewer: str = ""
    annotated_at: str = ""
    evidence_positions: tuple[Mapping[str, Any], ...] = ()
    quality: str = "synthetic"
    case_family: str = "default"

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CaseLabel":
        quality = str(raw.get("quality") or "synthetic")
        if quality not in QUALITY_LEVELS:
            quality = "synthetic"
        return cls(
            case_id=str(raw.get("case_id") or ""),
            field_code=str(raw.get("field_code") or ""),
            expected_definition=str(raw.get("expected_definition") or ""),
            expected_processing_logic=str(raw.get("expected_processing_logic") or ""),
            required_tokens=tuple(str(token) for token in raw.get("required_tokens") or ()),
            annotator=str(raw.get("annotator") or ""),
            reviewer=str(raw.get("reviewer") or ""),
            annotated_at=str(raw.get("annotated_at") or ""),
            evidence_positions=tuple(raw.get("evidence_positions") or ()),
            quality=quality,
            case_family=str(raw.get("case_family") or "default"),
        )

    def metadata_issues(self) -> list[str]:
        issues: list[str] = []
        if not self.case_id:
            issues.append("缺少 case_id")
        if not self.field_code:
            issues.append(f"{self.case_id or '?'} 缺少 field_code")
        if self.quality == "business":
            if not self.annotator:
                issues.append(f"{self.case_id} 业务用例缺少独立标注人（annotator）")
            if not self.annotated_at:
                issues.append(f"{self.case_id} 业务用例缺少标注时间（annotated_at）")
            if not self.evidence_positions:
                issues.append(f"{self.case_id} 业务用例缺少证据位置（evidence_positions）")
        return issues


@dataclass(frozen=True)
class CaseResult:
    """被测系统对同一字段的输出。"""

    case_id: str
    field_code: str
    definition: str = ""
    processing_logic: str = ""
    supported_claim_count: int = 0
    claim_count: int = 0

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CaseResult":
        return cls(
            case_id=str(raw.get("case_id") or ""),
            field_code=str(raw.get("field_code") or ""),
            definition=str(raw.get("definition") or ""),
            processing_logic=str(raw.get("processing_logic") or ""),
            supported_claim_count=int(raw.get("supported_claim_count") or 0),
            claim_count=int(raw.get("claim_count") or 0),
        )


@dataclass
class CaseScore:
    case_id: str
    field_code: str
    quality: str
    definition_exact: bool
    logic_exact: bool
    key_rule_recall: float | None
    evidence_support: float | None
    manual_edit_ratio: float
    scored: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "field_code": self.field_code,
            "quality": self.quality,
            "definition_exact": self.definition_exact,
            "logic_exact": self.logic_exact,
            "key_rule_recall": self.key_rule_recall,
            "evidence_support": self.evidence_support,
            "manual_edit_ratio": self.manual_edit_ratio,
            "scored": self.scored,
            "reason": self.reason,
        }


def _ratio(hits: int, total: int) -> float | None:
    return None if total <= 0 else round(hits / total, 4)


def score_case(case: CaseLabel, result: CaseResult | None) -> CaseScore:
    if result is None:
        return CaseScore(case.case_id, case.field_code, case.quality, False, False, None, None, 1.0,
                         scored=False, reason="未执行（not_run）：该用例没有系统输出")
    definition_exact = normalize(result.definition) == normalize(case.expected_definition)
    logic_exact = normalize(result.processing_logic) == normalize(case.expected_processing_logic)
    if case.required_tokens:
        present = sum(1 for token in case.required_tokens if normalize(token) in normalize(result.processing_logic))
        key_rule_recall: float | None = round(present / len(case.required_tokens), 4)
    else:
        key_rule_recall = None
    evidence_support = _ratio(result.supported_claim_count, result.claim_count) if result.claim_count > 0 else None
    manual_edit_ratio = 0.0 if (definition_exact and logic_exact) else 1.0
    return CaseScore(case.case_id, case.field_code, case.quality, definition_exact, logic_exact,
                     key_rule_recall, evidence_support, manual_edit_ratio, scored=True)


@dataclass
class TimingRecord:
    case_id: str
    phases_ms: Mapping[str, int] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "TimingRecord":
        phases: dict[str, int] = {}
        for key, value in (raw.get("phases_ms") or {}).items():
            if key in TIMING_PHASES:
                phases[key] = int(value or 0)
        return cls(case_id=str(raw.get("case_id") or ""), phases_ms=phases)

    @property
    def effective_ms(self) -> int:
        return sum(value for key, value in self.phases_ms.items() if key not in WAIT_PHASES)

    @property
    def wait_ms(self) -> int:
        return sum(value for key, value in self.phases_ms.items() if key in WAIT_PHASES)


def summarize_timing(records: Iterable[TimingRecord]) -> dict[str, Any]:
    items = list(records)
    if not items:
        return {"case_count": 0, "effective_ms_per_field": None, "wait_ms_per_field": None,
                "total_effective_ms": None, "phase_totals_ms": {}}
    phase_totals = Counter()
    for item in items:
        for key, value in item.phases_ms.items():
            phase_totals[key] += value
    count = len(items)
    return {
        "case_count": count,
        "effective_ms_per_field": round(sum(item.effective_ms for item in items) / count, 1),
        "wait_ms_per_field": round(sum(item.wait_ms for item in items) / count, 1),
        "total_effective_ms": sum(item.effective_ms for item in items),
        "phase_totals_ms": dict(sorted(phase_totals.items())),
    }


def evaluate(
    cases: Iterable[Mapping[str, Any]],
    results: Iterable[Mapping[str, Any]],
    *,
    timings: Iterable[Mapping[str, Any]] = (),
    dataset_version: str = "",
    executed_families: Iterable[str] | None = None,
) -> dict[str, Any]:
    """返回可直接入库/入库后再复算的报告。"""

    raw_cases = list(cases)
    labels = [CaseLabel.from_mapping(raw) for raw in raw_cases]
    by_case = {result.case_id: result for result in (CaseResult.from_mapping(raw) for raw in results)}
    metadata_issues = [issue for label in labels for issue in label.metadata_issues()]

    scores = [score_case(label, by_case.get(label.case_id)) for label in labels]
    executed = set(executed_families) if executed_families is not None else {label.case_family for label in labels}
    families = sorted({label.case_family for label in labels})

    def aggregate(subset: list[CaseScore]) -> dict[str, Any]:
        scored = [item for item in subset if item.scored]
        return {
            "cases": len(subset),
            "scored_cases": len(scored),
            "definition_exact_rate": _ratio(sum(1 for item in scored if item.definition_exact), len(scored)),
            "logic_exact_rate": _ratio(sum(1 for item in scored if item.logic_exact), len(scored)),
            "key_rule_recall": _ratio(
                sum(1 for item in scored if item.key_rule_recall is not None and item.key_rule_recall >= 1.0),
                sum(1 for item in scored if item.key_rule_recall is not None)),
            "evidence_support_rate": _ratio(
                sum(1 for item in scored if item.evidence_support is not None and item.evidence_support >= 1.0),
                sum(1 for item in scored if item.evidence_support is not None)),
            "manual_edit_rate": _ratio(sum(1 for item in scored if item.manual_edit_ratio > 0), len(scored)),
        }

    synthetic = [item for item in scores if item.quality == "synthetic"]
    business = [item for item in scores if item.quality == "business"]
    business_ready = bool(business) and not any("业务用例" in issue for issue in metadata_issues)

    family_report: dict[str, Any] = {}
    for family in families:
        subset = [item for item in scores if item.case_id and any(
            label.case_family == family and label.case_id == item.case_id for label in labels)]
        if family not in executed:
            family_report[family] = {"status": "not_run", "reason": "该案例族未执行，不参与任何比率"}
            continue
        family_report[family] = aggregate(subset)

    return {
        "metric_version": METRIC_VERSION,
        "dataset_version": dataset_version,
        "dataset_sha256": dataset_sha256(raw_cases),
        "case_count": len(labels),
        "metadata_issues": metadata_issues,
        "cases": [item.to_dict() for item in scores],
        "synthetic_consistency": aggregate(synthetic) | {"status": "SYNTHETIC_ONLY"},
        "business_accuracy": (
            aggregate(business) | {"status": "BUSINESS_MEASURED"}
            if business_ready else
            {"status": "N/A", "reason": "缺少独立业务标注（标注人/时间/证据位置），业务正确率不可计算，不得对外宣称"}
        ),
        "case_families": family_report,
        "manual_effort": summarize_timing(TimingRecord.from_mapping(raw) for raw in timings),
        "verdict": "BUSINESS_VERIFIED" if business_ready else "UNVERIFIED",
    }
