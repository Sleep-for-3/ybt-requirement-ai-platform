"""为 T_5_1（project 9 / requirement 30）写入 3 个**演示场景**的业务口径与技术溯源。

红线约束（本轮任务书 §6）：
- 这些行只是演示数据：正文写在 ``ai_generated_content`` 里，``business_definition`` /
  ``final_content`` / ``processing_logic`` 全部留空，``business_confirm_status`` /
  ``tech_confirm_status`` 保持 ``draft``，``confidence_level=low``。
  渲染器只会在没有人工确认正文时读取 AI 草稿，并强制加"（AI 生成草稿，待…确认）"前缀，
  因此导出文档不会出现"看起来已确认"的口径。
- 内容由现有事实推导：集市映射（mart_to_ybt_mappings 的 mart_table_summary /
  mart_field_summary）与跑批脚本 YBT_T_5_1.sql 的目标列；推导不出来的字段如实写"
  需要人工补充"。
- 可重复执行：按 (project_id, target_field_id, scenario_id) 做 upsert，只覆盖演示行。

用法::

    .venv\\Scripts\\python.exe scripts/seed_t51_scenarios.py --dry-run   # 只看计划
    .venv\\Scripts\\python.exe scripts/seed_t51_scenarios.py --apply     # 写库
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    MartToYbtMapping,
    ProductScenario,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    TargetField,
)

PROJECT_ID = 9
TARGET_TABLE_ID = 59
ACTOR = "demo-seed"
_SUMMARY = re.compile(r"^(?P<name>.*?)[（(](?P<code>[^（()）]*)[）)]\s*$")


@dataclass(frozen=True)
class DemoScenario:
    code: str
    name: str
    source_system: str
    sort_order: int
    description: str
    business_hint: str


SCENARIOS = (
    DemoScenario(
        code="DEBIT_CARD",
        name="借记卡",
        source_system="借记卡系统",
        sort_order=10,
        description="演示场景：借记卡产品口径（数据由集市映射与跑批脚本推导，可被人工覆盖）",
        business_hint="借记卡产品建档",
    ),
    DemoScenario(
        code="CREDIT_CARD",
        name="信用卡",
        source_system="贷记卡系统",
        sort_order=20,
        description="演示场景：信用卡产品口径（数据由集市映射与跑批脚本推导，可被人工覆盖）",
        business_hint="信用卡产品建档",
    ),
    DemoScenario(
        code="AGENT_WEALTH",
        name="代销理财",
        source_system="理财销售系统",
        sort_order=30,
        description="演示场景：代销理财产品口径（数据由集市映射与跑批脚本推导，可被人工覆盖）",
        business_hint="代销理财产品上线",
    ),
)


def _split_summary(value: str | None) -> tuple[str, str]:
    if not value:
        return "", ""
    match = _SUMMARY.match(str(value).strip())
    if not match:
        return str(value).strip(), ""
    return match.group("name").strip(), match.group("code").strip()


def _business_text(scenario: DemoScenario, field: TargetField, mart: MartToYbtMapping | None) -> str:
    if mart is not None:
        table_name, table_code = _split_summary(mart.mart_table_summary)
        field_name, field_code = _split_summary(mart.mart_field_summary)
        if table_name and field_name:
            return (
                f"{scenario.name}场景下，{field.field_name}取自{table_name}"
                f"（{table_code}）的{field_name}（{field_code}），"
                f"用于{scenario.business_hint}的一表通报表送，口径需{scenario.name}业务确认。"
            )
        if mart.business_rule:
            return (
                f"{scenario.name}场景下，{field.field_name}按集市映射规则加工："
                f"{str(mart.business_rule).strip()[:160]}，口径需{scenario.name}业务确认。"
            )
    return (
        f"{scenario.name}场景下，{field.field_name}（{field.field_code}）暂无集市映射依据，"
        f"需要{scenario.name}业务补充取数口径，不得直接引用其他场景口径。"
    )


def _lineage_text(
    scenario: DemoScenario, field: TargetField, mart: MartToYbtMapping | None
) -> tuple[str, str, str, str, str, str]:
    """返回 (表英文名, 表中文名, 字段英文名, 字段中文名, 处理逻辑类型, 处理逻辑)。"""

    if mart is None:
        return (
            "",
            "",
            "",
            "",
            "加工",
            (
                f"跑批脚本 YBT_T_5_1.sql 中 {field.field_code} 没有对应的集市字段，"
                f"由脚本常量或采集参数赋值，需{scenario.source_system}技术确认。"
            ),
        )
    table_name, table_code = _split_summary(mart.mart_table_summary)
    field_name, field_code = _split_summary(mart.mart_field_summary)
    if not (table_code and field_code):
        return (
            table_code,
            table_name,
            field_code,
            field_name,
            "加工",
            (
                f"跑批脚本按表达式计算 {field.field_code}，"
                f"取数来源见脚本血缘证据，需{scenario.source_system}技术确认。"
            ),
        )
    logic = (
        f"跑批脚本直取 {table_code}.{field_code} → {field.field_code}；"
        f"{scenario.source_system}侧口径需技术确认。"
    )
    return (table_code, table_name, field_code, field_name, "直取", logic)


def _resolve_scenario(db, demo: DemoScenario) -> ProductScenario:
    row = db.scalar(
        select(ProductScenario).where(
            ProductScenario.project_id == PROJECT_ID,
            ProductScenario.scenario_code == demo.code,
        )
    )
    if row is None:
        row = ProductScenario(
            project_id=PROJECT_ID,
            scenario_code=demo.code,
            scenario_name=demo.name,
            scenario_type="product",
            description=demo.description,
            enabled=True,
            sort_order=demo.sort_order,
        )
        db.add(row)
        db.flush()
    else:
        row.scenario_name = demo.name
        row.description = demo.description
        row.sort_order = demo.sort_order
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="写库（默认只打印计划）")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划（默认行为，写库需 --apply）")
    args = parser.parse_args()
    apply = args.apply and not args.dry_run

    db = SessionLocal()
    try:
        fields = list(
            db.scalars(
                select(TargetField)
                .where(
                    TargetField.project_id == PROJECT_ID,
                    TargetField.target_table_id == TARGET_TABLE_ID,
                )
                .order_by(TargetField.id)
            )
        )
        if not fields:
            raise SystemExit("T_5_1 没有目标字段，先跑 author-from-scripts")
        field_ids = [field.id for field in fields]
        mappings = list(
            db.scalars(
                select(MartToYbtMapping)
                .where(
                    MartToYbtMapping.project_id == PROJECT_ID,
                    MartToYbtMapping.target_field_id.in_(field_ids),
                )
                .order_by(MartToYbtMapping.id)
            )
        )
        by_field: dict[int, MartToYbtMapping] = {}
        for mapping in mappings:
            by_field.setdefault(mapping.target_field_id, mapping)

        print(f"字段 {len(fields)} 个，集市映射 {len(mappings)} 条，场景 {len(SCENARIOS)} 个")
        created_business = created_lineage = 0
        for demo in SCENARIOS:
            scenario = _resolve_scenario(db, demo)
            for field in fields:
                mart = by_field.get(field.id)
                business_text = _business_text(demo, field, mart)
                business = db.scalar(
                    select(ScenarioBusinessMapping).where(
                        ScenarioBusinessMapping.project_id == PROJECT_ID,
                        ScenarioBusinessMapping.target_field_id == field.id,
                        ScenarioBusinessMapping.scenario_id == scenario.id,
                    )
                )
                if business is None:
                    business = ScenarioBusinessMapping(
                        project_id=PROJECT_ID,
                        target_field_id=field.id,
                        scenario_id=scenario.id,
                        created_by=ACTOR,
                    )
                    db.add(business)
                    created_business += 1
                # 只写 AI 草稿：人工确认字段保持为空，状态保持 draft。
                business.ai_generated_content = business_text
                business.confidence_level = "low"
                business.business_confirm_status = "draft"
                business.remarks = "演示数据（AI 由集市映射与脚本血缘推导），可被人工覆盖"
                db.flush()

                (table_code, table_name, field_code, field_name, logic_type, logic_text) = (
                    _lineage_text(demo, field, mart)
                )
                lineage = db.scalar(
                    select(ScenarioTechnicalLineage).where(
                        ScenarioTechnicalLineage.project_id == PROJECT_ID,
                        ScenarioTechnicalLineage.target_field_id == field.id,
                        ScenarioTechnicalLineage.scenario_id == scenario.id,
                    )
                )
                if lineage is None:
                    lineage = ScenarioTechnicalLineage(
                        project_id=PROJECT_ID,
                        target_field_id=field.id,
                        scenario_id=scenario.id,
                        created_by=ACTOR,
                    )
                    db.add(lineage)
                    created_lineage += 1
                lineage.business_mapping_id = business.id
                lineage.source_system_name = demo.source_system
                lineage.source_table_english_name = table_code or None
                lineage.source_table_chinese_name = table_name or None
                lineage.source_field_english_name = field_code or None
                lineage.source_field_chinese_name = field_name or None
                lineage.processing_logic_type = logic_type
                lineage.ai_generated_content = logic_text
                lineage.confidence_level = "low"
                lineage.tech_confirm_status = "draft"
                lineage.lineage_status = "not_linked"
                lineage.remarks = "演示数据（AI 由集市映射与脚本血缘推导），可被人工覆盖"
                if apply:
                    db.flush()
            print(
                f"  场景 {demo.name}({demo.code}) 覆盖字段 {len(fields)} 个，"
                f"来源系统 {demo.source_system}"
            )

        if apply:
            db.commit()
            print(f"已写入：新增业务口径 {created_business} 条，新增技术溯源 {created_lineage} 条")
        else:
            db.rollback()
            print(
                f"[dry-run] 将新增业务口径 {created_business} 条、技术溯源 {created_lineage} 条，未写库"
            )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
