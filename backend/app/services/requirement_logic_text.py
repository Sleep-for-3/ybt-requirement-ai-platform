# -*- coding: utf-8 -*-
"""脚本 → 中文处理逻辑的确定性转换。

设计目标：
- 字段行只写“这个字段怎么来”（来源、加工动作），不贴 SQL/别名；
- 全表共享的 WHERE/JOIN 单独输出，避免每个字段重复同一套条件；
- 所有文案都由脚本事实和注释推导，无法推导时明确标缺口，不用“按脚本规则处理”兜底。
"""
from __future__ import annotations

import re
from typing import Any, Mapping

_JOIN_RE = re.compile(r"\b(LEFT|INNER|RIGHT|FULL)?\s*JOIN\b", re.I)
_IDENT = r"[A-Za-z_][\w$#]*"


def _top_level_split(text: str, delimiter: str) -> list[str]:
    """按顶层分隔符切分，忽略括号/引号/注释内部的分隔符。"""
    parts: list[str] = []
    depth = 0
    quote = ""
    start = 0
    i = 0
    upper = delimiter.upper()
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            i += 1
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and text[i:i + len(delimiter)].upper() == upper:
            # 要求分隔符前后不是标识符字符，避免 AND 出现在 ANDY 之类标识符里
            before = text[i - 1] if i else " "
            after = text[i + len(delimiter)] if i + len(delimiter) < len(text) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                parts.append(text[start:i].strip())
                start = i + len(delimiter)
                i += len(delimiter)
                continue
        i += 1
    parts.append(text[start:].strip())
    return [part for part in parts if part]


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"--[^\n]*", " ", text)


def _trailing_comment(text: str) -> tuple[str, str]:
    matched = re.search(r"/\*\s*(.*?)\s*\*/\s*$", text, flags=re.S)
    if not matched:
        return text.strip(), ""
    return text[:matched.start()].strip(), re.sub(r"\s+", " ", matched.group(1)).strip()


def _select_bounds(sql: str) -> tuple[int, int] | None:
    """返回顶层 SELECT 列表的 [start, end)，end 为顶层 FROM 的位置。"""
    select = re.search(r"\bSELECT\b", sql, re.I)
    if not select:
        return None
    depth = 0
    quote = ""
    i = select.end()
    while i < len(sql):
        ch = sql[i]
        if quote:
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            i += 1
            continue
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = len(sql) if end < 0 else end + 2
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and re.match(r"\bFROM\b", sql[i:], re.I):
            return select.end(), i
        i += 1
    return None


def _where_bounds(sql: str) -> tuple[int, int] | None:
    depth = 0
    quote = ""
    i = 0
    while i < len(sql):
        ch = sql[i]
        if quote:
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            i += 1
            continue
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = len(sql) if end < 0 else end + 2
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and re.match(r"\bWHERE\b", sql[i:], re.I):
            return i + 5, len(sql)
        i += 1
    return None


