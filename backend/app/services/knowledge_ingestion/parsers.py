from io import BytesIO
from pathlib import Path
import re
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from app.services.sql_parser import parse_sql
from app.core.settings import get_settings
from .base import KnowledgeUnitDraft
from .ocr import IMAGE_SUFFIXES

# A clause number written into the unit's own text, mirroring
# ``agent.tools.evidence.INSCRIBED_CLAUSE_PATTERN``: the ingestion side records what
# the citation side will accept, and neither may drift.
CLAUSE_NUMBER_PATTERN = re.compile(r"^(?:第[零一二三四五六七八九十百千\d]{1,12}条|\d+(?:\.\d+){1,4})(?![\d.])")
CHAPTER_NUMBER_PATTERN = re.compile(r"^(第[零一二三四五六七八九十百千\d]{1,12}章)")
QUESTION={"问题","答疑问题","监管问题","银行问题"};ANSWER={"回复","监管回复","答疑结果","处理意见"};SUGGESTION={"同业建议"};FIELD_CODE={"字段代码","数据项编码"};FIELD_NAME={"字段名称","字段中文名","数据项名称"};TABLE={"一表通表","表代码"};SCENARIO={"业务场景","产品场景","场景名称"};BUSINESS_SYSTEM={"来源系统","业务系统","系统名称"};SOURCE_TABLE={"来源表","来源表英文名","源表","源表英文名"};SOURCE_FIELD={"来源字段","来源字段英文名","源字段","源字段英文名"};MART_TABLE={"集市表","监管集市表"};MART_FIELD={"集市字段","监管集市字段"}

def parse_document(file_name,content,knowledge_type):
    units, warnings = _parse_document(file_name, content, knowledge_type)
    for index, unit in enumerate(units, 1):
        locator = unit.metadata.setdefault("locator", {})
        locator.setdefault("block_id", f"parsed-block-{index}")
        for key, value in (("page_no", unit.source_page_no), ("sheet_name", unit.source_sheet_name),
                           ("cell_range", unit.source_cell_range), ("heading", unit.source_heading),
                           ("row_no", unit.metadata.get("row")), ("paragraph_index", unit.metadata.get("paragraph")),
                           ("chapter_no", unit.metadata.get("chapter_no")), ("clause_no", unit.metadata.get("clause_no"))):
            if value is not None:
                locator.setdefault(key, value)
    return units, warnings


