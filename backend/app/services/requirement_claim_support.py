"""候选正文主张的确定性支持校验（P0-B，claim-support-v1）。

本模块是纯离线判定器：不调用模型、不访问网络、不读写数据库，只比较
「候选自行登记的主张」与「冻结输入里的固定事实（脚本规则 / 证据原文 / 物理字段）」。

设计约束（与需求单 P0-B 一致）：

* 只承认能由固定事实确定性复现的主张；无法判断时一律 ``unknown``，
  绝不因为「校验失败或无法校验」把内容标成 ``supported``。
* 校验器自身异常按 ``unknown`` 处理（fail-closed），并在报告里给出待人工确认文案。
* 无 claims 的历史候选返回 ``not_evaluated``，不追改历史内容，也不新增违规。
* 版本随语义规则演进；候选自行声明的版本与当前校验器不一致时拒绝认证。
"""
import logging
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.requirement_candidate_contract import CLAIM_SUPPORT_VERSION

logger = logging.getLogger("app.requirement_claim_support")

CONFLICT = "conflict"
UNKNOWN = "unknown"
SUPPORTED = "supported"

METHOD = "deterministic_fact_match"
METHOD_VERSION = CLAIM_SUPPORT_VERSION

Status = Literal["supported", "conflict", "unknown"]
ReportStatus = Literal["not_evaluated", "supported", "conflict", "unknown"]

_VERIFIABLE_KINDS = ("filter", "join_key", "aggregation", "as_of_date", "null_handling",
                     "code_mapping", "runtime_fact")

# 运行事实（P2-A 导入的事实包）在需求正文里被引用时的识别词。只有主张显式登记
# assertion_kind="runtime_fact" 时才启用这组词——否则「业务日期」「唯一性」这类
# 需求常见术语会被误判成运行事实断言，属于把确定性校验变成噪音。
_RUNTIME_FACT_ALIASES = {
    "key_uniqueness": ("键唯一", "唯一性", "主键唯一", "唯一率", "unique"),
    "null_rate": ("空值率", "空值比例", "非空率", "null 率"),
    "join_row_count": ("关联前后行数", "关联行数", "join 后行数", "join 前后", "匹配行数"),
    "group_reconciliation": ("分组对账", "对账一致", "分组金额一致", "总额一致"),
    "business_date": ("业务日期", "数据日期"),
    "script_hash": ("脚本版本", "脚本摘要", "脚本 hash", "脚本哈希"),
    "parameters": ("运行参数", "抽取参数", "跑批参数"),
    "metadata_version": ("元数据版本", "元数据快照"),
}
_LEVEL_RANK = {"static_inference": 0, "sampled_validation": 1, "full_run_validation": 2}

# 否定 / 反转表述：命中固定事实的否定语境时视为语义反转。
_NEGATION_MARKERS = (
    "无需", "不需要", "不筛选", "不做筛选", "不过滤", "不做过滤", "无需过滤", "无需判断",
    "排除", "剔除", "取消", "忽略", "不做任何限制", "无条件", "不区分",
)
_UNIVERSAL_MARKERS = ("全部", "所有", "全量", "无论", "任意", "不受限制")
_REVERSAL_PAIRS = (
    ("正常", "逾期"), ("正常", "不良"), ("正常", "异常"), ("有效", "无效"),
    ("纳入", "剔除"), ("保留", "排除"), ("纳入", "排除"), ("包含", "排出"),
)
_RESTRICTION_MARKERS = ("仅", "只", "限于", "筛选", "过滤", "where", "in (", "范围", "条件")
_SCOPE_MARKERS = ("仅", "只", "限于", "筛选", "过滤", "范围", "纳入", "口径", "条件", "状态")
# 语义上有判别力的状态词：证据里没有、主张里出现，就说明正文引入了未被支持的口径。
_DECISIVE_TOKENS = (
    "正常", "逾期", "不良", "有效", "无效", "关注类", "次级", "可疑", "损失",
    "本金", "利息", "余额", "笔数", "户数", "含息", "不含息",
)
_PERIOD_WORDS = ("月末", "季末", "年末", "期末", "期初", "月初", "年初", "日中", "时点")

_GROUPING_MARKERS = ("按", "分", "维度", "分组", "各组", "各")

_CN_AGGREGATIONS = {
    "求和": "sum", "合计": "sum", "汇总": "sum", "加总": "sum", "总额": "sum",
    "笔数": "count", "数量": "count", "计数": "count", "个数": "count", "条数": "count",
    "平均": "avg", "均值": "avg",
    "最大": "max", "最高": "max",
    "最小": "min", "最低": "min",
}

_SQL_RESERVED = {
    "where", "and", "or", "not", "on", "select", "from", "group", "by", "order", "having",
    "join", "left", "right", "inner", "outer", "as", "case", "when", "then", "else", "end",
    "null", "true", "false", "in", "like", "between", "exists", "union", "distinct", "limit",
}

_IDENT = r"[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*"
_DOTTED = rf"{_IDENT}(?:\s*\.\s*{_IDENT})*"