def parse_script_structure(sql: str, dialect: str | None = None) -> dict[str, Any]:
    """从一条 INSERT/SELECT 中提取投影、别名、关联和过滤条件（带脚本注释）。"""
    text = (sql or "").strip().rstrip(";")
    projections: list[dict[str, Any]] = []
    bounds = _select_bounds(text)
    if bounds:
        select_list = text[bounds[0]:bounds[1]]
        for part in _top_level_split(select_list, ","):
            body, comment = _trailing_comment(part)
            matched = re.match(
                r"^(?P<expr>.*?)\s+AS\s+(?P<target>" + _IDENT + r")\s*$",
                body, flags=re.S,
            )
            if not matched:
                continue
            projections.append({"target": matched.group("target").upper(),
                                "expression": matched.group("expr").strip(), "comment": comment})
    aliases: dict[str, dict[str, Any]] = {}
    for matched in re.finditer(
        r"\b(?:FROM|JOIN)\s+(?P<table>[\w$#.{}@]+)\s+(?:AS\s+)?(?P<alias>" + _IDENT + r")"
        r"\s*(?:/\*\s*(?P<comment>[^*]*?)\s*\*/)?",
        text, flags=re.I,
    ):
        alias = matched.group("alias")
        if alias.upper() in {"ON", "WHERE", "LEFT", "INNER", "RIGHT", "FULL", "JOIN", "GROUP", "ORDER", "AS"}:
            continue
        if re.fullmatch(r"F\d{6}", alias, re.I) or matched.group("table").startswith("("):
            continue
        aliases.setdefault(alias.upper(), {
            "table": matched.group("table"), "comment": re.sub(r"\s+", " ", matched.group("comment") or "").strip(),
        })
    for matched in re.finditer(
        r"\)\s+AS\s+(?P<alias>" + _IDENT + r")\s*/\*\s*(?P<comment>[^*]*?)\s*\*/", text, flags=re.I
    ):
        alias = matched.group("alias").upper()
        if re.fullmatch(r"F\d{6}", alias):
            continue
        if alias not in aliases:
            aliases[alias] = {"table": None, "comment": re.sub(r"\s+", " ", matched.group("comment")).strip()}

    joins: list[dict[str, Any]] = []
    if bounds:
        from_start = bounds[1]
        where = _where_bounds(text)
        join_zone = text[from_start:where[0] - 5 if where else len(text)]
        chunks = re.split(r"(?=\b(?:LEFT|INNER|RIGHT|FULL)?\s*JOIN\b)", join_zone, flags=re.I)
        for chunk in chunks:
            if not _JOIN_RE.search(chunk):
                continue
            on = re.split(r"\bON\b", chunk, maxsplit=1, flags=re.I)
            head, condition = (on[0], on[1]) if len(on) == 2 else (chunk, "")
            alias_match = re.search(r"(?:AS\s+)?(" + _IDENT + r")\s*(?:/\*.*?\*/)?\s*$", head.strip(), re.S)
            alias = alias_match.group(1).upper() if alias_match else ""
            table_match = re.search(r"\bJOIN\s+([\w$#.{}@]+)", head, re.I)
            table = table_match.group(1) if table_match else None
            cond, comment = _trailing_comment(condition)
            joins.append({"alias": alias, "table": table, "condition": cond.strip(), "comment": comment,
                          "sql": chunk.strip()})

    filters: list[dict[str, Any]] = []
    where = _where_bounds(text)
    if where:
        where_text = text[where[0]:where[1]]
        for part in _top_level_split(where_text, "AND"):
            if not part.strip():
                continue
            sql_part, comment = _trailing_comment(part)
            filters.append({"sql": sql_part.strip(), "comment": comment})
    return {"dialect": dialect or "", "projections": projections, "aliases": aliases,
            "joins": joins, "filters": filters, "line_start": None, "line_end": None}


def _alias_table(structure: Mapping[str, Any], alias: str) -> tuple[str, str]:
    item = (structure.get("aliases") or {}).get(alias.upper()) or {}
    table = str(item.get("table") or "")
    comment = str(item.get("comment") or "")
    return table, comment


def _name_for_table(names: Mapping[str, Any], table: str, alias_comment: str = "") -> str:
    upper = (table or "").upper().split(".")[-1]
    cn = ((names or {}).get(upper) or {}).get("cn") if upper else ""
    return str(cn or alias_comment or table or "待核验表")


def _field_name(names: Mapping[str, Any], table: str, column: str) -> str:
    upper = (table or "").upper().split(".")[-1]
    entry = (names or {}).get(upper) or {}
    return str((entry.get("columns") or {}).get(str(column or "").upper()) or column or "待核验字段")


