from __future__ import annotations

import hashlib
import re
from bisect import bisect_left
from dataclasses import dataclass, field, replace

import sqlglot
from sqlglot import exp
from sqlglot.lineage import lineage as trace_column_lineage
from sqlglot.tokens import TokenType

from app.services.lineage.preprocessing import preprocess_sql
from app.services.lineage.dialects import resolve_dialect


@dataclass(frozen=True)
class LineageNodeSpec:
    node_type: str
    logical_name: str
    database_name: str | None = None
    schema_name: str | None = None
    table_name: str | None = None
    column_name: str | None = None
    temporary_flag: bool = False
    unresolved_flag: bool = True
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LineageEdgeSpec:
    source: LineageNodeSpec
    target: LineageNodeSpec
    edge_type: str
    transformation_type: str | None = None
    transformation_expression: str | None = None
    join_condition: str | None = None
    filter_condition: str | None = None
    aggregation_rule: str | None = None
    code_mapping_rule: str | None = None
    confidence_level: str = "high"
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedStatementSpec:
    statement_index: int
    statement_type: str
    raw_sql_hash: str
    normalized_sql: str
    parse_status: str
    source_line_start: int
    source_line_end: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class StatementSemantics:
    """Statement-level constructs that never become lineage edges.

    GROUP BY keys, DISTINCT, UNION de-duplication, HAVING predicates, row limits,
    JOIN kinds and CTE names all change what a query *means* without changing which
    column feeds which target.  The edge comparator is blind to them by construction,
    so they are carried separately and compared as their own dimensions.

    Every field holds a normalized, sorted, human-readable text so that a formatting
    or alias-only rewrite compares equal; an empty tuple means "construct absent".
    """

    statement_index: int
    group_by: tuple[str, ...] = ()
    distinct: bool = False
    distinct_on: tuple[str, ...] = ()
    union_modes: tuple[str, ...] = ()
    having: tuple[str, ...] = ()
    row_limit: tuple[str, ...] = ()
    join_types: tuple[str, ...] = ()
    cte_names: tuple[str, ...] = ()
    # Statement-level ORDER BY (never a window's ORDER BY, which belongs to the
    # window expression and is already compared as a transformation).
    order_by: tuple[str, ...] = ()
    # Statement-level WHERE predicates outside CTE bodies, normalized for equality.
    # A predicate rewrite is a filter change even though a plain SELECT's lineage edge
    # carries no filter condition to compare.
    filters: tuple[str, ...] = ()
    # One readable signature per CTE: its name plus the normalized projection and
    # predicate text.  This is what lets a CTE-internal rewrite be attributed to the
    # CTE family instead of falling back to "unattributed AST change".
    cte_signatures: tuple[str, ...] = ()


@dataclass(frozen=True)
class SqlLineageParseResult:
    parse_status: str
    statements: tuple[ParsedStatementSpec, ...]
    nodes: tuple[LineageNodeSpec, ...]
    edges: tuple[LineageEdgeSpec, ...]
    warnings: tuple[str, ...]
    statement_semantics: tuple[StatementSemantics, ...] = ()