_COMPARE = re.compile(
    rf"(?P<column>{_DOTTED})\s*"
    rf"(?P<operator><=|>=|<>|!=|==|=|<|>|not\s+in|in|like|is\s+not|is)\s*"
    rf"(?P<value>'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\([^()]*\)|[-+]?\d+(?:\.\d+)?|null|true|false|{_DOTTED})",
    re.IGNORECASE,
)
_AGG_FUNCTION = re.compile(r"\b(sum|count|avg|max|min)\s*\(", re.IGNORECASE)
_GROUP_BY = re.compile(
    r"group\s+by\s+(?P<columns>.+?)(?=\border\s+by\b|\bhaving\b|\blimit\b|$)",
    re.IGNORECASE | re.DOTALL,
)
_DATE = re.compile(
    r"(?:19|20)\d{2}\s*[-/.年]\s*(?:1[0-2]|0?[1-9])"
    r"(?:\s*[-/.月]\s*(?:3[01]|[12]\d|0?[1-9])\s*日?)?"
)
_ENGLISH_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")


class ClaimSupportFinding(BaseModel):
    """一条不可认证的主张问题（冲突或待人工确认）。"""

    model_config = ConfigDict(extra="forbid")
    claim_id: str
    section: str = ""
    assertion_kind: str = ""
    status: Literal["conflict", "unknown"]
    code: str
    message: str
    refs: list[str] = Field(default_factory=list)


class ClaimEvaluation(BaseModel):
    """单条主张的最终判定（supported / conflict / unknown）。"""

    model_config = ConfigDict(extra="forbid")
    claim_id: str
    section: str = ""
    assertion_kind: str = ""
    status: Status
    codes: list[str] = Field(default_factory=list)
    message: str = ""
    method: str = METHOD
    method_version: str = METHOD_VERSION


class ClaimSupportReport(BaseModel):
    """生成期与审计用的主张支持报告。"""

    model_config = ConfigDict(extra="forbid")
    version: str = METHOD_VERSION
    status: ReportStatus
    claim_count: int = 0
    supported_count: int = 0
    conflict_count: int = 0
    unknown_count: int = 0
    evaluations: list[ClaimEvaluation] = Field(default_factory=list)
    findings: list[ClaimSupportFinding] = Field(default_factory=list)
    manual_review: list[str] = Field(default_factory=list)
    #: 全部问题文案（确定性冲突 + 无法判定），保持向后兼容的历史字段。
    violations: list[str] = Field(default_factory=list)
    #: 确定性冲突：正文与固定事实相矛盾，生成期必须阻断。
    blocking_violations: list[str] = Field(default_factory=list)
    #: 无法判定：证据不足/取值不在固定事实里，不阻断生成，写成缺口交人工确认。
    advisory_violations: list[str] = Field(default_factory=list)

    @property
    def evaluated(self) -> bool:
        return self.status != "not_evaluated"


def evaluate_claim_support(context: dict, candidate: dict) -> ClaimSupportReport:
    """确定性校验候选主张，返回可审计报告（含待人工确认文案）。

    旧候选（没有 claims 字段）返回 ``status="not_evaluated"`` 且 ``violations=[]``，
    保证向后兼容：不追改历史内容，也不新增违规。
    """
    payload = _as_mapping(candidate)
    claims = payload.get("claims")
    declared_version = str(payload.get("claim_support_version") or "").strip()
    if claims in (None, (), []):
        return ClaimSupportReport(status="not_evaluated")
    if not isinstance(claims, list):
        return _unavailable(0, "候选 claims 字段不是数组，无法执行主张校验")
    if declared_version and declared_version != CLAIM_SUPPORT_VERSION:
        return _version_refused(len(claims), declared_version)
    try:
        return _evaluate(context if isinstance(context, dict) else {}, claims)
    except Exception:  # noqa: BLE001 - fail-closed, never certify on internal error
        logger.exception("claim support evaluation failed; degrading to unknown")
        return _unavailable(len(claims), "主张校验器执行失败，无法确认候选正文语义")


