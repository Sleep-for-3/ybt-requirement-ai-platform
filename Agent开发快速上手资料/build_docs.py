from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor, Twips


OUT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(r"C:\Users\李儒伟\Desktop\claudetowork\ybt-requirement-ai-platform")
LEARNING_ROOT = Path(r"C:\Users\李儒伟\Documents\智能分析智能体平台\AI_AGENT_LEARNING_PATH")

BLUE = "2E74B5"
BLUE_DARK = "1F4D78"
TEAL = "146C62"
TEAL_LIGHT = "E8F4F1"
BLUE_LIGHT = "E8EEF5"
INK = "22313F"
MUTED = "66788A"
LINE = "C9D5E2"
WHITE = "FFFFFF"
AMBER = "A76500"
AMBER_LIGHT = "FFF4DB"
RED = "B42318"
RED_LIGHT = "FDECEC"
GREEN = "1E7A46"
GREEN_LIGHT = "EAF6EE"
GRAY_LIGHT = "F5F7FA"

PAGE_WIDTH_DXA = 9360


def _set_east_asia(font, name: str = "Microsoft YaHei") -> None:
    font.name = "Calibri"
    font._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def _set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def _set_cell_margins(cell, top=80, start=120, bottom=80, end=120) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def _set_cell_border(cell, **kwargs) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "start", "bottom", "end", "insideH", "insideV"):
        if edge not in kwargs:
            continue
        edge_data = kwargs[edge]
        tag = f"w:{edge}"
        element = borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            borders.append(element)
        for key in ("val", "sz", "space", "color"):
            if key in edge_data:
                element.set(qn(f"w:{key}"), str(edge_data[key]))


def _set_table_fixed(table) -> None:
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl_pr = table._tbl.tblPr
    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    layout.set(qn("w:type"), "fixed")
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(PAGE_WIDTH_DXA))
    tbl_w.set(qn("w:type"), "dxa")
    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:w"), "120")
    tbl_ind.set(qn("w:type"), "dxa")


def _apply_exact_table_geometry(table, widths_dxa: Sequence[int], indent_dxa: int = 120) -> None:
    """Keep tblW, tblInd, tblGrid and every tcW synchronized."""
    widths = [int(width) for width in widths_dxa]
    if not widths or any(width <= 0 for width in widths):
        raise ValueError("table widths must be positive")
    table_width = sum(widths)
    if table_width != PAGE_WIDTH_DXA:
        widths[-1] += PAGE_WIDTH_DXA - table_width
    if sum(widths) != PAGE_WIDTH_DXA:
        raise ValueError("table width must equal the 9360 DXA content width")
    _set_table_fixed(table)
    tbl = table._tbl
    grid = tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths:
        grid_col = OxmlElement("w:gridCol")
        grid_col.set(qn("w:w"), str(width))
        grid.append(grid_col)
    tbl_pr = tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    tbl_w.set(qn("w:w"), str(PAGE_WIDTH_DXA))
    tbl_w.set(qn("w:type"), "dxa")
    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    tbl_ind.set(qn("w:w"), str(int(indent_dxa)))
    tbl_ind.set(qn("w:type"), "dxa")
    for col_idx, width in enumerate(widths):
        table.columns[col_idx].width = Twips(width)
    for row in table.rows:
        row.height = None
        for col_idx, cell in enumerate(row.cells):
            cell.width = Twips(widths[col_idx])
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is None:
                tc_w = OxmlElement("w:tcW")
                tc_pr.append(tc_w)
            tc_w.set(qn("w:w"), str(widths[col_idx]))
            tc_w.set(qn("w:type"), "dxa")


def _repeat_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def _cant_split(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    cant_split = OxmlElement("w:cantSplit")
    tr_pr.append(cant_split)


def _keep_with_next(paragraph) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    keep_next = OxmlElement("w:keepNext")
    p_pr.append(keep_next)


def _keep_lines(paragraph) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    keep_lines = OxmlElement("w:keepLines")
    p_pr.append(keep_lines)


def _set_paragraph_shading(paragraph, fill: str) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    shd = p_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        p_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def _page_number(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run("第 ")
    run.font.size = Pt(8.5)
    run.font.color.rgb = RGBColor.from_string(MUTED)
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for node in (begin, instr, separate, text, end):
        run._r.append(node)
    run2 = paragraph.add_run(" 页")
    run2.font.size = Pt(8.5)
    run2.font.color.rgb = RGBColor.from_string(MUTED)


def _add_field_toc(paragraph) -> None:
    """Insert an updatable Word TOC field; the manual reading map remains usable without update."""
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = ' TOC \\o "1-3" \\h \\z \\u '
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    placeholder = OxmlElement("w:t")
    placeholder.text = "在 Word 中右键此处并选择“更新域”，即可生成带页码目录。"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for node in (begin, instr, separate, placeholder, end):
        run._r.append(node)


def configure_document(doc: Document, short_title: str) -> None:
    section = doc.sections[0]
    section.start_type = WD_SECTION_START.NEW_PAGE
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)
    section.different_first_page_header_footer = True

    styles = doc.styles
    normal = styles["Normal"]
    _set_east_asia(normal.font)
    normal.font.size = Pt(11)
    normal.font.color.rgb = RGBColor.from_string(INK)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.25

    title = styles["Title"]
    _set_east_asia(title.font)
    title.font.size = Pt(27)
    title.font.bold = True
    title.font.color.rgb = RGBColor.from_string(BLUE_DARK)
    title.paragraph_format.space_after = Pt(10)

    subtitle = styles["Subtitle"]
    _set_east_asia(subtitle.font)
    subtitle.font.size = Pt(12)
    subtitle.font.color.rgb = RGBColor.from_string(MUTED)
    subtitle.paragraph_format.space_after = Pt(8)

    for name, size, color, before, after in (
        ("Heading 1", 16, BLUE, 18, 10),
        ("Heading 2", 13, BLUE, 14, 7),
        ("Heading 3", 12, BLUE_DARK, 10, 5),
    ):
        style = styles[name]
        _set_east_asia(style.font)
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(color)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True

    for style_name in ("List Bullet", "List Bullet 2", "List Number", "List Number 2"):
        style = styles[style_name]
        _set_east_asia(style.font)
        style.font.size = Pt(11)
        style.paragraph_format.left_indent = Inches(0.375)
        style.paragraph_format.first_line_indent = Inches(-0.188)
        style.paragraph_format.space_after = Pt(4)
        style.paragraph_format.line_spacing = 1.25

    if "Small Body" not in styles:
        small = styles.add_style("Small Body", WD_STYLE_TYPE.PARAGRAPH)
        _set_east_asia(small.font)
        small.font.size = Pt(9)
        small.font.color.rgb = RGBColor.from_string(MUTED)
        small.paragraph_format.space_after = Pt(4)
        small.paragraph_format.line_spacing = 1.15

    if "Code Block" not in styles:
        code = styles.add_style("Code Block", WD_STYLE_TYPE.PARAGRAPH)
        code.font.name = "Consolas"
        code.font._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        code.font.size = Pt(8.5)
        code.font.color.rgb = RGBColor.from_string(INK)
        code.paragraph_format.left_indent = Inches(0.18)
        code.paragraph_format.right_indent = Inches(0.18)
        code.paragraph_format.space_before = Pt(4)
        code.paragraph_format.space_after = Pt(6)
        code.paragraph_format.line_spacing = 1.05

    if "Callout Title" not in styles:
        callout_title = styles.add_style("Callout Title", WD_STYLE_TYPE.PARAGRAPH)
        _set_east_asia(callout_title.font)
        callout_title.font.size = Pt(10)
        callout_title.font.bold = True
        callout_title.font.color.rgb = RGBColor.from_string(BLUE_DARK)
        callout_title.paragraph_format.space_after = Pt(3)

    if "Cover Tag" not in styles:
        tag = styles.add_style("Cover Tag", WD_STYLE_TYPE.PARAGRAPH)
        _set_east_asia(tag.font)
        tag.font.size = Pt(9)
        tag.font.bold = True
        tag.font.color.rgb = RGBColor.from_string(TEAL)
        tag.paragraph_format.space_after = Pt(2)

    header = section.header
    p = header.paragraphs[0]
    p.text = f"银行一表通 AI 平台  ·  {short_title}"
    p.style = styles["Small Body"]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_after = Pt(0)
    p_pr = p._p.get_or_add_pPr()
    border = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "4")
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), LINE)
    border.append(bottom)
    p_pr.append(border)

    footer = section.footer
    _page_number(footer.paragraphs[0])


def add_cover(
    doc: Document,
    title: str,
    subtitle: str,
    tags: Sequence[str],
    purpose: str,
    audience: str,
) -> None:
    doc.add_paragraph()
    cover = doc.add_table(rows=1, cols=2)
    _set_table_fixed(cover)
    cover.columns[0].width = Inches(0.12)
    cover.columns[1].width = Inches(6.38)
    left, right = cover.rows[0].cells
    _set_cell_shading(left, TEAL)
    _set_cell_border(left, top={"val": "nil"}, bottom={"val": "nil"}, start={"val": "nil"}, end={"val": "nil"})
    _set_cell_border(right, top={"val": "nil"}, bottom={"val": "nil"}, start={"val": "nil"}, end={"val": "nil"})
    _set_cell_margins(right, top=240, start=260, bottom=220, end=160)
    title_p = right.paragraphs[0]
    title_p.style = doc.styles["Title"]
    title_p.add_run(title)
    sub_p = right.add_paragraph(style="Subtitle")
    sub_p.add_run(subtitle)
    for tag_text in tags:
        tag_p = right.add_paragraph(style="Cover Tag")
        tag_p.add_run(tag_text)
    _apply_exact_table_geometry(cover, [173, 9187], indent_dxa=260)

    doc.add_paragraph()
    meta = doc.add_table(rows=3, cols=2)
    _set_table_fixed(meta)
    widths = [1.15, 5.35]
    values = [
        ("适合谁", audience),
        ("解决什么", purpose),
        ("版本", f"基于 2026-07-30 本地项目现状 · {date.today().isoformat()} 生成"),
    ]
    for row, (key, value) in zip(meta.rows, values, strict=True):
        _cant_split(row)
        for i, cell in enumerate(row.cells):
            cell.width = Inches(widths[i])
            _set_cell_margins(cell, top=100, start=140, bottom=100, end=140)
            _set_cell_border(
                cell,
                top={"val": "single", "sz": "4", "color": LINE},
                bottom={"val": "single", "sz": "4", "color": LINE},
                start={"val": "single", "sz": "4", "color": LINE},
                end={"val": "single", "sz": "4", "color": LINE},
            )
        _set_cell_shading(row.cells[0], BLUE_LIGHT)
        p0 = row.cells[0].paragraphs[0]
        p0.add_run(key).bold = True
        p1 = row.cells[1].paragraphs[0]
        p1.add_run(value)
    _apply_exact_table_geometry(meta, [1656, 7704], indent_dxa=140)
    doc.add_paragraph()
    note = doc.add_paragraph(style="Small Body")
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    note.add_run("阅读原则：先理解真实链路，再背术语；先证明已有能力，再讨论 Agent 演进。")
    doc.add_page_break()


