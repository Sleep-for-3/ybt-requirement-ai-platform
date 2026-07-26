import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DataSource


@dataclass
class ParsedNaturalLanguageTask:
    status: str
    message: str
    datasource_id: int | None = None
    datasource_name: str | None = None
    intent: str | None = None
    extracted_table_name: str | None = None
    extracted_field_name: str | None = None
    available_datasources: list[str] = field(default_factory=list)


INTENT_KEYWORDS = ["探查", "查询", "分析", "空值率", "枚举", "分布", "distinct", "最大值", "最小值", "数量", "count"]
IDENTIFIER_PATTERN = re.compile(r"\b[a-zA-Z][a-zA-Z0-9_]{2,}\b")


class NaturalLanguageTaskParser:
    def __init__(self, db: Session) -> None:
        self.db = db

    def parse(self, project_id: int, raw_text: str) -> ParsedNaturalLanguageTask:
        datasources = list(
            self.db.scalars(
                select(DataSource).where(DataSource.project_id == project_id, DataSource.enabled.is_(True)).order_by(DataSource.name)
            ).all()
        )
        matched = [datasource for datasource in datasources if datasource.name in raw_text]
        if not matched:
            return ParsedNaturalLanguageTask(
                status="need_clarification",
                message="未识别到数据源名称，请在任务中使用已配置的数据源名称。",
                available_datasources=[datasource.name for datasource in datasources],
            )
        if len(matched) > 1:
            return ParsedNaturalLanguageTask(
                status="need_clarification",
                message="识别到多个数据源名称，请明确使用其中一个。",
                available_datasources=[datasource.name for datasource in matched],
            )

        datasource = matched[0]
        if any(keyword in raw_text for keyword in ["查找", "候选字段", "相关字段", "数据目录"]):
            return ParsedNaturalLanguageTask(
                status="parsed", message=f"已识别为 {datasource.name} 数据目录搜索任务。",
                datasource_id=datasource.id, datasource_name=datasource.name, intent="catalog_search",
            )
        table_name, field_name = _extract_table_and_field(raw_text, datasource.name)
        intent = "db_query_or_profile" if any(keyword.lower() in raw_text.lower() for keyword in INTENT_KEYWORDS) else "unknown"
        if not table_name or not field_name:
            return ParsedNaturalLanguageTask(
                status="need_clarification",
                message=f"已识别数据源 {datasource.name}，但未识别到候选表名或字段名，请补充，例如：查询 ecif_customer 表 cert_type 字段。",
                datasource_id=datasource.id,
                datasource_name=datasource.name,
                intent=intent,
                extracted_table_name=table_name,
                extracted_field_name=field_name,
            )
        return ParsedNaturalLanguageTask(
            status="parsed",
            message=f"已识别数据源 {datasource.name}，表 {table_name}，字段 {field_name}。",
            datasource_id=datasource.id,
            datasource_name=datasource.name,
            intent=intent,
            extracted_table_name=table_name,
            extracted_field_name=field_name,
        )


def _extract_table_and_field(raw_text: str, datasource_name: str) -> tuple[str | None, str | None]:
    table_name = _match_first(raw_text, [r"from\s+([a-zA-Z][a-zA-Z0-9_]+)", r"([a-zA-Z][a-zA-Z0-9_]+)\s*表", r"表\s*([a-zA-Z][a-zA-Z0-9_]+)"])
    field_name = _match_first(raw_text, [r"([a-zA-Z][a-zA-Z0-9_]+)\s*字段", r"字段\s*([a-zA-Z][a-zA-Z0-9_]+)"])
    tokens = [token for token in IDENTIFIER_PATTERN.findall(raw_text) if token != datasource_name]
    if table_name is None and tokens:
        table_candidates = [token for token in tokens if "_" in token]
        table_name = table_candidates[0] if table_candidates else tokens[0]
    if field_name is None and tokens:
        remaining = [token for token in tokens if token != table_name]
        field_candidates = [token for token in remaining if "_" in token]
        field_name = field_candidates[0] if field_candidates else (remaining[0] if remaining else None)
    return table_name, field_name


def _match_first(raw_text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, raw_text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None