def _evaluate(context, claims):
    sources = _SourceIndex(context)
    evaluations = []
    findings = []
    manual_review = []
    violations = []
    blocking: list[str] = []
    advisory: list[str] = []
    for index, raw in enumerate(claims):
        claim = _as_mapping(raw)
        try:
            evaluation, claim_findings = _evaluate_claim(claim, index, sources)
        except Exception:  # noqa: BLE001 - one broken claim must not certify the rest
            logger.exception("claim %s evaluation failed", index)
            claim_id = str(claim.get("claim_id") or f"claim-{index + 1}")
            message = "该主张的校验过程异常，无法确认其语义是否被固定事实支持"
            evaluation = ClaimEvaluation(claim_id=claim_id,
                                         section=str(claim.get("section") or ""),
                                         assertion_kind=str(claim.get("assertion_kind") or ""),
                                         status=UNKNOWN, codes=["evaluator_unavailable"],
                                         message=message)
            claim_findings = [ClaimSupportFinding(claim_id=claim_id, status=UNKNOWN,
                                                  code="evaluator_unavailable", message=message)]
        evaluations.append(evaluation)
        claim_text = str(claim.get("text") or "").strip()
        for finding in claim_findings:
            findings.append(finding)
            if finding.status == CONFLICT:
                message = f"候选正文主张与固定事实冲突（{finding.claim_id}/{finding.code}）：{finding.message}"
                violations.append(message)
                blocking.append(message)
                manual_review.append(
                    f"请人工核对主张 {finding.claim_id}：{_excerpt(claim_text)} —— {finding.message}"
                )
            else:
                message = f"候选正文主张无法确定性校验，须人工确认（{finding.claim_id}/{finding.code}）：{finding.message}"
                violations.append(message)
                advisory.append(message)
                manual_review.append(
                    f"请人工确认主张 {finding.claim_id}：{_excerpt(claim_text)} —— {finding.message}"
                )
    if not evaluations:
        return ClaimSupportReport(status="not_evaluated")
    supported = sum(item.status == SUPPORTED for item in evaluations)
    conflicts = sum(item.status == CONFLICT for item in evaluations)
    unknowns = sum(item.status == UNKNOWN for item in evaluations)
    status = CONFLICT if conflicts else UNKNOWN if unknowns else SUPPORTED
    return ClaimSupportReport(
        status=status,
        claim_count=len(evaluations),
        supported_count=supported,
        conflict_count=conflicts,
        unknown_count=unknowns,
        evaluations=evaluations,
        findings=findings,
        manual_review=list(dict.fromkeys(manual_review)),
        violations=list(dict.fromkeys(violations)),
        blocking_violations=list(dict.fromkeys(blocking)),
        advisory_violations=list(dict.fromkeys(advisory)),
    )


def _unavailable(count, message):
    finding = ClaimSupportFinding(claim_id="claim-support", status=UNKNOWN,
                                  code="evaluator_unavailable", message=message)
    text = f"候选正文主张无法确定性校验，须人工确认（claim-support/evaluator_unavailable）：{message}"
    return ClaimSupportReport(status=UNKNOWN, claim_count=count, unknown_count=count,
                              findings=[finding],
                              manual_review=[f"请人工确认候选正文：{message}"],
                              violations=[text],
                              advisory_violations=[text])


def _version_refused(count, declared):
    message = (f"候选声明的支持校验版本 {declared} 与当前校验器 {CLAIM_SUPPORT_VERSION} 不一致，"
               "无法确认该主张是按当前规则核验过的")
    finding = ClaimSupportFinding(claim_id="claim-support", status=UNKNOWN,
                                  code="evaluator_version_mismatch", message=message)
    text = f"候选正文主张无法确定性校验，须人工确认（claim-support/evaluator_version_mismatch）：{message}"
    return ClaimSupportReport(status=UNKNOWN, claim_count=count, unknown_count=count,
                              findings=[finding],
                              manual_review=[f"请人工确认候选正文：{message}"],
                              violations=[text],
                              advisory_violations=[text])


class _Issues:
    """单条主张的问题收集器。"""

    def __init__(self):
        self.items = []
        self.refs = []

    def conflict(self, code, message, refs=()):
        self.items.append((CONFLICT, code, message))
        self.refs.extend(str(ref) for ref in refs if ref not in (None, ""))

    def unknown(self, code, message, refs=()):
        self.items.append((UNKNOWN, code, message))
        self.refs.extend(str(ref) for ref in refs if ref not in (None, ""))


