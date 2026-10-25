"""把冻结的需求内容导出成"一表通调研表式"需求文档（与客户示例同一版式）。

客户示例 `需求文档输出示例.xlsx` 的版式是：表级信息若干行，然后是**按来源系统重复**的
列组——每个来源系统一组"业务口径-<系统>"（6 列）加一组"溯源-<系统>"（9 列），
数据项每个一行、在各组里填写。

本模块只做版式与取值映射，不生成内容：正文全部来自冻结内容（业务口径、技术正文、
集市映射、脚本血缘），缺什么就写"待业务补充"，不猜测。

分组依据来自冻结内容里的集市映射：`HYF_` 前缀（监管集市）与 `BL_YBT_` 前缀（补录平台）
各自成组。真实模板里有一类字段的集市列写的是表达式（如 `SUBSTR(...)||BRANCH_NO`）或
多表拼接（`HYF_A||HYF_B`），Apply 时不会建出 MartField，冻结内容里也就没有标准的
`中文名(编码)` 摘要——这类字段按映射文本里出现的前缀归组；连前缀也没有的，归入
"未登记来源"，**不默认成补录平台**（那等于替业务声明"只能人工补录"）。
"""

from __future__ import annotations

import re

from app.services.office_determinism import normalize_office_bytes
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Mapping

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# 渲染器行为变化必须升版：产物身份（render_identity）含 renderer_version，
# 否则改了版式却命中旧产物，正式文件内容与代码不一致。
SURVEY_DOC_VERSION = "survey-requirement-doc-v9"

#: 表级信息：键 -> (标签, 取值来源)
#: 表级信息：键 -> (标签, 主取值路径, 备选取值路径)。
#: 备选路径是“模板里本来就有的事实”：调研表“表级口径”sheet 的主题/填报说明/报送数据域。
#: 顺序上仍然优先用需求侧填写的口径（人确认过的更权威），需求侧没填才回退模板事实，
#: 两边都没有才写“待业务补充”——不能把模板已有信息丢掉，也不能用模板去覆盖人工口径。
_TABLE_HEADERS = (
    ("data_category", "数据分类", ("target_table", "data_category"), None),
    ("subject", "数据主题名称", ("target_table", "theme"), ("scenario", "scenario_name")),
    ("table_name", "数据表名称", ("target_table", "table_name"), None),
    ("collect_scope", "采集范围", ("requirement", "inclusion"), ("target_table", "filing_note")),
    ("report_scope", "一表通报送范围确认", ("requirement", "objective"), ("target_table", "reporting_domain_name")),
    ("east_diff", "与EAST报送范围差异", ("requirement", "exclusion"), None),
)

#: 一表通基础信息与业务口径（A–K），对应示例第 11 行左半部分。
_BASE_COLUMNS = (
    ("field_code", "数据项编码", 12),
    ("field_name", "数据项名称", 16),
    ("data_category", "数据类别", 12),
    ("data_format", "数据格式", 12),
    ("regulatory_original_definition", "字段业务定义\n（监管原始口径）", 46),
    ("regulatory_refined_definition", "字段业务定义\n（监管定义细化）", 40),
    ("report_name", "报表名称", 16),
    ("report_field_name", "字段名称", 16),
    ("east_definition", "EAST口径", 28),
    ("internal_definition", "字段业务定义\n（行内）", 34),
    ("remarks", "备注", 26),
)

#: 每个来源系统的业务口径组（6 列）。
_BUSINESS_COLUMNS = (
    ("business_definition", "字段业务定义", 40),
    ("screenshot", "源系统截图", 14),
    ("system_change", "源系统改造", 14),
    ("external_data", "外部数据", 14),
    ("manual_entry", "手工补录", 12),
    ("business_confirmer", "业务口径确认人", 16),
)

#: 每个来源系统的溯源组（9 列），对应示例 R–Z。
_SOURCE_COLUMNS = (
    ("source_system", "来源系统", 16),
    ("source_table_code", "来源表英文名", 26),
    ("source_table_name", "来源表中文名", 24),
    ("source_field_code", "来源字段英文名", 26),
    ("source_field_name", "来源字段中文名", 20),
    ("source_logic", "处理逻辑", 32),
    ("source_logic_type", "处理逻辑类型", 14),
    ("technical_confirmer", "技术口径确认人", 16),
    ("source_remark", "备注", 18),
)