def add_callout(doc: Document, title: str, text: str, kind: str = "info") -> None:
    palette = {
        "info": (BLUE_LIGHT, BLUE),
        "success": (GREEN_LIGHT, GREEN),
        "warning": (AMBER_LIGHT, AMBER),
        "danger": (RED_LIGHT, RED),
        "neutral": (GRAY_LIGHT, MUTED),
        "teal": (TEAL_LIGHT, TEAL),
    }
    fill, accent = palette[kind]
    table = doc.add_table(rows=1, cols=1)
    _set_table_fixed(table)
    cell = table.cell(0, 0)
    _set_cell_shading(cell, fill)
    _set_cell_margins(cell, top=110, start=180, bottom=110, end=180)
    _set_cell_border(
        cell,
        top={"val": "single", "sz": "4", "color": fill},
        bottom={"val": "single", "sz": "4", "color": fill},
        start={"val": "single", "sz": "18", "color": accent},
        end={"val": "single", "sz": "4", "color": fill},
    )
    p = cell.paragraphs[0]
    p.style = doc.styles["Callout Title"]
    run = p.add_run(title)
    run.font.color.rgb = RGBColor.from_string(accent)
    body = cell.add_paragraph(text)
    body.paragraph_format.space_after = Pt(0)
    _apply_exact_table_geometry(table, [PAGE_WIDTH_DXA], indent_dxa=180)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def add_bullets(doc: Document, items: Iterable[str], level: int = 1) -> None:
    style = "List Bullet" if level == 1 else "List Bullet 2"
    for item in items:
        p = doc.add_paragraph(style=style)
        p.add_run(item)


def add_numbers(doc: Document, items: Iterable[str], level: int = 1) -> None:
    style = "List Number" if level == 1 else "List Number 2"
    for item in items:
        p = doc.add_paragraph(style=style)
        p.add_run(item)


def add_code(doc: Document, text: str) -> None:
    p = doc.add_paragraph(style="Code Block")
    p.add_run(text)
    _set_paragraph_shading(p, GRAY_LIGHT)
    _keep_lines(p)


def add_table(
    doc: Document,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    widths: Sequence[float],
    font_size: float = 9,
    header_fill: str = BLUE_LIGHT,
) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    _set_table_fixed(table)
    table.style = "Table Grid"
    hdr = table.rows[0]
    _repeat_header(hdr)
    _cant_split(hdr)
    for i, (cell, header, width) in enumerate(zip(hdr.cells, headers, widths, strict=True)):
        cell.width = Inches(width)
        _set_cell_shading(cell, header_fill)
        _set_cell_margins(cell)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        run = p.add_run(header)
        run.bold = True
        run.font.size = Pt(font_size)
        _set_east_asia(run.font)
    for row_values in rows:
        row = table.add_row()
        _cant_split(row)
        for i, (cell, value, width) in enumerate(zip(row.cells, row_values, widths, strict=True)):
            cell.width = Inches(width)
            _set_cell_margins(cell)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.1
            run = p.add_run(str(value))
            run.font.size = Pt(font_size)
            _set_east_asia(run.font)
    width_dxa = [int(round(width * 1440)) for width in widths]
    width_dxa[-1] += PAGE_WIDTH_DXA - sum(width_dxa)
    _apply_exact_table_geometry(table, width_dxa)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def add_flow(doc: Document, steps: Sequence[tuple[str, str]]) -> None:
    rows = []
    for index, (name, detail) in enumerate(steps, 1):
        rows.append((str(index), name, detail))
    add_table(doc, ["步骤", "处理环节", "系统做什么"], rows, [0.55, 1.65, 4.30], 9.2, TEAL_LIGHT)


def add_reading_map(doc: Document, items: Sequence[tuple[str, str]]) -> None:
    doc.add_heading("阅读导航", level=1)
    for section, goal in items:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.1)
        run = p.add_run(section)
        run.bold = True
        run.font.color.rgb = RGBColor.from_string(BLUE_DARK)
        p.add_run(f"  ·  {goal}")
    toc = doc.add_paragraph(style="Small Body")
    _add_field_toc(toc)


def set_core_properties(doc: Document, title: str, subject: str) -> None:
    props = doc.core_properties
    props.title = title
    props.subject = subject
    props.author = "Codex（基于本地项目源码整理）"
    props.keywords = "Agent, RAG, LLM, Milvus, FastAPI, Celery, 银行一表通"
    props.comments = "本资料区分当前已实现、原型建议与未来规划。"