def _evaluate_claim(claim, index, sources):
    """返回 (ClaimEvaluation, list[ClaimSupportFinding])。"""
    claim_id = str(claim.get("claim_id") or f"claim-{index + 1}")
    section = str(claim.get("section") or "")
    kind = str(claim.get("assertion_kind") or "")
    text = str(claim.get("text") or "")
    lowered = text.lower()
    issues = _Issues()
    supports = claim.get("support")
    supports = [_as_mapping(item) for item in supports] if isinstance(supports, list) else []

    if not text.strip():
        issues.unknown("claim_text_empty", "主张没有正文，无法核验其语义")
    if sources.section and section and section != sources.section:
        issues.conflict("claim_section_mismatch",
                        f"主张登记为 {section} 章节，与当前候选章节 {sources.section} 不一致", [claim_id])

    cited_rules = []
    cited_evidence = []
    declared_unknown = False
    declared_conflict = False
    if not supports:
        issues.unknown("claim_without_support", "主张没有登记任何支持项，无法对固定事实做核验")
    for support in supports:
        source = str(support.get("source") or "")
        ref_id = str(support.get("ref_id") or "").strip()
        declared = str(support.get("status") or UNKNOWN)
        if declared == CONFLICT:
            declared_conflict = True
        elif declared != SUPPORTED:
            declared_unknown = True
        if source == "script_rule":
            rule = sources.rules.get(ref_id)
            if rule is None:
                issues.conflict("rule_reference_out_of_scope",
                                f"主张引用的脚本规则 {ref_id or '（空）'} 不在固定输入范围内", [ref_id])
            else:
                cited_rules.append(rule)
        elif source == "evidence":
            unit = sources.evidence_for(ref_id)
            if unit is None:
                issues.conflict("evidence_reference_out_of_scope",
                                f"主张引用的证据 {ref_id or '（空）'} 不存在于固定输入中", [ref_id])
            else:
                cited_evidence.append(unit)
            _check_evidence_version(unit, support, sources, issues, ref_id)
        elif source == "physical_field":
            if not sources.physical_matches(ref_id):
                issues.conflict("physical_reference_out_of_scope",
                                f"主张引用的物理字段 {ref_id or '（空）'} 不在固定输入范围内", [ref_id])
        elif source == "runtime_fact":
            if sources.runtime is None:
                issues.unknown("runtime_fact_unavailable",
                               "主张引用了运行事实，但本次生成输入没有运行事实包", [ref_id])
            elif sources.runtime_fact(ref_id) is None:
                issues.conflict("runtime_fact_reference_out_of_scope",
                                f"主张引用的运行事实 {ref_id or '（空）'} 不在冻结事实包中", [ref_id])
        else:
            issues.unknown("support_source_unknown",
                           f"主张支持项来源 {source or '（空）'} 不是可核验类型", [ref_id])

    if declared_conflict:
        issues.conflict("declared_support_conflict",
                        "主张自述其支持项已与固定事实冲突，不能作为已支持内容")
    elif declared_unknown:
        issues.unknown("declared_support_unknown",
                       "主张自述其支持项状态为 unknown，未被固定事实确定性支持")

    if kind == "other":
        issues.unknown("assertion_not_verifiable",
                       "主张类型为 other，校验器没有可核验的语义断言口径")
    elif kind not in _VERIFIABLE_KINDS:
        issues.unknown("assertion_kind_unknown",
                       f"主张类型 {kind or '（空）'} 不是校验器可识别的类型")
    elif not declared_conflict and not declared_unknown:
        _dispatch(kind, lowered, text, cited_rules, cited_evidence, sources, issues)

    status = CONFLICT if any(item[0] == CONFLICT for item in issues.items) else (
        UNKNOWN if issues.items else SUPPORTED)
    message = issues.items[0][2] if issues.items else "主张内容与固定事实一致"
    codes = list(dict.fromkeys(item[1] for item in issues.items))
    evaluation = ClaimEvaluation(claim_id=claim_id, section=section, assertion_kind=kind,
                                 status=status, codes=codes, message=message)
    findings = [ClaimSupportFinding(claim_id=claim_id, section=section, assertion_kind=kind,
                                    status=item[0], code=item[1], message=item[2],
                                    refs=list(dict.fromkeys(issues.refs)))
                for item in issues.items]
    return evaluation, findings


def _dispatch(kind, lowered, text, rules, evidence, sources, issues):
    if kind == "filter":
        _check_filter(lowered, rules, evidence, sources, issues)
    elif kind == "join_key":
        _check_join(lowered, rules, sources, issues)
    elif kind == "aggregation":
        _check_aggregation(lowered, rules, sources, issues)
    elif kind == "as_of_date":
        _check_as_of(lowered, sources, issues)
    elif kind == "null_handling":
        _check_generic_evidence(lowered, evidence, "空值处理", issues)
    elif kind == "code_mapping":
        _check_code_mapping(lowered, rules, evidence, issues)
    elif kind == "runtime_fact":
        _check_runtime_fact(lowered, sources, issues)


def _check_runtime_fact(lowered, sources, issues):
    """运行事实断言只能说到事实包允许的强度。

    事实包在导入时冻结，`allowed_level` 已经由 `claim_allowed` 决定（低于要求的
    事实只允许当静态推断用）。这里只做确定性比对：主张提到的每一类事实，其允许
    级别必须达到该类事实的要求级别，否则不得表述为"运行验证/实测对账"结论。
    """
    mentioned = [key for key, aliases in _RUNTIME_FACT_ALIASES.items()
                 if any(alias in lowered for alias in aliases)]
    if sources.runtime is None:
        issues.unknown(
            "runtime_fact_unavailable",
            "主张登记为运行事实类型，但本次生成输入没有运行事实包；运行验证/实测对账类结论"
            "不得作为已支持内容，需导入脱敏运行事实包后重新校验",
        )
        return
    if not mentioned:
        issues.unknown(
            "runtime_fact_unspecified",
            "主张登记为运行事实类型，但正文没有可识别的运行事实项（键唯一性 / 空值率 / "
            "关联前后行数 / 分组对账 / 业务日期 / 脚本版本 / 运行参数 / 元数据版本）",
        )
        return
    for key in mentioned:
        entry = sources.runtime_fact(key)
        if entry is None:
            issues.unknown("runtime_fact_missing",
                           f"主张引用的运行事实 {key} 不在冻结事实包中，无法核验")
            continue
        allowed = str(entry.get("allowed_level") or "static_inference")
        required = str(entry.get("required_level") or "full_run_validation")
        if _LEVEL_RANK.get(allowed, 0) < _LEVEL_RANK.get(required, 2):
            issues.conflict(
                "runtime_fact_level_insufficient",
                f"运行事实 {key} 只达到 {allowed}（该类事实要求 {required}），"
                "低于要求级别的写入只能作为静态推断，不得表述为运行验证结论",
                [key],
            )



