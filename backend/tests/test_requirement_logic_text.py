from app.services.requirement_logic_text import (
    build_table_scope,
    classify_field_logic,
    parse_script_structure,
)

SQL = """INSERT INTO T_6_4
SELECT P1.CONTRACT_NO AS F040002 /* 协议ID */
     , COALESCE(P1.DUEBILL_NO, '') AS F040003 /* 借据ID */
     , COALESCE(CONCAT(SUBSTR(JG.C_FINA_LICEN_NO, 1, 11), JG.BRANCH_NO), BLJG.JGID, P1.BRANCH_NO, '') AS F040001 /* 机构ID */
     , P5.YBT_CODE AS F040005 /* 业务模式 */
     , CASE WHEN NVL(P2.AUTHOR_EFF_DATE, '') = '' THEN '' ELSE TO_CHAR(TO_DATE(P2.AUTHOR_EFF_DATE, 'YYYYMMDD'), 'YYYY-MM-DD') END AS F040010 /* 授权生效日期 */
     , 'SAFE_DATA_DATE' AS F040016 /* 采集日期 */
  FROM HYF_LN_BD_ONLINE_INFO_EXT_YBT AS P1 /* 信贷借据互联网贷款补充信息表 */
  LEFT JOIN HYF_LN_CONTRACT_INFO_EXT_YBT AS P2 /* 信贷合同信息表 */ ON P1.CONTRACT_NO = P2.CONTRACT_NO
  LEFT JOIN HYF_BK_INST_INFO_EXT_YBT AS JG /* 机构信息表 */ ON JG.BRANCH_NO = P1.BRANCH_NO
  LEFT JOIN YBT_CODE_MAPPING AS P5 /* 码值映射表 */ ON P5.HFK_CODE = P1.MANAGE_TYP
 WHERE P1.DATA_DT = 'SAFE_DATA_DATE' /* 数据日期 */
   AND P1.DATA_SOURCE <> 'ICB' /* 排除借呗 */
   AND P1.DUEBILL_NO NOT IN (SELECT S.DUEBILL_NO FROM HYF_LN_DUEBILL_INFO_EXT_YBT S WHERE S.LOAN_BAL = 0) /* 剔除上年末零余额借据 */"""

NAMES = {
    "HYF_LN_BD_ONLINE_INFO_EXT_YBT": {"cn": "信贷借据互联网贷款补充信息表",
                                     "columns": {"CONTRACT_NO": "信贷合同号", "DUEBILL_NO": "信贷借据号",
                                                 "DATA_DT": "数据日期", "DATA_SOURCE": "数据来源"}},
    "HYF_LN_CONTRACT_INFO_EXT_YBT": {"cn": "信贷合同信息表", "columns": {"AUTHOR_EFF_DATE": "授权生效日期"}},
    "HYF_BK_INST_INFO_EXT_YBT": {"cn": "机构信息表", "columns": {"C_FINA_LICEN_NO": "金融许可证号"}},
    "YBT_CODE_MAPPING": {"cn": "码值映射表", "columns": {"YBT_CODE": "映射代码"}},
}


def _rule(column, expression, logic_type="pass_through"):
    return {"source": {"table_name": "HYF_LN_BD_ONLINE_INFO_EXT_YBT", "column_name": column},
            "target": {"column_name": "F040002"}, "transformation_expression": expression,
            "transformation_type": logic_type}


def test_direct_field_has_short_text_without_sql():
    structure = parse_script_structure(SQL)
    result = classify_field_logic(_rule("CONTRACT_NO", "P1.CONTRACT_NO AS F040002"),
                                  {"field_name": "协议ID", "field_code": "F040002"}, structure, NAMES)
    assert result["logic_type"] == "直取"
    assert result["text"] == "取信贷借据互联网贷款补充信息表的信贷合同号（CONTRACT_NO），原值写入协议ID（F040002）。"
    assert "P1." not in result["text"] and "AS F" not in result["text"]


def test_null_handling_and_constant():
    structure = parse_script_structure(SQL)
    null_result = classify_field_logic(_rule("DUEBILL_NO", "COALESCE(P1.DUEBILL_NO, '')", "null_handling"),
                                       {"field_name": "借据ID", "field_code": "F040003"}, structure, NAMES)
    assert "空值转为空字符串" in null_result["text"]
    constant = classify_field_logic(_rule("", "'SAFE_DATA_DATE'", "constant"),
                                    {"field_name": "采集日期", "field_code": "F040016"}, structure, NAMES)
    assert constant["logic_type"] == "常量"
    assert "SAFE_DATA_DATE" in constant["text"]
    assert "上游表" in constant["text"]


def test_code_mapping_and_case_date():
    structure = parse_script_structure(SQL)
    mapping = classify_field_logic(_rule("YBT_CODE", "P5.YBT_CODE AS F040005"),
                                   {"field_name": "业务模式", "field_code": "F040005"}, structure, NAMES)
    assert mapping["logic_type"] == "码值映射"
    assert "码值映射表" in mapping["text"] and "映射代码" in mapping["text"]
    case = classify_field_logic(_rule(
        "AUTHOR_EFF_DATE",
        "CASE WHEN NVL(P2.AUTHOR_EFF_DATE, '') = '' THEN '' ELSE TO_CHAR(TO_DATE(P2.AUTHOR_EFF_DATE, 'YYYYMMDD'), 'YYYY-MM-DD') END AS F040010",
    ), {"field_name": "授权生效日期", "field_code": "F040010"}, structure, NAMES)
    assert case["logic_type"] == "条件分支"
    assert "YYYY-MM-DD" in case["text"]


def test_concat_states_precise_pieces_and_fallbacks():
    structure = parse_script_structure(SQL)
    result = classify_field_logic(
        _rule("C_FINA_LICEN_NO",
              "COALESCE(CONCAT(SUBSTR(JG.C_FINA_LICEN_NO, 1, 11), JG.BRANCH_NO), "
              "BLJG.JGID, P1.BRANCH_NO, '') AS F040001"),
        {"field_name": "机构ID", "field_code": "F040001"}, structure, NAMES,
    )
    assert "前 11 位" in result["text"]
    assert "拼接" in result["text"]
    assert "按脚本规则处理" not in result["text"]


def test_table_scope_separates_global_filters_and_joins():
    scope = build_table_scope(parse_script_structure(SQL), NAMES)
    text = "\n".join(item["text"] for item in scope)
    assert "SAFE_DATA_DATE" in text
    assert "排除借呗" in text
    assert "上年末零余额借据" in text
    assert "按合同号关联信贷合同信息表" in text
    assert "按业务模式关联码值映射表" in text
