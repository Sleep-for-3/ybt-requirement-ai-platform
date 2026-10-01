import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CatalogTable, DataSource


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


INTENT_KEYWORDS = [
    "探查", "查询", "分析", "空值率", "枚举", "分布", "distinct",
    "最大值", "最小值", "数量", "count", "统计", "汇总", "查看", "检查"
]
IDENTIFIER_PATTERN = re.compile(r"\b[a-zA-Z][a-zA-Z0-9_]{2,}\b")


class NaturalLanguageTaskParser:
    def __init__(self, db: Session) -> None:
        self.db = db

    def parse(self, project_id: int, raw_text: str) -> ParsedNaturalLanguageTask:
        datasources = list(
            self.db.scalars(
                select(DataSource).where(
                    DataSource.project_id == project_id,
                    DataSource.enabled.is_(True)
                ).order_by(DataSource.name)
            ).all()
        )
        if not datasources:
            return ParsedNaturalLanguageTask(
                status="need_clarification",
                message="当前项目未配置或未启用任何有效数据源，请先在数据源管理中配置数据源。",
                available_datasources=[],
            )

        # 1. First extract candidate table and field
        matched_ds_names = [ds.name for ds in datasources if ds.name in raw_text]
        primary_ds_name = matched_ds_names[0] if matched_ds_names else ""
        table_name, field_name = _extract_table_and_field(raw_text, primary_ds_name)

        # 2. Determine target DataSource
        datasource: DataSource | None = None
        inferred = False

        if len(matched_ds_names) == 1:
            datasource = next(ds for ds in datasources if ds.name == matched_ds_names[0])
        elif len(matched_ds_names) > 1:
            return ParsedNaturalLanguageTask(
                status="need_clarification",
                message="识别到多个数据源名称，请明确使用其中一个。",
                available_datasources=matched_ds_names,
            )
        else:
            # Automatic Schema Linking / Default Inference
            if len(datasources) == 1:
                datasource = datasources[0]
                inferred = True
            elif table_name:
                # Schema Linking via CatalogTable
                matching_tables = list(
                    self.db.scalars(
                        select(CatalogTable).where(
                            CatalogTable.project_id == project_id,
                            CatalogTable.table_name.ilike(table_name),
                        )
                    ).all()
                )
                if len(matching_tables) == 1 and matching_tables[0].datasource_id:
                    matched_ds = self.db.get(DataSource, matching_tables[0].datasource_id)
                    if matched_ds and matched_ds.enabled:
                        datasource = matched_ds
                        inferred = True

            if datasource is None:
                return ParsedNaturalLanguageTask(
                    status="need_clarification",
                    message="未识别到数据源名称且无法通过表名自动关联，请在任务中指明数据源名称。",
                    available_datasources=[ds.name for ds in datasources],
                    extracted_table_name=table_name,
                    extracted_field_name=field_name,
                )

        # 3. Intent detection
        if any(keyword in raw_text for keyword in ["查找", "候选字段", "相关字段", "数据目录"]):
            return ParsedNaturalLanguageTask(
                status="parsed",
                message=f"已识别为 {datasource.name} 数据目录搜索任务。",
                datasource_id=datasource.id,
                datasource_name=datasource.name,
                intent="catalog_search",
                extracted_table_name=table_name,
                extracted_field_name=field_name,
            )

        intent = "db_query_or_profile" if any(keyword.lower() in raw_text.lower() for keyword in INTENT_KEYWORDS) else "unknown"

        if not table_name or not field_name:
            prompt_prefix = f"已通过 Schema Linking 关联至数据源 {datasource.name}" if inferred else f"已识别数据源 {datasource.name}"
            return ParsedNaturalLanguageTask(
                status="need_clarification",
                message=f"{prompt_prefix}，但未识别到候选表名或字段名，请补充（例如：查询 ecif_customer 表 cert_type 字段）。",
                datasource_id=datasource.id,
                datasource_name=datasource.name,
                intent=intent,
                extracted_table_name=table_name,
                extracted_field_name=field_name,
                available_datasources=[ds.name for ds in datasources],
            )

        ack = f"已识别数据源 {datasource.name}" + ("（Schema Linking 自动推导）" if inferred else "")
        return ParsedNaturalLanguageTask(
            status="parsed",
            message=f"{ack}，表 {table_name}，字段 {field_name}。",
            datasource_id=datasource.id,
            datasource_name=datasource.name,
            intent=intent,
            extracted_table_name=table_name,
            extracted_field_name=field_name,
        )


def _extract_table_and_field(raw_text: str, datasource_name: str = "") -> tuple[str | None, str | None]:
    # 1. Check dot notation: e.g. "ecif_customer.cert_type"
    dot_match = re.search(r"\b([a-zA-Z][a-zA-Z0-9_]+)\.([a-zA-Z][a-zA-Z0-9_]+)\b", raw_text)
    if dot_match:
        t_cand, f_cand = dot_match.group(1), dot_match.group(2)
        if t_cand != datasource_name and f_cand != datasource_name:
            return t_cand, f_cand

    # 2. Check pattern matches with Chinese markers
    table_name = _match_first(
        raw_text,
        [
            r"from\s+([a-zA-Z][a-zA-Z0-9_]+)",
            r"([a-zA-Z][a-zA-Z0-9_]+)\s*表",
            r"表\s*[:：]?\s*([a-zA-Z][a-zA-Z0-9_]+)",
            r"([a-zA-Z][a-zA-Z0-9_]+)\s*的\s*[a-zA-Z][a-zA-Z0-9_]+",
        ],
    )
    field_name = _match_first(
        raw_text,
        [
            r"([a-zA-Z][a-zA-Z0-9_]+)\s*字段",
            r"字段\s*[:：]?\s*([a-zA-Z][a-zA-Z0-9_]+)",
            r"[a-zA-Z][a-zA-Z0-9_]+\s*的\s*([a-zA-Z][a-zA-Z0-9_]+)",
        ],
    )

    # 3. Fallback identifier token analysis
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