def _is_truncated(text: str) -> bool:
    """投影截断会在文本尾部留下明确标记；带标记的文本不得当作完整事实。"""
    return "（已截断" in text or text.rstrip().endswith("…")


def _check_filter(lowered, rules, evidence, sources, issues):
    parsed = []
    for rule in rules:
        condition = str(rule.get("filter_condition") or "").strip()
        if not condition:
            continue
        if _is_truncated(condition):
            issues.unknown("script_condition_truncated",
                           "过滤条件文本在生成输入中已被截断，无法确定性校验，须人工核对脚本原文",
                           [rule.get("rule_id")])
            continue
        predicates = _parse_predicates(condition)
        if predicates:
            parsed.append((rule, condition, predicates))
    evidence_texts = [str(unit.get("content") or "") for unit in evidence if str(unit.get("content") or "").strip()]

    if not parsed and not evidence_texts:
        issues.unknown("filter_source_missing",
                       "主张声称过滤条件，但所引用规则与证据都没有可核验的过滤事实")
        return

    for rule, condition, predicates in parsed:
        flip = _negation_conflict(lowered, condition.lower(), predicates)
        if flip:
            issues.conflict("filter_negation_flip",
                            f"主张对固定过滤条件做了否定或反转表述（{flip}），固定条件为：{condition}",
                            [rule.get("rule_id")])
    for unit in evidence:
        content = str(unit.get("content") or "")
        flip = _negation_conflict(lowered, content.lower(), _parse_predicates(content))
        if flip:
            issues.conflict("filter_negation_flip",
                            f"主张否定了证据原文的筛选口径（{flip}）", [unit.get("unit_id")])
    for rule, condition, predicates in parsed:
        missing = []
        for predicate in predicates:
            column = predicate["column"]
            if column.lower() in _SQL_RESERVED:
                continue
            if not _column_mentioned(lowered, column, sources.aliases):
                missing.append(column)
        if missing:
            issues.conflict("filter_column_missing",
                            f"主张未提及固定过滤列 {', '.join(dict.fromkeys(missing))}（漏过滤），"
                            f"固定条件为：{condition}", [rule.get("rule_id")])
            continue
        if not _value_attested(lowered, predicates):
            issues.conflict("filter_value_missing",
                            f"主张未体现固定过滤条件的取值或范围（漏过滤），固定条件为：{condition}",
                            [rule.get("rule_id")])
    if not parsed and evidence_texts:
        _check_generic_evidence(lowered, evidence, "过滤口径", issues)


def _check_join(lowered, rules, sources, issues):
    pairs = []
    rule_ids = []
    for rule in rules:
        condition = str(rule.get("join_condition") or "").strip()
        if not condition:
            continue
        for predicate in _parse_predicates(condition):
            raw = str(predicate["raw"]).strip()
            if not re.fullmatch(_DOTTED, raw):
                continue
            pairs.append((predicate["column"], _leaf(raw)))
        rule_ids.append(rule.get("rule_id"))
    if not pairs:
        issues.unknown("join_condition_missing",
                       "主张声称关联键，但所引用规则没有可核验的关联条件")
        return
    keys = sorted({pair[0] for pair in pairs})
    mentioned = [key for key in keys if _column_mentioned(lowered, key, sources.aliases)]
    if len(keys) >= 2 and len(mentioned) < len(keys):
        issues.conflict("join_composite_key_collapsed",
                        f"固定关联为复合键（{', '.join(keys)}），主张只体现 "
                        f"{', '.join(mentioned) or '未体现任何键'}（单键替代复合键）", rule_ids)
    elif len(keys) == 1 and not mentioned:
        issues.conflict("join_key_missing",
                        f"主张未体现固定关联键 {keys[0]}", rule_ids)


def _check_aggregation(lowered, rules, sources, issues):
    facts = []
    rule_ids = []
    for rule in rules:
        text = str(rule.get("aggregation_rule") or "").strip()
        if not text:
            continue
        facts.append((text, {match.group(1).lower() for match in _AGG_FUNCTION.finditer(text)},
                      _group_by_dims(text)))
        rule_ids.append(rule.get("rule_id"))
    if not facts:
        issues.unknown("aggregation_rule_missing",
                       "主张声称聚合口径，但所引用规则没有可核验的聚合规则")
        return
    rule_functions = set().union(*(functions for _, functions, _ in facts))
    dimensions = set().union(*(dims for _, _, dims in facts))
    claimed_functions = _claimed_functions(lowered)
    if claimed_functions and rule_functions and not claimed_functions <= rule_functions:
        issues.conflict("aggregation_function_mismatch",
                        f"主张的聚合函数 {', '.join(sorted(claimed_functions))} 与固定聚合规则 "
                        f"{', '.join(sorted(rule_functions))} 不一致", rule_ids)
    claimed_dimensions = _claimed_dimensions(lowered, sources.rule_columns, sources.aliases)
    wrong = sorted(claimed_dimensions - dimensions)
    if dimensions and wrong:
        issues.conflict("aggregation_dimension_mismatch",
                        f"主张按 {', '.join(wrong)} 分组，与固定分组维度 "
                        f"{', '.join(sorted(dimensions))} 不一致", rule_ids)
    if not claimed_functions and not claimed_dimensions:
        issues.unknown("aggregation_claim_unverifiable",
                       "主张没有给出可核验的聚合函数或分组维度")