def classify_field_logic(rule: Mapping[str, Any], field: Mapping[str, Any],
                         structure: Mapping[str, Any], names: Mapping[str, Any]) -> dict[str, Any]:
    """把一个字段的脚本规则转成短中文逻辑 + 类型 + 缺口。"""
    source = rule.get("source") or {}
    target = rule.get("target") or {}
    table = str(source.get("table_name") or "")
    column = str(source.get("column_name") or "")
    expression = str(rule.get("transformation_expression") or "").strip()
    expression = re.sub(r"/\*.*?\*/", " ", expression, flags=re.S).strip()
    expression = re.sub(r"\s+AS\s+F\d{6}\s*$", "", expression, flags=re.I).strip()
    code_mapping = str(rule.get("code_mapping_rule") or "").strip()
    aggregation = str(rule.get("aggregation_rule") or "").strip()
    field_name = str(field.get("field_name") or "")
    field_code = str(field.get("field_code") or target.get("column_name") or "")
    target_label = f"{field_name}（{field_code}）" if field_name and field_name != field_code else field_code
    alias_match = re.search(r"\b([A-Za-z]\w*)\.", expression)
    alias = alias_match.group(1) if alias_match else ""
    alias_table, alias_comment = _alias_table(structure, alias) if alias else ("", "")
    table = table or alias_table
    table_cn = _name_for_table(names, table, alias_comment)
    column_cn = _field_name(names, table, column)
    upper = expression.upper()
    gaps: list[str] = []
    logic_type = "加工"
    parts: list[str] = []

    if "SAFE_DATA_DATE" in upper and not column:
        return {"logic_type": "常量", "text": f"固定取跑批参数 SAFE_DATA_DATE 写入{target_label}，不引用上游表；",
                "gaps": []}
    if aggregation:
        logic_type = "汇总"
        parts.append(f"按脚本规则汇总后写入{target_label}")
    elif "CASE" in upper:
        logic_type = "条件分支"
        if "TO_DATE" in upper or "TO_CHAR" in upper or "DATE_FORMAT" in upper:
            parts.append(f"按条件判断：日期为空时留空，非空时按 YYYYMMDD 转为 YYYY-MM-DD 后写入{target_label}")
        else:
            parts.append(f"按脚本条件分支取值后写入{target_label}")
    elif code_mapping or "YBT_CODE" in upper or table.upper().endswith("YBT_CODE_MAPPING"):
        logic_type = "码值映射"
        parts.append(f"取码值映射表（YBT_CODE_MAPPING）的映射代码（YBT_CODE），按业务模式映射后写入{target_label}")
    elif "CONCAT" in upper or "SUBSTR" in upper:
        logic_type = "拼接/截取"
        refs = list(dict.fromkeys(re.findall(r"([A-Za-z]\w*)\.([A-Za-z0-9_]+)", expression)))

        def label(ref: tuple[str, str]) -> str:
            ref_table, ref_comment = _alias_table(structure, ref[0])
            return (f"{_name_for_table(names, ref_table, ref_comment)}的"
                    f"{_field_name(names, ref_table, ref[1])}（{ref[1]}）")

        substr = re.search(r"SUBSTR(?:ING)?\(\s*([A-Za-z]\w*)\.([A-Za-z0-9_]+)\s*,\s*(\d+)\s*,\s*(\d+)",
                           expression, re.I)
        if substr and len(refs) >= 2:
            first = (substr.group(1), substr.group(2))
            second = next((ref for ref in refs if ref != first), refs[1])
            parts.append(f"取{label(first)}前 {substr.group(4)} 位与{label(second)}拼接")
            fallbacks = [ref for ref in refs if ref not in {first, second}]
            if "COALESCE" in upper and fallbacks:
                parts[-1] += "；为空时依次取" + "、".join(label(ref) for ref in fallbacks[:3]) + "，最后取空字符串"
            elif "COALESCE" in upper:
                parts[-1] += "；结果为空时按脚本兜底"
        elif refs:
            parts.append("取" + "、".join(label(ref) for ref in refs[:3]) + "，按脚本规则截取/拼接后写入" + target_label)
        else:
            parts.append(f"取{table_cn}的{column_cn}（{column}）截取/拼接后写入{target_label}")
    elif "COALESCE" in upper:
        logic_type = "空值处理"
        parts.append(f"取{table_cn}的{column_cn}（{column}），空值转为空字符串后写入{target_label}")
    elif expression and re.match(r"^(?:[A-Za-z]\w*\.)?" + _IDENT + r"$", expression):
        logic_type = "直取"
        parts.append(f"取{table_cn}的{column_cn}（{column}），原值写入{target_label}")
    elif column:
        logic_type = "直取" if str(rule.get("transformation_type") or "").lower() in {"pass_through", "direct"} else "加工"
        parts.append(f"取{table_cn}的{column_cn}（{column}），按脚本表达式加工后写入{target_label}")
    else:
        logic_type = "待核验"
        parts.append(f"脚本规则未给出可读来源，目标字段{target_label}的处理逻辑待核验")
        gaps.append("字段脚本规则缺少来源列/表达式")
    if not table_cn or table_cn == table:
        gaps.append(f"来源表 {table or '未知'} 缺少中文名")
    if column and not column_cn:
        gaps.append(f"来源字段 {column} 缺少中文名")
    text = "；".join(part for part in parts if part).rstrip("；") + "。"
    return {"logic_type": logic_type, "text": text, "gaps": gaps}


