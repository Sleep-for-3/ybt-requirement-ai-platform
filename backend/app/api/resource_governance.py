from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import (BusinessSystem, CatalogTable, DataSource, HistoricalCaliberImport,
    KnowledgeDocument, KnowledgeDocumentVersion, MartTable, ProductScenario, TargetField,
    TemplateDocument, TemplateVersion, TraceabilityTemplateDocument)
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService


router = APIRouter(prefix="/projects", tags=["resource governance"])


@router.get("/{project_id}/resources/governance-summary")
def governance_summary(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    PermissionService(db, principal).require_project_permission(project_id, "knowledge.search")
    knowledge_count = _count(db, KnowledgeDocument, project_id)
    knowledge_active = _count(db, KnowledgeDocument, project_id, KnowledgeDocument.current_version_id.is_not(None))
    knowledge_pending = _count(db, KnowledgeDocumentVersion, project_id,
        KnowledgeDocumentVersion.lifecycle_status.in_(("draft", "pending_review", "approved")))
    knowledge_failed = _count(db, KnowledgeDocumentVersion, project_id, KnowledgeDocumentVersion.parse_status == "failed")
    template_count = _count(db, TemplateDocument, project_id)
    template_active = _count(db, TemplateVersion, project_id, TemplateVersion.status == "active")
    template_pending = _count(db, TemplateVersion, project_id, TemplateVersion.status.in_(("draft", "pending_review", "approved")))
    template_failed = _count(db, TemplateVersion, project_id, TemplateVersion.parse_status == "failed")
    resources = [
        _entry("knowledge", "知识文档", "/knowledge/documents", "监管制度、答疑和行内知识的受控证据库", knowledge_count,
            f"{knowledge_active} 份当前生效", KnowledgeDocument, db, project_id,
            [{"label":"待审核", "count":knowledge_pending}, {"label":"解析失败", "count":knowledge_failed}]),
        _entry("templates", "一表通监管模板", "/templates", "监管目标表和字段的版本化模板", template_count,
            f"{template_active} 个生效版本", TemplateDocument, db, project_id,
            [{"label":"待审核/激活", "count":template_pending}, {"label":"解析失败", "count":template_failed}]),
        _entry("fields", "目标字段与场景", "/fields", "目标字段及适用业务场景", _count(db, TargetField, project_id),
            f"覆盖 {_count(db, ProductScenario, project_id)} 个场景", TargetField, db, project_id, []),
        _entry("historical", "历史口径", "/historical-calibers", "历史业务与技术口径，用于追溯而非默认问答",
            _count(db, HistoricalCaliberImport, project_id), "历史资料，不默认进入当前问答", HistoricalCaliberImport, db, project_id, []),
        _entry("traceability", "历史口径模板", "/traceability-templates", "历史溯源模板及解析结果",
            _count(db, TraceabilityTemplateDocument, project_id), "按解析状态管理", TraceabilityTemplateDocument, db, project_id, [], "technical"),
        _entry("datasources", "只读数据源", "/datasources", "受控连接的只读业务数据源",
            _count(db, DataSource, project_id), f"{_count(db, DataSource, project_id, DataSource.enabled.is_(True))} 个已启用", DataSource, db, project_id, [], "technical"),
        _entry("catalog", "数据目录", "/catalog", "Schema、表和字段的技术目录",
            _count(db, CatalogTable, project_id), "目录表覆盖", CatalogTable, db, project_id, [], "technical"),
        _entry("systems", "业务系统", "/business-systems", "来源系统及责任边界",
            _count(db, BusinessSystem, project_id), f"{_count(db, BusinessSystem, project_id, BusinessSystem.enabled.is_(True))} 个已启用", BusinessSystem, db, project_id, [], "technical"),
        _entry("mart", "监管集市", "/mart", "监管报送集市表和字段",
            _count(db, MartTable, project_id), "监管集市表覆盖", MartTable, db, project_id, [], "technical"),
    ]
    recent = []
    for model, kind, title_attr, href in ((KnowledgeDocument,"知识文档","file_name","/knowledge/documents/{id}"),
        (TemplateDocument,"监管模板","display_name","/templates/{id}"),
        (HistoricalCaliberImport,"历史口径","import_name","/historical-calibers")):
        rows = list(db.scalars(select(model).where(model.project_id == project_id).order_by(model.updated_at.desc()).limit(3)).all())
        recent.extend({"kind":kind, "title":getattr(row,title_attr,None) or getattr(row,"file_name",None) or f"记录 {row.id}",
            "updated_at":row.updated_at, "href":href.format(id=row.id)} for row in rows)
    recent.sort(key=lambda item: item["updated_at"], reverse=True)
    pending = [
        {"type":"knowledge_review", "label":"知识版本待审核或激活", "count":knowledge_pending, "href":"/knowledge/documents"},
        {"type":"knowledge_failed", "label":"知识版本解析失败", "count":knowledge_failed, "href":"/knowledge/documents"},
        {"type":"template_review", "label":"模板版本待审核或激活", "count":template_pending, "href":"/templates"},
        {"type":"template_failed", "label":"模板版本解析失败", "count":template_failed, "href":"/templates"},
    ]
    return {"resources": resources, "recent_changes": recent[:8],
            "pending_items": [item for item in pending if item["count"]]}


def _count(db, model, project_id, *predicates):
    return int(db.scalar(select(func.count()).select_from(model).where(model.project_id == project_id, *predicates)) or 0)


def _entry(key, title, href, description, count, coverage, model, db, project_id, statuses, audience="all"):
    updated = db.scalar(select(func.max(model.updated_at)).where(model.project_id == project_id))
    return {"key":key, "title":title, "href":href, "description":description, "count":count,
        "coverage":coverage, "updated_at":updated, "statuses":[item for item in statuses if item["count"]],
        "audience":audience, "group":"资料治理" if key in {"knowledge","templates","fields","historical","traceability"} else "数据资产"}
