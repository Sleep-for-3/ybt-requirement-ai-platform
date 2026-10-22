"""Synthetic GBase/Hive SQL corpus used by the dialect matrix checks.

The corpus is intentionally synthetic: it mirrors production shapes (loan
slip -> contract -> product -> product term joins, partition increments,
window functions, template variables) without containing bank data.  Both
``tests/test_vnext2_sql_dialect_matrix.py`` and
``scripts/vnext2_sql_dialect_matrix.py`` consume it so the recorded
evidence and the regression suite never drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParseCase:
    name: str
    sql: str
    dialect: str
    expect_status: str
    expect_target: str | None = None
    expect_min_edges: int = 1
    expect_warning: bool = False
    variables: dict[str, str] | None = None
    note: str = ""


@dataclass(frozen=True)
class ChangeCase:
    name: str
    old_sql: str
    new_sql: str
    dialect: str = "gbase"
    expect_category: str | None = None
    expect_semantic_change: bool = True
    expect_caliber: bool | None = None
    note: str = ""
    extra_expect: dict[str, object] = field(default_factory=dict)


_LOAN_JOIN = """
insert into MART.DW_LOAN_SNAPSHOT (iou_no, product_id, term_no, loan_amt, report_dt)
select l.iou_no,
       p.product_id,
       t.term_no,
       l.loan_amt,
       '{bizdate}' as report_dt
  from SRC.LOAN_IOU l
  join SRC.CONTRACT c on c.contract_no = l.contract_no
  join SRC.PRODUCT p on p.product_id = l.product_id
  join SRC.PRODUCT_TERM t on t.product_id = p.product_id and t.term_no = l.term_no
 where l.dt = '{bizdate}'
   and l.loan_status = 'NORMAL'
"""


_LOAN_JOIN_TWO_STEP = """
drop table if exists TMP.LOAN_BASE;
create table TMP.LOAN_BASE as
select l.iou_no, l.product_id, l.term_no, l.loan_amt, l.contract_no
  from SRC.LOAN_IOU l
 where l.dt = '{bizdate}';

insert into MART.DW_LOAN_SNAPSHOT (iou_no, product_id, term_no, loan_amt)
select b.iou_no, p.product_id, t.term_no, b.loan_amt
  from TMP.LOAN_BASE b
  join SRC.PRODUCT p on p.product_id = b.product_id
  join SRC.PRODUCT_TERM t on t.product_id = p.product_id and t.term_no = b.term_no;
"""


_CTE_HIVE = """
with base as (
    select l.iou_no, l.product_id, l.term_no, l.loan_amt
      from src.loan_iou l
     where l.dt = '#{bizdate}'
),
product_term as (
    select p.product_id, t.term_no, p.product_name
      from src.product p
      join src.product_term t on t.product_id = p.product_id
)
insert overwrite table mart.dw_loan_snapshot partition (dt = '#{bizdate}')
select b.iou_no, pt.product_id, pt.term_no, b.loan_amt
  from base b
  join product_term pt on pt.product_id = b.product_id and pt.term_no = b.term_no
"""


_UNION_ALL_HIVE = """
insert overwrite table mart.dw_loan_snapshot partition (dt = '#{bizdate}')
select l.iou_no, l.loan_amt, 'IOU' as source_type
  from src.loan_iou l
 where l.dt = '#{bizdate}'
union all
select i.iou_no, i.loan_amt, 'IOU_ARCHIVE' as source_type
  from src.loan_iou_archive i
 where i.dt = '#{bizdate}'
"""


_GROUP_BY_CASE_WHEN = """
insert into mart.dw_loan_balance (product_id, term_no, loan_cnt, balance_amt)
select l.product_id,
       l.term_no,
       count(distinct l.iou_no) as loan_cnt,
       sum(case when l.loan_status = 'NORMAL' then l.loan_amt else 0 end) as balance_amt
  from src.loan_iou l
 where l.dt = '${bizdate}'
 group by l.product_id, l.term_no