def parse_sql_lineage(sql: str, *, dialect: str = "", variables: dict[str, str] | None = None) -> SqlLineageParseResult:
    """Statically parse SQL into evidence-bearing lineage specifications.

    This module has no database or execution dependency.  Parse failures are
    represented in the result and never replaced with invented lineage.
    """

    prepared = preprocess_sql(sql, variables)
    warnings = list(prepared.warnings)
    resolution = resolve_dialect(dialect)
    dialect = resolution.effective
    if resolution.warning:
        warnings.append(resolution.warning)
    statements: list[ParsedStatementSpec] = []
    _statement_semantics_list: list[StatementSemantics] = []
    edges: list[LineageEdgeSpec] = []
    try:
        chunks = _split_sql_statements(prepared.parse_sql, dialect)
    except (sqlglot.errors.SqlglotError, ValueError) as exc:
        warning = f"SQL parse failed: {exc}"
        return SqlLineageParseResult(
            parse_status="failed",
            statements=(ParsedStatementSpec(0, "unknown", _hash(sql), prepared.normalized_sql, "failed", 1, sql.count("\n") + 1, (warning,)),),
            nodes=(), edges=(), warnings=tuple(warnings + [warning]),
        )

    for index, (statement_sql, source_line_start, source_line_end) in enumerate(chunks):
        write_only = _write_only_statement_type(statement_sql)
        if write_only is not None:
            # Pure data statements (INSERT ... VALUES / DELETE / TRUNCATE) cannot
            # produce field lineage and parsing tens of thousands of them is what
            # made large customer data scripts time out.  Record the statement
            # verbatim; never claim lineage for it.
            statements.append(ParsedStatementSpec(
                index, write_only, _hash(statement_sql), statement_sql.strip(), "parsed",
                source_line_start, source_line_end,
            ))
            continue
        oversized = _decompose_oversized_statement(statement_sql, index, prepared.original_sql, dialect)
        if oversized is not None:
            statement, statement_edges, extra_warnings = oversized
            statements.append(replace(statement, source_line_start=source_line_start, source_line_end=source_line_end))
            edges.extend(statement_edges)
            warnings.extend(extra_warnings)
            continue
        try:
            expression = sqlglot.parse_one(statement_sql, read=dialect or None)
        except (sqlglot.errors.SqlglotError, ValueError) as exc:
            recovered = _decompose_oversized_statement(statement_sql, index, prepared.original_sql, dialect, force=True)
            if recovered is not None:
                recovered_statement, recovered_edges, recovered_warnings = recovered
                statements.append(replace(recovered_statement, source_line_start=source_line_start,
                                          source_line_end=source_line_end))
                edges.extend(recovered_edges)
                warnings.extend(recovered_warnings)
                continue
            warning = f"Statement {index + 1} parse failed: {exc}"
            warnings.append(warning)
            statements.append(ParsedStatementSpec(
                index, "unknown", _hash(statement_sql), statement_sql.strip(), "failed",
                source_line_start, source_line_end, (warning,),
            ))
            continue
        normalized = expression.sql(dialect=dialect or None, pretty=False)
        statement_type = _statement_type(expression)
        statement = ParsedStatementSpec(
            index, statement_type, _hash(statement_sql), normalized, "parsed",
            source_line_start, source_line_end,
        )
        statements.append(statement)
        try:
            edges.extend(_statement_edges(expression, index, prepared.original_sql, dialect))
        except Exception as exc:  # isolate one statement; retain successfully parsed siblings
            warning = f"Statement {index + 1} lineage partially parsed: {exc}"
            warnings.append(warning)
            statements[-1] = replace(statement, parse_status="partially_parsed", warnings=(warning,))
        # Statement-level constructs are collected even when the edge extraction above
        # degraded: a GROUP BY key is still factual information about the query.
        try:
            _statement_semantics_list.append(statement_semantics(expression, index))
        except Exception as exc:
            warnings.append(f"Statement {index + 1} semantic extraction failed: {exc}")
    parse_status = "parsed"
    if any(item.parse_status != "parsed" for item in statements):
        parse_status = "partially_parsed" if any(item.parse_status != "failed" for item in statements) else "failed"
    if parse_status == "partially_parsed":
        edges = [replace(item, confidence_level="low") for item in edges]
    nodes = _deduplicate_nodes(edge for edge in edges)
    return SqlLineageParseResult(
        parse_status, tuple(statements), nodes, tuple(_deduplicate_edges(edges)),
        tuple(dict.fromkeys(warnings)), tuple(_statement_semantics_list))


def statement_semantics(expression: exp.Expression, statement_index: int) -> StatementSemantics:
    """Extract the statement-level constructs the edge comparator cannot see.

    Deliberately conservative: anything ambiguous stays *absent* (an empty tuple)
    rather than being guessed, so a caller never reads an invented GROUP BY key.
    Text is normalized through sqlglot's own renderer so that whitespace, keyword
    case and redundant parentheses do not register as a change.
    """

    def rendered(items) -> tuple[str, ...]:
        values = {_semantic_text(item) for item in items if item is not None}
        return tuple(sorted(value for value in values if value))

    queries = [node for node in expression.walk() if isinstance(node, exp.Query)]
    if not queries:
        return StatementSemantics(statement_index)

    group_by: list[exp.Expression] = []
    having: list[exp.Expression] = []
    limits: list[exp.Expression] = []
    distinct_on: list[exp.Expression] = []
    union_modes: set[str] = set()
    join_types: set[str] = set()
    cte_names: set[str] = set()
    order_by: list[exp.Expression] = []
    filters: list[exp.Expression] = []
    cte_signatures: set[str] = set()
    distinct = False
    for query in queries:
        group = query.args.get("group")
        if group is not None:
            group_by.extend(group.expressions)
        having_node = query.args.get("having")
        if having_node is not None:
            having.append(having_node)
        limit = query.args.get("limit")
        if limit is not None:
            limits.append(limit)
        offset = query.args.get("offset")
        if offset is not None:
            limits.append(offset)
        # CTE bodies are compared through ``cte_signatures``; keeping their predicate
        # here would report one rewrite twice (filter + CTE).
        where = query.args.get("where")
        if isinstance(where, exp.Where) and not isinstance(query.parent, exp.CTE):
            filters.append(where.this)
        # Only a query-level ORDER BY is collected here; a window's ORDER BY lives in
        # the window expression and is compared as a transformation.
        order = query.args.get("order")
        if order is not None:
            order_by.extend(order.expressions)
        # ``distinct`` is either the boolean-ish Select arg or a Distinct node; both
        # forms appear across sqlglot versions and dialects.
        raw_distinct = query.args.get("distinct")
        if isinstance(raw_distinct, exp.Distinct):
            distinct = True
            distinct_on.extend(raw_distinct.expressions)
        elif raw_distinct is not None and raw_distinct is not False:
            distinct = True
        for union in query.find_all(exp.Union):
            union_modes.add("union_all" if union.args.get("distinct") is False else "union")
        for join in query.find_all(exp.Join):
            join_types.add(_join_kind(join))
    # The WITH node of "WITH ... INSERT INTO ... SELECT" hangs off the statement, so CTE
    # names and signatures must be collected from the root; reading them from the inner
    # query silently produced empty cte_signatures and mislabelled CTEs as physical tables.
    for cte in expression.find_all(exp.CTE):
        if cte.alias_or_name:
            cte_names.add(cte.alias_or_name)
        signature = _cte_signature(cte)
        if signature:
            cte_signatures.add(signature)
    return StatementSemantics(
        statement_index=statement_index,
        group_by=rendered(group_by),
        distinct=distinct,
        distinct_on=rendered(distinct_on),
        union_modes=tuple(sorted(union_modes)),
        having=rendered(having),
        row_limit=rendered(limits),
        join_types=tuple(sorted(join_types)),
        cte_names=tuple(sorted(cte_names)),
        order_by=rendered(order_by),
        filters=rendered(filters),
        cte_signatures=tuple(sorted(cte_signatures)),
    )


