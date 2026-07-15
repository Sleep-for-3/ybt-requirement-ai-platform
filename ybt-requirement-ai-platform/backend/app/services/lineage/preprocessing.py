from __future__ import annotations

import re
from dataclasses import dataclass


_VARIABLE_PATTERN = re.compile(
    r"(?P<expression>\#\{(?P<hash>[A-Za-z_][\w]*)\}"
    r"|\$\{(?P<brace>[A-Za-z_][\w]*)\}"
    r"|&(?P<amp>[A-Za-z_][\w]*)"
    r"|:(?P<colon>[A-Za-z_][\w]*)"
    r"|\$(?P<position>\d+))"
)


@dataclass(frozen=True)
class TemplateVariableOccurrence:
    expression: str
    variable_name: str
    variable_type: str
    start: int
    end: int
    resolved: bool


@dataclass(frozen=True)
class PreprocessedSql:
    original_sql: str
    normalized_sql: str
    parse_sql: str
    variables: tuple[TemplateVariableOccurrence, ...]
    warnings: tuple[str, ...]


def preprocess_sql(sql: str, variables: dict[str, str] | None = None) -> PreprocessedSql:
    """Prepare templated SQL for parsing without losing source expressions.

    Unknown identifiers use deliberately synthetic values.  They remain in
    ``normalized_sql`` and produce warnings; only ``parse_sql`` receives the
    safe replacements required by sqlglot.
    """

    configured = {key.upper(): value for key, value in (variables or {}).items()}
    occurrences: list[TemplateVariableOccurrence] = []
    warnings: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = next(value for value in match.groupdict().values() if value and value != match.group("expression"))
        expression = match.group("expression")
        variable_type = "positional" if match.group("position") else "identifier_or_value"
        configured_value = configured.get(name.upper())
        resolved = configured_value is not None
        occurrences.append(TemplateVariableOccurrence(expression, name, variable_type, match.start(), match.end(), resolved))
        if not resolved:
            warnings.append(f"Unknown template variable preserved: {expression}")
        if configured_value is not None:
            return _safe_test_value(configured_value)
        if match.group("colon") or match.group("position"):
            # Bind variables are accepted by most dialect parsers and are not
            # identifiers, so retaining them gives better evidence.
            return expression
        return f"SAFE_{re.sub(r'[^A-Za-z0-9_]', '_', name).upper()}"

    parse_sql = _VARIABLE_PATTERN.sub(replace, sql)
    normalized_sql = re.sub(r"[ \t]+", " ", sql).strip()
    return PreprocessedSql(
        original_sql=sql,
        normalized_sql=normalized_sql,
        parse_sql=parse_sql,
        variables=tuple(occurrences),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _safe_test_value(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value).strip("_")
    return cleaned or "SAFE_VALUE"