def build_interview_doc() -> Path:
    doc = Document()
    configure_document(doc, "面试讲解手册")
    title = "面试讲解：本项目 AI / Agent 架构与知识体系"
    set_core_properties(doc, title, "3 分钟与 10 分钟项目讲解、架构、RAG、Agent 边界和面试追问")
    add_cover(
        doc,
        title,
        "从业务问题、技术架构、知识链路到 Agent 演进，一份可以直接排练的讲稿",
        ["INTERVIEW PLAYBOOK", "真实边界 · 可验证指标 · 源码落点", "适合零基础转行 Agent 开发工程师"],
        "让你在面试中准确讲清项目解决了什么、如何工作、为什么这样设计，以及它与真正 Agent 的距离。",
        "具有银行、ETL、SQL 或数据仓库经验，但刚开始学习大模型与 Agent 的转行者。",
    )
    add_callout(
        doc,
        "先记住这一句话",
        "这是一个面向银行监管“一表通”的证据驱动 AI 平台：它用正式 RAG 找到可追溯证据，用受控大模型生成结构化草稿，用异步任务、权限、审计和人工审核保证可运行、可追踪、可接管。它是 Agent-ready，但目前不是自主 Agent。",
        "teal",
    )
    add_reading_map(
        doc,
        [
            ("1. 项目定位与真实边界", "回答“这是做什么的、是不是 Agent”"),
            ("2. 架构全景与组件职责", "把前端、API、任务、模型和数据库串起来"),
            ("3. 知识入库、索引与 RAG", "讲清知识如何变成可引用答案"),
            ("4. 从 RAG 到 Agent", "说明已有底座、缺口和演进路线"),
            ("5. 3 分钟与 10 分钟讲稿", "直接排练面试表达"),
            ("6. 设计决策、指标与追问", "用权衡和数据回答深挖"),
            ("7. 源码导航与演练清单", "证明不是只会背概念"),
        ],
    )

    doc.add_heading("1. 项目定位与真实边界", level=1)
    doc.add_heading("1.1 业务问题", level=2)
    add_bullets(
        doc,
        [
            "银行监管字段多、不同业务场景口径不同，历史 Excel、Word、PDF、SQL 和人工答疑分散，查找和复核成本高。",
            "大模型很会生成“像真的”文字，但监管口径不能靠语言流畅度判断；来源表、字段、计算规则都必须有真实证据。",
            "最终交付不只是一段答案，而是可引用、可审核、可版本化、可做 UAT、可追责的业务口径和技术溯源。",
        ],
    )
    add_callout(
        doc,
        "面试中的业务价值表达",
        "项目的核心不是“让模型写得更像”，而是把分散知识变成可检索证据，并把模型的不确定性限制在“有出处、能拒答、可人工接管”的边界内。",
        "success",
    )
    doc.add_heading("1.2 它是什么，不是什么", level=2)
    add_table(
        doc,
        ["可以准确说", "不要夸大成"],
        [
            ("证据约束的 RAG 业务助手", "会自主规划和循环执行的完整 Agent"),
            ("确定性业务编排 + 受控 LLM 能力", "模型自由决定下一步的开放式系统"),
            ("具备 Agent 工程底座的垂直 AI 平台", "已经落地的多 Agent 协作平台"),
            ("关键词 + 向量的混合检索", "已经接入独立 Cross-Encoder Reranker"),
            ("Coze、MCP、复杂 Agent 预留扩展点", "已经完成 Coze 工作流或 MCP 集成"),
            ("本地合成集验证通过", "已经证明真实银行全量生产效果"),
        ],
        [3.25, 3.25],
        9.3,
    )
    add_callout(
        doc,
        "回答“这算 Agent 吗？”",
        "严格来说当前不是自主 Agent。现在由后端代码预先决定检索、模型调用、校验和落库顺序，模型没有 Tool Calling、Planner、状态循环或多 Agent 协作。更准确的说法是“Agent-ready 的受治理 RAG 平台”。",
        "warning",
    )

    doc.add_heading("2. 架构全景与组件职责", level=1)
    doc.add_heading("2.1 六层架构", level=2)
    add_table(
        doc,
        ["层次", "当前实现", "一句话职责"],
        [
            ("交互层", "Next.js 14 / React / TypeScript", "项目工作台、知识库、模型配置、任务中心和状态反馈。"),
            ("API 与治理层", "FastAPI / JWT / Pydantic", "鉴权、项目隔离、输入输出校验、审计与 REST API。"),
            ("确定性业务编排", "知识摄取、口径草稿、审核、UAT、交付", "代码决定固定流程，模型只在受控节点提供智能能力。"),
            ("AI 能力层", "LLM Gateway / PromptRuntime / Embedding / RAG", "模型切换、结构化生成、语义向量和证据化回答。"),
            ("异步任务层", "Redis + Celery + BackgroundJob", "把解析、索引、评测等耗时工作移出 HTTP 请求。"),
            ("持久化与检索层", "PostgreSQL + Milvus + Local/S3 Storage", "事实、向量索引和原始文件分别存放，各司其职。"),
        ],
        [1.25, 2.35, 2.90],
        9,
        TEAL_LIGHT,
    )
    add_callout(
        doc,
        "横切能力",
        "权限、数据分级、脱敏、审计、幂等、重试、任务进度、模型调用日志、RAG 评测和 Human-in-the-loop 横跨所有层。",
        "info",
    )

    doc.add_heading("2.2 PostgreSQL、Redis、Milvus 不可混淆", level=2)
    add_table(
        doc,
        ["组件", "保存什么", "不负责什么", "面试关键词"],
        [
            ("PostgreSQL", "业务事实、知识正文、版本、权限、任务、审计、关键词索引", "不擅长大规模高维近邻搜索", "System of Record / 事实源"),
            ("Redis", "Celery Broker 与任务结果的短期状态", "不是业务主库，也不是本项目向量库", "Queue / Broker"),
            ("Celery Worker", "执行解析、索引、评测等后台任务", "不保存最终业务真相", "Async Job / Worker"),
            ("Milvus", "Embedding 向量及追踪元数据", "不保存知识正文，不决定权限真相", "Vector Index / 可重建派生索引"),
            ("Storage", "原始上传文件和交付物", "不替代结构化业务模型", "Blob / Object Storage"),
        ],
        [1.15, 2.25, 1.75, 1.35],
        8.6,
    )

    doc.add_heading("2.3 两条模型链路", level=2)
    add_table(
        doc,
        ["对比项", "Chat LLM", "Embedding 模型"],
        [
            ("做什么", "理解问题、生成结构化答案或草稿", "把文本变成可比较的数字向量"),
            ("当前接入", "统一 LLMService，可用 OpenAI-compatible Provider，如 DeepSeek", "本地 FastEmbed，默认 BAAI/bge-small-zh-v1.5"),
            ("输出", "文字或经 Pydantic 校验的 JSON", "512 维向量"),
            ("存放", "答案、日志写 PostgreSQL", "向量写 Milvus，正文仍在 PostgreSQL"),
            ("配置", "LLM_PROVIDER / ModelProfile", "EMBEDDING_PROVIDER / Embedding 配置"),
            ("关键风险", "幻觉、格式错误、敏感外发、费用", "模型/维度变更、召回偏差、索引一致性"),
        ],
        [1.15, 2.675, 2.675],
        8.8,
    )

    doc.add_heading("3. 知识入库、索引与 RAG", level=1)
    doc.add_heading("3.1 知识摄取链路", level=2)
    add_flow(
        doc,
        [
            ("上传与校验", "用户上传 xlsx/docx/pdf/txt/md/sql；API 校验项目权限、知识范围和敏感等级。"),
            ("创建后台任务", "立即返回 202 和任务编号，避免页面等待长时间 HTTP 请求。"),
            ("解析与规范化", "Celery Worker 按文件类型提取文本，清理格式并保留 Sheet、单元格、标题、页码等出处。"),
            ("知识单元", "形成 KnowledgeUnit；通过内容 Hash 去重，通过文档版本和软删除管理生命周期。"),
            ("关键词索引", "关键词倒排记录写入 PostgreSQL，支持字段代码和精确术语召回。"),
            ("等待正式索引", "Milvus 模式下先完成解析，随后由项目级重建任务统一生成版本化向量索引。"),
        ],
    )
    add_callout(
        doc,
        "一个常见误区",
        "上传成功不等于语义索引已经可用。正式模式下，文件先被解析成 KnowledgeUnit；项目级重建完成且新索引验证激活后，向量检索才会使用新知识。",
        "warning",
    )

    doc.add_heading("3.2 版本化语义索引", level=2)
    add_flow(
        doc,
        [
            ("冻结语料快照", "读取当前启用且对项目可见的 KnowledgeUnit，计算 corpus_hash。"),
            ("幂等与版本", "按项目、模型指纹、向量维度和语料 Hash 生成幂等键，创建 EmbeddingIndexVersion。"),
            ("批量生成向量", "按 Batch 调用 Embedding；checkpoint 记录已完成批次。"),
            ("写入新 Collection", "稳定向量 ID 批量 Upsert 到独立 Milvus Collection。"),
            ("验证", "检查向量数量、维度和抽样搜索；失败版本标记 failed。"),
            ("原子激活", "只有验证成功才切换 active；旧 active 变为 superseded，失败不影响当前服务。"),
        ],
    )
    add_callout(
        doc,
        "面试加分表达",
        "这相当于“蓝绿式向量索引发布”：新旧 Collection 隔离，新索引验证成功后再切流量，避免直接覆盖造成半新半旧、维度污染或线上不可用。",
        "success",
    )

    doc.add_heading("3.3 Hybrid RAG 问答链路", level=2)
    add_flow(
        doc,
        [
            ("用户问题", "问题携带 project_id，以及可选场景、知识类型等过滤条件。"),
            ("关键词通道", "PostgreSQL 倒排索引召回字段名、代码、监管编号等精确匹配。"),
            ("向量通道", "问题生成 Query Embedding，在当前 active Milvus Collection 中做语义相似搜索。"),
            ("融合排序", "分数归一化、关键词/向量加权与业务规则加分，得到 Top-K。"),
            ("回库校验", "按 ID 回 PostgreSQL 读取正文，并重新检查启用状态、项目/机构可见性。"),
            ("受控生成", "PromptRuntime 把问题和允许引用的证据交给 Chat LLM，要求固定结构。"),
            ("答案验证", "Pydantic 校验 JSON；检查 Citation 存在且可见；拦截证据中不存在的 table.field。"),
            ("返回与记录", "有证据则返回答案和出处；证据不足返回“待确认”；记录 RetrievalLog 和 ModelCallLog。"),
        ],
    )
    add_callout(
        doc,
        "当前不是独立 Reranker",
        "代码中的 rerank_score 是融合后的最终分数，并没有再调用 Cross-Encoder。面试时应说“融合排序”，不要说“已经接入重排模型”。",
        "danger",
    )

    doc.add_heading("3.4 为什么需要 Human-in-the-loop", level=2)
    add_bullets(
        doc,
        [
            "模型结果先写入 ai_generated_content 或草稿字段，不直接覆盖人工 final_content。",
            "物理 schema/table/field 必须能在真实数据目录中验证。",
            "草稿绑定证据，经过采用、审核、版本与 UAT 后才能进入交付。",
            "高风险写操作、发布和数据外发必须由服务端规则或人工审批控制，不能只靠 Prompt。",
        ],
    )

    doc.add_heading("4. 从 RAG 到真正 Agent", level=1)
    doc.add_heading("4.1 Agent 的最小组成", level=2)
    add_table(
        doc,
        ["Agent 能力", "当前项目可复用基础", "当前状态 / 缺口"],
        [
            ("目标", "业务口径、知识问答、索引与审核任务", "已有业务目标，但不是统一 Agent Run。"),
            ("感知 / Context", "知识检索、数据目录、血缘、任务状态", "已有，可封装成工具。"),
            ("工具", "HybridRetriever、SafeSqlExecutor、目录与工作流 Service", "尚无统一 Tool Schema/Registry。"),
            ("决策", "PromptRuntime 与结构化输出", "模型尚不能动态选择下一步。"),
            ("循环", "BackgroundJob、重试、进度", "没有“决策→工具→观察→继续”的 Agent Loop。"),
            ("状态 / 记忆", "PostgreSQL、知识库、任务记录", "没有 AgentRun/AgentStep 和记忆策略。"),
            ("安全", "权限、数据分级、脱敏、审计、人工审核", "底座较完整，可直接复用。"),
            ("评测", "RAG Golden Dataset、检索与回答指标", "需增加工具正确率、任务成功率、越权率和轨迹评测。"),
        ],
        [1.2, 2.65, 2.65],
        8.7,
    )

    doc.add_heading("4.2 推荐的演进顺序", level=2)
    add_numbers(
        doc,
        [
            "先把知识搜索、文档读取、后台任务查询封装成三个只读工具，并用 Pydantic 定义参数和返回结构。",
            "实现单 Agent 状态机：目标、步骤、工具结果、最大步数、超时、Token/费用预算和明确终止条件。",
            "把 AgentRun、AgentStep、ToolCall 持久化到 PostgreSQL；长任务放入 Celery，并支持 checkpoint 和恢复。",
            "只读工具可自动执行；重建索引、保存草稿、创建审核任务等写操作先展示影响范围并要求人工确认。",
            "扩展评测：任务成功率、工具选择正确率、平均步骤、越权率、循环率、延迟与成本。",
            "只有单 Agent 在数据上不够用且角色确有独立上下文时，再比较 Planner/Executor/Reviewer 多 Agent。",
        ],
    )
    add_code(
        doc,
        "用户目标\n"
        "  → 读取当前状态\n"
        "  → 选择受控工具\n"
        "  → 服务端鉴权与参数校验\n"
        "  → 执行工具并获得 Observation\n"
        "  → 更新 Agent State\n"
        "  → 继续 / 人工审批 / 安全终止\n"
        "  → 输出答案、引用与完整 Trace",
    )

    doc.add_heading("5. 3 分钟项目讲稿", level=1)
    add_callout(
        doc,
        "使用方法",
        "不要一字不差死背。先按“问题—架构—主链路—安全—结果—边界”六个锚点讲；把其中“我做了什么”替换成你本人确实参与的工作。",
        "info",
    )
    script_3 = (
        "这个项目解决的是银行“一表通”监管报送中，业务口径、技术溯源和历史知识分散，人工查找慢，而且大模型容易编造来源表字段的问题。\n\n"
        "整体上它不是一个让模型自由行动的 Agent，而是一个受治理的 RAG 业务助手。前端使用 Next.js，后端是 FastAPI；PostgreSQL 保存业务事实、知识正文、任务和审计；Redis 与 Celery 负责异步解析和索引；Milvus 保存向量；本地 FastEmbed 生成中文 Embedding；Chat 模型通过统一的 OpenAI-compatible Gateway 接入。\n\n"
        "知识文件上传后，接口立即返回任务编号，Worker 在后台解析 Excel、Word、PDF、Markdown、SQL 等文件，将内容切成带文件名、Sheet、单元格或页码的 KnowledgeUnit。项目级语义索引任务再批量生成向量，写入新的版本化 Milvus Collection。只有数量、维度和抽样搜索都验证通过后，新版本才会激活，因此重建失败不会影响旧索引。\n\n"
        "查询时走 Hybrid RAG：PostgreSQL 关键词检索和 Milvus 语义检索分别得到候选，分数归一化、加权融合，再按项目、机构、知识类型和业务场景过滤。Top-K 证据交给 Chat 模型生成结构化答案，返回前还会检查 Citation 是否真实、是否可见，以及是否虚构了证据中不存在的表字段。没有证据时系统返回“待确认”。\n\n"
        "AI 生成的业务口径只进入草稿，不会直接覆盖人工最终口径，后面还有采用、审核、版本和 UAT，这体现了金融场景中的 Human-in-the-loop。\n\n"
        "本机用 10 份合成文档、100 个 Chunk、20 个问题做过验收。Hybrid 的 Recall@5、Recall@10、MRR 和 Citation Coverage 都是 1.0，P95 约 687 毫秒；Vector-only Recall 是 0.6，所以保留了关键词与向量混合方案。这个结果证明当前小规模链路有效，但不能直接代表真实银行全量语料。\n\n"
        "当前还没有 Planner、Tool Calling、多 Agent、MCP 或自主循环。下一步会把知识检索、安全探查、草稿生成和审核任务封装成受权限控制的工具，再增加持久化状态机、预算和人工审批，演进为真正的单 Agent。"
    )
    for para in script_3.split("\n\n"):
        p = doc.add_paragraph(para)
        p.paragraph_format.first_line_indent = Inches(0.28)

    doc.add_heading("6. 10 分钟深挖结构", level=1)
    add_table(
        doc,
        ["时间", "讲什么", "必须落到的事实"],
        [
            ("0:00–1:00", "业务问题与价值", "监管字段不能由 AI 发明；交付需要证据、审核和可追溯。"),
            ("1:00–2:30", "六层架构", "Next.js、FastAPI、适配器、Celery、PostgreSQL、Milvus 的职责边界。"),
            ("2:30–5:00", "知识入库与 RAG", "KnowledgeUnit 出处、批量摄取、版本化索引、Hybrid、Citation 回库校验。"),
            ("5:00–6:30", "模型治理", "ModelProfile、Prompt 版本、Pydantic、重试、日志、数据外发控制。"),
            ("6:30–8:00", "异步可靠性", "202 + Job、Redis/Celery、幂等、checkpoint、旧索引兜底。"),
            ("8:00–9:00", "指标与局限", "真实本机验收数据；小规模合成集；Vector-only 不足；无 OCR。"),
            ("9:00–10:00", "Agent 边界与演进", "当前 deterministic orchestration；下一步 Tool、State、Loop、HITL、Eval。"),
        ],
        [0.9, 1.65, 3.95],
        9,
    )
    doc.add_heading("6.1 讲个人贡献时的安全模板", level=2)
    add_code(
        doc,
        "背景：原系统在 ______ 方面存在 ______ 问题。\n"
        "我的实际工作：我负责 / 参与了 ______（只写确实做过的内容）。\n"
        "关键决策：我们选择 ______，因为 ______；没有选择 ______，代价是 ______。\n"
        "验证：通过 ______ 测试 / 指标证明 ______。\n"
        "复盘：当前不足是 ______，下一步会 ______。",
    )

    doc.add_heading("7. 关键决策、指标与权衡", level=1)
    doc.add_heading("7.1 可验证指标", level=2)
    add_table(
        doc,
        ["验收项", "本机结果", "怎么解读"],
        [
            ("语料规模", "10 份合成文档、100 个 Chunk、20 个问题", "是链路验收，不是生产规模结论。"),
            ("Keyword", "Top1 20/20；Recall@5/10=1；MRR=1", "合成集精确术语强，体现关键词价值。"),
            ("Vector-only", "Top1 11/20；Recall@5/10=0.60；MRR=0.5625", "当前模型/语料下纯向量不够稳定。"),
            ("Hybrid", "Top1 20/20；Recall@5/10=1；MRR=1", "混合策略在该固定集上优于纯向量。"),
            ("Hybrid 延迟", "P50 570.6 ms；P95 686.8 ms", "主要包含本地 Query Embedding 与向量检索。"),
            ("索引吞吐", "100 Chunk 约 9.36 秒；约 10.7 Chunk/s", "说明批量链路已打通，仍需大规模容量测试。"),
            ("持久化", "Milvus 重启后向量数仍为 100", "验证 Docker Volume 的基本持久化。"),
            ("Citation Coverage", "三种模式均为 1.0", "正确证据可被引用，但需继续扩展真实集与逐 Claim 验证。"),
        ],
        [1.25, 2.10, 3.15],
        8.7,
    )
    add_callout(
        doc,
        "不能说“准确率 100%”",
        "Recall、MRR 和 Citation Coverage 是在 20 个合成问题上的特定指标，不等于模型回答准确率 100%，更不等于生产环境效果。面试时要同时说明数据集大小、来源和局限。",
        "danger",
    )

    doc.add_heading("7.2 八个设计决策", level=2)
    add_table(
        doc,
        ["设计决策", "为什么", "代价 / 后续"],
        [
            ("RAG 而非微调保存知识", "监管知识变化快且必须引用来源", "需要建设解析、索引和评测链路。"),
            ("Hybrid 而非纯向量", "字段代码、表名与自然语言需要不同召回能力", "融合权重需基于 Golden Dataset 调整。"),
            ("PostgreSQL 做事实源", "权限、版本、正文和事务需要强一致", "向量命中后要回库读取和校验。"),
            ("向量索引版本化", "避免模型、维度、语料更新污染线上索引", "会增加 Collection 管理和存储成本。"),
            ("Celery 异步", "上传解析、索引和评测不阻塞请求", "必须补任务状态、幂等、重试和可观察性。"),
            ("结构化输出", "业务系统需要可校验字段，不接受任意自然语言", "Schema 变化需要版本治理和兼容。"),
            ("草稿与最终值分离", "高风险领域保留人工决定权", "业务流程多一步，但可审计、可接管。"),
            ("适配器隔离 Provider", "减少厂商锁定并允许 Mock/本地/外部切换", "接口要保持小而稳定，不能泄漏厂商细节。"),
        ],
        [1.6, 2.65, 2.25],
        8.7,
    )

    doc.add_heading("8. 高频追问与回答", level=1)
    qa = [
        ("这是 Agent 吗？", "严格说不是自主 Agent，而是确定性编排的 RAG 业务助手。模型不能自主选工具或循环规划；项目已有模型、检索、任务、安全和评测底座，下一步才增加 Tool Calling 与状态机。"),
        ("RAG 和微调有什么区别？", "微调主要改变行为或表达，不适合频繁变化且要求引用的监管知识。RAG 运行时取最新证据、知识可独立更新并返回 Citation；本项目没有做模型微调。"),
        ("为什么不用纯向量检索？", "字段名、监管编号和表字段代码需要精确匹配；本机 Vector-only Recall@5 只有 0.60，而 Hybrid 为 1.00，因此保留关键词与向量融合。"),
        ("Embedding 与 Chat 模型是什么关系？", "Embedding 生成向量供检索，Chat 模型生成答案。它们用途、配置和风险不同，可用本地 FastEmbed 检索、外部 DeepSeek 生成。"),
        ("为什么 PostgreSQL 和 Milvus 都要用？", "PostgreSQL 保存事实、正文、权限和版本；Milvus 优化高维向量近邻搜索。Milvus 返回 ID 后仍要回 PostgreSQL 校验，向量库不是事实源。"),
        ("Redis 能代替 Milvus 吗？", "本项目中 Redis 只承载 Celery Broker/Result Backend；正式向量检索由 Milvus 完成。不要把某产品可能有的能力与当前实现混在一起。"),
        ("如何降低幻觉？", "证据检索、结构化输出、无证据拒答、table.field 真实性检查、Citation 回库校验、草稿/最终值分离和人工审核。只能说降低和可控，不能说彻底消除。"),
        ("为什么索引要版本化？", "Embedding 模型、维度和语料变化时直接覆盖会造成混合空间和半完成状态。新 Collection 验证成功后再激活，失败时旧 active 继续服务。"),
        ("怎样避免重复任务？", "前端禁用按钮只是体验层；后端按业务 payload 生成语义幂等键并依赖数据库唯一约束，并发重复提交复用同一 BackgroundJob。"),
        ("Celery 任务失败怎么办？", "任务保存状态、错误摘要和重试信息；索引按批 checkpoint；失败版本不激活，旧 active 保持可用；恢复应重试或重建，不删除业务数据。"),
        ("换 Embedding 模型要注意什么？", "不同模型属于不同语义空间，维度也可能变化，不能混写同一 Collection；必须按模型指纹和维度创建新版本并完整重建。"),
        ("如何评估 RAG？", "固定 Golden Dataset，分别看解析、检索、生成和系统指标；检索关注 Recall@K/MRR，回答关注 Citation/Groundedness/Correctness，同时记录 P50/P95、失败率和成本。"),
        ("当前有真正 Reranker 吗？", "没有。当前是关键词、向量和规则的融合排序；字段名虽然有 rerank_score，但没有调用 Cross-Encoder。"),
        ("AI 会自由查询数据库吗？", "不会。数据库探查受固定模板、权限和 SafeSqlExecutor 控制，只允许受控只读 SQL；模型不能绕过 Service 直接访问 ORM 或执行任意 SQL。"),
        ("为什么暂时不用 LangChain/LangGraph？", "当前核心流程确定性强，直接实现更易审计。等模型需要动态选工具、暂停恢复和状态图时，再评估 LangGraph 或自建状态机的收益。"),
        ("怎么升级成真正 Agent？", "把已有 Service 封装成最小权限工具，增加 AgentRun/Step 持久化、受限循环、预算、审批与轨迹评测；先做单 Agent，再用数据决定是否多 Agent。"),
        ("最大技术不足是什么？", "Vector-only 召回偏低；评测集小且合成；没有 OCR、独立 Reranker 和 Agent Loop；Milvus 容量、备份、鉴权与高可用仍需专项验收。"),
        ("Mock 是什么？", "Mock 是遵守同一接口的可控假实现，用于测试和无密钥演示；它不代表真实模型或真实语义能力。正式环境失败不能静默回退 Mock，否则会制造“假成功”。"),
    ]
    for index, (question, answer) in enumerate(qa, 1):
        p = doc.add_paragraph()
        _keep_with_next(p)
        run = p.add_run(f"Q{index}. {question}")
        run.bold = True
        run.font.color.rgb = RGBColor.from_string(BLUE_DARK)
        a = doc.add_paragraph(answer)
        a.paragraph_format.left_indent = Inches(0.18)
        a.paragraph_format.space_after = Pt(8)

    doc.add_heading("9. 源码导航与演练清单", level=1)
    add_table(
        doc,
        ["主题", "建议阅读路径", "你要能证明"],
        [
            ("LLM 网关", "backend/app/services/llm/base.py；openai_compatible.py；factory.py", "业务依赖接口，Provider 可替换；结构化输出和重试边界。"),
            ("Prompt 运行时", "backend/app/services/llm/prompt_runtime.py；structured_outputs.py", "Prompt/ModelProfile 选择、数据外发、Pydantic 与调用日志。"),
            ("知识摄取", "backend/app/services/knowledge_ingestion/ingestion_service.py；parsers.py", "批量解析、Hash 去重、版本、出处与关键词索引。"),
            ("语义索引", "backend/app/services/semantic_index/reindex.py；versioning.py", "语料快照、batch、checkpoint、验证与 active 切换。"),
            ("向量存储", "backend/app/services/vector/milvus.py", "Collection、维度校验、Upsert、Search、Count。"),
            ("混合检索", "backend/app/services/retrieval/hybrid_retriever.py", "三种模式、融合、过滤、RetrievalLog。"),
            ("有证据回答", "backend/app/services/rag/grounded_answer_service.py；citation_validator.py", "无证据拒答、Citation 可见性与反虚构。"),
            ("后台任务", "backend/app/services/task_queue/；backend/app/workers.py", "Inline/Celery 接缝、幂等、状态、进度和处理器。"),
            ("评测", "backend/app/services/evaluation/rag_evaluator.py", "Recall@K、MRR、Citation、Groundedness、延迟。"),
            ("Agent 缺口", "backend/app/services/coze/connector.py；README.md", "Coze 仅占位；复杂 Agent、MCP 未实现。"),
        ],
        [1.1, 3.05, 2.35],
        8.3,
    )
    doc.add_heading("9.1 面试前最后检查", level=2)
    add_bullets(
        doc,
        [
            "能不看稿在 3 分钟内讲清业务问题、六层架构、RAG 主链路、指标和 Agent 边界。",
            "能画出“上传→Worker→KnowledgeUnit→索引→检索→LLM→Citation”的时序图。",
            "能解释 Chat、Embedding、Milvus、PostgreSQL、Redis、Celery 各自做什么。",
            "能说出至少 10 个真实代码文件，并任选一条链从 API 追到数据库与测试。",
            "把“项目已有”“你本人完成”“原型建议”“未来规划”分开，绝不把路线图当成已落地。",
            "所有数字都附带数据集规模和限制，不使用“准确率 100%”“杜绝幻觉”等夸大表述。",
        ],
    )
    add_callout(
        doc,
        "最后一句",
        "一个好的 Agent 工程师不只是会调用模型，而是能把不确定的模型放进有权限、有状态、有证据、有停止条件、可观测且可人工接管的系统里。",
        "teal",
    )

    path = OUT_DIR / "01_面试讲解_本项目AI与Agent架构.docx"
    doc.save(path)
    return path


