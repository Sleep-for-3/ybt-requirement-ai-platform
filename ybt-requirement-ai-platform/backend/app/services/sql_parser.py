from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp


@dataclass
class SqlParseData:
    parsed_success: bool
    source_tables: list[str] = field(default_factory=list)
    selected_fields: list[str] = field(default_factory=list)
    joins: list[str] = field(default_factory=list)
    where_conditions: list[str] = field(default_factory=list)
    error_message: str | None = None


def parse_sql(raw_sql: str) -> SqlParseData:
    try:
        tree = sqlglot.parse_one(raw_sql)
        if tree is None:
            raise ValueError("SQL parser returned no syntax tree")
        selected_fields = [
            projection.sql(dialect="postgres")
            for select in tree.find_all(exp.Select)
            for projection in select.expressions
        ]
        source_tables = sorted({table.name for table in tree.find_all(exp.Table) if table.name})
        joins = []
        for join in tree.find_all(exp.Join):
            join_condition = join.args.get("on")
            joins.append(join_condition.sql(dialect="postgres") if join_condition else join.sql(dialect="postgres"))
        where_conditions = [
            where.this.sql(dialect="postgres")
            for where in tree.find_all(exp.Where)
            if where.this is not None
        ]
        if not source_tables and isinstance(tree, exp.Select):
            raise ValueError("SELECT statement does not contain a source table")
        return SqlParseData(
            parsed_success=True,
            source_tables=source_tables,
            selected_fields=selected_fields,
            joins=joins,
            where_conditions=where_conditions,
        )
    except Exception as exc:
        return SqlParseData(parsed_success=False, error_message=str(exc))