def _text_units(text, file_name, unit_type="paragraph"):
    units = []
    for index, match in enumerate(re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", text), 1):
        if not match.group().strip():
            continue
        units.append(KnowledgeUnitDraft(unit_type, file_name, match.group(), metadata={"locator": {
            "paragraph_index": index, "char_start": match.start(), "char_end": match.end(),
            "line_start": text.count("\n", 0, match.start()) + 1,
            "line_end": text.count("\n", 0, match.end()) + 1,
        }}))
    return units


def _parse_document(file_name,content,knowledge_type):
    suffix=Path(file_name).suffix.lower()
    SUPPORTED_SUFFIXES = {".xlsx", ".docx", ".pdf", ".txt", ".md", ".sql"} | IMAGE_SUFFIXES
    if suffix not in SUPPORTED_SUFFIXES:raise ValueError(f"Unsupported knowledge document format: {suffix or 'missing extension'}")
    if suffix==".xlsx":return _excel(content,knowledge_type)
    if suffix==".docx":return _docx(content)
    if suffix==".pdf":return _pdf(content)
    if suffix in IMAGE_SUFFIXES:
        # Images are only a knowledge document once OCR can read them; otherwise the
        # historical "unsupported format" contract is preserved byte-for-byte.
        if not getattr(get_settings(),"ocr_enabled",False):raise ValueError(f"Unsupported knowledge document format: {suffix or 'missing extension'}")
        return _image(content,suffix)
    text=content.decode("utf-8",errors="replace").replace("\r\n","\n").replace("\r","\n")
    if suffix==".sql":
        parsed=parse_sql(text);summary=f"来源表: {', '.join(parsed.source_tables)}\n来源字段: {', '.join(parsed.selected_fields)}\n关联条件: {'; '.join(parsed.joins)}\n过滤条件: {'; '.join(parsed.where_conditions)}"
        return [KnowledgeUnitDraft("sql_summary",file_name,summary,metadata={"raw_sql":text,"parsed_success":parsed.parsed_success,"locator":{"line_start":1,"line_end":len(text.splitlines()) or 1}}), *_text_units(text,file_name,"sql_text")],[parsed.error_message] if parsed.error_message else []
    return _text_units(text,file_name),[]

def _excel(content,knowledge_type):
    wb=load_workbook(BytesIO(content),data_only=True);units=[];warnings=[]
    for sheet in wb.worksheets:
        matrix=_expanded_matrix(sheet)
        header_row=None;headers={}
        for row in range(1,min(len(matrix),50)+1):
            values={column:str(matrix[row-1][column-1] or "").strip() for column in range(1,sheet.max_column+1)}
            if any(value in QUESTION|ANSWER|FIELD_CODE|FIELD_NAME for value in values.values()):header_row=row;headers=values;break
        if not header_row:warnings.append(f"{sheet.title} 未识别表头");continue
        for row in range(header_row+1,sheet.max_row+1):
            values={headers[column]:matrix[row-1][column-1] for column in headers if headers[column]}
            if not any(value not in (None,"") for value in values.values()):continue
            question=next((str(values[key]) for key in QUESTION if values.get(key)),"");answer=next((str(values[key]) for key in ANSWER if values.get(key)),"");suggestion=next((str(values[key]) for key in SUGGESTION if values.get(key)),"")
            field_code=next((str(values[key]) for key in FIELD_CODE if values.get(key)),None);field_name=next((str(values[key]) for key in FIELD_NAME if values.get(key)),None);table=next((str(values[key]) for key in TABLE if values.get(key)),None);scenario_name=next((str(values[key]) for key in SCENARIO if values.get(key)),None);business_system=next((str(values[key]) for key in BUSINESS_SYSTEM if values.get(key)),None);source_table=next((str(values[key]) for key in SOURCE_TABLE if values.get(key)),None);source_field=next((str(values[key]) for key in SOURCE_FIELD if values.get(key)),None);mart_table=next((str(values[key]) for key in MART_TABLE if values.get(key)),None);mart_field=next((str(values[key]) for key in MART_FIELD if values.get(key)),None)
            content_text="\n".join(filter(None,[f"问题：{question}" if question else "",f"回复：{answer}" if answer else "",f"同业建议：{suggestion}" if suggestion else "", "；".join(f"{key}：{value}" for key,value in values.items() if value not in (None,"") and key not in QUESTION|ANSWER|SUGGESTION)]))
            unit_type="qa" if question or knowledge_type=="regulatory_qa" else "field_mapping" if field_code else "table_row"
            units.append(KnowledgeUnitDraft(unit_type,question or field_name or f"{sheet.title} 第{row}行",content_text,source_sheet_name=sheet.title,source_cell_range=f"A{row}:{get_column_letter(sheet.max_column)}{row}",target_table_code=table,target_field_code=field_code,target_field_name=field_name,scenario_name=scenario_name,source_table_name=source_table,source_field_name=source_field,metadata={"row":row,"scenario_name":scenario_name,"business_system_name":business_system,"mart_table_name":mart_table,"mart_field_name":mart_field}))
    return units,warnings

def _expanded_matrix(sheet):
    matrix=[[sheet.cell(row,column).value for column in range(1,sheet.max_column+1)] for row in range(1,sheet.max_row+1)]
    for merged in sheet.merged_cells.ranges:
        value=matrix[merged.min_row-1][merged.min_col-1]
        for row in range(merged.min_row,merged.max_row+1):
            for column in range(merged.min_col,merged.max_col+1):matrix[row-1][column-1]=value
    return matrix

def _docx(content):
    from docx import Document
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    doc=Document(BytesIO(content));units=[];heading=None;chapter=None
    paragraph_index=0;table_index=0
    for element in doc.element.body.iterchildren():
        if element.tag.endswith("}p"):
            paragraph_index+=1;p=Paragraph(element,doc);text=p.text.strip()
            if not text:continue
            if p.style and p.style.name.lower().startswith("heading"):
                heading=text
                chapter_match=CHAPTER_NUMBER_PATTERN.match(text)
                # A heading without a chapter number (``附录``, ``总则``) ends the chapter
                # scope of the previous one: clauses below it are not part of 第三章.
                chapter=chapter_match.group(1) if chapter_match else None
                # A heading states where the units below it live; it is not a citable
                # clause of its own.  Emitting it as a policy_clause made every chapter
                # heading an uncitable unit and a permanent clause_locator_missing gap.
                continue
            clause_match=CLAUSE_NUMBER_PATTERN.match(text)
            metadata={"paragraph":paragraph_index,
                      "clause_no":clause_match.group(0) if clause_match else None,
                      "chapter_no":chapter,
                      "chapter_heading":heading}
            units.append(KnowledgeUnitDraft("policy_clause",heading or f"段落 {paragraph_index}",text,source_heading=heading,metadata=metadata))
        elif element.tag.endswith("}tbl"):
            table_index+=1;table=Table(element,doc)
            for row_index,row in enumerate(table.rows,1):
                text=" | ".join(cell.text.strip() for cell in row.cells)
                if text.strip(" | "):units.append(KnowledgeUnitDraft("table_row",f"表格 {table_index} 第{row_index}行",text,source_heading=heading,source_cell_range=f"table:{table_index}:row:{row_index}",metadata={"locator":{"table_index":table_index,"row_no":row_index},"chapter_no":chapter}))
    return units,[]

def _pdf(content):
    """Parse a PDF; scanned pages go through OCR only when ocr_enabled is on."""
    if not getattr(get_settings(),"ocr_enabled",False):return _pdf_text_layer(content)
    return _pdf_with_ocr(content)


def _pdf_text_layer(content):
    from pypdf import PdfReader
    units=[];warnings=[]
    for page_no,page in enumerate(PdfReader(BytesIO(content)).pages,1):
        text=(page.extract_text() or "").strip()
        if text:units.append(KnowledgeUnitDraft("policy_clause",f"第 {page_no} 页",text,source_page_no=page_no))
        else:warnings.append(f"第 {page_no} 页无可提取文本，未启用 OCR")
    return units,warnings


def _pdf_with_ocr(content):
    """OCR fallback for pages without a text layer, truncated at ocr_max_pages."""
    from pypdf import PdfReader
    from .ocr import run_ocr
    settings=get_settings()
    try:pages=list(PdfReader(BytesIO(content)).pages)
    except Exception as exc:raise ValueError(f"PDF 无法读取：{type(exc).__name__}: {exc}") from exc
    raw_max_pages=getattr(settings,"ocr_max_pages",50)
    max_pages=50 if raw_max_pages is None else int(raw_max_pages)
    if max_pages<=0:return [],[f"ocr_max_pages={max_pages} 无效，未处理任何页面"]
    units=[];warnings=[]
    state={"engine":None,"loaded":False,"provider_reported":False}
    if len(pages)>max_pages:warnings.append(f"扫描件共 {len(pages)} 页，超过 ocr_max_pages={max_pages}，仅处理前 {max_pages} 页（已截断）")
    for page_no,page in enumerate(pages[:max_pages],1):
        text=(page.extract_text() or "").strip()
        if text:units.append(KnowledgeUnitDraft("policy_clause",f"第 {page_no} 页",text,source_page_no=page_no));continue
        units.extend(_ocr_pdf_page(page,page_no,settings,run_ocr,warnings,state))
    return units,warnings


def _ocr_pdf_page(page,page_no,settings,run_ocr,warnings,state):
    from .ocr import page_images, resolve_provider_name
    images=page_images(page)
    if not images:warnings.append(f"第 {page_no} 页无可提取文本且无可 OCR 图像，已跳过");return []
    engine,provider_error=_ocr_engine(settings,state)
    if engine is None:
        if provider_error and not state.get("provider_reported"):
            state["provider_reported"]=True;warnings.append(provider_error)
        warnings.append(f"第 {page_no} 页无可提取文本：OCR provider '{resolve_provider_name(getattr(settings,'ocr_provider',None))}' 不可用，已跳过该页")
        return []
    result=run_ocr(images,provider=getattr(settings,"ocr_provider",None),engine=engine)
    warnings.extend(result.warnings)
    if not result.available:warnings.append(f"第 {page_no} 页无可提取文本：OCR provider '{result.provider}' 不可用，已跳过该页");return []
    text="\n".join(part.strip() for part in result.texts if part and part.strip()).strip()
    if not text:warnings.append(f"第 {page_no} 页 OCR 未识别出文本");return []
    units=_text_units(text,f"第 {page_no} 页（OCR）","policy_clause")
    for unit in units:unit.source_page_no=page_no
    return units


def _ocr_engine(settings,state):
    """Load the OCR engine at most once per document, caching failures too."""
    if not state["loaded"]:
        from .ocr import load_engine_or_warn
        engine,error=load_engine_or_warn(getattr(settings,"ocr_provider",None))
        state["loaded"]=True;state["engine"]=engine;state["error"]=error
    return state["engine"],state.get("error")


def _image(content,suffix):
    """Parse a standalone scanned image; callers gate this on ocr_enabled."""
    from .ocr import image_from_bytes, run_ocr
    settings=get_settings()
    title=f"扫描图片 {suffix.lstrip('.')}"

    image=image_from_bytes(content)
    if image is None:return [],[f"{title} 无法解码为图像，OCR 已跳过"]
    result=run_ocr([image],provider=getattr(settings,"ocr_provider",None))
    warnings=list(result.warnings)
    if not result.available:warnings.append(f"{title} OCR provider '{result.provider}' 不可用，已跳过");return [],warnings
    text="\n".join(part.strip() for part in result.texts if part and part.strip()).strip()
    if not text:warnings.append(f"{title} OCR 未识别出文本");return [],warnings
    units=_text_units(text,title,"policy_clause")
    for unit in units:unit.source_page_no=1
    return units,warnings