def _cte_signature(cte: exp.CTE) -> str:
    """Readable, normalized signature of one CTE's own projection and predicate.

    The edge comparator never looks inside a CTE, so a rewrite such as
    ``select amt from t1`` → ``select amt * 2 as amt from t1`` used to surface only as
    "unattributed AST change".  Rendering the CTE name with its projection and WHERE
    text gives the CTE family a structural dimension while still keeping the evidence
    human-readable.  Anything unrendarable stays absent instead of being guessed.
    """

    name = (cte.alias_or_name or "").strip()
    if not name:
        return ""
    relation = cte.this
    if not isinstance(relation, exp.Query):
        return ""
    projection = ", ".join(_semantic_text(item) for item in relation.expressions if item is not None)
    predicate = relation.args.get("where")
    where_text = _semantic_text(predicate.this) if isinstance(predicate, exp.Where) else ""
    body = f"{projection} where {where_text}".strip() if where_text else projection
    # The CTE *name* is deliberately excluded: renaming a CTE while keeping its body and
    # every reference consistent is an equivalent rewrite, not a caliber change. Bodies
    # are compared as a normalized multiset, so a real projection/predicate rewrite still
    # differs while a pure rename stays silent.
    return body.strip()


def _semantic_text(node: exp.Expression) -> str:
    """Normalized rendering used for equality only; never parsed back.

    Table qualifiers are stripped from column references before rendering: ``a.dt`` and
    ``b.dt`` denote the same grouping key on the same table, so an alias rename must not
    read as a GROUP BY change.  Only the qualifier is dropped -- the column name, literal
    and expression shape are preserved, so a genuine key change still differs.
    """

    try:
        unqualified = node.copy()
        for column in unqualified.find_all(exp.Column):
            column.set("table", None)
        text = unqualified.sql(pretty=False, normalize=True)
    except Exception:
        return ""
    return re.sub(r"\s+", " ", text).strip().lower()


def _join_kind(join: exp.Join) -> str:
    side = (join.args.get("side") or "").upper()
    kind = (join.args.get("kind") or "").upper()
    if kind == "CROSS":
        return "cross"
    if side == "LEFT" and kind == "OUTER":
        return "left"
    if side == "RIGHT" and kind == "OUTER":
        return "right"
    if side == "FULL" and kind == "OUTER":
        return "full"
    if side in {"LEFT", "RIGHT", "FULL"}:
        return side.lower()
    if kind == "INNER":
        return "inner"
    if kind:
        return kind.lower()
    return "inner" if side else "inner"


MAX_STATEMENT_CHARS = 120_000
"""Largest statement handed to sqlglot in one call.

Real GBase batch scripts contain single ``INSERT ... SELECT`` statements built
from hundreds of ``UNION ALL`` branches (one customer script is 2.28 MB).  A
full parse of such a statement does not finish in usable time, so oversized
statements are decomposed instead of timing out.  The limit is a parsing budget,
never a truncation: nothing is dropped silently.
"""

MAX_UNION_BRANCHES = 400
"""Upper bound on decomposed branches; above this the statement is reported as
unparsed instead of spending unbounded time."""

_WRITE_ONLY_KINDS = (
    ("insert", "insert_values"),
    ("delete", "delete"),
    ("truncate", "truncate"),
    ("drop", "drop"),
    ("commit", "commit"),
)
"""Statement kinds that carry data, not field lineage, and are cheap to classify."""

