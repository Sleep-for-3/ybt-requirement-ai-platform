"""P2-A 脱敏运行事实包：把"跑批实际结果"接进需求，但不把推断当事实。

设计边界（与需求说明书一致）：

1. 平台**不执行**客户跑批；只接收在授权环境里产生的脱敏事实包（JSON）。
2. 事实包进入需求时，必须区分三种证据强度：
   ``static_inference``（只有脚本静态解析）< ``sampled_validation``（抽样/样例统计）
   < ``full_run_validation``（有执行批次、业务日期、来源与文件 hash，并且给出
   键唯一率与 join 前后行数等对账数字）。
3. 强度只能由证据**降级**决定，不能被调用方抬高：缺执行批次或业务日期就永远
   不能标"运行已验证"。
4. 校验失败只产出问题清单与降级，不抛异常吞数据；调用方把问题写进需求缺口与
   生成输入 limitations，让审核人看到"这条结论来自静态推断"。

本模块不读数据库、不发网络请求，纯函数，便于在隔离测试里复现。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping

FACT_PACK_VERSION = "runtime-fact-v1"
VALIDATION_VERSION = "runtime-fact-validation-v1"

LEVEL_STATIC = "static_inference"
LEVEL_SAMPLED = "sampled_validation"
LEVEL_FULL = "full_run_validation"
LEVELS = (LEVEL_STATIC, LEVEL_SAMPLED, LEVEL_FULL)

STATUS_VERIFIED = "verified"
STATUS_UNVERIFIED = "unverified"
STATUS_PARTIAL = "partially_verified"

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_BUSINESS_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: 每类事实能支撑的最强结论。运行级额度统计不能由静态推断得出。
FACT_REQUIRED_LEVEL: dict[str, str] = {
    "key_uniqueness": LEVEL_FULL,
    "null_rate": LEVEL_FULL,
    "join_row_count": LEVEL_FULL,
    "group_reconciliation": LEVEL_FULL,
    "business_date": LEVEL_FULL,
    "script_hash": LEVEL_SAMPLED,
    "parameters": LEVEL_SAMPLED,
    "metadata_version": LEVEL_SAMPLED,
}

_LABELS = {
    "source.file_sha256": "事实包来源文件 hash",
    "run.execution_batch": "执行批次",
    "run.business_date": "业务日期",
    "quality.key_uniqueness": "键唯一率",
    "quality.join_counts": "join 前后行数对账",
}


@dataclass(frozen=True)
class FactIssue:
    code: str
    message: str
    severity: str = "warning"
    field: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "field": self.field,
        }


@dataclass(frozen=True)
class FactPackValidation:
    level: str
    status: str
    pack_version: str
    execution_batch: str | None
    business_date: str | None
    issues: tuple[FactIssue, ...] = ()
    missing: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    fact_statuses: Mapping[str, str] = field(default_factory=dict)
    pack_sha256: str = ""
    validation_version: str = VALIDATION_VERSION

    @property
    def verified(self) -> bool:
        return self.status == STATUS_VERIFIED

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "status": self.status,
            "pack_version": self.pack_version,
            "execution_batch": self.execution_batch,
            "business_date": self.business_date,
            "issues": [issue.as_dict() for issue in self.issues],
            "missing": list(self.missing),
            "limitations": list(self.limitations),
            "fact_statuses": dict(self.fact_statuses),
            "pack_sha256": self.pack_sha256,
            "validation_version": self.validation_version,
        }


def pack_sha256(pack: Mapping[str, Any]) -> str:
    """事实包内容 hash：用于绑定"这份需求引用的是哪一版运行事实"。"""

    material = json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _nested(pack: Mapping[str, Any], *path: str) -> Any:
    current: Any = pack
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _valid_business_date(value: Any) -> bool:
    if not isinstance(value, str) or not _BUSINESS_DATE_PATTERN.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _collect_issues(pack: Mapping[str, Any]) -> list[FactIssue]:
    issues: list[FactIssue] = []

    if not isinstance(pack, Mapping):
        return [FactIssue("not_a_mapping", "事实包必须是 JSON 对象", "error", "")]

    version = pack.get("pack_version")
    if version != FACT_PACK_VERSION:
        issues.append(
            FactIssue(
                "pack_version_unknown",
                f"事实包版本 {version!r} 不是当前支持的 {FACT_PACK_VERSION}，不做自动兼容",
                "error",
                "pack_version",
            )
        )

    file_sha256 = _nested(pack, "source", "file_sha256")
    if file_sha256 is None:
        pass
    elif not isinstance(file_sha256, str) or not _SHA256_PATTERN.match(file_sha256):
        issues.append(
            FactIssue("file_sha256_invalid", "来源文件 hash 必须是 64 位十六进制", "error", "source.file_sha256")
        )

    exported_at = _nested(pack, "source", "exported_at")
    if exported_at is not None and not isinstance(exported_at, str):
        issues.append(
            FactIssue("exported_at_invalid", "导出时间必须是 ISO8601 字符串", "warning", "source.exported_at")
        )

    business_date = _nested(pack, "run", "business_date")
    if business_date is not None and not _valid_business_date(business_date):
        issues.append(
            FactIssue("business_date_invalid", "业务日期必须是 YYYY-MM-DD 的合法日期", "error", "run.business_date")
        )

    execution_batch = _nested(pack, "run", "execution_batch")
    if execution_batch is not None and (
        not isinstance(execution_batch, str) or not execution_batch.strip()
    ):
        issues.append(
            FactIssue("execution_batch_invalid", "执行批次必须是非空字符串", "error", "run.execution_batch")
        )

    uniqueness = _nested(pack, "quality", "key_uniqueness")
    if uniqueness is not None:
        if not isinstance(uniqueness, list) or not uniqueness:
            issues.append(
                FactIssue("key_uniqueness_invalid", "键唯一率必须是非空列表", "error", "quality.key_uniqueness")
            )
        else:
            for index, item in enumerate(uniqueness):
                if not isinstance(item, Mapping):
                    issues.append(
                        FactIssue(
                            "key_uniqueness_item_invalid",
                            f"第 {index} 项键唯一率不是对象",
                            "error",
                            "quality.key_uniqueness",
                        )
                    )
                    continue
                keys = item.get("keys")
                rate = item.get("unique_rate")
                if not isinstance(keys, list) or not keys or not all(isinstance(key, str) and key for key in keys):
                    issues.append(
                        FactIssue(
                            "key_uniqueness_keys_invalid",
                            f"第 {index} 项缺少复合键列表",
                            "error",
                            "quality.key_uniqueness",
                        )
                    )
                if not _is_number(rate) or not 0 <= float(rate) <= 1:
                    issues.append(
                        FactIssue(
                            "key_uniqueness_rate_invalid",
                            f"第 {index} 项唯一率必须在 0 与 1 之间",
                            "error",
                            "quality.key_uniqueness",
                        )
                    )

    join_counts = _nested(pack, "quality", "join_counts")
    if join_counts is not None:
        if not isinstance(join_counts, list) or not join_counts:
            issues.append(
                FactIssue("join_counts_invalid", "join 行数对账必须是非空列表", "error", "quality.join_counts")
            )
        else:
            for index, item in enumerate(join_counts):
                if not isinstance(item, Mapping):
                    issues.append(
                        FactIssue(
                            "join_counts_item_invalid",
                            f"第 {index} 项 join 对账不是对象",
                            "error",
                            "quality.join_counts",
                        )
                    )
                    continue
                for name in ("left_rows", "right_rows", "matched_rows"):
                    value = item.get(name)
                    if not _is_number(value) or value < 0:
                        issues.append(
                            FactIssue(
                                "join_counts_number_invalid",
                                f"第 {index} 项的 {name} 必须是非负数",
                                "error",
                                "quality.join_counts",
                            )
                        )
                matched = item.get("matched_rows")
                left = item.get("left_rows")
                if _is_number(matched) and _is_number(left) and matched > left:
                    issues.append(
                        FactIssue(
                            "join_counts_matched_exceeds_left",
                            f"第 {index} 项匹配行数大于左表行数，说明统计口径不一致",
                            "error",
                            "quality.join_counts",
                        )
                    )

    null_rates = _nested(pack, "quality", "null_rates")
    if null_rates is not None:
        if not isinstance(null_rates, Mapping):
            issues.append(FactIssue("null_rates_invalid", "空值率必须是对象", "error", "quality.null_rates"))
        else:
            for name, value in null_rates.items():
                if not _is_number(value) or not 0 <= float(value) <= 1:
                    issues.append(
                        FactIssue(
                            "null_rate_invalid",
                            f"{name} 的空值率必须在 0 与 1 之间",
                            "error",
                            "quality.null_rates",
                        )
                    )

    return issues


def _required_missing(pack: Mapping[str, Any]) -> list[str]:
    """运行级验证必须具备的事实；缺任何一项都不能标"运行已验证"。"""

    missing: list[str] = []
    if not _SHA256_PATTERN.match(str(_nested(pack, "source", "file_sha256") or "")):
        missing.append("source.file_sha256")
    if not isinstance(_nested(pack, "run", "execution_batch"), str) or not str(
        _nested(pack, "run", "execution_batch")
    ).strip():
        missing.append("run.execution_batch")
    if not _valid_business_date(_nested(pack, "run", "business_date")):
        missing.append("run.business_date")
    uniqueness = _nested(pack, "quality", "key_uniqueness")
    if not isinstance(uniqueness, list) or not uniqueness:
        missing.append("quality.key_uniqueness")
    join_counts = _nested(pack, "quality", "join_counts")
    if not isinstance(join_counts, list) or not join_counts:
        missing.append("quality.join_counts")
    return missing


def _sampled_signals(pack: Mapping[str, Any]) -> list[str]:
    signals: list[str] = []
    if _SHA256_PATTERN.match(str(_nested(pack, "source", "file_sha256") or "")):
        signals.append("source")
    if isinstance(_nested(pack, "script", "version_id"), (int, str)):
        signals.append("script_version")
    if _is_number(_nested(pack, "quality", "sampled_rows")):
        signals.append("sampled_rows")
    if isinstance(_nested(pack, "quality", "null_rates"), Mapping):
        signals.append("null_rates")
    return signals


def validate_fact_pack(pack: Mapping[str, Any]) -> FactPackValidation:
    """校验事实包并给出**不许抬高**的验证强度。"""

    issues = _collect_issues(pack)
    errors = [issue for issue in issues if issue.severity == "error"]
    missing = _required_missing(pack) if isinstance(pack, Mapping) else []
    sampled = _sampled_signals(pack) if isinstance(pack, Mapping) else []

    if errors:
        level = LEVEL_STATIC
        status = STATUS_UNVERIFIED
    elif not missing:
        level = LEVEL_FULL
        status = STATUS_VERIFIED
    elif sampled:
        level = LEVEL_SAMPLED
        status = STATUS_PARTIAL
    else:
        level = LEVEL_STATIC
        status = STATUS_UNVERIFIED

    limitations: list[str] = []
    if level != LEVEL_FULL:
        limitations.append(
            "运行事实未达到全量运行验证："
            + "、".join(_LABELS[name] for name in missing)
            + "。相关结论只能按静态推断或抽样验证表述，不得称为已由运行数据验证。"
        )
    for issue in errors:
        limitations.append(f"运行事实包存在错误（{issue.code}）：{issue.message}")

    fact_statuses: dict[str, str] = {}
    for name, required in FACT_REQUIRED_LEVEL.items():
        order = LEVELS.index(level)
        fact_statuses[name] = STATUS_VERIFIED if order >= LEVELS.index(required) else STATUS_UNVERIFIED

    return FactPackValidation(
        level=level,
        status=status,
        pack_version=str(pack.get("pack_version")) if isinstance(pack, Mapping) else "",
        execution_batch=(_nested(pack, "run", "execution_batch") if isinstance(pack, Mapping) else None),
        business_date=(_nested(pack, "run", "business_date") if isinstance(pack, Mapping) else None),
        issues=tuple(issues),
        missing=tuple(missing),
        limitations=tuple(limitations),
        fact_statuses=fact_statuses,
        pack_sha256=pack_sha256(pack) if isinstance(pack, Mapping) else "",
    )


def claim_allowed(validation: FactPackValidation, fact: str) -> str:
    """返回某类事实当前可以使用的表述强度；未知事实按最保守处理。"""

    required = FACT_REQUIRED_LEVEL.get(fact)
    if required is None:
        return LEVEL_STATIC
    current = LEVELS.index(validation.level)
    if current >= LEVELS.index(required):
        return validation.level
    return LEVEL_STATIC


def fact_pack_gaps(validation: FactPackValidation) -> list[dict[str, Any]]:
    """把未达标的运行事实转成需求缺口（与既有 gap 结构一致）。"""

    if validation.verified:
        return []
    return [
        {
            "id": "runtime_fact:unverified",
            "origin": "runtime_fact",
            "status": "open",
            "message": (
                f"运行事实强度为 {validation.level}（{validation.status}），"
                "键唯一率、空值率、join 行数对账等结论需补全执行批次、业务日期与来源文件 hash 后才能作为运行已验证引用。"
            ),
            "missing": list(validation.missing),
            "pack_sha256": validation.pack_sha256,
        }
    ]
