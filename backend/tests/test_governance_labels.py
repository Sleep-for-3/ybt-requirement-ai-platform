"""防回归闸门：中文标签映射表绝不允许把英文标识符直出给用户。

这些映射是通知正文、审计正文等「用户可见自由文本」的唯一口径来源。
历史上 `step_key` / `severity` / `status` / `project_role` 曾被直接插值进人话
（如「已分派 business_review 任务」「脚本 #1 产生 high 级影响」），
用户看到的是机器标识符。本测试钉死两件事：

1. 每个映射函数遇到未登记的枚举值时，回落成通用中文，不得回落原值；
2. 返回值里不含 ASCII 字母 —— 这是「没有英文标识符泄漏」的机器可判定形式。

如果将来有人把 fallback 改成 `return value`，或者新增映射时忘了写中文，
第 2 条断言会立刻失败。
"""
from __future__ import annotations

import re

import pytest

from app.services.governance.labels import (
    agent_step_status_label,
    evidence_type_label,
    knowledge_type_label,
    lineage_node_type_label,
    mapping_status_label,
    parse_status_label,
    project_role_label,
    replan_reason_label,
    semantic_status_label,
    severity_label,
    uat_run_status_label,
    workflow_step_label,
)

ASCII_LETTER = re.compile(r"[A-Za-z]")

# (函数, 便于报错的名称)
MAPPERS = [
    (workflow_step_label, "workflow_step_label"),
    (severity_label, "severity_label"),
    (uat_run_status_label, "uat_run_status_label"),
    (project_role_label, "project_role_label"),
    (parse_status_label, "parse_status_label"),
    (mapping_status_label, "mapping_status_label"),
    (semantic_status_label, "semantic_status_label"),
    (knowledge_type_label, "knowledge_type_label"),
    (lineage_node_type_label, "lineage_node_type_label"),
    (evidence_type_label, "evidence_type_label"),
    (agent_step_status_label, "agent_step_status_label"),
    (replan_reason_label, "replan_reason_label"),
]

# 典型但不限于这些的机器标识符；未知值必须被兜底吃掉
UNKNOWN_VALUES = [
    "some_unknown_key",
    "NOT_A_REAL_STATUS",
    "future_enum_value",
    "",
    "high_risk_custom",
    "zzz",
]


@pytest.mark.parametrize("mapper,name", MAPPERS, ids=[name for _, name in MAPPERS])
@pytest.mark.parametrize("unknown", UNKNOWN_VALUES)
def test_unknown_value_falls_back_to_chinese_without_ascii_letters(mapper, name, unknown):
    label = mapper(unknown)

    assert label, f"{name}({unknown!r}) 返回了空字符串"
    assert not ASCII_LETTER.search(label), (
        f"{name}({unknown!r}) 回落成 {label!r}，把英文标识符泄漏给了用户；"
        f"fallback 必须是通用中文（如「该环节」「未知」「该角色」），不能回落原值"
    )


@pytest.mark.parametrize("mapper,name", MAPPERS, ids=[name for _, name in MAPPERS])
def test_known_values_are_chinese(mapper, name):
    """已知值走查表分支，同样不该出现 ASCII 字母。"""
    known = {
        "workflow_step_label": ["business_review", "final_review", "uat_signoff"],
        "severity_label": ["critical", "high", "medium", "low"],
        "uat_run_status_label": ["pending", "running", "passed", "failed"],
        "project_role_label": ["project_manager", "business_analyst"],
        "parse_status_label": ["pending", "parsed", "failed", "partially_parsed", "parsing"],
        "mapping_status_label": ["draft", "reviewed", "approved", "confirmed"],
        "semantic_status_label": ["draft", "ai_suggested", "confirmed", "deprecated"],
        "knowledge_type_label": ["regulatory_policy", "data_dictionary", "meeting_note"],
        "lineage_node_type_label": ["table", "column", "target_field"],
        "evidence_type_label": ["source_field", "catalog_column", "script_file_version"],
        "agent_step_status_label": ["pending", "running", "completed", "waiting_human"],
        "replan_reason_label": ["tool_failed", "permission_denied", "http_404"],
    }[name]
    for value in known:
        label = mapper(value)
        assert label, f"{name}({value!r}) 返回了空字符串"
        assert not ASCII_LETTER.search(label), f"{name}({value!r}) 返回英文 {label!r}"


def test_fallback_is_not_the_input_value():
    """显式钉死「不能回落原值」——即使原值本身是中文也不行被误判为映射命中。"""
    for mapper, name in MAPPERS:
        unknown = "definitely_not_registered"
        assert mapper(unknown) != unknown, f"{name} 把未登记的值原样返回了"


def test_http_status_reason_keeps_only_the_number():
    """`http_<状态码>` 这类拼接码也要落成中文，不能把 `http_404` 直出。"""

    assert not ASCII_LETTER.search(replan_reason_label("http_503"))
    # 未登记的拼接码也不能直出 http_599，只把状态码保留成数字
    unknown = replan_reason_label("http_599")
    assert not ASCII_LETTER.search(unknown), f"重规划原因回落成 {unknown!r}"
    assert "599" in unknown


def test_east_mapping_keeps_the_product_name():
    """EAST 是报送产品名（银保监 EAST），是唯一允许保留大写字母的标签。"""

    assert knowledge_type_label("east_mapping") == "EAST 映射"