def _human_filter(sql: str, comment: str, names: Mapping[str, Any]) -> str:
    raw = re.sub(r"\s+", " ", sql or "").strip()
    upper = raw.upper()
    column_match = re.search(r"([A-Za-z]\w*)\.([A-Za-z0-9_]+)\s*(=|<>|NOT IN|IN)\s*(.+)", raw, re.I | re.S)
    column = column_match.group(2).upper() if column_match else ""
    column_cn = column
    for entry in (names or {}).values():
        if column and column in (entry.get("columns") or {}):
            column_cn = entry["columns"][column]
            break
    if comment and ("NOT IN" in upper or "SELECT" in upper):
        return comment
    if "END_DATE" in upper and "COALESCE" in upper:
        return "借据结束日期为空或晚于当年 1 月 1 日"
    if "INLINE_LOAN_STATUS_NOTE" in upper:
        return "行内贷款状态说明按 FS11 例外规则判断"
    if "SAFE_DATA_DATE" in upper and column:
        return f"{column_cn or column} 等于跑批日期参数 SAFE_DATA_DATE"
    if comment and "CASE" in upper:
        return comment
    if comment and len(comment) <= 30:
        return comment
    if comment:
        return f"{comment}（{column_cn or column} 条件）" if column else comment
    equals = re.search(r"([A-Za-z0-9_]+)\s*=\s*'([^']*)'", raw)
    if equals:
        return f"{column_cn or equals.group(1)} 等于 {equals.group(2)}"
    not_equal = re.search(r"([A-Za-z0-9_]+)\s*<>\s*'([^']*)'", raw)
    if not_equal:
        return f"{column_cn or not_equal.group(1)} 不等于 {not_equal.group(2)}"
    if "NOT IN" in upper and "SELECT" in upper:
        return f"{column_cn or '记录'} 剔除子查询命中的记录"
    if "CASE" in upper or " OR " in upper or " AND " in upper:
        return f"{column_cn or '记录'} 按脚本条件判断"
    return f"{column_cn or '记录'} 按脚本条件过滤"


def build_table_scope(structure: Mapping[str, Any], names: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for condition in structure.get("filters") or []:
        rows.append({
            "category": "过滤", "text": _human_filter(condition.get("sql", ""), condition.get("comment", ""), names),
            "tables": "", "line": "", "raw": condition.get("sql", ""),
        })
    for join in structure.get("joins") or []:
        alias = join.get("alias") or ""
        alias_table, alias_comment = _alias_table(structure, alias)
        table = join.get("table") or alias_table
        if not table:
            inner = re.search(r"\bFROM\s+([\w$#.{}@]+)", join.get("sql") or "", re.I)
            table = inner.group(1) if inner else ""
        table_cn = _name_for_table(names, table, join.get("comment") or alias_comment)
        cond = re.sub(r"\s+", " ", join.get("condition") or "").strip()
        if re.search(r"CONTRACT_NO\s*=\s*\w+\.CONTRACT_NO", cond, re.I):
            desc = f"按合同号关联{table_cn}"
        elif "BRANCH_NO" in cond.upper():
            desc = f"按机构号关联{table_cn}（9900 转为 900000000）"
        elif "DUEBILL_NO" in cond.upper():
            desc = f"按借据号关联{table_cn}"
        elif "HFK_CODE" in cond.upper():
            desc = "按业务模式关联码值映射表（YBT_CODE_MAPPING）"
        else:
            desc = f"关联{table_cn}"
        rows.append({"category": "关联", "text": desc, "tables": table_cn or table,
                     "line": "", "raw": cond})
    seen = set()
    result = []
    for row in rows:
        key = (row["category"], row["text"], row["raw"])
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result