def _term_rows(entries: Sequence[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    return [(term, plain, project) for term, plain, project in entries]


def build_glossary_doc() -> Path:
    doc = Document()
    configure_document(doc, "术语与技术手册")
    title = "Agent 开发工程师术语与项目技术手册"
    set_core_properties(doc, title, "零基础术语、项目落点、源码阅读、排障与工程实践")
    add_cover(
        doc,
        title,
        "把大模型、RAG、Agent、后端与运维术语，逐一对应到当前项目",
        ["TECHNICAL FIELD GUIDE", "中文解释 · 英文含义 · 项目落点", "从“听过名词”到“能读源码、能排障”"],
        "建立一套能直接用于读代码、沟通需求、排查问题和面试回答的专业词汇与技术框架。",
        "没有大模型基础，但希望快速进入企业 AI 应用 / Agent 开发岗位的人。",
    )
    add_callout(
        doc,
        "最重要的四个区分",
        "LLM 负责生成；Embedding 负责把文本变向量；RAG 负责先找证据再生成；Agent 负责围绕目标动态选择工具并循环执行。四者有关联，但绝不是同一个东西。",
        "teal",
    )
    add_reading_map(
        doc,
        [
            ("1. 六个心智模型", "先建立全局，不陷入名词堆"),
            ("2. LLM 与 Prompt", "看懂模型调用链和结构化输出"),
            ("3. RAG 与向量检索", "看懂知识入库、索引、召回和评测"),
            ("4. Agent 与工具", "区分 Workflow、RAG 和真正 Agent"),
            ("5. 后端、数据与异步任务", "看懂 FastAPI、数据库、Redis、Celery"),
            ("6. 安全、运维与质量", "看懂上线需要的治理与可观测性"),
            ("7. 八条源码学习链", "用问题驱动方式读当前项目"),
            ("8. 常用操作与排障", "能启动、检查、定位，不靠猜"),
        ],
    )

    doc.add_heading("1. 六个心智模型", level=1)
    add_table(
        doc,
        ["你看到的功能", "背后的工程模型", "一句话理解"],
        [
            ("模型回答问题", "概率生成", "LLM 生成的是最可能的文字，不是从事实表中读取答案。"),
            ("知识库问答", "Retrieve then Generate", "先检索可见证据，再让模型依据证据作答。"),
            ("创建索引任务", "派生数据发布", "向量是可重建索引；新版本验证成功后才激活。"),
            ("后台任务", "异步状态机", "HTTP 只提交任务；Worker 执行；数据库记录可恢复状态。"),
            ("Agent", "受限决策循环", "模型在工具白名单内决定下一步，代码控制权限、预算和停止。"),
            ("企业上线", "不确定能力的治理", "权限、审计、评测、拒答和人工审批比“会调用模型”更重要。"),
        ],
        [1.45, 1.75, 3.30],
        9.1,
        TEAL_LIGHT,
    )
    doc.add_heading("1.1 三组最容易混淆的组件", level=2)
    add_table(
        doc,
        ["对比", "A", "B", "记忆口诀"],
        [
            ("Chat vs Embedding", "Chat 生成文字/JSON", "Embedding 生成向量", "一个会说，一个会找相似。"),
            ("PostgreSQL vs Milvus", "事实、正文、权限、事务", "向量近邻检索", "主库管真相，向量库管召回。"),
            ("Redis vs Celery", "消息 Broker/短期结果", "取任务并执行的 Worker 框架", "Redis 放队列，Celery 干活。"),
            ("Workflow vs Agent", "步骤预先写死", "模型可在边界内选择下一步", "流程可预测，Agent 可决策。"),
            ("Mock vs Formal", "可控假实现/测试替身", "真实模型、真实向量、真实依赖", "Mock 验流程，Formal 验能力。"),
        ],
        [1.35, 1.85, 1.85, 1.45],
        8.8,
    )
    add_callout(
        doc,
        "Mock 到底是什么？",
        "Mock（模拟实现）会遵守和正式组件相同的接口，但返回可预测的假结果，便于单元测试、CI 和无密钥演示。Mock Embedding 不代表真实语义理解，Mock Vector Store 也不代表真实持久化。正式服务配置错误时应明确失败，不能悄悄回退 Mock。",
        "warning",
    )

    doc.add_heading("2. LLM 与 Prompt 术语", level=1)
    llm_terms = [
        ("LLM / Large Language Model", "大语言模型。根据上下文逐步预测 Token，擅长理解和生成语言，但不天然等于事实数据库。", "services/llm/；项目让 LLM 生成解释与草稿，确定性规则仍在后端。"),
        ("Token", "模型切分和计费的基本单位，不完全等于一个汉字或单词。", "ModelCallLog 可记录 usage；Top-K、Chunk 和 Prompt 长度都会影响 Token。"),
        ("Inference", "推理：使用训练好的模型生成结果。不是训练，也不是微调。", "OpenAI-compatible Chat 调用属于推理。"),
        ("Prompt", "发给模型的指令、上下文、证据和输出要求。", "prompt_runtime.py 统一读取 PromptTemplateVersion，不应散落在路由。"),
        ("System Prompt", "高层角色和边界指令，例如“仅依据证据、不得虚构表字段”。", "default_system_prompt() 定义受控生成边界；安全仍需服务端校验。"),
        ("User Prompt", "本次具体任务与证据。", "RAG 把问题、Top-K KnowledgeUnit 和目标字段拼成模型输入。"),
        ("Context Window", "一次调用能读取的最大 Token 容量。", "Chunk 大小、Top-K 与历史消息必须受上下文窗口约束。"),
        ("Temperature", "控制随机程度；越高越发散，越低越稳定。", "业务结构化任务通常应低温；仍需 Schema 校验。"),
        ("Completion", "模型生成的输出。", "项目不直接信任 Completion，而是解析为结构化输出。"),
        ("Structured Output", "要求模型按固定字段返回 JSON。", "structured_outputs.py 定义业务口径、技术溯源和问答 Schema。"),
        ("JSON Schema", "描述 JSON 字段、类型、必填项和约束的机器可读规范。", "Pydantic 模型承担输出和未来 Tool 参数的结构约束。"),
        ("Pydantic Validation", "把不可信输入解析、校验成明确类型；失败就报错。", "API 请求、模型输出和未来工具参数都需要 Pydantic。"),
        ("Hallucination", "幻觉：模型生成看似合理但没有事实支持的内容。", "通过 RAG、Citation、物理字段校验、拒答和 HITL 降低风险。"),
        ("Grounding", "把答案绑定到给定事实或证据。", "grounded_answer_service.py 仅允许基于检索证据回答。"),
        ("Provider", "实际提供模型 API 的厂商或本地服务。", "Mock、OpenAI-compatible、本地模型都可作为 Provider。"),
        ("Model Profile", "模型地址、名称、Provider、参数和密钥环境变量名的运行配置。", "ModelProfile + api/ai_runtime.py；业务代码不写死 DeepSeek。"),
        ("Gateway / Adapter", "用小接口隔离具体厂商，让业务层面向统一能力。", "LLMService、Embedding Gateway、VectorStore、TaskQueue 都采用此思路。"),
        ("OpenAI-compatible", "接口形状兼容 OpenAI 风格，不代表一定调用 OpenAI。", "llm/openai_compatible.py 与 embeddings/openai_compatible.py。"),
        ("Retry / Backoff", "对暂时性错误有限次数重试，并逐步增加等待。", "超时、429、5xx 可重试；401/403/404 通常不盲目重试。"),
        ("Prompt Versioning", "把 Prompt 当成可发布、可回滚、可评测的版本，而非随手字符串。", "PromptTemplateVersion 与 ModelCallLog 记录 prompt_key/version。"),
    ]
    add_table(doc, ["术语", "通俗解释", "本项目如何体现"], _term_rows(llm_terms), [1.55, 2.55, 2.40], 8.2)
    add_callout(
        doc,
        "面试表达",
        "“LLM 负责概率生成，后端负责确定性边界。Prompt 是契约而不是安全边界；模型输出、工具参数和物理字段仍要经过 Schema、权限和业务规则验证。”",
        "success",
    )

    doc.add_heading("3. RAG 与知识库术语", level=1)
    rag_terms = [
        ("RAG / Retrieval-Augmented Generation", "检索增强生成：先找资料，再让模型依据资料回答。", "services/retrieval/ + services/rag/；答案返回 Citation。"),
        ("Ingestion", "摄取：把外部文件转成系统可管理的知识。", "knowledge_ingestion/ 解析 xlsx/docx/pdf/txt/md/sql。"),
        ("Parser", "解析器：把不同文件格式转换为文本与位置元数据。", "parsers.py；PDF 当前无 OCR，扫描件可能无文本。"),
        ("Normalization", "规范化：清理空格、换行、编码等差异，形成稳定内容。", "normalizer.py；有利于 Hash、去重和一致索引。"),
        ("Chunk", "把长文档切成可检索的小块。", "项目以 KnowledgeUnit 作为核心检索单元。"),
        ("Metadata", "描述 Chunk 的结构化信息，如项目、机构、页码、Sheet、敏感等级。", "用于过滤、权限和 Citation 定位。"),
        ("Content Hash", "内容的数字指纹；内容相同通常 Hash 相同。", "文档与 KnowledgeUnit 去重、版本和 corpus_hash。"),
        ("Embedding", "把文本编码成向量，使语义相近文本在空间中更接近。", "本地 FastEmbed 默认 BAAI/bge-small-zh-v1.5。"),
        ("Dimension", "向量中数字的数量。", "当前 512 维；维度必须与 Milvus Collection 一致。"),
        ("Cosine Similarity", "比较两个向量方向是否相近的相似度方法。", "Milvus 默认 COSINE；相似不等于事实正确。"),
        ("Vector Database", "面向高维向量近邻搜索优化的数据库。", "Milvus；只保存向量与追踪元数据，不是知识事实源。"),
        ("Collection", "Milvus 中一组结构相同的向量记录。", "项目/模型指纹/维度/索引版本对应独立 Collection。"),
        ("Upsert", "同一主键存在则更新，不存在则插入。", "稳定向量 ID + 批量 Upsert 支持幂等重建。"),
        ("Semantic Search", "按语义相近程度搜索，不要求字面相同。", "Query Embedding → active Milvus Collection。"),
        ("Keyword Search", "按词、代码和标识符做精确或加权匹配。", "KnowledgeKeywordIndex；当前不是标准 BM25。"),
        ("Hybrid Retrieval", "融合关键词与向量候选。", "hybrid_retriever.py；当前默认模式。"),
        ("Top-K", "取排序最靠前的 K 个结果。", "K 太小可能漏证据，太大增加噪声和 Token。"),
        ("Filtering", "按项目、机构、场景、类型、启用状态等筛选。", "向量召回后仍回 PostgreSQL 进行可见性校验。"),
        ("Score Fusion", "把不同通道分数归一化后加权合并。", "当前 Hybrid 的主要排序方法。"),
        ("RRF", "Reciprocal Rank Fusion，按名次而不是原始分数融合。", "尚未实现，是原学习路线中的量化改造方向。"),
        ("Reranker", "对初步候选进行更精细的二次排序，常用 Cross-Encoder。", "当前未接入；rerank_score 只是融合分数。"),
        ("Citation", "答案引用的知识来源和位置。", "citation_validator.py 验证 KnowledgeUnit 存在、启用、可见。"),
        ("Grounded Answer", "有证据约束的答案；证据不足就明确不确定。", "无证据返回“待确认”，并阻止虚构 table.field。"),
        ("Index Version", "一次完整构建且可切换的向量索引版本。", "EmbeddingIndexVersion；验证成功后原子激活。"),
        ("Corpus Hash", "当前有效语料快照的指纹。", "与模型指纹、维度共同形成重建幂等依据。"),
        ("Recall@K", "所有应该命中的证据中，有多少出现在前 K 条。", "rag_evaluator.py 计算 Recall@5/10。"),
        ("MRR", "第一个正确结果越靠前，分数越高。", "用于衡量正确证据出现位置。"),
        ("Precision", "返回结果中有多少真正相关。", "项目当前核心报告更关注 Recall/MRR；后续可补 Precision 切片。"),
        ("Groundedness", "答案中的陈述有多少得到证据支撑。", "当前为较粗粒度规则，未来可逐 Claim 验证。"),
        ("Golden Dataset", "固定问题、期望证据和答案要点构成的评测集。", "EvaluationCase / EvaluationRun；不能只靠人工“感觉不错”。"),
    ]
    add_table(doc, ["术语", "通俗解释", "本项目如何体现"], _term_rows(rag_terms), [1.55, 2.55, 2.40], 8.0)

    doc.add_heading("3.1 一次 RAG 查询中的数据形态", level=2)
    add_code(
        doc,
        "用户问题（文本）\n"
        "  → Query Embedding（512 个浮点数）\n"
        "  → Milvus 返回候选 ID + 相似度\n"
        "  → PostgreSQL 读取 KnowledgeUnit 正文 + 权限元数据\n"
        "  → Keyword / Vector / Rule 融合后的 Top-K\n"
        "  → Prompt = 系统约束 + 问题 + 允许引用的证据\n"
        "  → Chat LLM 输出结构化答案\n"
        "  → Citation 回库验证\n"
        "  → 答案 + 引用 + RetrievalLog / ModelCallLog",
    )

    doc.add_heading("4. Agent 与工具术语", level=1)
    agent_terms = [
        ("Workflow", "程序预先写死步骤；输入相同通常路径可预测。", "当前知识入库、索引、审核大多是 Workflow。"),
        ("Agent", "围绕目标，根据当前状态和结果动态决定下一步。", "当前尚无完整 Agent Loop；项目是 Agent-ready。"),
        ("Agent Loop", "决策→调用工具→观察结果→更新状态→继续/停止。", "建议新增 services/agent/，并限制最大步骤和预算。"),
        ("Tool / Function Calling", "模型从受控工具列表中选择工具并给出参数。", "可先封装 search_knowledge、get_document、get_background_job。"),
        ("Tool Schema", "工具名称、用途、参数、返回结构和风险说明。", "应由 Pydantic/JSON Schema 定义；Executor 再校验。"),
        ("Tool Registry", "集中登记可用工具及权限、超时、幂等信息。", "当前未实现；不可让模型直接访问 ORM。"),
        ("State", "目标、当前步骤、已调用工具、结果、错误和预算。", "应持久化为 AgentRun/AgentStep，而不是只放 Prompt。"),
        ("Observation", "工具执行后返回给 Agent 的结构化结果。", "需限制大小、脱敏并保留 trace 摘要。"),
        ("Planner", "根据目标和现状决定下一步或子任务。", "当前未实现；后端现在预先决定流程。"),
        ("Executor", "鉴权、校验并真正执行模型提出的工具调用。", "可复用现有 Service，绝不能由模型直接执行代码。"),
        ("ReAct", "Reason + Act 的循环思想：推理、行动、观察。", "可作为单 Agent 设计参考，但生产 Trace 不应泄露敏感思维链。"),
        ("Memory", "跨步骤或跨会话保留有用信息。", "知识库、对话历史、任务状态是三种不同记忆。"),
        ("Checkpoint", "保存可恢复执行快照。", "索引 Batch 已有类似机制；Agent 需新增 Run/Step checkpoint。"),
        ("Guardrail", "对输入、输出、工具、权限、预算和停止设置边界。", "权限、外发检查、SafeSqlExecutor、HITL 可复用。"),
        ("Human-in-the-loop / HITL", "关键操作暂停等待人确认。", "草稿采用、审核、UAT 和未来写工具审批。"),
        ("Trace", "记录一次 Agent 每步决策、工具、耗时、结果和错误。", "可串联 request_id、RetrievalLog、ModelCallLog、AuditLog。"),
        ("Termination Condition", "何时停止：完成、无证据、超时、预算尽、重复循环或人工接管。", "第一版必须硬编码安全上限。"),
        ("Budget", "限制最大步骤、Token、费用和总耗时。", "避免失控循环、费用放大和任务长期占用。"),
        ("Prompt Injection", "恶意输入试图让模型忽略规则或调用危险工具。", "知识文档也视为不可信输入；权限必须由服务端执行。"),
        ("Multi-Agent", "多个拥有独立角色/上下文的 Agent 协作。", "当前未实现；先证明单 Agent，避免为了名称增加复杂度。"),
        ("MCP", "Model Context Protocol，标准化暴露工具和资源的协议。", "当前未接入；MCP 是接入协议，不等于 Agent。"),
        ("Agent Evaluation", "评估任务成功、工具选择、步骤、费用和安全。", "可在现有 RAG Evaluator 上扩展轨迹与越权指标。"),
    ]
    add_table(doc, ["术语", "通俗解释", "本项目如何体现"], _term_rows(agent_terms), [1.55, 2.55, 2.40], 8.0)
    add_callout(
        doc,
        "判断一个功能是不是 Agent",
        "至少问五件事：有没有目标？模型能否选择工具？是否根据 Observation 改变下一步？有没有持久化 State？有没有停止条件？如果只是“检索一次再生成一次”，那是 RAG Workflow，不是完整 Agent。",
        "success",
    )

    doc.add_heading("5. 后端、数据与异步任务术语", level=1)
    eng_terms = [
        ("API", "系统之间约定的调用入口、参数和返回。", "FastAPI 暴露项目、知识、检索、任务和模型配置接口。"),
        ("REST", "围绕资源使用 HTTP 方法和状态码组织 API。", "GET 读取，POST 创建/触发，PATCH 更新等。"),
        ("HTTP 202", "请求已接受，但工作还在后台进行。", "知识上传/索引返回 Job，前端再查询状态。"),
        ("FastAPI", "Python Web API 框架，支持类型、异步和自动文档。", "backend/app/main.py 与 api/。"),
        ("Pydantic", "用类型定义输入输出并自动校验。", "API Schema、模型结构化输出、未来 Tool Schema。"),
        ("ORM", "用对象映射数据库表与查询。", "SQLAlchemy Model 表示 KnowledgeUnit、BackgroundJob 等。"),
        ("SQLAlchemy", "Python 数据库与 ORM 工具。", "负责 Session、查询、事务与模型映射。"),
        ("Transaction", "一组数据库操作要么全部成功，要么回滚。", "摄取按 Batch 提交，避免整文件长事务。"),
        ("Alembic", "SQLAlchemy 常用数据库迁移工具。", "修改模型后通过 migration 演进 PostgreSQL Schema。"),
        ("PostgreSQL", "关系数据库，支持事务、约束、索引和 SQL。", "生产事实库；SQLite 仅用于测试/兼容模式。"),
        ("Redis", "高性能内存数据服务。", "本项目主要作为 Celery Broker/Result Backend。"),
        ("Broker", "消息中间人：接收任务消息并交给 Worker。", "Redis 存放待处理 Celery 消息。"),
        ("Celery", "Python 分布式任务队列框架。", "长任务异步执行，进度写 BackgroundJob。"),
        ("Worker", "从队列取任务并执行的进程。", "解析、索引、评测等处理器运行在 Worker。"),
        ("BackgroundJob", "持久化后台任务的状态模型。", "记录 queued/running/completed/failed、进度与错误。"),
        ("Idempotency", "同一业务请求重复执行，不产生重复副作用。", "语义幂等键 + 数据库唯一约束收敛重复点击。"),
        ("Retry", "暂时失败后有边界地再次尝试。", "需区分可重试/不可重试，限制次数，避免请求风暴。"),
        ("Checkpoint", "记录已完成的安全位置，失败后从此恢复。", "索引 Batch 使用 BackgroundJobItem。"),
        ("Correlation ID", "跨 API、Worker、日志关联一次业务请求的标识。", "用于把前台点击、后台任务、检索与模型调用串起来。"),
        ("Adapter", "把外部系统细节包在统一接口后。", "TaskQueue 的 Inline/Celery、Storage 的 local/S3。"),
        ("Dependency Injection", "把依赖从外部传入，方便替换和测试。", "FastAPI Depends 与 Service Factory。"),
        ("Mock", "与真实组件同接口的可控测试替身。", "Mock LLM/Embedding/VectorStore；不可冒充正式能力。"),
    ]
    add_table(doc, ["术语", "通俗解释", "本项目如何体现"], _term_rows(eng_terms), [1.55, 2.55, 2.40], 8.0)

    doc.add_heading("6. 前端、运维、安全与质量术语", level=1)
    ops_terms = [
        ("Next.js", "基于 React 的 Web 应用框架。", "frontend/；页面、路由、服务端/客户端组件。"),
        ("React", "用组件和状态构建交互界面。", "按钮加载态、任务进度、错误提示都依赖状态管理。"),
        ("TypeScript", "带静态类型的 JavaScript。", "减少 API 字段和空值错误；仍需运行时防御。"),
        ("CORS", "浏览器对跨来源请求的安全控制。", "前端 3000 调后端端口时需允许正确 Origin。"),
        ("JWT", "签名令牌，常用于表示登录身份。", "API 鉴权；不能只在前端隐藏按钮。"),
        ("RBAC", "按角色授予权限。", "项目权限和角色控制读写、审核和管理操作。"),
        ("Docker", "把应用与依赖打包成可重复运行的容器。", "Milvus、etcd、MinIO 等通过 Docker/WSL 启动。"),
        ("Docker Compose", "用一个配置编排多个容器。", "本地统一启动正式语义检索基础设施。"),
        ("WSL", "Windows Subsystem for Linux。", "本机可能在 Ubuntu 中运行 Docker Engine。"),
        ("Health Check", "检查进程是否活着。", "只说明服务有响应，不一定具备完整业务能力。"),
        ("Readiness", "检查依赖是否就绪、能否接收业务流量。", "/health/ready；比容器 Running 更接近“可用”。"),
        ("Environment Variable", "运行时配置值，避免写死在代码。", "模型地址、Provider、数据库连接和密钥环境变量名。"),
        ("Secret", "密码、Token、API Key 等敏感配置。", "Profile 只保存环境变量名，不应保存明文密钥。"),
        ("Data Masking", "外发前遮蔽敏感字段。", "prompt_runtime.py 对外部模型输入执行分级与脱敏。"),
        ("Audit Log", "记录谁在何时对什么做了什么。", "高风险变更、模型外发拒绝和审核决策可追踪。"),
        ("Observability", "用 Logs、Metrics、Traces 理解系统行为。", "BackgroundJob、RetrievalLog、ModelCallLog、correlation id。"),
        ("Log", "离散事件记录。", "错误摘要应可诊断，但不能写密钥、完整敏感 Prompt。"),
        ("Metric", "随时间聚合的数值。", "延迟、吞吐、失败率、Recall、MRR、Token。"),
        ("Trace", "一次请求跨组件的完整路径。", "API→Job→Retrieval→Model→Audit 需要关联。"),
        ("Unit Test", "验证一个小单元的行为。", "Mock/Inline 适合稳定单元测试。"),
        ("Integration Test", "验证多个真实组件协作。", "PostgreSQL、Redis、Celery、Milvus 联调。"),
        ("Smoke Test", "快速确认最关键链路能跑通。", "scripts/smoke_test.py 与本地启动验收。"),
        ("CI/CD", "自动测试、构建、发布和部署。", "提交前 Check；正式 Provider 不能被 Mock 测试替代。"),
        ("Human Approval", "危险或重要动作需人确认。", "审核/UAT；未来 Agent 写工具的门禁。"),
    ]
    add_table(doc, ["术语", "通俗解释", "本项目如何体现"], _term_rows(ops_terms), [1.55, 2.55, 2.40], 8.0)

    doc.add_heading("7. 八条源码学习链", level=1)
    add_callout(
        doc,
        "读代码方法",
        "不要先横向扫完所有 models 或 api。每次沿一条真实用户请求纵向阅读，记录：入口是谁、状态读写什么、边界在哪里、哪个测试证明承诺。",
        "info",
    )
    source_chains = [
        ("模型测试按钮", "前端请求 → api/ai_runtime.py → ModelProfile → llm/factory.py → openai_compatible.py", "看 Provider 选择、密钥环境变量、超时/重试和错误分类。"),
        ("知识上传", "api/knowledge_rag.py → task_queue/submission.py → Redis/Celery → domain_handlers.py → ingestion_service.py", "看 202、幂等、进度、Batch、版本和失败状态。"),
        ("重新构建索引", "reindex API → BackgroundJob → semantic_index/reindex.py → Embedding → Milvus → versioning.py", "看 corpus_hash、checkpoint、验证和原子激活。"),
        ("知识查询", "knowledge_rag API → hybrid_retriever.py → keyword_index.py + Milvus → PostgreSQL", "看过滤、融合、Top-K 和 RetrievalLog。"),
        ("有证据回答", "grounded_answer_service.py → PromptRuntime → LLM → citation_validator.py", "看证据 Prompt、结构化输出、无证据拒答和反虚构。"),
        ("创建后台任务", "前端按钮 → API → idempotency.py → BackgroundJob → Worker → /jobs/{id}", "看重复点击、状态机、进度与任务详情。"),
        ("受控数据库探查", "自然语言/目录请求 → 固定模板 → safe_sql_executor.py", "看为什么模型不能自由写 SQL，以及只读、限行和权限。"),
        ("RAG 评测", "EvaluationCase → rag_evaluator.py → 三种 retrieval_mode → EvaluationResult", "看 Recall@K、MRR、Citation、延迟和版本固化。"),
    ]
    add_table(doc, ["用户问题", "纵向阅读路径", "你要回答"], source_chains, [1.2, 3.25, 2.05], 8.2, TEAL_LIGHT)

    doc.add_heading("8. 常用操作与排障", level=1)
    doc.add_heading("8.1 项目启停", level=2)
    add_code(
        doc,
        "# 在项目根目录打开 PowerShell\n"
        ".\\scripts\\项目启停.ps1 start\n\n"
        "# 查看整体状态、地址和各服务存活情况\n"
        ".\\scripts\\项目启停.ps1 status\n\n"
        "# 重启 / 停止\n"
        ".\\scripts\\项目启停.ps1 restart\n"
        ".\\scripts\\项目启停.ps1 stop",
    )
    add_bullets(
        doc,
        [
            "前端默认：http://127.0.0.1:3000",
            "后端接口文档：以脚本 status 输出为准，通常为 http://127.0.0.1:8000/docs 或项目配置端口。",
            "就绪检查：以脚本 status 中的 /health/ready 为准；不要只看进程或容器是否 Running。",
            "日志目录：项目根目录下 .local-run/logs；脚本失败时会显示最近错误日志。",
        ],
    )
    doc.add_heading("8.2 五步排障法", level=2)
    add_numbers(
        doc,
        [
            "复现并记录：页面、按钮、时间、请求 URL、HTTP 状态码、task/job id。",
            "判断层次：前端状态问题、API 参数/权限、后台任务、数据库、Embedding、Milvus 还是 Chat Provider。",
            "沿 correlation id / job id 查日志和数据库状态，不只看页面报错字符串。",
            "检查依赖 readiness 与配置：PostgreSQL、Redis、Worker、Milvus、Embedding、Chat 模型各自验证。",
            "先写或补一个能复现的测试，再做最小修复；验证成功、失败和重复请求三条路径。",
        ],
    )
    add_table(
        doc,
        ["症状", "先查什么", "常见原因"],
        [
            ("按钮没反馈", "浏览器 Network、前端 loading/error state、API 是否返回 202", "异常未捕获、未显示 job id、重复点击未禁用。"),
            ("任务一直排队", "Redis、Celery Worker、BackgroundJob 状态", "Worker 未启动、Broker 地址不一致、任务未注册。"),
            ("上传后查不到", "文档状态、KnowledgeUnit 数、active index 版本", "只解析未重建索引、任务失败、权限范围不匹配。"),
            ("Embedding 失败", "Embedding health、模型缓存、维度、Provider 配置", "首次下载失败、端口不通、模型/维度不一致。"),
            ("Milvus 查询失败", "容器、19530、Collection、active version", "Docker/WSL 未运行、Collection 未创建、索引未激活。"),
            ("模型测试失败", "ModelProfile、base_url、model、API Key 环境变量", "密钥只填在错误进程环境、地址路径不兼容、401/404。"),
            ("有结果但回答乱", "检索候选、Prompt、结构化输出、Citation", "召回噪声、Top-K 过大、证据冲突、模型未受约束。"),
        ],
        [1.35, 2.55, 2.60],
        8.5,
    )

    doc.add_heading("9. 你真正要达到的工作能力", level=1)
    add_bullets(
        doc,
        [
            "能把一个页面按钮追到 API、Service、数据库、Worker、模型和测试。",
            "能区分模型错误、检索错误、任务错误、权限错误和前端反馈错误。",
            "能用 Schema、权限、幂等、超时、重试、预算与审批约束模型和工具。",
            "能建立固定评测集，用指标判断改造是否有效，而不是只展示 Demo。",
            "能诚实说明“已实现 / 原型 / 规划”，并用真实源码与结果支撑表达。",
        ],
    )
    add_callout(
        doc,
        "术语不是终点",
        "每学一个词，都要完成四个动作：用自己的话解释；在项目中找到真实文件；动手做一个小实验；说出一个失败模式和一个评价指标。",
        "teal",
    )

    path = OUT_DIR / "02_Agent开发工程师术语与项目技术手册.docx"
    doc.save(path)
    return path


def build_roadmap_doc() -> Path:
    doc = Document()
    configure_document(doc, "30 天上手路线")
    title = "30 天快速上手 Agent 开发：项目驱动路线"
    set_core_properties(doc, title, "按当前项目从零学习 LLM、RAG、Agent 与企业工程")
    add_cover(
        doc,
        title,
        "沿用原学习路线的五步闭环，用一个真实项目形成可投递能力",
        ["30-DAY PROJECT-BASED ROADMAP", "说清楚 · 找得到 · 改得动 · 测得出 · 讲得像负责人", "目标岗位：企业 AI 应用 / Agent / 数据 + AI 工程师"],
        "在 30 天内做到：能独立运行与排障项目、讲清 RAG、实现受控单 Agent 原型，并形成面试和作品集证据。",
        "有数据开发、SQL/ETL 或银行业务经验，但 LLM、RAG 和 Agent 基础薄弱的学习者。",
    )
    add_callout(
        doc,
        "路线选择",
        "你的最快路径不是从模型训练或多 Agent 框架开始，而是把已有的数据、SQL、跑批和监管经验翻译成 AI 工程能力：知识建模、工具设计、异步可靠性、证据治理和评测。",
        "teal",
    )
    add_reading_map(
        doc,
        [
            ("1. 目标与学习方法", "知道 30 天后应能交付什么"),
            ("2. 四周能力地图", "先后顺序与依赖关系"),
            ("3. 每日任务表", "每天读什么、做什么、留下什么证据"),
            ("4. 三个递进实战", "从 RAG 诊断到生产级单 Agent"),
            ("5. 入职首周与能力评价", "把学习能力转换成工作能力"),
            ("6. 作品集与面试交付", "让成果可展示、可验证"),
        ],
    )

    doc.add_heading("1. 30 天后的完成标准", level=1)
    add_table(
        doc,
        ["能力", "最低完成标准", "证据"],
        [
            ("项目运行", "能独立启动、查看 status、读日志、定位一个依赖故障", "启动截图 + 一页故障记录"),
            ("LLM", "能解释模型调用、Prompt、结构化输出、错误与安全", "LLM 调用链图 + 一个 Schema"),
            ("RAG", "能讲清摄取、Chunk、Embedding、Milvus、Hybrid、Citation、评测", "RAG 时序图 + 10～50 条 Golden Questions"),
            ("Agent", "能区分 Workflow/RAG/Agent，并做有限步骤单 Agent", "3 个工具 + 最多 5～8 步的可运行 Demo"),
            ("工程化", "能处理异步、幂等、重试、状态、权限、日志与测试", "至少 1 个完整小改动及测试"),
            ("面试", "能用 3 分钟和 10 分钟讲清项目、指标与局限", "录音/视频 + 问题复盘"),
        ],
        [1.15, 3.15, 2.20],
        8.8,
        TEAL_LIGHT,
    )
    add_callout(
        doc,
        "30 天不是“学会所有 AI”",
        "目标是建立可迁移能力：面对陌生模型或框架时，能判断它解决的是生成、检索、编排、状态、工具、安全还是评测问题，并能在真实项目中验证。",
        "warning",
    )

    doc.add_heading("1.1 每天固定节奏", level=2)
    add_table(
        doc,
        ["环节", "工作日 60～120 分钟", "周末 180～240 分钟"],
        [
            ("复述", "10 分钟闭卷讲昨天内容", "20 分钟复盘本周薄弱点"),
            ("阅读", "20～30 分钟概念 + 指定源码", "40 分钟深入一条调用链"),
            ("动手", "20～60 分钟小实验或测试", "100～140 分钟完成一个纵向切片"),
            ("沉淀", "10～20 分钟术语卡/链路图/录音", "30～40 分钟整理 README、指标与演示"),
        ],
        [1.05, 2.75, 2.70],
        9,
    )
    doc.add_heading("1.2 五步学习闭环", level=2)
    add_numbers(
        doc,
        [
            "说清楚：两分钟内不用术语堆砌，用业务语言解释。",
            "找得到：在真实项目定位 API、Service、Model、配置和测试。",
            "改得动：做一个最小、可回滚的小改造。",
            "测得出：定义成功指标、失败样本和回归测试。",
            "讲得像负责人：按问题、决策、权衡、证据、结果、复盘表达。",
        ],
    )

    doc.add_heading("2. 四周能力地图", level=1)
    add_table(
        doc,
        ["阶段", "核心主题", "项目主链", "阶段成果"],
        [
            ("第 1 周", "项目、HTTP、FastAPI、PostgreSQL、Redis/Celery、前端", "按钮→API→DB/Job→Worker", "能独立运行并追踪一条请求"),
            ("第 2 周", "LLM、Prompt、结构化输出、Embedding、RAG", "知识上传→索引→检索→LLM→Citation", "RAG 全链路图与基线"),
            ("第 3 周", "Agent、Tool、State、Loop、Guardrail、Eval", "现有 Service→受控工具→单 Agent", "可运行单 Agent 原型"),
            ("第 4 周", "治理、可靠性、作品集、面试", "权限/审计/评测/故障→交付", "10 分钟讲稿、改造 PR、作品集"),
            ("第 30 天", "综合演练", "启动→演示→故障→评测→面试", "一小时模拟面试与下月 Backlog"),
        ],
        [0.9, 1.75, 2.10, 1.75],
        8.7,
        TEAL_LIGHT,
    )

    doc.add_heading("3. 每日任务表", level=1)
    doc.add_heading("第 1 周：先成为“能跑、能追、能排”的工程师", level=2)
    week1 = [
        ("1", "项目全貌", "README、说明文档索引、部署架构、项目启停.ps1", "启动 production 模式；查看 status 和 /health/ready", "手画六层组件图"),
        ("2", "HTTP/API/JSON", "frontend/lib/api.ts + 一个后端 API 路由", "在 /docs 调一个 GET 和一个 POST；记录状态码", "请求/响应样例"),
        ("3", "FastAPI/Pydantic", "backend/app/main.py、api/、schemas/", "从路由追到 Service；故意提交错误参数", "路由→服务→Schema 图"),
        ("4", "PostgreSQL/ORM", "core/database.py、models 中 Knowledge/Job/Index", "写 5 条只读 SQL，查文档、Chunk、任务、索引版本", "实体关系草图"),
        ("5", "Redis/Celery", "task_queue/、workers.py、jobs API", "创建后台任务，观察 queued/running/completed", "任务时序图"),
        ("6", "Next.js/状态反馈", "页面组件、api.ts、任务轮询", "从按钮追到请求；解释 loading、error、job id", "一次前后端链路"),
        ("7", "复盘演示", "重读第 1 周笔记", "完整演示启动、上传、任务详情与日志", "5 分钟录屏 + 错题"),
    ]
    add_table(doc, ["日", "主题", "阅读", "动手", "必须产出"], week1, [0.35, 0.9, 1.75, 2.15, 1.35], 7.9)

    doc.add_heading("第 2 周：真正理解 LLM 与 RAG", level=2)
    week2 = [
        ("8", "LLM 基础", "模型调用流程.md；llm/base.py", "闭卷解释 Token、Prompt、Inference、Hallucination", "9 张术语卡"),
        ("9", "Provider/Gateway", "llm/factory.py、openai_compatible.py、ModelProfile", "查看模型测试接口；区分 401/404/429/5xx", "LLM 调用链图"),
        ("10", "结构化输出", "structured_outputs.py、prompt_runtime.py", "新增一个简单 Pydantic 输出 Schema 和失败用例", "Schema + 测试"),
        ("11", "模型安全", "security/、prepare_model_input、ModelCallLog", "找出分级、脱敏、日志摘要和拒绝外发", "5 条安全边界"),
        ("12", "Embedding", "embeddings/、local_embedding_server.py", "生成同义句与无关句向量，记录维度和相似度", "三组向量实验"),
        ("13", "知识摄取", "parsers.py、normalizer.py、ingestion_service.py", "上传一种文件；追踪 KnowledgeUnit 与出处", "入库数据流图"),
        ("14", "Milvus/索引", "vector/milvus.py、semantic_index/reindex.py", "查看 active index、Collection、count；解释重建", "版本发布图"),
    ]
    add_table(doc, ["日", "主题", "阅读", "动手", "必须产出"], week2, [0.35, 0.9, 1.75, 2.15, 1.35], 7.9)
    week2b = [
        ("15", "关键词检索", "keyword_index.py", "测试字段名、代码、中文自然语言问题", "关键词优势清单"),
        ("16", "向量检索", "hybrid_retriever.py 的 vector_only", "运行相同问题，记录成功和失败样例", "失败分类"),
        ("17", "Hybrid", "hybrid_retriever.py 全链路", "比较 keyword/vector/hybrid 三组 Top-K", "效果对比表"),
        ("18", "Citation", "grounded_answer_service.py、citation_validator.py", "构造无证据、错误 citation、跨项目引用", "三类失败测试"),
        ("19", "RAG 评测", "rag_evaluator.py、rag-evaluation.md", "解释 Recall@5、MRR、Citation Coverage、P95", "一页指标卡"),
        ("20", "黄金问题集", "现有 EvaluationCase 与业务文档", "先建 10 条，再扩展到 20～50 条问题", "版本化数据集"),
        ("21", "第 2 周复盘", "五条 RAG 源码链", "不看稿讲完整入库与查询；复跑基线", "10 分钟 RAG 讲解"),
    ]
    add_table(doc, ["日", "主题", "阅读", "动手", "必须产出"], week2b, [0.35, 0.9, 1.75, 2.15, 1.35], 7.9)

    doc.add_heading("第 3 周：从 Workflow 走到受控单 Agent", level=2)
    week3 = [
        ("22", "Workflow vs Agent", "原路线 04-Agent开发.md；本手册 Agent 术语", "给当前功能分类：固定流程 / 可作为工具 / 需 Agent", "边界表"),
        ("23", "工具设计", "HybridRetriever、文档读取、jobs API", "定义 3 个只读工具的 Pydantic Schema", "Tool Contract"),
        ("24", "Agent State", "BackgroundJob 与治理状态模型", "定义 AgentRun、AgentStep、ToolResult", "状态模型草图"),
        ("25", "最小 Agent Loop", "普通 Python 状态机；暂不依赖框架", "实现最多 5 步：选择工具→执行→观察→停止", "CLI Demo"),
        ("26", "Guardrail", "权限、resource guard、SafeSqlExecutor", "加入参数校验、项目鉴权、重复调用与超时", "被拒绝测试"),
        ("27", "Memory/HITL", "知识库、任务状态、审核流程", "区分三种记忆；为写操作增加人工确认", "生命周期表"),
        ("28", "Agent Eval", "现有 Evaluator 设计", "建立 10 条任务 + 10 条安全样例，记录轨迹", "成功率/步骤/越权"),
    ]
    add_table(doc, ["日", "主题", "阅读", "动手", "必须产出"], week3, [0.35, 0.9, 1.75, 2.15, 1.35], 7.9)

    doc.add_heading("第 4 周：可靠性、作品集与面试", level=2)
    week4 = [
        ("29A", "可靠性", "task_queue/idempotency.py、checkpoint、日志", "模拟模型超时、Redis 失败或 Milvus 不可用；写恢复方案", "故障演练记录"),
        ("29B", "作品集", "本项目指标与源码路径", "整理架构图、RAG 对比、Agent Trace、测试与 README", "作品集目录"),
        ("29C", "面试表达", "面试讲解文档 + 原 300 题题库", "录制 3 分钟和 10 分钟讲解，回答 20 题", "错题与改稿"),
        ("30", "综合验收", "所有资料", "启动、演示、制造一个故障、解释指标、完成 60 分钟模拟面试", "评分表 + 下月 Backlog"),
    ]
    add_table(doc, ["日", "主题", "阅读", "动手", "必须产出"], week4, [0.45, 0.9, 1.75, 2.15, 1.25], 7.9)
    add_callout(
        doc,
        "日期说明",
        "原路线按 2026-07-23 至 2026-08-21 排期。本版保留 30 个学习日的依赖顺序，但不绑定日历；中断后从最近一个“必须产出”继续，不必从头重来。",
        "neutral",
    )

    doc.add_heading("4. 三个递进实战", level=1)
    doc.add_heading("实战一：RAG 检索诊断助手", level=2)
    add_bullets(
        doc,
        [
            "输入同一个问题，同时展示 Keyword、Vector、Hybrid 三种 Top-K。",
            "每条结果展示文档、Chunk、分数、Citation、索引版本与耗时。",
            "不调用 Chat 模型也能使用，以便把检索问题和生成问题分开。",
            "至少准备 10 个固定问题，记录成功、失败和为什么。",
        ],
    )
    add_callout(
        doc,
        "验收",
        "你能解释某条结果为什么排前、某个问题为什么 Vector-only 失败，以及调整 Top-K/融合权重后 Recall 与延迟如何变化。",
        "success",
    )

    doc.add_heading("实战二：单 Agent 知识助理", level=2)
    add_code(
        doc,
        "search_knowledge(query, project_id)\n"
        "get_document(document_id, project_id)\n"
        "get_background_job(job_id, project_id)",
    )
    add_bullets(
        doc,
        [
            "最大 5 步；每步只允许调用一个工具；参数必须 Pydantic 校验。",
            "每次工具执行重新做 project 权限校验，错误返回结构化错误。",
            "每步记录模型、工具、参数摘要、结果摘要、耗时和终止原因。",
            "无证据不得编造；任务仍在执行时先返回任务状态。",
        ],
    )
    add_callout(
        doc,
        "示例任务",
        "“查找贷款余额计算规则，确认知识库是否有依据；若索引任务仍在执行，先告诉我任务状态；有证据则返回出处，没有则明确待确认。”",
        "info",
    )

    doc.add_heading("实战三：可恢复、可审批的生产级单 Agent", level=2)
    add_bullets(
        doc,
        [
            "AgentRun、AgentStep、ToolCall 持久化到 PostgreSQL。",
            "Celery 异步执行，支持 checkpoint、失败恢复和取消。",
            "只读工具自动执行；request_knowledge_reindex、save_draft、create_review_task 等写工具必须人工审批。",
            "限制最大步骤、总耗时、Token、费用和重复调用。",
            "固定评测集验证任务成功率、工具选择正确率、平均步骤、越权率、延迟与成本。",
            "页面展示每步轨迹、失败原因和人工审批节点。",
        ],
    )
    add_callout(
        doc,
        "为什么先单 Agent",
        "多 Agent 会增加调用次数、状态、延迟和不可预测性。只有评测证明 Planner/Executor/Reviewer 分工相对单 Agent 有稳定收益，才值得保留。",
        "warning",
    )

    doc.add_heading("5. 入职 Agent 岗位后的首周检查清单", level=1)
    first_week = [
        ("第 1 天：业务边界", "目标是什么？哪些步骤必须确定性？哪些允许模型判断？哪些会写库、发消息、花钱或影响客户？哪里必须人工审批？"),
        ("第 2 天：系统运行", "能否独立启动 API、前端、Worker、数据库、Redis、向量库？Health 与 Ready 有何区别？Mock 与正式 Provider 如何辨认？"),
        ("第 3 天：主链路", "从页面按钮找到 API、Service、数据库和外部模型；找到对应测试；用 correlation id 串起来。"),
        ("第 4 天：数据与失败", "事实源是什么？向量索引是否可重建？重试会不会重复写？换 Embedding 是否重建？失败能否恢复？"),
        ("第 5 天：完整小改动", "先补失败测试，修改最小范围，验证成功/失败/重复请求，更新文档，并能解释权衡。"),
    ]
    add_table(doc, ["时间", "必须问清并做到"], first_week, [1.4, 5.1], 9.2, TEAL_LIGHT)

    doc.add_heading("6. 能力评价与投递门槛", level=1)
    add_table(
        doc,
        ["能力", "1 分：能解释", "2 分：能实现", "3 分：能评测与权衡"],
        [
            ("LLM", "Token、Prompt、结构化输出", "接入 Provider、Schema、失败处理", "Prompt/模型版本、成本、回归"),
            ("RAG", "Chunk、Embedding、Hybrid、Citation", "完成摄取、检索、问答", "Golden Dataset、Recall/MRR、切片"),
            ("Agent", "Workflow/Agent、Tool、State", "有限循环、鉴权、停止", "轨迹、安全、预算、HITL"),
            ("后端", "API、ORM、事务、异步", "FastAPI/PostgreSQL/Celery", "幂等、恢复、性能、观测"),
            ("治理", "权限、分级、审计", "服务端控制与人工审批", "威胁模型、门禁与演练"),
            ("表达", "能讲概念", "能讲真实源码", "能讲问题、决策、数据和复盘"),
        ],
        [1.0, 1.75, 1.85, 1.90],
        8.3,
    )
    add_callout(
        doc,
        "开始投递的现实标准",
        "综合达到“多数能力 2 分”，并且有一项量化 RAG 改造、一个受控单 Agent 原型、一次完整模拟面试，就可以边投边学。不要等待“全会了”。",
        "success",
    )

    doc.add_heading("7. 作品集交付清单", level=1)
    add_bullets(
        doc,
        [
            "architecture/：六层架构图、知识入库时序图、RAG 查询时序图、单 Agent 状态图。",
            "experiments/：Keyword/Vector/Hybrid/RRF 对比，包含数据集版本、Recall@K、MRR、P50/P95 和失败样例。",
            "tests/：Golden Questions、模型输出 Schema 测试、重复任务、跨项目 Citation、Prompt Injection 与越权测试。",
            "demo/：项目启动、知识上传、索引、问答、任务详情和 Agent Demo 的 3～5 分钟录屏。",
            "interview/：3 分钟与 10 分钟讲稿、20 个高频问答、5 个真实 STAR 故事。",
            "README：清楚区分当前已实现、你本人改动、原型能力和未来规划。",
        ],
    )
    doc.add_heading("7.1 每日学习记录模板", level=2)
    add_code(
        doc,
        "日期：\n"
        "主题：\n"
        "我能不看资料解释什么：\n"
        "我定位了哪些源码：\n"
        "我做了什么改动或实验：\n"
        "指标 / 测试结果：\n"
        "仍然不会的问题：\n"
        "两分钟面试回答：",
    )
    doc.add_heading("7.2 高频坑：每周复盘一次", level=2)
    add_bullets(
        doc,
        [
            "把调用一次模型叫 Agent；把 RAG 叫 Agent；把知识库叫 Agent Memory。",
            "混淆 Chat 与 Embedding；换 Embedding 模型却不重建索引。",
            "把向量库当事实源；认为相似度高就一定正确；Top-K 越大越好。",
            "只测最终答案，不单独测解析、召回、排序、Citation 和权限。",
            "正式 Provider 失败后静默回退 Mock，产生看似成功的假结果。",
            "只在前端禁用按钮，没有后端幂等；无限重试导致重复任务或费用风暴。",
            "信任模型 JSON、SQL 或工具参数；把安全只写进 Prompt。",
            "一开始就上多 Agent 或复杂框架，却没有状态、停止和评测。",
        ],
    )
    add_callout(
        doc,
        "你的差异化定位",
        "推荐目标：企业级 AI 应用开发工程师 / Agent 工程师 / 数据 + AI 工程师。不要包装成大模型训练或算法研究专家；你的优势是银行业务、数据语义、SQL/ETL、可靠性与 AI 治理的结合。",
        "teal",
    )

    path = OUT_DIR / "03_30天快速上手Agent开发项目路线.docx"
    doc.save(path)
    return path


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = [
        build_interview_doc(),
        build_glossary_doc(),
        build_roadmap_doc(),
    ]
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
