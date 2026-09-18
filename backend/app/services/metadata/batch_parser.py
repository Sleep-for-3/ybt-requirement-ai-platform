"""Bounded offline parsing only: none of these functions execute uploaded SQL."""
from dataclasses import asdict
from io import BytesIO
import re
from zipfile import ZipFile

import sqlglot
from sqlglot import exp

from app.services.lineage.sql_parser import parse_sql_lineage
from app.services.metadata.excel_import import _parse, _bool

MAX_ROWS = 10000


def identity(database, schema, table):
    return {"database_name": str(database or ""), "schema_name": str(schema or ""), "table_name": str(table)}


def parse_dictionary(data):
    # Check workbook container before openpyxl allocates cells or follows dimensions.
    with ZipFile(BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 2000 or sum(x.file_size for x in entries) > 40 * 1024 * 1024:
            raise ValueError("Excel 解压内容超出限制")
        cells = 0
        for entry in entries:
            if entry.filename.startswith("xl/worksheets/") and entry.filename.endswith(".xml"):
                content = archive.read(entry)
                cells += len(re.findall(rb"<c\b", content))
                max_row = max_column = 0
                for column, row in re.findall(rb'\br="([A-Z]+)(\d+)"', content):
                    if len(column) > 2 or int(row) > MAX_ROWS:
                        raise ValueError("Excel 行列范围超出限制")
                    column_number = 0
                    for letter in column:
                        column_number = column_number * 26 + letter - ord("A") + 1
                    max_column = max(max_column, column_number)
                    max_row = max(max_row, int(row))
                if max_row * max_column > 100000:
                    raise ValueError("Excel 稀疏工作表范围超出限制")
        if cells > 100000:
            raise ValueError("Excel 单元格数量超出限制")
    rows, warnings = _parse(BytesIO(data), preserve_missing_schema=True)
    if len(rows) > MAX_ROWS:
        raise ValueError("Excel 字段数超出限制")
    tables = {}
    for row in rows:
        location = identity(row.get("database_name"), row.get("schema_name"), row["table_name"])
        key = tuple(location.values())
        table = tables.setdefault(key, {**location, "table_comment": str(row.get("table_comment") or ""), "columns": []})
        column = {"column_name": str(row["column_name"]), "data_type": str(row.get("data_type") or ""),
                  "column_comment": str(row.get("column_comment") or ""), "nullable": _bool(row.get("nullable"), True),
                  "is_primary_key": _bool(row.get("is_primary_key"), False),
                  "ordinal_position": len(table["columns"]) + 1}
        existing = next((x for x in table["columns"] if x["column_name"] == column["column_name"]), None)
        if existing and {k: v for k, v in existing.items() if k != "ordinal_position"} != {k: v for k, v in column.items() if k != "ordinal_position"}:
            raise ValueError("同一字典内存在字段定义冲突")
        if not existing:
            table["columns"].append(column)
    if not tables:
        raise ValueError("未识别到表和字段，请检查字典表头")
    return {"tables": list(tables.values()), "warnings": warnings, "complete": not warnings}


def parse_ddl(text, dialect):
    statements = sqlglot.parse(text, read=dialect or None)
    tables, comments, warnings = [], [], []
    for statement in statements:
        if statement is None:
            continue
        if isinstance(statement, exp.Comment):
            comments.append(statement)
            continue
        if not isinstance(statement, exp.Create) or statement.args.get("kind") != "TABLE" or not isinstance(statement.this, exp.Schema):
            warnings.append("无法作为完整表结构识别的语句，需要单独核验")
            continue
        ref = statement.this.this
        columns = []
        for node in statement.this.expressions:
            if not isinstance(node, exp.ColumnDef):
                continue
            constraint = list(node.find_all(exp.ColumnConstraint))
            comment = next(node.find_all(exp.CommentColumnConstraint), None)
            columns.append({"column_name": node.name, "data_type": node.args["kind"].sql(dialect=dialect or None),
                "column_comment": comment.this.this if comment else "", "ordinal_position": len(columns) + 1,
                "nullable": not any(isinstance(x.kind, exp.NotNullColumnConstraint) for x in constraint),
                "is_primary_key": any(isinstance(x.kind, exp.PrimaryKeyColumnConstraint) for x in constraint)})
        for primary in statement.this.find_all(exp.PrimaryKey):
            keys = {x.name for x in primary.expressions}
            for column in columns:
                if column["column_name"] in keys:
                    column["is_primary_key"] = True
                    column["nullable"] = False
        comment = next(statement.find_all(exp.SchemaCommentProperty), None)
        if not columns:
            raise ValueError("DDL 未包含可识别字段")
        tables.append({**identity(ref.catalog, ref.db, ref.name), "table_comment": comment.this.this if comment else "", "columns": columns})
    for comment in comments:
        ref = comment.this
        name = ref.table if isinstance(ref, exp.Column) else ref.name
        matches = [x for x in tables if tuple(x[k] for k in ("database_name", "schema_name", "table_name")) == (ref.catalog, ref.db, name)]
        if len(matches) != 1:
            warnings.append("注释未能绑定本文件中唯一的表")
            continue
        if isinstance(ref, exp.Column):
            column = next((x for x in matches[0]["columns"] if x["column_name"] == ref.name), None)
            if column:
                column["column_comment"] = comment.expression.this
            else:
                warnings.append("注释引用未知字段")
        else:
            matches[0]["table_comment"] = comment.expression.this
    if not tables or sum(len(x["columns"]) for x in tables) > MAX_ROWS:
        raise ValueError("DDL 未识别表或字段数超出限制")
    return {"tables": tables, "warnings": warnings, "complete": not warnings}


def parse_file(data, name, kind="auto", dialect=""):
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("单文件大小不能超过 10 MB")
    if name.lower().endswith(".xlsx"):
        return "excel", parse_dictionary(data)
    text = data.decode("utf-8-sig")
    if kind == "auto":
        kind = "ddl" if name.lower().endswith(".ddl") else "sql"
        if kind == "sql":
            try:
                statements = [x for x in sqlglot.parse(text, read=dialect or None) if x is not None]
                if statements and all(isinstance(x, exp.Comment) or
                    (isinstance(x, exp.Create) and x.args.get("kind") == "TABLE" and isinstance(x.this, exp.Schema)) for x in statements):
                    kind = "ddl"
            except sqlglot.errors.ParseError:
                pass
    if kind == "ddl":
        return kind, parse_ddl(text, dialect)
    if kind != "sql":
        raise ValueError("不支持的文件类型")
    result = parse_sql_lineage(text, dialect=dialect)
    warnings = list(result.warnings)
    if not result.edges:
        warnings.append("未提取可用血缘规则")
    if re.search(r"\b(EXECUTE|EXEC|PROCEDURE|TEMPORARY)\b|\$\{|\bSELECT\s+\*", text, re.I):
        warnings.append("动态 SQL、过程、临时表或星号需要人工核验")
    try:
        for statement in sqlglot.parse(text, read=dialect or None):
            if isinstance(statement, exp.Insert) and not isinstance(statement.this, exp.Schema):
                warnings.append("INSERT 缺少显式目标字段列表，不能确认字段映射完整性")
    except (sqlglot.errors.ParseError, ValueError):
        pass
    return "sql", {"rules": [asdict(edge) for edge in result.edges],
        "statements": [asdict(statement) for statement in result.statements],
        "warnings": warnings, "complete": result.parse_status == "parsed" and not warnings, "tables": []}