def _check_as_of(lowered, sources, issues):
    dates = _extract_dates(lowered)
    periods = [word for word in _PERIOD_WORDS if word in lowered]
    if not dates and not periods:
        issues.unknown("as_of_date_missing",
                       "主张声称统计时点，但正文没有可核验的日期或期末口径")
        return
    missing = [value for value in dates if not _date_attested(value, sources)]
    if missing:
        issues.unknown("as_of_date_unattested",
                       f"主张声称统计时点 {', '.join(dict.fromkeys(missing))}，"
                       "但固定规则与证据中都没有该时点")
    missing_periods = [word for word in periods if word not in sources.corpus_text]
    if missing_periods:
        issues.unknown("as_of_period_unattested",
                       f"主张声称统计口径 {', '.join(dict.fromkeys(missing_periods))}，"
                       "但固定规则与证据中都没有该口径")


def _check_code_mapping(lowered, rules, evidence, issues):
    mappings = [str(rule.get("code_mapping_rule") or "").strip() for rule in rules]
    mappings = [text for text in mappings if text]
    if not mappings:
        if evidence:
            _check_generic_evidence(lowered, evidence, "码值映射", issues)
        else:
            issues.unknown("code_mapping_rule_missing",
                           "主张声称码值映射，但所引用规则没有可核验的码值映射事实")
        return
    mapping_text = " ".join(mappings).lower()
    claim_tokens = set(_ENGLISH_TOKEN.findall(lowered)) | set(_extract_dates(lowered))
    shared = {token for token in claim_tokens if token and token in mapping_text}
    if not claim_tokens:
        issues.unknown("code_mapping_claim_unverifiable",
                       "主张没有给出可核验的码值或字段，无法确认映射结论")
    elif not shared:
        issues.conflict("code_mapping_unrelated",
                        f"主张正文与固定码值映射事实没有共同可核验对象：" + "；".join(mappings))


def _check_generic_evidence(lowered, evidence, topic, issues):
    texts = [str(unit.get("content") or "").lower() for unit in evidence if str(unit.get("content") or "").strip()]
    if not texts:
        issues.unknown("evidence_missing",
                       f"主张声称{topic}，但没有可核验的证据原文")
        return
    joined = "\n".join(texts)
    tokens = _decisive_tokens(lowered)
    if not tokens:
        issues.unknown("claim_unverifiable_tokens",
                       f"主张没有可核验的{topic}关键词，无法确认其与证据原文的一致性")
        return
    unattested = [token for token in tokens if token not in joined]
    if unattested:
        issues.conflict("claim_token_unattested",
                        f"主张出现证据原文不存在的口径关键词：{', '.join(unattested)}")
        return
    flip = _negation_conflict(lowered, joined, [])
    if flip:
        issues.conflict("filter_negation_flip",
                        f"主张对证据原文做了否定或反转表述（{flip}）")


# --------------------------------------------------------------------------- #
# 固定事实索引
# --------------------------------------------------------------------------- #
_RULE_TEXT_FIELDS = ("transformation_expression", "join_condition", "filter_condition",
                     "aggregation_rule", "code_mapping_rule")


def _resolve_rule_refs(rule: dict, pool: dict) -> dict:
    """把投影后的 sha 引用还原成长文本。

    `requirement_input._project_script_basis` 把重复的长表达式去重进
    `condition_texts`，规则里只留 `*_ref`。校验前必须还原，否则所有过滤/关联
    断言都会因为"读不到条件文本"被误判成 unknown，等于把确定性校验关掉了。
    """
    if not any(str(key).endswith("_ref") for key in rule):
        return rule
    resolved = dict(rule)
    for key in [key for key in list(resolved) if str(key).endswith("_ref")]:
        digest = resolved.pop(key)
        field = str(key)[:-4]
        if field not in _RULE_TEXT_FIELDS:
            continue
        text = pool.get(digest) if isinstance(pool, dict) else None
        if isinstance(text, str) and text.strip():
            resolved[field] = text
    return resolved


