"""Scenario routing: which banking job is this objective actually asking for?

V1 collapsed every unrecognised objective into ``regulatory_field_analysis``, which
made the agent run a 15-step requirement chain for a question that was really about
mapping or a SQL change. V2 routes in two stages:

* **Stage A** — deterministic keyword/structure rules. Fast, explainable, no model.
* **Stage B** — when Stage A is not confident, the planner may ask the model to
  classify; the model only picks one of the registered scenario keys (never free text)
  and its answer is validated against the registry.

A low-confidence result is **not** forced into a scenario: the caller turns it into a
clarification gate so the agent asks instead of guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SCENARIO_REGULATORY_FIELD = "regulatory_field_analysis"
SCENARIO_REQUIREMENT_GENERATION = "requirement_generation"
SCENARIO_SQL_CHANGE_IMPACT = "sql_change_impact"
SCENARIO_MAPPING_RESOLUTION = "mapping_resolution"
DEFAULT_SCENARIO = SCENARIO_REGULATORY_FIELD

CONFIDENCE_RESOLVED = 0.75
CONFIDENCE_FLOOR = 0.45

SOURCE_RULE = "rule"
SOURCE_LLM = "llm"
SOURCE_FALLBACK = "fallback"
SOURCE_HUMAN = "human"


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_key: str
    label: str
    description: str
    keywords: tuple[str, ...]
    requires_subject: bool
    requires_change_context: bool = False
    plan_key: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario_key": self.scenario_key, "label": self.label, "description": self.description,
            "requires_subject": self.requires_subject,
            "requires_change_context": self.requires_change_context,
        }


SCENARIOS: dict[str, ScenarioSpec] = {
    SCENARIO_SQL_CHANGE_IMPACT: ScenarioSpec(
        scenario_key=SCENARIO_SQL_CHANGE_IMPACT,
        label="SQL 变更影响分析",
        description="脚本版本变化对监管字段、映射与需求的影响。",
        keywords=("sql", "脚本", "变更", "修改", "版本", "diff", "差异", "最近一次", "上线", "发布"),
        requires_subject=False, requires_change_context=True, plan_key=SCENARIO_SQL_CHANGE_IMPACT,
    ),
    SCENARIO_MAPPING_RESOLUTION: ScenarioSpec(
        scenario_key=SCENARIO_MAPPING_RESOLUTION,
        label="字段映射定位",
        description="为监管字段推荐来源系统字段与映射候选。",
        keywords=("映射", "对应", "来源系统", "源系统", "哪个字段", "取值来源", "mapping", "source"),
        requires_subject=True, plan_key=SCENARIO_MAPPING_RESOLUTION,
    ),
    SCENARIO_REQUIREMENT_GENERATION: ScenarioSpec(
        scenario_key=SCENARIO_REQUIREMENT_GENERATION,
        label="监管需求生成",
        description="生成银行监管需求候选与需求文档草稿。",
        keywords=("需求文档", "开发需求", "需求说明", "需求规格", "生成需求", "写一份", "需求书"),
        requires_subject=True, plan_key=SCENARIO_REQUIREMENT_GENERATION,
    ),
    SCENARIO_REGULATORY_FIELD: ScenarioSpec(
        scenario_key=SCENARIO_REGULATORY_FIELD,
        label="监管字段口径分析",
        description="分析监管字段的报送口径与当前实现差异。",
        keywords=("口径", "监管", "报送", "字段", "分析", "血缘", "影响"),
        requires_subject=True, plan_key=SCENARIO_REGULATORY_FIELD,
    ),
}
SCENARIO_KEYS: tuple[str, ...] = tuple(SCENARIOS)


@dataclass(frozen=True)
class ScenarioRouting:
    scenario_key: str
    confidence: float
    rationale: str
    alternatives: tuple[tuple[str, float], ...] = ()
    requires_clarification: bool = False
    source: str = SOURCE_RULE
    scores: dict[str, float] = field(default_factory=dict)

    @property
    def spec(self) -> ScenarioSpec:
        return SCENARIOS.get(self.scenario_key) or SCENARIOS[DEFAULT_SCENARIO]

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario_key": self.scenario_key,
            "label": self.spec.label,
            "confidence": round(self.confidence, 4),
            "rationale": self.rationale,
            "source": self.source,
            "requires_clarification": self.requires_clarification,
            "alternatives": [{"scenario_key": key, "score": round(score, 4)}
                             for key, score in self.alternatives],
            "scores": {key: round(value, 4) for key, value in self.scores.items()},
        }


def scenario_requires_subject(scenario_key: str) -> bool:
    spec = SCENARIOS.get(scenario_key) or SCENARIOS[DEFAULT_SCENARIO]
    return spec.requires_subject


def scenario_spec(scenario_key: str) -> ScenarioSpec:
    return SCENARIOS.get(scenario_key) or SCENARIOS[DEFAULT_SCENARIO]


def score_objective(objective: str) -> dict[str, float]:
    """Deterministic keyword scoring (Stage A). Longer keyword hits count more."""

    text = (objective or "").lower()
    scores: dict[str, float] = {}
    for key, spec in SCENARIOS.items():
        score = 0.0
        for keyword in spec.keywords:
            if keyword.lower() in text:
                score += min(1.0, len(keyword) / 4.0)
        scores[key] = round(score, 4)
    return scores


def route_scenario(objective: str) -> ScenarioRouting:
    """Stage A routing. Never returns a scenario it cannot justify."""

    scores = score_objective(objective)
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    leader_key, leader_score = ranked[0]
    second_key, second_score = ranked[1] if len(ranked) > 1 else (None, 0.0)
    total = sum(scores.values())
    confidence = round(leader_score / total, 4) if total else 0.0
    alternatives = tuple((key, score) for key, score in ranked[1:4] if score > 0)

    if leader_score <= 0:
        return ScenarioRouting(
            scenario_key=DEFAULT_SCENARIO, confidence=0.0, source=SOURCE_FALLBACK,
            rationale="目标中没有可用于识别场景的关键词，需要人工确认场景。",
            requires_clarification=True, scores=scores,
        )
    # A single clear winner: the leader matched something the others did not.
    if leader_score >= 2.0 and (leader_score - second_score) >= 1.0:
        return ScenarioRouting(
            scenario_key=leader_key, confidence=max(confidence, CONFIDENCE_RESOLVED),
            rationale=f"目标命中「{SCENARIOS[leader_key].label}」特征词（{leader_score:.1f} 分，明显领先）。",
            alternatives=alternatives, scores=scores,
        )
    # A structured signal that only one scenario can produce.
    if _requires_change_context(objective) and scores[SCENARIO_SQL_CHANGE_IMPACT] > 0:
        return ScenarioRouting(
            scenario_key=SCENARIO_SQL_CHANGE_IMPACT,
            confidence=max(confidence, CONFIDENCE_RESOLVED), source=SOURCE_RULE,
            rationale="目标描述了脚本版本/变更上下文，属于 SQL 变更影响分析。",
            alternatives=alternatives, scores=scores,
        )
    if confidence >= CONFIDENCE_RESOLVED:
        return ScenarioRouting(
            scenario_key=leader_key, confidence=confidence,
            rationale=f"目标命中「{SCENARIOS[leader_key].label}」特征词占比最高（{confidence:.2f}）。",
            alternatives=alternatives, scores=scores,
        )
    if confidence >= CONFIDENCE_FLOOR:
        return ScenarioRouting(
            scenario_key=leader_key, confidence=confidence,
            rationale=f"场景识别置信度偏低（{confidence:.2f}），优先按「{SCENARIOS[leader_key].label}」执行。",
            alternatives=alternatives, scores=scores,
        )
    return ScenarioRouting(
        scenario_key=DEFAULT_SCENARIO, confidence=confidence, source=SOURCE_FALLBACK,
        rationale="目标特征词分布无法确定场景，需要人工确认。",
        alternatives=alternatives, requires_clarification=True, scores=scores,
    )


_CHANGE_PATTERNS = (
    re.compile(r"版本\s*\d+"),
    re.compile(r"最近一次(修改|变更|调整)"),
    re.compile(r"(修改|变更|调整)了?(哪些|什么)"),
    re.compile(r"from\s+version", re.IGNORECASE),
)


def _requires_change_context(objective: str) -> bool:
    text = objective or ""
    return any(pattern.search(text) for pattern in _CHANGE_PATTERNS) or "sql" in text.lower()


def route_with_llm(objective: str, model_result: dict[str, Any] | None) -> ScenarioRouting:
    """Validate a model classification against the registry (Stage B)."""

    rule = route_scenario(objective)
    if not isinstance(model_result, dict):
        return rule
    key = str(model_result.get("scenario_key") or "")
    if key not in SCENARIOS:
        return ScenarioRouting(
            scenario_key=rule.scenario_key, confidence=rule.confidence, source=rule.source,
            rationale=f"模型给出的场景 {key!r} 未注册，使用规则识别结果。",
            alternatives=rule.alternatives, requires_clarification=rule.requires_clarification,
            scores=rule.scores,
        )
    try:
        confidence = float(model_result.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    rationale = str(model_result.get("rationale") or "模型场景分类")[:500]
    alternatives = tuple((other, 0.0) for other in (model_result.get("alternative_scenarios") or [])
                         if isinstance(other, str) and other in SCENARIOS and other != key)
    return ScenarioRouting(
        scenario_key=key, confidence=max(0.0, min(1.0, confidence)), rationale=rationale,
        alternatives=alternatives, source=SOURCE_LLM,
        requires_clarification=confidence < CONFIDENCE_RESOLVED or bool(model_result.get("requires_clarification")),
    )
