"""多目标需求生成的用量与费用对账（P1-C）。

设计原则（与治理边界一致）：

1. **不猜 token**：只使用 provider 回报的 `prompt_tokens`/`completion_tokens`。
   provider 没回报时标 `unavailable`；最多给出显式标注的 `estimated`
   （CJK 按字符、ASCII 按 4 字符估算），并且绝不与 provider 数值混算成一个数。
2. **不猜价格**：价格表由调用方显式传入（版本化）。没有价格就返回 `cost=None`
   且预算状态为 `unknown`，绝不把费用当 0 计入"未超预算"。
3. **可对账**：每个 item、每次尝试的用量都逐条保留（`attempts`），汇总值由明细
   重新计算得出，重放同一批明细得到同一结果（幂等，不重复计费）。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

LEDGER_VERSION = "requirement-generation-ledger-v1"
PRICING_VERSION = "requirement-generation-pricing-v1"
ESTIMATE_METHOD = "cjk-aware-char-estimate-v1"

USAGE_SOURCES = ("provider_reported", "estimated", "unavailable")
BUDGET_STATUSES = ("within", "exceeded", "unknown")

MICRO = Decimal("0.000001")


def estimate_tokens(text: str) -> int:
    """保守估算 token 数：CJK 1 字符 ≈ 1 token，ASCII 4 字符 ≈ 1 token。

    这是**估算**，返回值只能与 `source="estimated"` 一起使用；不得写入
    provider token 字段，也不得用"向量维度"或"字符数"冒充 token。
    """

    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f")
    ascii_count = sum(1 for ch in text if ch.isascii() and not ch.isspace())
    other = len(text) - cjk - ascii_count
    return int(cjk + other + (ascii_count + 3) // 4)


def normalize_usage(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """把 provider 用量规整成可审计结构，并标出数据来源。

    接受两种形态：provider 原始用量（`usage_available`/`prompt_tokens`/
    `completion_tokens`）与本模块已规整的结构（`source`/`input_tokens`/
    `output_tokens`）。函数是幂等的：`normalize(normalize(x)) == normalize(x)`，
    这样明细落库后再汇总不会把 token 数弄丢。
    """

    raw = dict(raw or {})
    input_tokens = _int_or_none(raw.get("prompt_tokens"))
    if input_tokens is None:
        input_tokens = _int_or_none(raw.get("input_tokens"))
    output_tokens = _int_or_none(raw.get("completion_tokens"))
    if output_tokens is None:
        output_tokens = _int_or_none(raw.get("output_tokens"))
    total_tokens = _int_or_none(raw.get("total_tokens"))
    declared_available = bool(raw.get("usage_available")) or raw.get("available") is True
    observed = input_tokens is not None or output_tokens is not None or total_tokens is not None
    available = declared_available or observed
    source = raw.get("source") if raw.get("source") in USAGE_SOURCES else None
    if source is None:
        source = "provider_reported" if available else "unavailable"
    if available and source == "unavailable":
        # 明明有用量却标 unavailable，属于账目矛盾；按 provider 可用处理，避免丢账。
        source = "provider_reported"
    if source == "provider_reported" and not available:
        # 标了 provider 来源却没有任何数字：如实降级为不可用，不伪造 0。
        source = "unavailable"
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    if source != "provider_reported":
        # 非 provider 来源不保留"看起来像 provider 数字"的字段，避免误读。
        if source == "unavailable":
            input_tokens = None
            output_tokens = None
            total_tokens = None
    return {
        "source": source,
        "available": source == "provider_reported",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": _int_or_none(raw.get("cached_tokens")),
        "estimate_method": raw.get("estimate_method") if source == "estimated" else None,
    }


def estimated_usage(prompt: str, output: Any) -> dict[str, Any]:
    """provider 未回报用量时的显式估算；结果标 `estimated`，不计入 provider 账单口径。"""

    output_text = output if isinstance(output, str) else _json_text(output)
    return {
        "source": "estimated",
        "available": False,
        "estimate_method": ESTIMATE_METHOD,
        "input_tokens": estimate_tokens(prompt),
        "output_tokens": estimate_tokens(output_text),
        "total_tokens": estimate_tokens(prompt) + estimate_tokens(output_text),
        "cached_tokens": None,
    }


def _json_text(value: Any) -> str:
    import json

    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:  # pragma: no cover - defensive
        return str(value)


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def price_for(model: str | None, prices: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """从显式价格表取单价；缺价格返回 None（不是 0）。"""

    if not prices or not model:
        return None
    entry = prices.get(model) or prices.get(str(model).lower())
    if not isinstance(entry, Mapping):
        return None
    try:
        input_price = Decimal(str(entry["input_per_million"]))
        output_price = Decimal(str(entry["output_per_million"]))
    except (KeyError, InvalidOperation, TypeError, ValueError):
        return None
    if input_price < 0 or output_price < 0:
        return None
    return {
        "input_per_million": input_price,
        "output_per_million": output_price,
        "currency": str(entry.get("currency") or "CNY"),
        "pricing_version": str(entry.get("pricing_version") or PRICING_VERSION),
    }


def cost_for(
    usage: Mapping[str, Any], model: str | None, prices: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    """按显式单价计算费用；用量不可用或价格缺失时返回 None。"""

    normalized = normalize_usage(usage)
    if normalized["source"] != "provider_reported":
        return None
    price = price_for(model, prices)
    if price is None:
        return None
    input_tokens = normalized["input_tokens"] or 0
    output_tokens = normalized["output_tokens"] or 0
    amount = (
        Decimal(input_tokens) * price["input_per_million"]
        + Decimal(output_tokens) * price["output_per_million"]
    ) / Decimal(1_000_000)
    return {
        "amount": amount.quantize(MICRO),
        "currency": price["currency"],
        "pricing_version": price["pricing_version"],
    }


def attempt_record(
    *,
    attempt: int,
    execution_metadata: Mapping[str, Any] | None,
    failed: bool = False,
    error_type: str | None = None,
) -> dict[str, Any]:
    """把一次模型调用的用量、时延、重试与版本信息压成一条可审计尝试记录。"""

    metadata = dict(execution_metadata or {})
    usage = normalize_usage(metadata.get("token_usage"))
    return {
        "attempt": attempt,
        "failed": bool(failed),
        "error_type": error_type,
        "execution_kind": metadata.get("execution_kind"),
        "provider": metadata.get("provider_type") or metadata.get("provider"),
        "model": metadata.get("model_name"),
        "prompt_key": metadata.get("prompt_key"),
        "prompt_version": metadata.get("prompt_version"),
        "latency_ms": _int_or_none(metadata.get("latency_ms")),
        "retry_count": _int_or_none(metadata.get("retry_count")) or 0,
        "usage": usage,
        "context_budget": metadata.get("context_budget"),
    }


def summarize_ledger(
    items: Iterable[Mapping[str, Any]],
    *,
    prices: Mapping[str, Any] | None = None,
    budget: Any = None,
    currency: str = "CNY",
) -> dict[str, Any]:
    """汇总一次生成输入的用量与费用。

    `items` 每项至少含 `field_id`、`section`、`status`、`usage`（形如
    `{"attempts": [...]}`）。函数是纯函数：同输入必得同输出，不存在"第二次
    汇总又计一次费"的问题。
    """

    detail: list[dict[str, Any]] = []
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "provider_reported_items": 0,
        "estimated_items": 0,
        "unavailable_items": 0,
        "cost_amount": Decimal("0"),
        "priced_items": 0,
        "unpriced_items": 0,
        "attempts": 0,
        "retries": 0,
        "failed_attempts": 0,
        "execution_ms": 0,
    }
    currencies: set[str] = set()
    pricing_versions: set[str] = set()

    for item in items:
        usage_block = dict(item.get("usage") or {})
        attempts = list(usage_block.get("attempts") or [])
        item_cost = Decimal("0")
        item_priced = 0
        item_sources: set[str] = set()
        for attempt in attempts:
            normalized = normalize_usage(attempt.get("usage"))
            totals["attempts"] += 1
            totals["retries"] += int(attempt.get("retry_count") or 0)
            if attempt.get("failed"):
                totals["failed_attempts"] += 1
            latency = _int_or_none(attempt.get("latency_ms"))
            if latency:
                totals["execution_ms"] += latency
            if normalized["source"] == "provider_reported":
                totals["input_tokens"] += normalized["input_tokens"] or 0
                totals["output_tokens"] += normalized["output_tokens"] or 0
            item_sources.add(normalized["source"])
            cost = cost_for(normalized, attempt.get("model"), prices)
            if cost is None:
                totals["unpriced_items"] += 1
            else:
                item_cost += cost["amount"]
                item_priced += 1
                currencies.add(cost["currency"])
                pricing_versions.add(cost["pricing_version"])
        totals["cost_amount"] += item_cost
        totals["priced_items"] += item_priced
        if "provider_reported" in item_sources:
            totals["provider_reported_items"] += 1
        elif "estimated" in item_sources:
            totals["estimated_items"] += 1
        else:
            totals["unavailable_items"] += 1
        detail.append({
            "field_id": item.get("field_id"),
            "section": item.get("section"),
            "status": item.get("status"),
            "attempt_count": len(attempts),
            "sources": sorted(item_sources),
            "cost_amount": str(item_cost) if item_priced else None,
        })

    cost_is_complete = totals["unpriced_items"] == 0 and totals["attempts"] > 0
    total_cost = totals["cost_amount"] if cost_is_complete else None
    status = _budget_status(total_cost if total_cost is not None else totals["cost_amount"],
                            cost_is_complete, budget)
    return {
        "ledger_version": LEDGER_VERSION,
        "pricing_version": sorted(pricing_versions)[0] if pricing_versions else PRICING_VERSION,
        "currency": sorted(currencies)[0] if currencies else currency,
        "item_count": len(detail),
        "attempt_count": totals["attempts"],
        "failed_attempt_count": totals["failed_attempts"],
        "retry_count": totals["retries"],
        "input_tokens": totals["input_tokens"],
        "output_tokens": totals["output_tokens"],
        "execution_ms": totals["execution_ms"],
        "usage_sources": {
            "provider_reported": totals["provider_reported_items"],
            "estimated": totals["estimated_items"],
            "unavailable": totals["unavailable_items"],
        },
        "cost": None if total_cost is None else {
            "amount": str(total_cost),
            "currency": sorted(currencies)[0] if currencies else currency,
            "pricing_version": sorted(pricing_versions)[0] if pricing_versions else PRICING_VERSION,
            "complete": True,
        },
        "partial_cost_amount": None if cost_is_complete else str(totals["cost_amount"]),
        "budget": status,
        "items": detail,
    }


def _budget_status(spent: Decimal, complete: bool, budget: Any) -> dict[str, Any]:
    limit = _decimal_or_none(budget)
    if limit is None:
        return {"limit": None, "spent": None if not complete else str(spent), "status": "unknown",
                "reason": "未配置本次生成的费用预算（budget=None），无法判定是否超预算"}
    if not complete:
        return {"limit": str(limit), "spent": None, "status": "unknown",
                "reason": "存在未计价或用量不可用的条目，费用不完整，不能判定未超预算"}
    return {"limit": str(limit), "spent": str(spent), "status": "exceeded" if spent > limit else "within"}


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def item_usage_payload(
    attempts: list[dict[str, Any]], *, final_status: str, self_correction_attempts: int = 0,
    detail: str | None = None,
) -> dict[str, Any]:
    """组装写入 `RequirementGenerationItem.usage_json` 的载荷。

    `detail` 记录"为什么被阻断/失败"的首条原因：它不进 token 账，但决定用户能不能
    在没有日志的情况下判断该重试还是改需求。脱敏由调用方负责（只放校验结论）。
    """

    payload = {
        "schema_version": LEDGER_VERSION,
        "final_status": final_status,
        "self_correction_attempts": int(self_correction_attempts or 0),
        "attempts": list(attempts),
    }
    if detail:
        payload["detail"] = str(detail)[:500]
    return payload