"""


_WINDOW_ROW_NUMBER = """
insert overwrite table mart.dw_loan_latest partition (dt = '#{bizdate}')
select iou_no, product_id, term_no, loan_amt
  from (
      select l.iou_no, l.product_id, l.term_no, l.loan_amt,
             row_number() over (partition by l.iou_no order by l.updated_at desc) as rn
        from src.loan_iou l
       where l.dt = '#{bizdate}'
  ) ranked
 where rn = 1
"""


_FULL_JOIN_HIVE = """
insert overwrite table mart.dw_product_diff partition (dt = '#{bizdate}')
select coalesce(p.product_id, t.product_id) as product_id,
       p.product_name,
       t.term_no
  from src.product p
  full outer join src.product_term t on t.product_id = p.product_id
"""


_SUBQUERY_GBASE = """
insert into mart.dw_loan_snapshot (iou_no, product_id, term_no, loan_amt)
select x.iou_no, x.product_id, x.term_no, x.loan_amt
  from (select l.iou_no, l.product_id, l.term_no, sum(l.loan_amt) as loan_amt
          from src.loan_iou l
         where l.dt between '${start_dt}' and '${end_dt}'
         group by l.iou_no, l.product_id, l.term_no) x
 where x.loan_amt > 0
"""


_VARIABLE_RESOLVED_GBASE = """
insert into mart.dw_loan_snapshot (iou_no, loan_amt)
select l.iou_no, l.loan_amt
  from src.loan_iou l
 where l.dt = '${bizdate}'
"""


_NULL_CONCAT_GBASE = """
insert into mart.dw_loan_snapshot (iou_no, key_desc)
select l.iou_no,
       concat(ifnull(l.product_id, ''), '|', ifnull(l.term_no, '')) as key_desc
  from src.loan_iou l
 where l.dt = '${bizdate}'
"""


_HIVE_FUNCTIONS = """
insert overwrite table mart.dw_loan_snapshot partition (dt = '#{bizdate}')
select l.iou_no,
       concat_ws('|', nvl(l.product_id, 'NA'), nvl(l.term_no, 'NA')) as key_desc,
       from_unixtime(unix_timestamp(l.updated_at)) as updated_ts,
       get_json_object(l.ext_info, '$.channel') as channel
  from src.loan_iou l
 where l.dt = '#{bizdate}'
"""


_ALIAS_RENAME = """
insert into mart.dw_loan_snapshot (iou_no, loan_amt)
select i.iou_no as iou_no, i.loan_amt as loan_amt
  from src.loan_iou i
 where i.dt = '${bizdate}'
