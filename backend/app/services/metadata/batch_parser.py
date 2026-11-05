"""Bounded offline parsing only: none of these functions execute uploaded SQL."""
from dataclasses import asdict
from io import BytesIO
import os
import re
from zipfile import ZipFile

import sqlglot
from sqlglot import exp

from app.services.lineage.preprocessing import (
    strip_hash_comments,
    truncate_unterminated_block_comment,
)
from app.services.lineage.sql_parser import parse_sql_lineage, resolve_dialect
from app.services.metadata.excel_import import _parse, _bool

MAX_ROWS = 10000
# 补录 DDL 一次导出可能包含 1000+ 张表 / 3.6 万字段（真实材料即如此）。
# 旧的 10000 字段上限会把整份 DDL 判为"解析失败"，而错误提示只说
# "请检查编码、方言与格式"，用户无法知道是上限问题。
# DDL 单文件上限独立配置，默认 200000 字段（约 5000 张表），
# 仍保留总量保护，避免恶意超大文件拖垮进程。
DDL_MAX_COLUMNS = int(os.environ.get("IMPORT_DDL_MAX_COLUMNS", "200000"))



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


def infer_ddl_dialect(text):
    """Pick the DDL grammar for vendor exports before any sqlglot call.

    Real bank exports here are Hive/Spark style (``USING parquet``,
    ``PARTITIONED BY``, ``TBLPROPERTIES``, backtick-quoted ``db.table``).  The
    generic grammar turns those statements into ``Command`` nodes and the whole
    file fails with "DDL 未识别表"; the same text parses cleanly as Hive.
    """
    sample = text[:200000]
    if (re.search(r"(?i)\bTBLPROPERTIES\b|\bUSING\s+(?:PARQUET|ORC|TEXT|DELTA|JSON|AVRO)\b|"
                  r"\bPARTITIONED\s+BY\b|\bROW\s+FORMAT\b", sample) or "`" in sample
            or re.search(r"(?im)^\s*CREATE\s+(?:EXTERNAL\s+)?TABLE\s+`", sample)):
        return "hive"
    return ""


def parse_ddl(text, dialect):
    statements = sqlglot.parse(text, read=dialect or None)
    tables, comments, warnings = [], [], []
    for statement in statements:
        if statement is None:
            continue
        if isinstance(statement, (exp.Comment, exp.Semicolon)):
            comments.append(statement)
            continue
        if not isinstance(statement, exp.Create) or statement.args.get("kind") != "TABLE" or not isinstance(statement.this, exp.Schema):
            warnings.append("无法作为完整表结构识别的语句，需要单独核验")
            continue
        ref = statement.this.this
        # Hive/GBase 的 ``db.table`` 是"库.表"，不是"schema.表"：sqlglot 把第一段
        # 放在 ref.db，旧实现会把它当 schema，再叠加导入参数里的默认库名，
        # 产生 ``dm_bappdb_tcyl.dm_bappdb_tcyl.hyf_x`` 这种永不匹配的资产身份。
        if ref.catalog is None and ref.db is not None:
            location = identity(ref.db, "", ref.name)
        else:
            location = identity(ref.catalog, ref.db, ref.name)
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
            # 一份真实导出里常混有 ``CREATE TABLE x LIKE y`` / CTAS 这类没有字段
            # 清单的语句；旧实现直接抛错，会把整份 1000+ 表的 DDL 判为解析失败。
            warnings.append(f"表 {ref.name} 没有可识别字段定义，已跳过")
            continue
        tables.append({**location, "table_comment": comment.this.this if comment else "", "columns": columns})
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
    if not tables:
        raise ValueError("DDL 未包含可识别的建表语句（需要 CREATE TABLE 与字段定义）")
    if sum(len(x["columns"]) for x in tables) > DDL_MAX_COLUMNS:
        raise ValueError(
            f"DDL 字段数超出限制（上限 {DDL_MAX_COLUMNS} 字段，"
            "可通过 IMPORT_DDL_MAX_COLUMNS 调整）")
    return {"tables": tables, "warnings": warnings, "complete": not warnings}


