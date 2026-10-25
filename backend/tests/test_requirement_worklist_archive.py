"""派工清单"按监管表分装"导出的回归：分组、计数、字节可复现、只读。"""

from __future__ import annotations

import io
import zipfile

from app.services.requirement_worklist_archive import (
    ARCHIVE_VERSION,
    MANIFEST_NAME,
    build_worklist_archive,
    read_manifest,
)

# 夹具来自演示链路用例；只 import snapshot_api 会报 "fixture 'snapshot_db' not found"。
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401

PAYLOAD = {
    "worklist_version": "requirement-field-worklist-v1",
    "project_id": 9,
    "reason_labels": {
        "business_definition_missing": "缺少业务口径正文",
        "mart_mapping_missing": "没有固定集市映射",
        "open_gap": "仍有未关闭的字段级缺口",
        "pending_candidate": "有已生成但未采纳的候选",
    },
    "field_count": 4,
    "returned": 4,
    "items": [
        {
            "requirement_id": 11,
            "requirement_name": "T_1_2 监管字段需求",
            "target_table_code": "T_1_2",
            "target_table_name": "机构关系",
            "field_id": 487,
            "field_code": "A020001",
            "field_name": "机构ID",
            "reasons": ["business_definition_missing", "open_gap"],
            "reason_labels": ["缺少业务口径正文", "仍有未关闭的字段级缺口"],
            "open_gap_count": 5,
            "pending_candidate_count": 0,
        },
        {
            "requirement_id": 11,
            "requirement_name": "T_1_2 监管字段需求",
            "target_table_code": "T_1_2",
            "target_table_name": "机构关系",
            "field_id": 488,
            "field_code": "A020002",
            "field_name": "上级机构ID",
            "reasons": ["mart_mapping_missing"],
            "reason_labels": ["没有固定集市映射"],
            "open_gap_count": 0,
            "pending_candidate_count": 0,
        },
        {
            "requirement_id": 10,
            "requirement_name": "T_8_1 监管字段需求",
            "target_table_code": "T_8_1",
            "target_table_name": "贷款借据",
            "field_id": 2315,
            "field_code": "H010001",
            "field_name": "借据ID",
            "reasons": ["pending_candidate"],
            "reason_labels": ["有已生成但未采纳的候选"],
            "open_gap_count": 0,
            "pending_candidate_count": 2,
        },
        {
            "requirement_id": 10,
            "requirement_name": "T_8_1 监管字段需求",
            "target_table_code": None,
            "target_table_name": None,
            "field_id": 2320,
            "field_code": "=CMD|' /C calc'!A1",
            "field_name": "可疑字段",
            "reasons": ["open_gap"],
            "reason_labels": ["仍有未关闭的字段级缺口"],
            "open_gap_count": 1,
            "pending_candidate_count": 0,
        },
    ],
}


def test_archive_groups_items_by_table_with_manifest() -> None:
    archive, manifest = build_worklist_archive(PAYLOAD)

    assert manifest["archive_version"] == ARCHIVE_VERSION
    assert manifest["worklist_version"] == "requirement-field-worklist-v1"
    assert manifest["project_id"] == 9
    # 没有监管表编号的行不能丢：归到"未登记监管表"，否则经办人看不出这几行属于谁。
    assert manifest["table_count"] == 3
    assert manifest["item_count"] == 4
    assert manifest["reason_totals"]["open_gap"] == 2
    by_code = {table["target_table_code"]: table for table in manifest["tables"]}
    assert by_code["T_1_2"]["item_count"] == 2
    assert by_code["T_1_2"]["reason_totals"]["business_definition_missing"] == 1
    assert by_code["T_8_1"]["item_count"] == 1
    assert by_code["未登记监管表"]["item_count"] == 1
    # 清单里不写生成时间：写了的话同一份清单两次导出字节就不同。
    assert "generated_at" not in manifest

    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        names = set(zipped.namelist())
        assert MANIFEST_NAME in names
        assert len(names) == 4  # 3 张表 + manifest
        csv_text = zipped.read(by_code["T_1_2"]["file_name"]).decode("utf-8")
    assert csv_text.startswith("\ufeff"), "CSV 必须带 BOM，否则 Excel 显示乱码"
    assert "\r\n" in csv_text
    assert '"T_1_2","机构关系","T_1_2 监管字段需求","A020001","机构ID"' in csv_text
    assert '"缺少业务口径正文；仍有未关闭的字段级缺口"' in csv_text


def test_archive_is_byte_reproducible() -> None:
    first, _ = build_worklist_archive(PAYLOAD)
    second, _ = build_worklist_archive(PAYLOAD)
    assert first == second, "同一份清单两次导出必须字节相同（zip 条目时间固定、清单不写调用态字段）"
    assert read_manifest(first) == read_manifest(second)


def test_archive_escapes_formula_cells() -> None:
    archive, manifest = build_worklist_archive(PAYLOAD)
    code = "未登记监管表"
    name = next(t["file_name"] for t in manifest["tables"] if t["target_table_code"] == code)
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        csv_text = zipped.read(name).decode("utf-8")
    assert "\"'=CMD|' /C calc'!A1\"" in csv_text, "= 开头的字段编码必须前置单引号，避免被 Excel 当公式执行"


def test_archive_rejects_empty_payload() -> None:
    from app.services.requirement_worklist_archive import WorklistArchiveError

    try:
        build_worklist_archive({"items": [], "reason_labels": {}})
    except WorklistArchiveError as exc:
        assert exc.code == "worklist_empty"
    else:  # pragma: no cover - 走不到这里说明校验失效
        raise AssertionError("空清单必须报 worklist_empty，而不是导出空 zip")


def test_worklist_archive_endpoint_is_read_only(snapshot_api) -> None:
    client, db, project, *_ = snapshot_api

    response = client.get(f"/projects/{project.id}/requirements-worklist/archive")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["x-requirement-worklist-tables"].isdigit()
    assert len(response.headers["x-requirement-worklist-file-sha256"]) == 64
    assert "filename*=UTF-8''" in response.headers["content-disposition"]

    manifest = read_manifest(response.content)
    assert manifest["archive_version"] == ARCHIVE_VERSION
    assert manifest["project_id"] == project.id

    # 只读：不产生快照、不产生产物。
    from app.models import RequirementDelivery, RequirementRenderArtifact

    assert db.query(RequirementDelivery).filter_by(project_id=project.id).count() == 0
    assert db.query(RequirementRenderArtifact).filter_by(project_id=project.id).count() == 0