_SELECT_TOKEN = re.compile(r"(?i)\bSELECT\b")
_USING_OR_FROM_TAIL = re.compile(r"(?i)\b(?:USING|FROM)\b")


def _strip_leading_comments(sql: str) -> str:
    """Drop leading whitespace and comments so statement heads can be matched."""

    index = 0
    length = len(sql)
    while index < length:
        if sql[index].isspace():
            index += 1
            continue
        if sql.startswith("--", index):
            newline = sql.find("\n", index)
            index = length if newline < 0 else newline + 1
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            index = length if end < 0 else end + 2
            continue
        break
    return sql[index:]


def _write_only_statement_type(statement_sql: str) -> str | None:
    """Classify a data statement that cannot yield field lineage.

    Returns ``None`` when the statement must go through the real parser (it
    contains ``SELECT`` or is not a recognised write statement), so nothing is
    silently skipped.
    """

    head = statement_sql.lstrip()[:64].lower()
    if _SELECT_TOKEN.search(statement_sql):
        return None
    if _USING_OR_FROM_TAIL.search(statement_sql):
        # ``DELETE ... USING`` and ``UPDATE ... FROM`` do carry lineage.
        return None
    for prefix, kind in _WRITE_ONLY_KINDS:
        if head.startswith(prefix):
            return kind
    return None

_INSERT_HEADER = re.compile(
    r"(?is)\A\s*(?P<header>INSERT\s+(?:OVERWRITE\s+)?(?:INTO\s+)?(?:TABLE\s+)?(?P<target>[^\s(;]+)\s*(?:\([^)]*\)\s*)?)(?P<select>SELECT\b.*)\Z"
)
_UNION_KEYWORD = re.compile(r"(?is)\bUNION\b(?:\s+ALL\b)?")


def _top_level_union_branches(select_sql: str) -> list[str] | None:
    """Split a SELECT chain on top-level ``UNION [ALL]`` markers.

    Quoting, parentheses and ``--`` comments are honoured so a UNION inside a
    sub-query or a string literal never splits the statement.  Returns ``None``
    when there is nothing to split.
    """

    cuts: list[tuple[int, int]] = []
    depth = 0
    index = 0
    length = len(select_sql)
    while index < length:
        char = select_sql[index]
        if char in ("'", '"', "`"):
            quote = char
            index += 1
            while index < length:
                if select_sql[index] == "\\":
                    index += 2
                    continue
                if select_sql[index] == quote:
                    if index + 1 < length and select_sql[index + 1] == quote:
                        index += 2
                        continue
                    break
                index += 1
            index += 1
            continue
        if char == "-" and select_sql.startswith("--", index):
            newline = select_sql.find("\n", index)
            index = length if newline < 0 else newline + 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        elif depth == 0 and select_sql[index : index + 5].upper() == "UNION":
            match = _UNION_KEYWORD.match(select_sql, index)
            if match:
                cuts.append((index, match.end()))
                index = match.end()
                continue
        index += 1
    if not cuts:
        return None
    branches: list[str] = []
    start = 0
    for begin, end in cuts:
        branches.append(select_sql[start:begin])
        start = end
    branches.append(select_sql[start:])
    cleaned = [branch.strip() for branch in branches if branch.strip()]
    return cleaned if len(cleaned) > 1 else None


