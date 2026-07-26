import re

HIGHLY_SENSITIVE = {"密码","密钥","password","secret","身份证号","证件号","id_no","cert_no","账号","卡号","account_no","card_no"}
SENSITIVE = {"客户姓名","姓名","手机号","电话号码","地址","customer_name","cust_name","mobile","phone","address"}

SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\d)\d{17}[\dXx](?!\w)"),
    re.compile(r"(?<!\d)\d{12,19}(?!\d)"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
)

def classify_column_sensitivity(name: str, comment: str | None = None) -> str:
    text = re.sub(r"[\s_]+", "", f"{name} {comment or ''}".lower())
    if any(re.sub(r"[\s_]+", "", item.lower()) in text for item in HIGHLY_SENSITIVE): return "highly_sensitive"
    if any(re.sub(r"[\s_]+", "", item.lower()) in text for item in SENSITIVE): return "sensitive"
    return "normal" if text else "unknown"


def looks_sensitive_value(value: object) -> bool:
    if value is None or isinstance(value, (bool, float)):
        return False
    text = str(value).strip()
    return bool(text) and any(pattern.search(text) for pattern in SENSITIVE_VALUE_PATTERNS)


def sanitize_profile_result(result: dict, sensitivity: str) -> tuple[dict, list[str]]:
    """Apply a final value-aware filter before profile data is persisted or returned."""
    sanitized = dict(result)
    warnings: list[str] = []
    if sensitivity in {"sensitive", "highly_sensitive"} and sanitized.pop("top_values", None) is not None:
        warnings.append("敏感字段的 top values 已在结果过滤阶段移除")
    if sensitivity in {"sensitive", "highly_sensitive"}:
        removed_range = sanitized.pop("min_value", None) is not None
        removed_range = sanitized.pop("max_value", None) is not None or removed_range
        if removed_range:
            warnings.append("敏感字段的 min/max 原值已在结果过滤阶段移除")
    top_values = sanitized.get("top_values")
    if top_values and any(looks_sensitive_value(row.get("value")) for row in top_values if isinstance(row, dict)):
        sanitized.pop("top_values", None)
        warnings.append("top values 包含疑似敏感值，已全部移除")
    for key in ("min_value", "max_value"):
        if looks_sensitive_value(sanitized.get(key)):
            sanitized.pop(key, None)
            warnings.append(f"{key} 包含疑似敏感值，已移除")
    return sanitized, warnings
