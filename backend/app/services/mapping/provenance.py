"""Read the exact mapping's last successful generation, with text correlation."""
from fastapi import HTTPException
from sqlalchemy import select

from app.models import (AuditLog, ModelCallLog, SourceToMartMapping, MartToYbtMapping,
                        ScenarioBusinessMapping, ScenarioTechnicalLineage)
from app.services.ai_skills.provenance import safe_execution_metadata
from app.services.auth.permission_service import PermissionService
from app.services.llm.execution_metadata import stable_hash

TARGETS = {
    "source_to_mart": (SourceToMartMapping, "source_to_mart_mapping", "generate_source_to_mart"),
    "mart_to_ybt": (MartToYbtMapping, "mart_to_ybt_mapping", "generate_mart_to_ybt"),
    "scenario_business": (ScenarioBusinessMapping, "scenario_business_mapping", "generate_business_draft"),
    "scenario_technical": (ScenarioTechnicalLineage, "scenario_technical_lineage", "generate_technical_draft"),
}


def mapping_provenance(db, principal, mapping_type, mapping_id):
    if mapping_type not in TARGETS:
        raise HTTPException(404, "Mapping not found")
    model, resource_type, action = TARGETS[mapping_type]
    mapping = db.get(model, mapping_id)
    if mapping is None:
        raise HTTPException(404, "Mapping not found")
    PermissionService(db, principal).require_project_permission(mapping.project_id, "project.view")
    event = db.scalar(select(AuditLog).where(AuditLog.project_id == mapping.project_id,
        AuditLog.resource_type == resource_type, AuditLog.resource_id == str(mapping_id),
        AuditLog.action == action, AuditLog.result == "success").order_by(AuditLog.id.desc()).limit(1))
    if event is None or not (event.after_summary_json or {}).get("execution_metadata"):
        return {"status": "unavailable", "execution_metadata": None}
    saved = event.after_summary_json
    metadata = safe_execution_metadata(saved["execution_metadata"])
    if metadata.get("runtime_mode") == "skill":
        log = db.get(ModelCallLog, metadata.get("run_id")) if metadata.get("run_id") else None
        if (log is None or log.project_id != mapping.project_id or log.status != "success"
                or log.skill_version_id != metadata.get("skill_version_id")
                or log.skill_key != metadata.get("skill_key") or log.context_hash != metadata.get("context_hash")):
            return {"status": "unavailable", "execution_metadata": None}
    status = "historical_unverified"
    if saved.get("draft_hash"):
        status = "current_text" if mapping.ai_generated_content and saved["draft_hash"] == stable_hash(mapping.ai_generated_content) else "text_changed"
    return {"status": status, "audit_id": event.id, "generated_at": event.created_at,
            "current_draft_hash": stable_hash(mapping.ai_generated_content or ""), "execution_metadata": metadata}