"""


_UNPARSABLE = """
insert into mart.dw_loan_snapshot (iou_no)
select amt from (
"""


_PARTIAL_MULTI_STATEMENT = """
insert into mart.dw_loan_snapshot (iou_no, loan_amt)
select l.iou_no, l.loan_amt
  from src.loan_iou l
 where l.dt = '${bizdate}';

insert into mart.dw_loan_snapshot (iou_no)
select amt from (
"""


PARSE_CASES: tuple[ParseCase, ...] = (
    ParseCase("multi_layer_insert_join", _LOAN_JOIN, "gbase", "parsed", "DW_LOAN_SNAPSHOT", 4,
              note="借据-合同-产品-产品期限四表关联；库表限定名"),
    ParseCase("temp_table_two_step", _LOAN_JOIN_TWO_STEP, "gbase", "parsed", "DW_LOAN_SNAPSHOT", 3,
              note="DROP/CREATE TABLE AS + INSERT 两段式"),
    ParseCase("cte_hive_partition", _CTE_HIVE, "hive", "parsed", "dw_loan_snapshot", 3,
              note="CTE + INSERT OVERWRITE 分区"),
    ParseCase("union_all_hive", _UNION_ALL_HIVE, "hive", "parsed", "dw_loan_snapshot", 2,
              note="UNION ALL 两支"),
    ParseCase("group_by_case_when", _GROUP_BY_CASE_WHEN, "gbase", "parsed", "dw_loan_balance", 2,
              note="GROUP BY + CASE WHEN 码值折算"),
    ParseCase("window_row_number", _WINDOW_ROW_NUMBER, "hive", "parsed", "dw_loan_latest", 2,
              note="ROW_NUMBER 去重取最新"),
    ParseCase("full_outer_join", _FULL_JOIN_HIVE, "hive", "parsed", "dw_product_diff", 2,
              note="FULL OUTER JOIN + COALESCE"),
    ParseCase("subquery_date_range", _SUBQUERY_GBASE, "gbase", "parsed", "dw_loan_snapshot", 2,
              variables={"start_dt": "20260901", "end_dt": "20260930"},
              note="子查询 + 日期区间变量"),
    ParseCase("template_variable_resolved", _VARIABLE_RESOLVED_GBASE, "gbase", "parsed", "dw_loan_snapshot", 1,
              variables={"bizdate": "20261021"}, note="变量替换 ${bizdate}"),
    ParseCase("template_variable_unresolved", _VARIABLE_RESOLVED_GBASE, "gbase", "parsed", "dw_loan_snapshot", 1,
              expect_warning=True, note="未配置变量保留证据并告警，不静默猜测"),
    ParseCase("null_concat_gbase", _NULL_CONCAT_GBASE, "gbase", "parsed", "dw_loan_snapshot", 1,
              note="NULL 参与 CONCAT + IFNULL 兜底"),
    ParseCase("hive_functions", _HIVE_FUNCTIONS, "hive", "parsed", "dw_loan_snapshot", 1,
              note="Hive 特有函数 concat_ws/nvl/from_unixtime/get_json_object"),
    ParseCase("column_alias_rename", _ALIAS_RENAME, "gbase", "parsed", "dw_loan_snapshot", 1,
              note="来源列与目标列同名、别名重命名"),
    ParseCase("unparsable_single", _UNPARSABLE, "gbase", "failed", None, 0,
              note="无法解析时不伪造血缘"),
    ParseCase("partially_parsed_script", _PARTIAL_MULTI_STATEMENT, "gbase", "partially_parsed", "dw_loan_snapshot", 1,
              note="首段正常、次段不可解析"),
)


_JOIN_SQL = """
insert into mart.dw_loan_snapshot (iou_no, loan_amt)
select l.iou_no, l.loan_amt
  from src.loan_iou l
  {join} src.product p on p.product_id = l.product_id
 where l.dt = '${{bizdate}}'
"""

_CHANGE_CASES: tuple[ChangeCase, ...] = (
    ChangeCase(
        "join_type_inner_to_left",
        _JOIN_SQL.format(join="inner join"),
        _JOIN_SQL.format(join="left join"),
        expect_category="join_type_changed",
        expect_caliber=True,
        note="JOIN 类型变化改变最终统计范围（正例）",
    ),
    ChangeCase(
        "group_by_key_added",
        """
        insert into mart.dw_loan_balance (product_id, loan_cnt)
        select l.product_id, count(distinct l.iou_no)
          from src.loan_iou l
         where l.dt = '${bizdate}'
         group by l.product_id
        """,
        """
        insert into mart.dw_loan_balance (product_id, loan_cnt)
        select l.product_id, count(distinct l.iou_no)
          from src.loan_iou l
         where l.dt = '${bizdate}'
         group by l.product_id, l.term_no
        """,
        expect_category="group_by_changed",
        expect_caliber=True,
        note="GROUP BY 粒度变化（正例）",
    ),
    ChangeCase(
        "row_limit_changed",
        """
        insert into mart.dw_loan_topn (iou_no, loan_amt)
        select l.iou_no, l.loan_amt
          from src.loan_iou l
         where l.dt = '${bizdate}'
         order by l.loan_amt desc
         limit 10
        """,
        """
        insert into mart.dw_loan_topn (iou_no, loan_amt)
        select l.iou_no, l.loan_amt
          from src.loan_iou l
         where l.dt = '${bizdate}'
         order by l.loan_amt desc
         limit 100
        """,
        expect_category="top_limit_changed",
        expect_caliber=True,
        note="TOP/LIMIT 改变样本范围（正例）",
    ),
    ChangeCase(
        "cte_inner_filter_changed",
        """
        with base as (
            select l.iou_no, l.loan_amt from src.loan_iou l where l.dt = '${bizdate}' and l.status = 'NORMAL'
        )
        insert into mart.dw_loan_snapshot (iou_no, loan_amt)
        select b.iou_no, b.loan_amt from base b
        """,
        """
        with base as (
            select l.iou_no, l.loan_amt from src.loan_iou l where l.dt = '${bizdate}' and l.status in ('NORMAL', 'OVERDUE')
        )
        insert into mart.dw_loan_snapshot (iou_no, loan_amt)
        select b.iou_no, b.loan_amt from base b
        """,
        expect_category="cte_changed",
        expect_caliber=True,
        note="CTE 内部过滤变化（正例）",
    ),
    ChangeCase(
        "formatting_and_comments_only",
        """
        insert into mart.dw_loan_snapshot (iou_no, loan_amt)
        select l.iou_no, l.loan_amt
          from src.loan_iou l
         where l.dt = '${bizdate}' and l.status = 'NORMAL'
        """,
        """
        -- 仅格式与注释变化
        insert into mart.dw_loan_snapshot (iou_no, loan_amt)
        select
            l.iou_no,
            l.loan_amt
        from src.loan_iou l
        where l.dt = '${bizdate}'
          AND l.status = 'NORMAL'
        """,
        expect_semantic_change=False,
        expect_caliber=False,
        note="仅格式与注释（反例：不得误报口径变化）",
    ),
    ChangeCase(
        "alias_rename_only",
        """
        with base as (
            select l.iou_no, l.loan_amt from src.loan_iou l where l.dt = '${bizdate}'
        )
        insert into mart.dw_loan_snapshot (iou_no, loan_amt)
        select b.iou_no, b.loan_amt from base b
        """,
        """
        with loan_base as (
            select l.iou_no, l.loan_amt from src.loan_iou l where l.dt = '${bizdate}'
        )
        insert into mart.dw_loan_snapshot (iou_no, loan_amt)
        select x.iou_no, x.loan_amt from loan_base x
        """,
        expect_semantic_change=False,
        expect_caliber=False,
        note="等价重写：CTE 与别名重命名（反例）",
    ),
    ChangeCase(
        "order_by_only",
        """
        insert into mart.dw_loan_snapshot (iou_no, loan_amt)
        select l.iou_no, l.loan_amt from src.loan_iou l where l.dt = '${bizdate}'
        """,
        """
        insert into mart.dw_loan_snapshot (iou_no, loan_amt)
        select l.iou_no, l.loan_amt from src.loan_iou l where l.dt = '${bizdate}' order by l.iou_no
        """,
        expect_category=None,
        expect_semantic_change=True,
        expect_caliber=False,
        note="单独 ORDER BY：变化存在但无法归因，且不声称影响口径（显式 limitation）",
    ),
    ChangeCase(
        "function_variant_same_semantics",
        """
        insert into mart.dw_loan_snapshot (iou_no, key_desc)
        select l.iou_no, ifnull(l.product_id, 'NA') from src.loan_iou l where l.dt = '${bizdate}'
        """,
        """
        insert into mart.dw_loan_snapshot (iou_no, key_desc)
        select l.iou_no, nvl(l.product_id, 'NA') from src.loan_iou l where l.dt = '${bizdate}'
        """,
        dialect="hive",
        expect_semantic_change=False,
        expect_caliber=False,
        note="方言等价函数替换（ifnull -> nvl）：不得误报为口径变化",
    ),
)


CHANGE_CASES = _CHANGE_CASES