def _decompose_oversized_statement(statement_sql: str, statement_index: int, original_sql: str, dialect: str,
                                   *, force: bool = False):
    """Parse an oversized ``INSERT ... SELECT ... UNION ALL ...`` by branch.

    Returns ``None`` when the statement is within budget or cannot be
    decomposed, so the caller keeps its normal behaviour.  Each branch is parsed
    as its own ``INSERT`` so field-level mapping survives the budget; when a
    branch fails the statement is reported as ``partially_parsed`` and the
    failure is named — no lineage is invented for the failed branch.
    """

    if len(statement_sql) <= MAX_STATEMENT_CHARS and not force:
        return None
    core = _strip_leading_comments(statement_sql)
    header = _INSERT_HEADER.match(core)
    if header is None:
        if force:
            # Recovering from a failed parse: only a real decomposition helps,
            # otherwise let the caller report its original error verbatim.
            return None
        warning = (f"Statement {statement_index + 1} skipped: {len(statement_sql)} characters exceed the "
                   f"{MAX_STATEMENT_CHARS}-character parse budget and it is not a decomposable INSERT ... SELECT；"
                   "未做字段级解析，需人工核验")
        return (ParsedStatementSpec(statement_index, "unknown", _hash(statement_sql), statement_sql.strip()[:2000],
                                    "failed", 1, 1, (warning,)), [], [warning])
    branches = _top_level_union_branches(header.group("select"))
    if branches is None or len(branches) > MAX_UNION_BRANCHES:
        if force:
            return None
        warning = (f"Statement {statement_index + 1} skipped: {len(statement_sql)} characters exceed the "
                   f"{MAX_STATEMENT_CHARS}-character parse budget and its UNION branches cannot be split safely；"
                   "未做字段级解析，需人工核验")
        return (ParsedStatementSpec(statement_index, "unknown", _hash(statement_sql), statement_sql.strip()[:2000],
                                    "failed", 1, 1, (warning,)), [], [warning])
    prefix = header.group("header")
    merged: list[LineageEdgeSpec] = []
    failures: list[str] = []
    for branch_index, branch in enumerate(branches):
        branch_sql = f"{prefix}{branch}"
        if not branch_sql.endswith("\n"):
            # sqlglot raises TokenError when a trailing ``--`` comment reaches EOF.
            branch_sql += "\n"
        try:
            expression = sqlglot.parse_one(branch_sql, read=dialect or None)
        except (sqlglot.errors.SqlglotError, ValueError) as exc:
            failures.append(f"branch {branch_index + 1}: {exc}")
            continue
        try:
            merged.extend(_statement_edges(expression, statement_index, original_sql, dialect))
        except Exception as exc:  # isolate a single branch
            failures.append(f"branch {branch_index + 1} lineage: {exc}")
    reason = ("its single-call parse failed, lineage recovered per UNION branch" if force else
              f"{len(statement_sql)} characters exceed the {MAX_STATEMENT_CHARS}-character budget")
    warnings = [f"Statement {statement_index + 1} decomposed into {len(branches)} UNION branches ({reason})"]
    status = "partially_parsed" if failures else "parsed"
    if failures:
        warnings.append(f"Statement {statement_index + 1} branch parse failed: " + "; ".join(failures[:5]))
    statement = ParsedStatementSpec(statement_index, "insert_select", _hash(statement_sql),
                                    f"{prefix}<{len(branches)} UNION branches>", status, 1, 1,
                                    tuple(warnings))
    return statement, merged, warnings


def _split_sql_statements(sql: str, dialect: str) -> list[tuple[str, int, int]]:
    """Split on semicolons outside strings and comments.

    The previous implementation tokenized the whole file with sqlglot to confirm
    every semicolon.  A 2.28 MB customer script (19 400 ``INSERT ... VALUES``
    data rows) spent ~30 s just tokenizing, before parsing anything.  A single
    quote/comment-aware scan gives the same boundaries in linear time; syntax is
    still validated per statement afterwards, so a bad statement stays isolated.
    """

    chunks: list[tuple[str, int, int]] = []
    length = len(sql)
    start = 0
    index = 0
    newlines = [position for position, character in enumerate(sql) if character == "\n"]

    def line_of(offset: int) -> int:
        return bisect_left(newlines, offset) + 1

    def emit(begin: int, end: int) -> None:
        raw = sql[begin:end]
        # A chunk that holds only comments/semicolons is not a statement; keeping
        # it produced "No expression was parsed from '\n--…'" noise for every
        # script banner (and for scripts truncated at a disabled block comment).
        if raw.strip().strip(";").strip() and _has_sql_content(raw):
            first_non_space = begin + len(raw) - len(raw.lstrip())
            last_non_space = begin + len(raw.rstrip()) - 1
            # Precomputed newline offsets: per-chunk ``str.count`` over a 2 MB
            # script made splitting quadratic (19 400 statements × full scan).
            chunks.append((raw, line_of(first_non_space), line_of(max(last_non_space, first_non_space))))

    while index < length:
        char = sql[index]
        if char in ("'", '"', "`"):
            quote = char
            index += 1
            while index < length:
                if sql[index] == "\\":
                    index += 2
                    continue
                if sql[index] == quote:
                    if index + 1 < length and sql[index + 1] == quote:
                        index += 2
                        continue
                    break
                index += 1
            index += 1
            continue
        if char == "-" and sql.startswith("--", index):
            newline = sql.find("\n", index)
            index = length if newline < 0 else newline + 1
            continue
        if char == "/" and sql.startswith("/*", index):
            end_comment = sql.find("*/", index + 2)
            index = length if end_comment < 0 else end_comment + 2
            continue
        if char == ";":
            emit(start, index + 1)
            start = index + 1
        index += 1
    emit(start, length)
    return chunks


def _has_sql_content(chunk: str) -> bool:
    """True when the chunk contains something other than comments and blanks."""

    return bool(_strip_sql_comments(chunk).strip().strip(";").strip())