def effective_dialect(dialect):
    """Resolve vendor aliases (GBase/4A, Hive, ...) once for every sqlglot call.

    ``sqlglot`` rejects vendor names such as ``gbase`` with
    ``ValueError: Unknown dialect``.  Legacy batch parsing passed the raw value
    straight to sqlglot, so the whole file failed even though the statement
    itself parses fine under the compatible grammar.  Returning the resolved
    dialect plus the resolver's warning keeps that fall back explicit instead of
    silently guessing.
    """

    resolution = resolve_dialect(dialect)
    return resolution.effective, ([resolution.warning] if resolution.warning else [])


def parse_file(data, name, kind="auto", dialect=""):
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("单文件大小不能超过 10 MB")
    if name.lower().endswith(".xlsx"):
        return "excel", parse_dictionary(data)
    text = data.decode("utf-8-sig")
    # A script that was switched off by commenting out everything after an
    # unterminated ``/*`` must be reported as "disabled", not as a parser error.
    text, block_warning = truncate_unterminated_block_comment(text)
    block_warnings = [block_warning] if block_warning else []
    # GBase/4A scripts use ``#`` line comments; normalize before any sqlglot call.
    parse_text = strip_hash_comments(text)
    read, dialect_warnings = effective_dialect(dialect)
    # 数据库导出的建表语句经常直接存成 .txt（例如 ``监管集市ddl.txt``）：先按内容
    # 判断是否为 Hive/Spark 方言，再决定是否走 DDL 分支，避免整份文件被误判成脚本。
    ddl_read = read or infer_ddl_dialect(parse_text)
    if kind == "auto":
        if name.lower().endswith(".ddl"):
            kind = "ddl"
        else:
            # 建表语句里常混有 ``CREATE TABLE ... LIKE`` / CTAS 等 sqlglot 无法展开
            # 成字段清单的写法（解析为 Command）。只要出现真正的 CREATE TABLE 且没有
            # DML，就按 DDL 处理：被跳过的语句由 parse_ddl 记入提示，而不是把整份
            # 1000+ 表的文件误判成脚本。
            dml = (exp.Insert, exp.Select, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Merge)
            try:
                statements = [x for x in sqlglot.parse(parse_text, read=ddl_read or None) if x is not None]
                tables = [x for x in statements if isinstance(x, exp.Create) and x.args.get("kind") == "TABLE"]
                has_dml = any(isinstance(x, dml) for x in statements)
                looks_ddl = bool(tables) or bool(re.search(r"(?i)\bCREATE\s+(?:EXTERNAL\s+)?TABLE\b", parse_text))
                kind = "ddl" if looks_ddl and not has_dml else "sql"
            except (sqlglot.errors.ParseError, sqlglot.errors.TokenError, ValueError):
                kind = "sql"
    if kind == "ddl":
        return kind, parse_ddl(text, ddl_read)
    if kind != "sql":
        raise ValueError("不支持的文件类型")
    result = parse_sql_lineage(text, dialect=read)
    warnings = list(block_warnings) + list(dialect_warnings) + list(result.warnings)
    if not result.edges:
        warnings.append("未提取可用血缘规则")
    if re.search(r"\b(EXECUTE|EXEC|PROCEDURE|TEMPORARY)\b|\bSELECT\s+\*", text, re.I):
        warnings.append("动态 SQL、过程、临时表或星号需要人工核验")
    try:
        for statement in sqlglot.parse(parse_text, read=read or None):
            if isinstance(statement, exp.Insert) and not isinstance(statement.this, exp.Schema):
                warnings.append("INSERT 缺少显式目标字段列表，不能确认字段映射完整性")
    except (sqlglot.errors.ParseError, sqlglot.errors.TokenError, ValueError):
        pass
    # 模板变量、INSERT 无显式列清单是"可解释的已知限制"，不是解析缺口：真实跑批脚本
    # 100% 带 ${DATA_DATE}，旧逻辑把它们全判成 complete=False，导致每个文件都要人工
    # 勾选"保留解析缺口"才能应用，批量导入事实上不可用。真正的解析失败/过程/星号仍阻断。
    informational = ("Unknown template variable preserved",
                     "Unknown template variable used as table qualifier dropped")
    blocking = [warning for warning in warnings if not warning.startswith(informational)]
    return "sql", {"rules": [asdict(edge) for edge in result.edges],
        "statements": [asdict(statement) for statement in result.statements],
        "warnings": warnings, "complete": result.parse_status == "parsed" and not blocking, "tables": []}
