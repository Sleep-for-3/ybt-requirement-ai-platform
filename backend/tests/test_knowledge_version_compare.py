"""制度版本对比：固定两个版本，逐条输出差异与双侧出处。"""

from __future__ import annotations

import pytest

from app.models import (
    Institution,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeUnit,
    Project,
    ProjectMembership,
    User,
)
from app.services.auth.dependencies import Principal
from app.services.knowledge_versions import compare_versions


@pytest.fixture()
def scope(db_session):
    institution = Institution(institution_code="cmp-bank", institution_name="对比银行",
                              institution_type="bank", status="active")
    user = User(username="cmp_user", display_name="对比用户", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="对比项目", institution_id=institution.id, project_status="active",
                      bank_name="对比银行", description="版本对比")
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active"))
    db_session.commit()
    return {"db": db_session, "project": project, "user": user,
            "principal": Principal(user.id, user.username, user.display_name)}


def _document(db, project):
    document = KnowledgeDocument(
        project_id=project.id, file_name="合作机构类型_对比样本.xlsx", file_type="xlsx",
        source_type="upload", storage_path="projects/x/real.xlsx", knowledge_type="regulatory_qa",
        knowledge_scope="project", document_status="active", confidentiality_level="internal",
        current_version_no=2, source_category="regulatory_qa", parse_status="indexed",
        created_by="1",
    )
    db.add(document)
    db.flush()
    versions = []
    for number in (1, 2):
        version = KnowledgeDocumentVersion(
            project_id=project.id, document_id=document.id, version_no=number,
            file_name=document.file_name, storage_path=f"projects/x/v{number}.xlsx",
            file_hash=f"hash-{number}", parse_status="indexed", lifecycle_status="active",
            created_by="1",
        )
        db.add(version)
        db.flush()
        versions.append(version)
    document.current_version_id = versions[-1].id
    db.commit()
    return document, versions


def _unit(db, project, document, version, content, cell):
    unit = KnowledgeUnit(
        project_id=project.id, document_id=document.id, document_version_id=version.id,
        knowledge_type="regulatory_qa", knowledge_scope="project", unit_type="clause",
        content=content, normalized_content=content, source_file_name=document.file_name,
        source_sheet_name="转1104问答", source_cell_range=cell, confidentiality_level="internal",
        enabled=True, content_hash=f"unit-{cell}-{version.version_no}", tags_json=[], metadata_json={},
    )
    db.add(unit)
    db.flush()
    return unit


def test_compare_two_versions_reports_each_change_with_both_citations(scope):
    db, project = scope["db"], scope["project"]
    document, versions = _document(db, project)
    old_text = ("数据项编码：F250007；数据项名称：合作方式；反馈意见：建议合作方式的码值修改为："
                "01 营销获客。02 联合贷款。03 支付结算。04 风险分担。00 无合作方。")
    new_text = old_text.replace("00 无合作方。", "11 其他合作方。00 无合作方。")
    old_unit = _unit(db, project, document, versions[0], old_text, "A237:AF237")
    new_unit = _unit(db, project, document, versions[1], new_text, "A237:AF237")
    removed_unit = _unit(db, project, document, versions[0], "旧版独有条款", "A240:AF240")
    added_unit = _unit(db, project, document, versions[1], "新版新增条款", "A241:AF241")
    db.commit()

    result = compare_versions(db, scope["principal"], project.id, document.id,
                              versions[0].id, versions[1].id)
    assert result["counts"] == {"added": 1, "removed": 1, "changed": 1}
    changed = next(item for item in result["items"] if item["change_type"] == "changed")
    assert changed["base"]["document_version_id"] == versions[0].id
    assert changed["target"]["document_version_id"] == versions[1].id
    assert changed["base"]["knowledge_unit_id"] == old_unit.id
    assert changed["target"]["knowledge_unit_id"] == new_unit.id
    assert "11 其他合作方" in "\n".join(changed["diff"])
    assert changed["base"]["locator"]["cell_range"] == "A237:AF237"
    assert changed["target"]["locator"]["cell_range"] == "A237:AF237"
    added = next(item for item in result["items"] if item["change_type"] == "added")
    assert added["target"]["knowledge_unit_id"] == added_unit.id
    assert "base" not in added
    removed = next(item for item in result["items"] if item["change_type"] == "removed")
    assert removed["base"]["knowledge_unit_id"] == removed_unit.id
    assert "target" not in removed


def test_compare_rejects_version_from_another_document(scope):
    db, project = scope["db"], scope["project"]
    document, versions = _document(db, project)
    other_document, other_versions = _document(db, project)
    with pytest.raises(ValueError, match="version_not_found"):
        compare_versions(db, scope["principal"], project.id, document.id,
                         versions[0].id, other_versions[1].id)
