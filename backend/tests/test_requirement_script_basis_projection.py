"""脚本事实投影：长表达式与重复行不能挤爆模型输入预算，但也不许静默丢事实。"""

import hashlib

from app.services.mapping.requirement_input import SCRIPT_TEXT_LIMIT, _project_script_basis


def _rule(rule_id: str, *, statement_id: int = 1, join: str | None = None, source: str = "HYF_LN_DUEBILL_INFO") -> dict:
    return {
        "rule_id": rule_id,
        "script_version_id": 71,
        "statement_id": statement_id,
        "source_line_start": 17,
        "source_line_end": 87,
        "edge_type": "reads_from",
        "transformation_type": None,
        "confidence_level": "high",
        "source": {"schema_name": "SAFE_INSTANCE_GB", "table_name": source, "column_name": None},
        "target": {"schema_name": "SAFE_INSTANCE_GB", "table_name": "T_8_1", "column_name": None},
        "transformation_expression": None,
        "join_condition": join,
        "filter_condition": None,
        "aggregation_rule": None,
        "code_mapping_rule": None,
    }


def _basis() -> dict:
    return {
        "policy_version": "requirement-script-basis-v1",
        "template": {"id": 2, "version_no": 2, "tables": [
            {"sheet_name": "T_8_1-贷款借据", "table_code": "T_8_1", "table_name": "贷款借据", "rows": [
                {"row_number": 5, "field_code": "H010001", "field_name": "借据ID"},
                {"row_number": 6, "field_code": "H010010", "field_name": "借款余额"},
                {"row_number": 55, "field_code": "H010001", "field_name": "借据ID"},
                {"row_number": 7, "field_code": "H010099", "field_name": "不在本次范围"},
            ]},
        ]},
        "rules": [],
    }


def test_template_rows_are_projected_to_bound_columns_and_deduplicated():
    basis = _basis()
    limitations: list[str] = []

    _project_script_basis(basis, {"H010001", "H010010"}, limitations)

    rows = basis["template"]["tables"][0]["rows"]
    assert [row["field_code"] for row in rows] == ["H010001", "H010010"]
    # 一行重复（H010001 出现两次）+ 一行不在绑定范围（H010099）
    assert "省略 2 行" in limitations[0]
    assert "进入模型 2 行" in limitations[0]


def test_long_texts_are_truncated_with_the_original_length_recorded():
    basis = _basis()
    basis["rules"] = [_rule("edge-1", join="A" * (SCRIPT_TEXT_LIMIT + 50))]
    limitations: list[str] = []

    _project_script_basis(basis, {"H010001"}, limitations)

    rule = basis["rules"][0]
    digest = rule["join_condition_ref"]
    text = basis["condition_texts"][digest]
    assert len(text) < SCRIPT_TEXT_LIMIT + 80
    assert text.endswith(f"…（已截断，原文共 {SCRIPT_TEXT_LIMIT + 50} 字符）")
    assert digest == hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    assert basis["projection"]["truncated_field_count"] == 1
    assert any("截断" in item for item in limitations)


def test_identical_conditions_share_one_pool_entry():
    basis = _basis()
    join = "P1.CONTRACT_NO = P2.CONTRACT_NO AND P1.DUEBILL_NO = BL.JJID"
    basis["rules"] = [_rule("edge-1", statement_id=1, join=join), _rule("edge-2", statement_id=2, join=join)]
    _project_script_basis(basis, {"H010001"}, [])

    refs = {rule["join_condition_ref"] for rule in basis["rules"]}
    assert len(refs) == 1
    assert len(basis["condition_texts"]) == 1


def test_duplicate_edges_are_collapsed_and_counted():
    basis = _basis()
    join = "P1.DUEBILL_NO = BL.JJID"
    basis["rules"] = [_rule("edge-1", join=join), _rule("edge-2", join=join)]
    _project_script_basis(basis, {"H010001"}, [])

    assert [rule["rule_id"] for rule in basis["rules"]] == ["edge-1"]
    assert basis["projection"]["duplicate_rule_count"] == 1
    assert basis["projection"]["rule_count"] == 1


def test_projection_keeps_source_column_identity_and_rule_ids():
    basis = _basis()
    basis["rules"] = [_rule("script-edge-9", join="X = Y")]
    _project_script_basis(basis, {"H010001"}, [])

    rule = basis["rules"][0]
    # 血缘事实的定位信息必须保留：候选正文里的 script_rule_ids 将来要对得上。
    assert rule["rule_id"] == "script-edge-9"
    assert rule["source"] == {"schema_name": "SAFE_INSTANCE_GB", "table_name": "HYF_LN_DUEBILL_INFO", "column_name": None}
    assert rule["target"]["table_name"] == "T_8_1"
