"""Identifier and code-value extraction with CJK-safe boundaries."""
import re

FIELD_CODE_RE = re.compile(r"(?<![0-9A-Za-z_])[A-Z]\d{6}(?![0-9A-Za-z_])", re.I)
SQL_IDENTIFIER_RE = re.compile(r"(?<![0-9A-Za-z_])[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+(?![0-9A-Za-z_])")
_VALUE_RE = re.compile(r"(?<![0-9A-Za-z_])\d{2}(?![0-9A-Za-z_])")
_NON_CODE_RE = re.compile(
    r"(?<![0-9A-Za-z_])[A-Za-z][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)+(?![0-9A-Za-z_])"
    r"|\d{4}[-/.年]\d{1,2}(?:[-/.月]\d{1,2}日?)?"
    r"(?:[T \t]+\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
    r"|(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?!\d)"
    r"|\d+\.\d+(?:\.\d+)*|\[[0-9]+\]|【[0-9]+】"
)
_CONTEXT_RE = re.compile(r"码值|填报|填写|填|取值|应为|可选|值域|只能|允许")
_NEGATIVE_RE = re.compile(r"不得|不能|禁止|不允许|不可|不应|不是|不填|无需填")


def extract_field_codes(text: str) -> set[str]:
    return {value.upper() for value in FIELD_CODE_RE.findall(text or "")}


def extract_sql_identifiers(text: str) -> set[str]:
    """Extract explicitly written uppercase SQL table/column identifiers."""
    return set(SQL_IDENTIFIER_RE.findall(text or ""))


def extract_code_values(text: str, *, affirmative_only: bool = False,
                        require_context: bool = False, prohibited_only: bool = False) -> set[str]:
    text = _NON_CODE_RE.sub(" ", str(text or ""))
    text = re.sub(r"(?<=\d)[;；](?=\d)", ",", text)
    values = set()
    for clause in re.split(r"[。；;\n!?！？]", text):
        if require_context and not _CONTEXT_RE.search(clause):
            continue
        inherited_negative = False
        for match in _VALUE_RE.finditer(clause):
            prefix = re.split(r"[，,]", clause[:match.start()])[-1]
            if re.search(r"(?:表|第)\s*$", prefix):
                continue
            # A new explicit positive instruction ends an earlier negation.
            negative = list(_NEGATIVE_RE.finditer(prefix))
            is_negative = inherited_negative if not _CONTEXT_RE.search(prefix) else False
            if negative:
                tail = prefix[negative[-1].end():]
                is_negative = not bool(re.search(r"(?:而应|应当|只能|仅允许|可以|应填|应为)", tail))
            inherited_negative = is_negative
            if (affirmative_only and is_negative) or (prohibited_only and not is_negative):
                continue
            suffix = clause[match.end():]
            if re.match(r"\s*(?:年|月|日|岁|元|万元|亿元|%|％)", suffix):
                continue
            values.add(match.group())
    return values