class _SourceIndex:
    def __init__(self, context):
        self.section = str(context.get("section") or "")
        self.evidence = {}
        for unit in context.get("evidence") or []:
            if isinstance(unit, dict) and isinstance(unit.get("unit_id"), int) and not isinstance(unit.get("unit_id"), bool):
                self.evidence[unit["unit_id"]] = unit
        runtime = context.get("runtime_facts")
        self.runtime = runtime if isinstance(runtime, dict) else None
        self.runtime_facts = {}
        for entry in (self.runtime or {}).get("facts") or []:
            if isinstance(entry, dict) and isinstance(entry.get("fact"), str):
                self.runtime_facts[entry["fact"]] = entry
        basis = context.get("script_basis") or {}
        pool = basis.get("condition_texts") or {}
        self.rules = {}
        for rule in basis.get("rules") or []:
            if isinstance(rule, dict) and isinstance(rule.get("rule_id"), str):
                self.rules[rule["rule_id"]] = _resolve_rule_refs(rule, pool)
        self.aliases = _column_aliases(basis.get("metadata") or [])
        self.rule_columns = set(self.aliases)
        for rule in self.rules.values():
            for side in ("source", "target"):
                node = rule.get(side)
                if isinstance(node, dict) and node.get("column_name"):
                    self.rule_columns.add(str(node["column_name"]).lower())
        self.physical_tokens = set()
        # 需求字段已固定的监管集市映射（mapping_sources）与 physical_sources 一样可用于核对溯源引用；
        # 只索引 physical_sources 会让模型引用自己字段的集市字段时被判"不在固定输入范围内"（真实事故）。
        for row in list(context.get("physical_sources") or []) + list(context.get("mapping_sources") or []):
            if not isinstance(row, dict):
                continue
            self.physical_tokens.add(f"{row.get('kind')}:{row.get('table_id')}:{row.get('field_id')}")
            self.physical_tokens.add(str(row.get("field_id")))
            if row.get("field_code"):
                code = str(row["field_code"]).lower()
                self.physical_tokens.add(code)
                self.physical_tokens.add(f"{row.get('table_code')}.{code}".lower())
        self.pins = {str(key): str(value) for key, value in (context.get("pinned_versions") or {}).items()
                     if str(value).strip()}
        chunks = []
        for rule in self.rules.values():
            for key in ("filter_condition", "join_condition", "aggregation_rule", "code_mapping_rule",
                        "transformation_expression", "transformation_type", "edge_type"):
                if rule.get(key):
                    chunks.append(str(rule[key]))
        chunks.extend(str(unit.get("content") or "") for unit in self.evidence.values())
        requirement = context.get("requirement") or {}
        if isinstance(requirement, dict):
            for key in ("effective_date", "objective", "background", "inclusion", "exclusion"):
                if requirement.get(key):
                    chunks.append(str(requirement[key]))
        chunks.extend(self.pins.values())
        self.corpus_text = " ".join(chunks).lower()
        self.corpus_dates = _extract_dates(self.corpus_text)
        effective = str((requirement or {}).get("effective_date") or "") if isinstance(requirement, dict) else ""
        if effective:
            self.corpus_dates.extend(_extract_dates(effective.lower()))

    def evidence_for(self, ref_id):
        text = str(ref_id or "").strip()
        for prefix in ("knowledge-unit:", "knowledge_unit:", "unit:", "evidence:"):
            if text.lower().startswith(prefix):
                text = text[len(prefix):]
                break
        if not text.isdigit():
            return None
        unit_id = int(text)
        return self.evidence.get(unit_id)

    def physical_matches(self, ref_id):
        text = str(ref_id or "").strip().lower()
        if not text:
            return False
        if text in self.physical_tokens:
            return True
        return False

    def runtime_fact(self, key):
        return self.runtime_facts.get(str(key or "").strip())


def _column_aliases(metadata):
    aliases = {}
    for table in metadata:
        if not isinstance(table, dict):
            continue
        for column in table.get("columns") or []:
            if not isinstance(column, dict):
                continue
            name = str(column.get("name") or "").strip()
            if not name:
                continue
            bucket = aliases.setdefault(name.lower(), set())
            bucket.add(name.lower())
            comment = str(column.get("comment") or "").strip()
            if comment:
                bucket.add(comment.lower())
    return aliases


# --------------------------------------------------------------------------- #
# 文本与事实抽取
# --------------------------------------------------------------------------- #
def _as_mapping(value):
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except TypeError:  # pragma: no cover - defensive
            return dump()
    return {}


def _excerpt(text, limit=80):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def _leaf(value):
    text = re.sub(r"\s+", "", str(value or "").strip())
    text = text.strip("`\"'[]()")
    return text.split(".")[-1].strip("`\"'[]()")


def _parse_predicates(text):
    facts = []
    for match in _COMPARE.finditer(text or ""):
        column = _leaf(match.group("column"))
        if not column or column.lower() in _SQL_RESERVED:
            continue
        facts.append({"column": column, "operator": match.group("operator").lower(),
                      "raw": match.group("value"), "values": _literal_values(match.group("value"))})
    return facts


def _literal_values(raw):
    text = str(raw or "").strip()
    if not text:
        return []
    if text.startswith("(") and text.endswith(")"):
        values = []
        for part in _split_top_level(text[1:-1]):
            values.extend(_literal_values(part))
        return values
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return [text[1:-1].replace(text[0] * 2, text[0]).strip()]
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
        return [text]
    if text.lower() in {"null", "true", "false"}:
        return [text.lower()]
    return [_leaf(text)]


def _split_top_level(text):
    parts, buffer, depth, quote = [], [], 0, None
    for char in text:
        if quote:
            buffer.append(char)
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
            buffer.append(char)
        elif char == "(":
            depth += 1
            buffer.append(char)
        elif char == ")":
            depth -= 1
            buffer.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
    if buffer:
        parts.append("".join(buffer))
    return parts