def _strip_sql_comments(sql: str) -> str:
    out: list[str] = []
    index, length = 0, len(sql)
    while index < length:
        char = sql[index]
        if char in ("'", '"', "`"):
            quote = char
            out.append(char)
            index += 1
            while index < length:
                if sql[index] == "\\" and index + 1 < length:
                    out.append(sql[index:index + 2])
                    index += 2
                    continue
                out.append(sql[index])
                if sql[index] == quote:
                    index += 1
                    break
                index += 1
            continue
        if char == "-" and sql.startswith("--", index):
            newline = sql.find("\n", index)
            index = length if newline < 0 else newline
            continue
        if char == "/" and sql.startswith("/*", index):
            end_comment = sql.find("*/", index + 2)
            index = length if end_comment < 0 else end_comment + 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _statement_edges(statement: exp.Expression, statement_index: int, original_sql: str, dialect: str) -> list[LineageEdgeSpec]:
    if isinstance(statement, exp.Merge):
        return _merge_edges(statement, statement_index, original_sql)
    if isinstance(statement, exp.Update):
        return _update_edges(statement, statement_index, original_sql)
    target_table, target_columns, query = _write_target(statement)
    if query is None:
        return []
    query = _scope_query_with_ctes(statement, query)
    sources, aliases = _source_tables(query)
    filter_sql = " AND ".join(where.this.sql() for where in query.find_all(exp.Where)) or None
    join_sql = " AND ".join(join.args["on"].sql() for join in query.find_all(exp.Join) if join.args.get("on")) or None
    evidence = {"statement_index": statement_index, "template_expressions": _template_expressions(original_sql)}
    result: list[LineageEdgeSpec] = []

    if target_table is not None:
        for source in sources:
            result.append(LineageEdgeSpec(source, target_table, "reads_from", join_condition=join_sql, filter_condition=filter_sql, evidence=evidence))

    projections = list(query.selects) if isinstance(query, exp.Query) else []
    if target_table is None:
        return result
    for index, projection in enumerate(projections):
        output_name = target_columns[index] if index < len(target_columns) else projection.alias_or_name
        if not output_name:
            continue
        target_column = _column_node(target_table, output_name)
        source_columns = _physical_projection_sources(query, projection, sources, aliases, dialect)
        if not source_columns and isinstance(projection, exp.Column):
            source_columns = [_resolve_column(projection, sources, aliases)]
        if not source_columns:
            constant = LineageNodeSpec("constant", f"constant:{projection.sql()}", metadata={"expression": projection.sql()})
            result.append(LineageEdgeSpec(constant, target_column, "derives_from", "constant", projection.sql(), join_condition=join_sql, filter_condition=filter_sql, evidence=evidence))
            continue
        edge_type, transformation_type = _transformation(projection)
        for source_column in source_columns:
            result.append(LineageEdgeSpec(
                source_column,
                target_column,
                edge_type,
                transformation_type,
                projection.sql(),
                join_condition=join_sql,
                filter_condition=filter_sql,
                aggregation_rule=projection.sql() if edge_type == "aggregates" else None,
                code_mapping_rule=projection.sql() if transformation_type == "code_mapping" else None,
                confidence_level="high" if source_column.node_type != "unknown" else "low",
                evidence=evidence,
            ))
    return result


def _merge_edges(statement: exp.Merge, statement_index: int, original_sql: str) -> list[LineageEdgeSpec]:
    target_table = _table_node(statement.this)
    source_expression = statement.args.get("using")
    source_table = _table_node(source_expression) if source_expression is not None else None
    if target_table is None or source_table is None:
        return []
    join_condition = statement.args.get("on").sql() if statement.args.get("on") is not None else None
    evidence = {"statement_index": statement_index, "template_expressions": _template_expressions(original_sql)}
    edges = [LineageEdgeSpec(source_table, target_table, "reads_from", join_condition=join_condition, evidence=evidence)]
    aliases = {
        (statement.this.alias_or_name or statement.this.name).upper(): target_table,
        statement.this.name.upper(): target_table,
        (source_expression.alias_or_name or source_expression.name).upper(): source_table,
        source_expression.name.upper(): source_table,
    }
    assignments: list[tuple[exp.Expression, exp.Expression]] = []
    whens = statement.args.get("whens")
    for when in whens.expressions if whens is not None else []:
        action = when.args.get("then")
        if isinstance(action, exp.Update):
            assignments.extend((item.this, item.expression) for item in action.expressions if isinstance(item, exp.EQ))
        elif isinstance(action, exp.Insert) and isinstance(action.this, exp.Tuple) and isinstance(action.expression, exp.Tuple):
            assignments.extend(zip(action.this.expressions, action.expression.expressions))
    for target_expression, source_value in assignments:
        target_name = target_expression.name if isinstance(target_expression, (exp.Column, exp.Identifier)) else target_expression.alias_or_name
        if not target_name:
            continue
        target_column = _column_node(target_table, target_name)
        source_columns = list(source_value.find_all(exp.Column))
        if isinstance(source_value, exp.Column) and not source_columns:
            source_columns = [source_value]
        edge_type, transformation_type = _transformation(source_value)
        for column in source_columns:
            source_column = _resolve_column(column, [source_table], aliases)
            # MERGE RHS should reference USING.  If it points at the target,
            # retain it as evidence but lower confidence instead of inventing
            # a source-table binding.
            confidence = "high" if source_column.logical_name.startswith(source_table.logical_name + ".") else "low"
            edges.append(LineageEdgeSpec(
                source_column, target_column, edge_type, transformation_type, source_value.sql(),
                join_condition=join_condition, confidence_level=confidence, evidence=evidence,
                aggregation_rule=source_value.sql() if edge_type == "aggregates" else None,
                code_mapping_rule=source_value.sql() if transformation_type == "code_mapping" else None,
            ))
    return edges


