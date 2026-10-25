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


def strip_hash_comments(sql: str) -> str:
    """Normalize GBase/4A ``#`` line comments into ``--`` comments.

    GBase batch scripts use ``#`` for comments (``####`` banners, ``# 说明：…``)
    and ``#{VAR}`` for templated placeholders.  sqlglot's generic grammar and
    some dialect tokenizers either reject ``#`` outright or crash on a
    ``#`` comment that reaches end of input, which used to drop the whole
    statement.  Converting the comment marker keeps the statement text (and all
    line numbers) intact without inventing lineage.

    ``#{…}`` placeholders are *not* comments and are left for the variable
    substitution step.
    """

    out: list[str] = []
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        if char in ("'", '"'):
            quote = char
            out.append(char)
            index += 1
            while index < length:
                current = sql[index]
                out.append(current)
                if current == "\\" and index + 1 < length:
                    out.append(sql[index + 1])
                    index += 2
                    continue
                if current == quote:
                    if index + 1 < length and sql[index + 1] == quote:
                        out.append(sql[index + 1])
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char == "#" and not sql.startswith("#{", index):
            while index < length and sql[index] != "\n":
                index += 1
            out.append("--")
            continue
        out.append(char)
        index += 1
    return "".join(out)


def truncate_unterminated_block_comment(sql: str) -> tuple[str, str | None]:
    """Cut the script at an unterminated ``/*`` block comment.

    Some GBase batch scripts are switched off by commenting out everything after
    a banner and never closing it (``YBT_T_3_5.sql`` starts one at line 17 with
    no ``*/`` anywhere in the file).  Feeding the rest of such a file to a parser
    yields ``Error tokenizing`` / ``Statement path parse failed``, which looks
    like a parser defect and hides the real reason: the script is disabled.

    Truncating at the comment keeps the statements before it parseable and
    returns an explicit warning so the requirement pipeline can say "this table
    is not reported" instead of inventing a target.  Quoted literals, ``--`` and
    ``#`` line comments are skipped so their content is never mistaken for a
    block comment.
    """

    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        if char in ("'", '"'):
            quote = char
            index += 1
            while index < length:
                if sql[index] == "\\" and index + 1 < length:
                    index += 2
                    continue
                if sql[index] == quote:
                    if index + 1 < length and sql[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if sql.startswith("--", index) or (char == "#" and not sql.startswith("#{", index)):
            while index < length and sql[index] != "\n":
                index += 1
            continue
        if sql.startswith("/*", index):
            close = sql.find("*/", index + 2)
            if close == -1:
                line_no = sql.count("\n", 0, index) + 1
                warning = (
                    f"未闭合的块注释：第 {line_no} 行起的 SQL 被视为注释（脚本可能被人工屏蔽），"
                    "其后的语句不参与解析"
                )
                return sql[:index], warning
            index = close + 2
            continue
        index += 1
    return sql, None


def preprocess_sql(sql: str, variables: dict[str, str] | None = None) -> PreprocessedSql:
    """Prepare templated SQL for parsing without losing source expressions.

    Unknown identifiers use deliberately synthetic values.  They remain in
    ``normalized_sql`` and produce warnings; only ``parse_sql`` receives the
    safe replacements required by sqlglot.
    """

    configured = {key.upper(): value for key, value in (variables or {}).items()}
    occurrences: list[TemplateVariableOccurrence] = []
    warnings: list[str] = []
    visible_sql, block_warning = truncate_unterminated_block_comment(sql)
    if block_warning:
        warnings.append(block_warning)

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

    parse_sql = _VARIABLE_PATTERN.sub(replace, strip_hash_comments(visible_sql))
    if not parse_sql.endswith("\n"):
        # sqlglot raises IndexError when a ``--`` comment reaches end of input.
        parse_sql += "\n"
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