def _column_mentioned(lowered_text, column, aliases):
    names = {str(column).lower(), _leaf(column).lower()}
    names.update(aliases.get(str(column).lower(), set()))
    names.update(aliases.get(_leaf(column).lower(), set()))
    return any(name and name in lowered_text for name in names)


def _value_attested(lowered_text, predicates):
    for predicate in predicates:
        for value in predicate["values"]:
            candidate = str(value).strip().lower()
            if not candidate:
                continue
            if candidate in lowered_text:
                return True
            digits = re.sub(r"\D", "", candidate)
            if len(digits) >= 2 and digits in re.sub(r"\D", "", lowered_text):
                return True
    # 取值可能被码值化（如 status='1' 对应“正常”）；主张已明确声明筛选范围时不再判为漏过滤。
    return any(marker in lowered_text for marker in _SCOPE_MARKERS)


def _source_tokens(source_text, predicates):
    tokens = set()
    for predicate in predicates:
        for value in predicate["values"]:
            value = str(value).strip().lower()
            if value and value not in {"null", "true", "false"}:
                tokens.add(value)
    for token in _DECISIVE_TOKENS:
        if token.lower() in source_text:
            tokens.add(token.lower())
    return tokens


def _negation_conflict(claim_text, source_text, predicates):
    source_tokens = _source_tokens(source_text, predicates)
    if source_tokens:
        for marker in _NEGATION_MARKERS:
            start = claim_text.find(marker)
            while start != -1:
                window = claim_text[start:start + len(marker) + 14]
                for token in source_tokens:
                    if token and token in window:
                        return f"{marker}…{token}"
                start = claim_text.find(marker, start + 1)
    for left, right in _REVERSAL_PAIRS:
        if left in source_text and right in claim_text and left not in claim_text:
            return f"{left}→{right}"
    if any(marker in source_text for marker in _RESTRICTION_MARKERS):
        for marker in _UNIVERSAL_MARKERS:
            if marker in claim_text and marker not in source_text:
                return f"{marker}（固定事实为限定范围）"
    return None


def _decisive_tokens(text):
    tokens = [token for token in _DECISIVE_TOKENS if token in text]
    tokens.extend(_extract_dates(text))
    for value in re.findall(r"\d+(?:\.\d+)?", text):
        if len(value) >= 2:
            tokens.append(value)
    return list(dict.fromkeys(tokens))


def _claimed_functions(text):
    claimed = {match.group(1).lower() for match in re.finditer(r"\b(sum|count|avg|max|min)\b", text, re.IGNORECASE)}
    for word, function in _CN_AGGREGATIONS.items():
        if word in text:
            claimed.add(function)
    return claimed


def _group_by_dims(text):
    match = _GROUP_BY.search(text or "")
    if not match:
        return set()
    dims = set()
    for part in re.split(r",", match.group("columns")):
        leaf = _leaf(part)
        if leaf:
            dims.add(leaf.lower())
    return dims


def _claimed_dimensions(lowered, known_columns, aliases):
    claimed = set()
    for marker in _GROUPING_MARKERS:
        start = 0
        while True:
            index = lowered.find(marker, start)
            if index < 0:
                break
            window = lowered[index + len(marker):index + len(marker) + 20]
            for column in known_columns:
                if _column_mentioned(window, column, aliases):
                    claimed.add(column)
            start = index + 1
    return claimed


def _extract_dates(text):
    return [match.group(0).strip() for match in _DATE.finditer(text or "") if match.group(0).strip()]


def _digits(value):
    return re.sub(r"\D", "", str(value or ""))


def _date_attested(value, sources):
    digits = _digits(value)
    if len(digits) < 4:
        return True
    for candidate in sources.corpus_dates:
        other = _digits(candidate)
        if not other:
            continue
        if other.startswith(digits) or digits.startswith(other):
            return True
    return False


def _check_evidence_version(unit, support, sources, issues, ref_id):
    if unit is None:
        return
    title = str(unit.get("title") or "").strip()
    actual = str(unit.get("regulatory_version") or "").strip()
    declared = str(support.get("ref_version") or "").strip()
    pinned = sources.pins.get(title) if title else None
    if pinned is not None:
        if not actual:
            issues.conflict("pinned_version_missing",
                            f"证据《{title}》被钉扎为 {pinned}，但该证据没有可核验的监管版本", [ref_id])
        elif _normalise_version(actual) != _normalise_version(pinned):
            issues.conflict("pinned_version_mismatch",
                            f"证据《{title}》的实际版本 {actual} 与冻结钉扎版本 {pinned} 不一致", [ref_id])
    if declared:
        if not actual:
            issues.conflict("evidence_version_missing",
                            f"主张声明证据版本 {declared}，但该证据没有可核验的监管版本", [ref_id])
        elif _normalise_version(declared) != _normalise_version(actual):
            issues.conflict("evidence_version_mismatch",
                            f"主张声明证据版本 {declared}，与证据实际版本 {actual} 不一致", [ref_id])


def _normalise_version(value):
    return re.sub(r"\s+", "", str(value or "")).lower()
