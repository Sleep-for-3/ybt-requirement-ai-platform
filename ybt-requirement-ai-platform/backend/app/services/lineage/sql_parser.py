from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace

import sqlglot
from sqlglot import exp
from sqlglot.lineage import lineage as trace_column_lineage
from sqlglot.tokens import TokenType

from app.services.lineage.preprocessing import preprocess_sql


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
class SqlLineageParseResult:
    parse_status: str
    statements: tuple[ParsedStatementSpec, ...]
    nodes: tuple[LineageNodeSpec, ...]
    edges: tuple[LineageEdgeSpec, ...]
    warnings: tuple[str, ...]


def parse_sql_lineage(sql: str, *, dialect: str = "", variables: dict[str, str] | None = None) -> SqlLineageParseResult:
    """Statically parse SQL into evidence-bearing lineage specifications.

    This module has no database or execution dependency.  Parse failures are
    represented in the result and never replaced with invented lineage.
    """

    prepared = preprocess_sql(sql, variables)
    warnings = list(prepared.warnings)
    statements: list[ParsedStatementSpec] = []
    edges: list[LineageEdgeSpec] = []
    try:
        chunks = _split_sql_statements(prepared.parse_sql, dialect)
    except (sqlglot.errors.ParseError, ValueError) as exc:
        warning = f"SQL parse failed: {exc}"
        return SqlLineageParseResult(
            parse_status="failed",
            statements=(ParsedStatementSpec(0, "unknown", _hash(sql), prepared.normalized_sql, "failed", 1, sql.count("\n") + 1, (warning,)),),
            nodes=(), edges=(), warnings=tuple(warnings + [warning]),
        )

    for index, (statement_sql, source_line_start, source_line_end) in enumerate(chunks):
        try:
            expression = sqlglot.parse_one(statement_sql, read=dialect or None)
        except (sqlglot.errors.ParseError, ValueError) as exc:
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

    parse_status = "parsed"
    if any(item.parse_status != "parsed" for item in statements):
        parse_status = "partially_parsed" if any(item.parse_status != "failed" for item in statements) else "failed"
    if parse_status == "partially_parsed":
        edges = [replace(item, confidence_level="low") for item in edges]
    nodes = _deduplicate_nodes(edge for edge in edges)
    return SqlLineageParseResult(parse_status, tuple(statements), nodes, tuple(_deduplicate_edges(edges)), tuple(dict.fromkeys(warnings)))


def _split_sql_statements(sql: str, dialect: str) -> list[tuple[str, int, int]]:
    """Split on tokenizer-confirmed semicolons so one bad statement stays isolated."""

    tokenizer = sqlglot.Dialect.get_or_raise(dialect).tokenizer() if dialect else sqlglot.Tokenizer()
    tokens = tokenizer.tokenize(sql)
    boundaries = [token.end + 1 for token in tokens if token.token_type == TokenType.SEMICOLON]
    chunks: list[tuple[str, int, int]] = []
    start = 0
    for end in [*boundaries, len(sql)]:
        raw = sql[start:end]
        if raw.strip().strip(";").strip():
            first_non_space = start + len(raw) - len(raw.lstrip())
            last_non_space = start + len(raw.rstrip()) - 1
            chunks.append((
                raw,
                sql.count("\n", 0, first_non_space) + 1,
                sql.count("\n", 0, max(last_non_space, first_non_space)) + 1,
            ))
        start = end
    return chunks


def _statement_edges(statement: exp.Expression, statement_index: int, original_sql: str, dialect: str) -> list[LineageEdgeSpec]:
    if isinstance(statement, exp.Merge):
        return _merge_edges(statement, statement_index, original_sql)
    if isinstance(statement, exp.Update):
        return _update_edges(statement, statement_index, original_sql)
    target_table, target_columns, query = _write_target(statement)
    if query is None:
        return []
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