def _update_edges(statement: exp.Update, statement_index: int, original_sql: str) -> list[LineageEdgeSpec]:
    target_table = _table_node(statement.this)
    from_expression = statement.args.get("from")
    if target_table is None or from_expression is None:
        return []
    source_tables = [_table_node(item) for item in from_expression.find_all(exp.Table)]
    source_tables = [item for item in source_tables if item is not None]
    source_ast = list(from_expression.find_all(exp.Table))
    join_condition = statement.args.get("where").this.sql() if statement.args.get("where") is not None else None
    evidence = {"statement_index": statement_index, "template_expressions": _template_expressions(original_sql)}
    edges = [LineageEdgeSpec(source, target_table, "reads_from", join_condition=join_condition, filter_condition=join_condition, evidence=evidence) for source in source_tables]
    aliases = {(statement.this.alias_or_name or statement.this.name).upper(): target_table, statement.this.name.upper(): target_table}
    for ast_table, node in zip(source_ast, source_tables):
        aliases[(ast_table.alias_or_name or ast_table.name).upper()] = node
        aliases[ast_table.name.upper()] = node
    for assignment in statement.expressions:
        if not isinstance(assignment, exp.EQ):
            continue
        target_name = assignment.this.name
        target_column = _column_node(target_table, target_name)
        edge_type, transformation_type = _transformation(assignment.expression)
        columns = list(assignment.expression.find_all(exp.Column))
        if isinstance(assignment.expression, exp.Column) and not columns:
            columns = [assignment.expression]
        for column in columns:
            source_column = _resolve_column(column, source_tables, aliases)
            edges.append(LineageEdgeSpec(
                source_column, target_column, edge_type, transformation_type, assignment.expression.sql(),
                join_condition=join_condition, filter_condition=join_condition,
                confidence_level="high" if source_column.node_type != "unknown" else "low", evidence=evidence,
                aggregation_rule=assignment.expression.sql() if edge_type == "aggregates" else None,
                code_mapping_rule=assignment.expression.sql() if transformation_type == "code_mapping" else None,
            ))
    return edges


def _physical_projection_sources(
    query: exp.Expression,
    projection: exp.Expression,
    sources: list[LineageNodeSpec],
    aliases: dict[str, LineageNodeSpec],
    dialect: str,
) -> list[LineageNodeSpec]:
    """Resolve a projection through CTEs, subqueries and UNION scopes."""

    output_name = projection.alias_or_name
    if output_name:
        try:
            root = trace_column_lineage(output_name, query, dialect=dialect or None)
            resolved: list[LineageNodeSpec] = []
            for node in root.walk():
                if node.downstream or not isinstance(node.expression, exp.Table):
                    continue
                table = _table_node(node.expression)
                if table is None:
                    continue
                table = next((item for item in sources if _same_table(item, table)), table)
                traced_column_name = node.name.rsplit(".", 1)[-1]
                column_name = next(
                    (item.name for item in query.find_all(exp.Column) if item.name.lower() == traced_column_name.lower()),
                    traced_column_name,
                )
                value = _column_node(table, column_name)
                if value not in resolved:
                    resolved.append(value)
            if resolved:
                return resolved
        except (sqlglot.errors.SqlglotError, ValueError, IndexError, KeyError):
            pass
    return [_resolve_column(column, sources, aliases) for column in projection.find_all(exp.Column)]


def _same_table(left: LineageNodeSpec, right: LineageNodeSpec) -> bool:
    return all(
        not expected or (actual or "").lower() == expected.lower()
        for actual, expected in (
            (left.database_name, right.database_name),
            (left.schema_name, right.schema_name),
            (left.table_name, right.table_name),
        )
    )


def _write_target(statement: exp.Expression) -> tuple[LineageNodeSpec | None, list[str], exp.Expression | None]:
    if isinstance(statement, exp.Insert):
        target = statement.this
        columns: list[str] = []
        if isinstance(target, exp.Schema):
            columns = [item.name for item in target.expressions]
            target = target.this
        return _table_node(target), columns, statement.expression
    if isinstance(statement, exp.Create) and statement.args.get("expression") is not None:
        target = statement.this
        if isinstance(target, exp.Schema):
            target = target.this
        return _table_node(target, temporary=bool(statement.args.get("temporary"))), [], statement.expression
    if isinstance(statement, exp.Merge):
        return _table_node(statement.this), [], statement.args.get("using")
    if isinstance(statement, exp.Update):
        return _table_node(statement.this), [item.this.name for item in statement.expressions if isinstance(item, exp.EQ)], statement
    if isinstance(statement, exp.Select):
        return None, [], statement
    return None, [], None