_HEADER_FILL = PatternFill("solid", fgColor="D9E1F2")
_GROUP_FILL = PatternFill("solid", fgColor="F2F2F2")
_LABEL_FILL = PatternFill("solid", fgColor="FCE4D6")
_THIN = Side(style="thin", color="B4B4B4")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_WRAP = Alignment(wrap_text=True, vertical="top")
_CENTER = Alignment(wrap_text=True, vertical="center", horizontal="center")

_SUMMARY_PATTERN = re.compile(r"^(?P<name>.*?)[（(](?P<code>[^（()）]*)[）)]\s*$")

#: 来源系统分组：(系统名, 表编码前缀)。顺序即列组顺序。
_SYSTEM_GROUPS = (
    ("监管集市", "HYF_"),
    ("补录平台", "BL_YBT_"),
)
_UNREGISTERED_GROUP = "未登记来源"
#: 有脚本血缘、无集市映射的字段：值由跑批脚本直接产出。
_SCRIPT_GROUP = "跑批脚本"
_EMPTY_SOURCE_VALUES = {key: "" for key, _, _ in _SOURCE_COLUMNS}


def _text(value: Any, default: str = "待业务补充") -> str:
    if value in (None, "", []):
        return default
    return str(value)


def _dig(data: Mapping[str, Any] | None, path: Iterable[str]) -> Any:
    current: Any = data or {}
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _split_summary(value: Any) -> tuple[str, str]:
    """把 `信贷借据信息表(HYF_LN_DUEBILL_INFO)` 拆成（中文名, 编码）。

    冻结内容里的集市摘要就是这种"中文名(编码)"形态；拆不出来时整串当中文名，编码留空，
    不猜前缀。
    """
    text = str(value or "").strip()
    match = _SUMMARY_PATTERN.match(text)
    if not match:
        return text, ""
    return match.group("name").strip(), match.group("code").strip()


def _group_for(mapping: Mapping[str, Any] | None) -> str:
    """判断一条集市映射属于哪个来源系统。

    优先用 `中文名(编码)` 摘要里的编码；摘要被表达式/多表拼接污染时退回扫描映射文本
    （真实模板里 `集市表英文名` 就是这种形态）。都没有前缀时归"未登记来源"，不做默认。
    """
    data = mapping or {}
    code = " ".join(
        (
            _split_summary(data.get("mart_table_summary"))[1],
            _split_summary(data.get("mart_field_summary"))[1],
        )
    ).upper()
    text = " ".join(
        str(data.get(key) or "")
        for key in ("mart_table_summary", "mart_field_summary", "business_rule", "final_content")
    ).upper()
    for name, prefix in _SYSTEM_GROUPS:
        if prefix in code or prefix in text:
            return name
    return _UNREGISTERED_GROUP