def _scope_query_with_ctes(statement: exp.Expression, query: exp.Expression) -> exp.Expression:
    """Attach the statement-level WITH scope to the write query before tracing.

    ``WITH base AS (...) INSERT INTO t SELECT ... FROM base`` keeps the ``With`` node on
    the ``Insert``; the inner ``Select`` does not own it.  Tracing columns with the bare
    ``Select`` therefore stopped at a table literally named ``base`` and emitted lineage
    that pointed at a non-existent physical table.  Copying the scope onto a private query
    copy keeps the statement untouched while letting the tracer follow CTEs to the real
    source tables.
    """

    scope = statement.args.get("with")
    if scope is None or query.args.get("with") is not None:
        return query
    try:
        widened = query.copy()
        widened.set("with", scope.copy())
        return widened
    except Exception:  # defensive: tracing still degrades to the previous behaviour
        return query


def _source_tables(query: exp.Expression) -> tuple[list[LineageNodeSpec], dict[str, LineageNodeSpec]]:
    cte_names = {cte.alias_or_name.upper() for cte in query.find_all(exp.CTE)}
    sources: list[LineageNodeSpec] = []
    aliases: dict[str, LineageNodeSpec] = {}
    for table in query.find_all(exp.Table):
        if table.name.upper() in cte_names:
            continue
        node = _table_node(table)
        if node is None or node not in sources:
            sources.append(node)
        aliases[(table.alias_or_name or table.name).upper()] = node
        aliases[table.name.upper()] = node
    return sources, aliases


def _table_node(value: exp.Expression, temporary: bool = False) -> LineageNodeSpec | None:
    if not isinstance(value, exp.Table):
        return None
    parts = [part for part in [value.catalog, value.db, value.name] if part]
    logical_name = ".".join(parts)
    return LineageNodeSpec(
        "temporary_table" if temporary else "table",
        logical_name,
        database_name=value.catalog or None,
        schema_name=value.db or None,
        table_name=value.name,
        temporary_flag=temporary,
    )


def _column_node(table: LineageNodeSpec, column_name: str) -> LineageNodeSpec:
    return LineageNodeSpec(
        "column", f"{table.logical_name}.{column_name}", table.database_name, table.schema_name,
        table.table_name, column_name, table.temporary_flag,
    )


def _resolve_column(column: exp.Column, sources: list[LineageNodeSpec], aliases: dict[str, LineageNodeSpec]) -> LineageNodeSpec:
    table = aliases.get(column.table.upper()) if column.table else (sources[0] if len(sources) == 1 else None)
    if table is None:
        return LineageNodeSpec("unknown", column.sql(), table_name=column.table or None, column_name=column.name, unresolved_flag=True)
    return _column_node(table, column.name)


def _transformation(projection: exp.Expression) -> tuple[str, str]:
    if any(True for _ in projection.find_all(exp.AggFunc)):
        return "aggregates", "aggregation"
    if projection.find(exp.Case) is not None:
        return "maps_code", "code_mapping"
    if projection.find(exp.Coalesce) is not None:
        return "derives_from", "coalesce"
    if projection.find(exp.Window) is not None:
        return "derives_from", "window"
    if isinstance(projection, (exp.Column, exp.Alias)) and len(list(projection.find_all(exp.Column))) == 1:
        return "derives_from", "pass_through"
    return "derives_from", "expression"


def _statement_type(expression: exp.Expression) -> str:
    if isinstance(expression, exp.Insert): return "insert_select"
    if isinstance(expression, exp.Select): return "select"
    if isinstance(expression, exp.Merge): return "merge"
    if isinstance(expression, exp.Update): return "update"
    if isinstance(expression, exp.Delete): return "delete"
    if isinstance(expression, exp.Create):
        kind = str(expression.args.get("kind") or "").upper()
        return "create_view" if kind == "VIEW" else "create_table_as" if expression.args.get("expression") is not None else "ddl"
    return "unknown"


def _deduplicate_nodes(edges) -> tuple[LineageNodeSpec, ...]:
    result: dict[tuple, LineageNodeSpec] = {}
    for edge in edges:
        for node in (edge.source, edge.target):
            key = (node.node_type, node.logical_name)
            result.setdefault(key, node)
    return tuple(result.values())


def _deduplicate_edges(edges: list[LineageEdgeSpec]) -> list[LineageEdgeSpec]:
    result: dict[tuple, LineageEdgeSpec] = {}
    for edge in edges:
        key = (edge.source.logical_name, edge.target.logical_name, edge.edge_type, edge.transformation_expression)
        result.setdefault(key, edge)
    return list(result.values())


def _template_expressions(sql: str) -> list[str]:
    return [item.expression for item in preprocess_sql(sql).variables]


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