def _script_rules_by_target(content: Mapping[str, Any]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    basis = content.get("script_basis") or {}
    pool = basis.get("condition_texts") or {}
    for rule in basis.get("rules") or []:
        target = rule.get("target") or {}
        column = str(target.get("column_name") or "")
        if not column:
            continue
        resolved = dict(rule)
        for key in (
            "transformation_expression",
            "join_condition",
            "filter_condition",
            "aggregation_rule",
            "code_mapping_rule",
        ):
            ref = rule.get(f"{key}_ref")
            # 投影后的规则可能显式把长文本置空并改成 `*_ref`：值为空时也要还原，
            # 否则导出文档的"脚本加工逻辑"会整列为空。
            if ref and not resolved.get(key):
                resolved[key] = pool.get(ref) or ""
        grouped.setdefault(column, []).append(resolved)
    return grouped


def _script_columns(rules: list[dict]) -> tuple[str, str]:
    """汇总某目标字段的脚本事实：来源列清单 + 可读的处理逻辑。

    真实脚本里同一个目标字段可能由几十条血缘边（多个 UNION 分支 + 大量 join/filter）
    共同决定，把全部条件原文塞进单元格既不可读也会撑爆列宽。这里只保留**第一条取值
    表达式**（真正说明"这个字段怎么算出来"）、码值映射原文，其余条件按条数注明，
    需要细节的人去看脚本血缘证据。
    """
    sources: list[str] = []
    expressions: list[str] = []
    code_mappings: list[str] = []
    conditions = 0
    for rule in rules:
        source = rule.get("source") or {}
        table = str(source.get("table_name") or "")
        column = str(source.get("column_name") or "")
        label = f"{table}.{column}" if column else table
        if label and label not in sources:
            sources.append(label)
        expression = (rule.get("transformation_expression") or "").strip()
        if expression and expression not in expressions:
            expressions.append(expression)
        mapping = (rule.get("code_mapping_rule") or "").strip()
        if mapping and mapping not in code_mappings:
            code_mappings.append(mapping)
        if (rule.get("join_condition") or "").strip() or (
            rule.get("filter_condition") or ""
        ).strip():
            conditions += 1
    parts: list[str] = []
    if expressions:
        parts.append(expressions[0])
        if len(expressions) > 1:
            parts.append(f"（另有 {len(expressions) - 1} 个分支表达式见脚本血缘）")
    if code_mappings:
        parts.append("码值映射：" + code_mappings[0])
    if conditions:
        parts.append(f"关联/过滤条件 {conditions} 条，见脚本血缘证据")
    logic = "\n".join(parts)
    if len(logic) > 800:
        logic = logic[:800] + "…（已截断，完整规则见脚本血缘证据）"
    return "；".join(sources), logic


def _logic_type(rule_text: str) -> str:
    if not rule_text:
        return "直取"
    if any(token in rule_text for token in ("直取", "直接取", "直接取值", "同名字段")):
        return "直取"
    return "加工"


def _groups_in_use(
    fields: list[Mapping[str, Any]], rules_by_target: Mapping[str, list[dict]] | None = None
) -> list[str]:
    rules_by_target = rules_by_target or {}
    used: list[str] = []
    for record in fields:
        mappings = record.get("mart_mappings") or []
        code = str((record.get("field") or {}).get("field_code") or "")
        if mappings:
            names = {_group_for(m) for m in mappings}
        elif rules_by_target.get(code):
            # 有脚本血缘、没有集市映射：值由跑批脚本直接产出，来源是脚本而不是某个集市表。
            # 归"补录平台"是编造（脚本并不读补录表），归"未登记来源"又会掩盖已有的脚本事实。
            names = {_SCRIPT_GROUP}
        else:
            names = {_UNREGISTERED_GROUP}
        for name in sorted(names):
            if name not in used:
                used.append(name)
    ordered = [name for name, _ in _SYSTEM_GROUPS if name in used]
    for name in used:
        if name not in ordered:
            ordered.append(name)
    return ordered or [_UNREGISTERED_GROUP]


def _only_group_for(
    record: Mapping[str, Any], rules_by_target: Mapping[str, list[dict]]
) -> str:
    """无集市映射的字段属于哪个组：有脚本血缘→跑批脚本，否则→未登记来源。"""
    code = str((record.get("field") or {}).get("field_code") or "")
    return _SCRIPT_GROUP if rules_by_target.get(code) else _UNREGISTERED_GROUP


def _mappings_for_group(record: Mapping[str, Any], group: str) -> list[Mapping[str, Any]]:
    """同一来源系统可能给出多个集市字段（例如机构 ID 由机构表与信用证表各出一段）。

    只取第一条会把"拼接/多来源"的需求写成单来源，这是事实性错误；因此同组多条
    在单元格内用换行并列，而不是丢弃。
    """

    return [m for m in record.get("mart_mappings") or [] if _group_for(m) == group]


def _mapping_for_group(
    record: Mapping[str, Any], group: str
) -> Mapping[str, Any] | None:
    return next(iter(_mappings_for_group(record, group)), None)


def _business_values(
    record: Mapping[str, Any], group: str, mapping: Mapping[str, Any] | None
) -> dict[str, str]:
    business = record.get("business") or {}
    definition = (
        business.get("business_definition")
        or business.get("final_content")
        or (mapping or {}).get("final_content")
        or ""
    )
    return {
        # 正文为空时写"待业务补充"而不是留白：空白单元格在交付评审里会被当成漏排，
        # 占位符能把责任交回业务方；无映射的列组仍整组留空（见 _EMPTY_SOURCE_VALUES）。
        "business_definition": _text(definition),
        "screenshot": "",
        "system_change": "",
        "external_data": "",
        # 手工补录只能来自显式映射事实：真实模板里绝大多数行并没有补录标记，
        # 写死"否"等于替业务确认"不需要补录"，所以没有事实就留空。
        "manual_entry": "是" if str((mapping or {}).get("is_manual") or "").lower() in {"1", "true", "yes", "是"} else "",
        "business_confirmer": _text(
            business.get("confirmed_by") or business.get("reviewed_by"), ""
        ),
    }


def _source_values(
    record: Mapping[str, Any],
    group: str,
    mappings: list[Mapping[str, Any]],
    script_logic: str,
    script_sources: str = "",
) -> dict[str, str]:
    if not mappings:
        # 没有集市映射：来源表/字段只能来自脚本事实（"表.字段"清单），不能编造。
        tables: list[str] = []
        columns: list[str] = []
        for item in (script_sources or "").split("；"):
            label = item.strip()
            if not label:
                continue
            table, _, column = label.partition(".")
            if table and table not in tables:
                tables.append(table)
            if column and column not in columns:
                columns.append(column)
        # 来源系统只能写平台确实知道的事实：来自脚本事实时写"跑批脚本"，连脚本事实都没有时留空；
        # 绝不能把分组名（如"未登记来源"）当成来源系统写进去，那等于替业务声明存在一个叫这个名字的系统。
        known_source_system = "跑批脚本" if (tables or columns or script_logic) else ""
        return {
            **_EMPTY_SOURCE_VALUES,
            "source_system": known_source_system,
            "source_table_code": "\n".join(tables),
            "source_field_code": "\n".join(columns),
            "source_logic": script_logic,
            "source_logic_type": _logic_type(script_logic) if script_logic else "",
        }
    table_names: list[str] = []
    table_codes: list[str] = []
    field_names: list[str] = []
    field_codes: list[str] = []
    logics: list[str] = []
    confirmers: list[str] = []
    remarks: list[str] = []
    for mapping in mappings:
        table_name, table_code = _split_summary(mapping.get("mart_table_summary"))
        field_name, field_code = _split_summary(mapping.get("mart_field_summary"))
        table_names.append(table_name or table_code)
        table_codes.append(table_code or table_name)
        field_names.append(field_name or field_code)
        field_codes.append(field_code or field_name)
        rule_text = _text(
            mapping.get("business_rule")
            or mapping.get("final_content")
            or mapping.get("ai_generated_content"),
            "",
        )
        logics.append(rule_text or script_logic)
        confirmers.append(_text(mapping.get("reviewed_by"), ""))
        remarks.append(_text(mapping.get("open_questions"), ""))
    logic = "\n".join(item for item in dict.fromkeys(logics) if item)
    return {
        "source_system": group,
        "source_table_code": "\n".join(item for item in table_codes if item),
        "source_table_name": "\n".join(item for item in table_names if item),
        "source_field_code": "\n".join(item for item in field_codes if item),
        "source_field_name": "\n".join(item for item in field_names if item),
        "source_logic": logic,
        "source_logic_type": _logic_type(logic),
        "technical_confirmer": "\n".join(item for item in dict.fromkeys(confirmers) if item),
        "source_remark": "\n".join(item for item in dict.fromkeys(remarks) if item),
    }



def _completeness_rows(
    fields: list[Mapping[str, Any]],
    rules_by_target: Mapping[str, list[Mapping[str, Any]]],
) -> list[tuple[str, str]]:
    """交付完整度统计：只统计冻结内容里已有的事实，缺什么就写缺。

    真实评审打开文档第一件事是"这份文档覆盖了多少、哪些还是要人补"。把它写在文档末尾，
    比让人逐字段数更可靠；但统计本身不能替业务确认，所以标题必须写明这一点。
    """
    total = len(fields)
    with_business = 0
    with_mapping = 0
    multi_source = 0
    script_only = 0
    unregistered = 0
    for record in fields:
        business = record.get("business") or {}
        if str(business.get("business_definition") or "").strip():
            with_business += 1
        mappings = record.get("mart_mappings") or []
        field_code = str((record.get("field") or {}).get("field_code") or "")
        if mappings:
            with_mapping += 1
            if len(mappings) > 1:
                multi_source += 1
        elif rules_by_target.get(field_code):
            script_only += 1
        else:
            unregistered += 1
    return [
        ("字段总数", str(total)),
        ("有业务口径正文", f"{with_business}（待补 {total - with_business}）"),
        ("有集市映射", str(with_mapping)),
        ("多来源字段（≥2 条映射）", str(multi_source)),
        ("仅跑批脚本直接产出", str(script_only)),
        ("未登记来源字段", str(unregistered)),
    ]

def _renderer_fingerprint() -> str:
    """渲染器源码指纹：渲染器行为改了但忘了升 SURVEY_DOC_VERSION 时，渲染身份仍会变。

    真实事故：同一 SURVEY_DOC_VERSION 下改了版式，导出继续命中旧产物，正式文件与代码不一致
    （本轮第二次踩到：来源说明改了、版本号没动，导出拿回的仍是旧产物）。指纹是兜底，
    语义版本号仍必须按规范手动升。
    """
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
    except OSError:  # pragma: no cover - 源码被删/不可读时不让导出整条失败
        return "unknown"


RENDERER_FINGERPRINT = _renderer_fingerprint()


def renderer_version() -> str:
    """对外声明的渲染器版本：语义版本 + 源码指纹。"""
    return f"{SURVEY_DOC_VERSION}+{RENDERER_FINGERPRINT}"


def _source_notes(
    fields: list[Mapping[str, Any]],
    groups: list[str],
    rules_by_target: Mapping[str, list[Mapping[str, Any]]],
) -> list[str]:
    """来源说明：把"空白单元格代表什么"写清楚，避免评审把留空当成"未核实"或"否"。

    只陈述冻结内容里能数出来的事实：哪个来源组覆盖几个字段、多少个字段只有脚本、
    多少个字段连来源都没有、多来源要业务确认。不做业务判断。
    """
    total = len(fields)
    script_only = 0
    unregistered = 0
    per_group: dict[str, int] = {group: 0 for group in groups}
    multi = 0
    for record in fields:
        mappings = record.get("mart_mappings") or []
        field_code = str((record.get("field") or {}).get("field_code") or "")
        if mappings:
            if len(mappings) > 1:
                multi += 1
            for group in {_group_for(m) for m in mappings}:
                per_group[group] = per_group.get(group, 0) + 1
            continue
        only = _only_group_for(record, rules_by_target)
        if only == _SCRIPT_GROUP and rules_by_target.get(field_code):
            script_only += 1
        elif only == _UNREGISTERED_GROUP:
            unregistered += 1
        per_group[only] = per_group.get(only, 0) + 1
    notes = [
        f"本表共 {total} 个字段；其中 {script_only} 个字段由跑批脚本直接产出（不经过集市表），"
        f"{unregistered} 个字段既没有集市映射也没有脚本血缘，来源需人工补充。",
    ]
    for group in groups:
        covered = per_group.get(group, 0)
        if group == _UNREGISTERED_GROUP:
            notes.append(
                f"「业务口径-{group}」与「溯源-{group}」覆盖 {covered} 个字段：既有完全没有来源的字段，"
                "也有带集市映射但来源系统前缀未识别的字段（溯源列会照抄映射原文）。"
            )
        else:
            notes.append(f"「业务口径-{group}」与「溯源-{group}」覆盖 {covered} 个字段。")
    notes.append("列组留空表示该字段不来自该来源系统；留空不等于“否”，也不代表已经核实。")
    if multi:
        notes.append(
            f"有 {multi} 个字段来自多个集市字段（单元格内并列显示），取数口径需业务确认，不能默认取第一条。"
        )
    return notes


def export_survey_document(content: Mapping[str, Any]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "需求文档"

    all_fields = list(content.get("fields") or [])
    fields = [
        record for record in all_fields if (record.get("field") or {}).get("field_code")
    ]
    rules_by_target = _script_rules_by_target(content)
    groups = _groups_in_use(all_fields, rules_by_target)

    sheet.cell(row=1, column=1, value="返回目录")

    row = 3
    for _, label, path, fallback in _TABLE_HEADERS:
        label_cell = sheet.cell(row=row, column=1, value=label)
        label_cell.font = Font(bold=True)
        label_cell.fill = _LABEL_FILL
        label_cell.border = _BORDER
        label_cell.alignment = _CENTER
        sheet.merge_cells(
            start_row=row, start_column=3, end_row=row, end_column=len(_BASE_COLUMNS)
        )
        raw_value = _dig(content, path)
        # 注意：_text() 对空值会返回默认占位“待业务补充”，所以这里必须判原始值，
        # 不能用 not _text(raw_value)（那永远为假，备选路径永远不会生效）。
        if raw_value in (None, "", []) and fallback is not None:
            raw_value = _dig(content, fallback)
        value_cell = sheet.cell(row=row, column=3, value=_text(raw_value))
        value_cell.alignment = _WRAP
        value_cell.border = _BORDER
        row += 1

    # 分组标题行（示例第 10 行）：基础信息 + EAST 同源映射 + 每个系统两组
    title_row = row + 1
    base_span = 6  # A–F：一表通数据基础信息
    sheet.merge_cells(
        start_row=title_row, start_column=1, end_row=title_row, end_column=base_span
    )
    sheet.cell(row=title_row, column=1, value="一表通数据基础信息").fill = _GROUP_FILL
    sheet.merge_cells(
        start_row=title_row,
        start_column=base_span + 1,
        end_row=title_row,
        end_column=len(_BASE_COLUMNS),
    )
    sheet.cell(
        row=title_row, column=base_span + 1, value="EAST5.0同源映射列"
    ).fill = _GROUP_FILL
    column = len(_BASE_COLUMNS) + 1
    for group in groups:
        sheet.merge_cells(
            start_row=title_row,
            start_column=column,
            end_row=title_row,
            end_column=column + len(_BUSINESS_COLUMNS) - 1,
        )
        sheet.cell(
            row=title_row, column=column, value=f"业务口径-{group}"
        ).fill = _GROUP_FILL
        column += len(_BUSINESS_COLUMNS)
        sheet.merge_cells(
            start_row=title_row,
            start_column=column,
            end_row=title_row,
            end_column=column + len(_SOURCE_COLUMNS) - 1,
        )
        sheet.cell(row=title_row, column=column, value=f"溯源-{group}").fill = _GROUP_FILL
        column += len(_SOURCE_COLUMNS)

    header_row = title_row + 1
    headers = [label for _, label, _ in _BASE_COLUMNS]
    widths = [width for _, _, width in _BASE_COLUMNS]
    for _ in groups:
        headers.extend(label for _, label, _ in _BUSINESS_COLUMNS)
        widths.extend(width for _, _, width in _BUSINESS_COLUMNS)
        headers.extend(label for _, label, _ in _SOURCE_COLUMNS)
        widths.extend(width for _, _, width in _SOURCE_COLUMNS)
    for index, (label, width) in enumerate(zip(headers, widths), start=1):
        cell = sheet.cell(row=header_row, column=index, value=label)
        cell.font = Font(bold=True)
        cell.fill = _HEADER_FILL
        cell.alignment = _CENTER
        cell.border = _BORDER
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.row_dimensions[header_row].height = 42

    data_row = header_row + 1
    for record in fields:
        field = record.get("field") or {}
        field_code = str(field.get("field_code") or "")
        script_sources, script_logic = _script_columns(rules_by_target.get(field_code, []))
        row_values = [
            field_code,
            _text(field.get("field_name"), ""),
            _text(field.get("data_category"), ""),
            _text(field.get("data_format"), ""),
            _text(
                field.get("regulatory_original_definition") or field.get("field_definition"),
                "",
            ),
            _text(field.get("regulatory_refined_definition"), ""),
            _text(field.get("report_name"), ""),
            _text(field.get("report_field_name"), ""),
            _text(field.get("east_definition"), ""),
            _text(field.get("internal_definition"), ""),
            _text(field.get("remarks"), ""),
        ]
        mappings = record.get("mart_mappings") or []
        for group in groups:
            group_mappings = _mappings_for_group(record, group)
            # 该字段在这个来源系统里没有映射且项目里确有集市映射时整组留空：空着是
            # "没有这项来源"，写"否"或占位会把未映射说成已核实。
            # 有映射但这一组没有 → 整组留空（空着是"没有这项来源"）；
            # 整条字段都没有映射时，只给它自己的来源组填内容，别的组留空。
            field_group = None if mappings else _only_group_for(record, rules_by_target)
            if not group_mappings and (mappings or group != field_group):
                row_values.extend("" for _ in _BUSINESS_COLUMNS)
                row_values.extend("" for _ in _SOURCE_COLUMNS)
                continue
            business = _business_values(record, group, group_mappings[0] if group_mappings else None)
            source = _source_values(record, group, group_mappings, script_logic, script_sources)
            row_values.extend(business[key] for key, _, _ in _BUSINESS_COLUMNS)
            row_values.extend(source[key] for key, _, _ in _SOURCE_COLUMNS)
        for index, value in enumerate(row_values, start=1):
            cell = sheet.cell(row=data_row, column=index, value=value)
            cell.alignment = _WRAP
            cell.border = _BORDER
        sheet.row_dimensions[data_row].height = 96
        data_row += 1

    # 交付完整度：写在数据之后，避免打乱监管模板的固定版式（表级信息 6 行 + 数据表）。
    completeness_rows = _completeness_rows(fields, rules_by_target)
    footer_row = data_row + 1
    title_cell = sheet.cell(row=footer_row, column=1, value="交付完整度（自动统计，不替代业务确认）")
    title_cell.font = Font(bold=True)
    title_cell.fill = _HEADER_FILL
    title_cell.border = _BORDER
    for column in range(2, len(headers) + 1):
        cell = sheet.cell(row=footer_row, column=column, value=None)
        cell.fill = _HEADER_FILL
        cell.border = _BORDER
    footer_row += 1
    for label, value in completeness_rows:
        label_cell = sheet.cell(row=footer_row, column=1, value=label)
        label_cell.font = Font(bold=True)
        label_cell.border = _BORDER
        label_cell.alignment = _WRAP
        value_cell = sheet.cell(row=footer_row, column=2, value=value)
        value_cell.alignment = _WRAP
        value_cell.border = _BORDER
        for column in range(3, min(len(headers), 11) + 1):
            sheet.cell(row=footer_row, column=column).border = _BORDER
        sheet.merge_cells(start_row=footer_row, start_column=2, end_row=footer_row, end_column=min(len(headers), 11))
        footer_row += 1

    # 来源说明：解释列组留空的含义，防止"空白"被读成"已核实"。
    notes_title_row = footer_row + 1
    notes_title = sheet.cell(row=notes_title_row, column=1, value="来源说明（自动统计，不替代业务确认）")
    notes_title.font = Font(bold=True)
    notes_title.fill = _HEADER_FILL
    notes_title.border = _BORDER
    for column in range(2, len(headers) + 1):
        cell = sheet.cell(row=notes_title_row, column=column, value=None)
        cell.fill = _HEADER_FILL
        cell.border = _BORDER
    notes_row = notes_title_row + 1
    for note in _source_notes(fields, groups, rules_by_target):
        note_cell = sheet.cell(row=notes_row, column=1, value=note)
        note_cell.alignment = _WRAP
        note_cell.border = _BORDER
        sheet.merge_cells(start_row=notes_row, start_column=1, end_row=notes_row, end_column=min(len(headers), 11))
        for column in range(2, min(len(headers), 11) + 1):
            sheet.cell(row=notes_row, column=column).border = _BORDER
        notes_row += 1

    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=3)
    buffer = BytesIO()
    workbook.save(buffer)
    # openpyxl 会把当前时间写进 docProps/core.xml 与 zip 条目头：跨秒导出会得到
    # 不同字节，冻结产物因此失去意义（真实事故见 office_determinism 模块说明）。
    return normalize_office_bytes(buffer.getvalue())


__all__ = ["RENDERER_FINGERPRINT", "SURVEY_DOC_VERSION", "export_survey_document", "renderer_version"]
