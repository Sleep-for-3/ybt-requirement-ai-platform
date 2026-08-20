"""Transactional lifecycle and effective-date services for semantic versions."""

from datetime import UTC, date, datetime

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Project, SemanticConcept, SemanticConceptVersion
from app.services.semantic.binding_service import apply_status_transition
from app.services.semantic.status_policy import SemanticVisibilityMode, status_predicate, trusted_statuses


_VERSION_FIELDS = {
    "concept_name",
    "definition",
    "description",
    "aliases_json",
    "business_domain",
    "owner_department",
    "provenance_json",
    "confidence_level",
    "source_type",
    "source_id",
    "created_by",
    "confirmed_by",
    "confirmed_at",
    "effective_from",
    "effective_to",
    "status",
}


def _error(code: str, message: str, **extra: object) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": code, "message": message, **extra})


def _as_date(value: date | datetime | str | None, *, default: date | None = None) -> date:
    if value is None:
        if default is None:
            raise ValueError("effective_from is required")
        return default
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _project_concept(db: Session, project_id: int, concept_id: int) -> SemanticConcept:
    concept = db.get(SemanticConcept, concept_id)
    if concept is None or concept.project_id != project_id:
        raise HTTPException(status_code=404, detail="SemanticConcept not found")
    return concept


def _concept_for_version(db: Session, version: SemanticConceptVersion) -> SemanticConcept:
    concept = db.get(SemanticConcept, version.semantic_concept_id)
    if concept is None or concept.project_id != version.project_id:
        raise HTTPException(status_code=404, detail="SemanticConcept not found")
    return concept


def _latest_version(db: Session, concept: SemanticConcept) -> SemanticConceptVersion | None:
    return db.scalar(select(SemanticConceptVersion).where(
        SemanticConceptVersion.semantic_concept_id == concept.id,
        SemanticConceptVersion.project_id == concept.project_id,
    ).order_by(SemanticConceptVersion.version_no.desc(), SemanticConceptVersion.id.desc()).limit(1))


def _lock_stable_concept(db: Session, concept_id: int) -> SemanticConcept | None:
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        return db.scalar(select(SemanticConcept).where(SemanticConcept.id == concept_id).with_for_update())
    return db.get(SemanticConcept, concept_id)


def _assert_confirmed_interval_available(
    db: Session,
    concept_id: int,
    effective_from: date | datetime | str,
    effective_to: date | datetime | str | None = None,
    *,
    exclude_version_id: int | None = None,
) -> None:
    """Reject inclusive overlap among confirmed versions in the write transaction."""

    concept = _lock_stable_concept(db, concept_id)
    if concept is None:
        raise HTTPException(status_code=404, detail="SemanticConcept not found")
    start = _as_date(effective_from)
    end = _as_date(effective_to) if effective_to is not None else None
    if end is not None and end < start:
        raise _error("SEMANTIC_VERSION_INVALID_INTERVAL", "effective_to must be on or after effective_from")

    statement = select(SemanticConceptVersion).where(
        SemanticConceptVersion.semantic_concept_id == concept_id,
        status_predicate(SemanticConceptVersion.status, SemanticVisibilityMode.TRUSTED),
    )
    if exclude_version_id is not None:
        statement = statement.where(SemanticConceptVersion.id != exclude_version_id)
    existing = list(db.scalars(statement.order_by(SemanticConceptVersion.version_no)).all())
    for row in existing:
        existing_end = row.effective_to
        starts_before_end = end is None or row.effective_from <= end
        ends_after_start = existing_end is None or existing_end >= start
        if starts_before_end and ends_after_start:
            raise _error(
                "SEMANTIC_VERSION_INTERVAL_CONFLICT",
                "Confirmed semantic version effective intervals cannot overlap",
                semantic_concept_id=concept_id,
                conflicting_version_id=row.id,
            )


def sync_legacy_concept_projection(
    concept: SemanticConcept,
    version: SemanticConceptVersion,
) -> SemanticConcept:
    """Project canonical version meaning onto the legacy Concept row in-place."""

    concept.concept_name = version.concept_name
    concept.definition = version.definition
    concept.description = version.description
    concept.aliases_json = list(version.aliases_json or [])
    concept.business_domain = version.business_domain
    concept.owner_department = version.owner_department
    concept.status = version.status
    concept.confidence_level = version.confidence_level
    concept.source_type = version.source_type
    concept.source_id = version.source_id
    concept.confirmed_by = version.confirmed_by
    concept.confirmed_at = version.confirmed_at
    if concept.version < version.version_no:
        concept.version = version.version_no
    return concept


def create_concept_with_initial_version(
    db: Session,
    *,
    project_id: int,
    values: dict,
    institution_id: int | None = None,
    created_by: str | None = None,
    effective_from: date | datetime | str | None = None,
) -> SemanticConcept:
    """Create stable identity plus canonical v1 without committing the caller transaction."""

    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    payload = dict(values)
    payload["concept_code"] = str(payload.get("concept_code", "")).strip().upper()
    payload.setdefault("institution_id", institution_id if institution_id is not None else project.institution_id)
    payload.setdefault("created_by", created_by)
    status = payload.get("status", "draft")
    concept = SemanticConcept(**{
        key: value for key, value in payload.items()
        if key in {
            "institution_id", "project_id", "concept_type", "concept_code", "concept_name", "definition",
            "description", "aliases_json", "business_domain", "owner_department", "status", "confidence_level",
            "version", "source_type", "source_id", "created_by", "confirmed_by", "confirmed_at",
        }
    }, project_id=project_id)
    db.add(concept)
    try:
        db.flush()
    except IntegrityError as exc:
        raise _error("SEMANTIC_CONCEPT_DUPLICATE", "Semantic concept code already exists in this project and type") from exc
    create_concept_version(
        db,
        concept=concept,
        project_id=project_id,
        version_no=1,
        values={
            key: value for key, value in payload.items()
            if key in _VERSION_FIELDS
        },
        created_by=created_by,
        effective_from=effective_from,
        status=status,
    )
    return concept


def create_concept_version(
    db: Session,
    concept: SemanticConcept | None = None,
    *,
    project_id: int | None = None,
    concept_id: int | None = None,
    version_no: int | None = None,
    values: dict | None = None,
    created_by: str | None = None,
    effective_from: date | datetime | str | None = None,
    effective_to: date | datetime | str | None = None,
    status: str | None = None,
) -> SemanticConceptVersion:
    payload = dict(values or {})
    if concept is None:
        if concept_id is None or project_id is None:
            raise ValueError("concept or concept_id/project_id is required")
        concept = _project_concept(db, project_id, concept_id)
    if project_id is None:
        project_id = concept.project_id
    if concept.project_id != project_id:
        raise HTTPException(status_code=404, detail="SemanticConcept not found")
    if version_no is None:
        latest = _latest_version(db, concept)
        version_no = (latest.version_no + 1) if latest is not None else 1
    resolved_status = str(payload.get("status", status or "draft"))
    start = _as_date(payload.get("effective_from", effective_from), default=date.today())
    end_value = payload.get("effective_to", effective_to)
    end = _as_date(end_value) if end_value is not None else None
    if resolved_status == "confirmed":
        _assert_confirmed_interval_available(db, concept.id, start, end)
    canonical = {
        "semantic_concept_id": concept.id,
        "project_id": project_id,
        "institution_id": concept.institution_id,
        "version_no": version_no,
        "concept_name": payload.get("concept_name", concept.concept_name),
        "definition": payload.get("definition", concept.definition),
        "description": payload.get("description", concept.description),
        "aliases_json": list(payload.get("aliases_json", concept.aliases_json or [])),
        "business_domain": payload.get("business_domain", concept.business_domain),
        "owner_department": payload.get("owner_department", concept.owner_department),
        "provenance_json": dict(payload.get("provenance_json", {})),
        "status": resolved_status,
        "confidence_level": payload.get("confidence_level", concept.confidence_level),
        "source_type": payload.get("source_type", concept.source_type),
        "source_id": payload.get("source_id", concept.source_id),
        "created_by": payload.get("created_by", created_by or concept.created_by),
        "confirmed_by": payload.get("confirmed_by", concept.confirmed_by if resolved_status == "confirmed" else None),
        "confirmed_at": payload.get("confirmed_at", concept.confirmed_at if resolved_status == "confirmed" else None),
        "effective_from": start,
        "effective_to": end,
    }
    version = SemanticConceptVersion(**canonical)
    if resolved_status == "confirmed" and version.confirmed_at is None:
        version.confirmed_at = datetime.now(UTC)
    db.add(version)
    try:
        db.flush()
    except IntegrityError as exc:
        raise _error("SEMANTIC_VERSION_DUPLICATE", "Semantic concept version already exists") from exc
    if resolved_status == "confirmed":
        sync_legacy_concept_projection(concept, version)
    return version


def patch_concept_via_version_service(
    db: Session,
    *,
    project_id: int,
    concept_id: int,
    values: dict,
) -> SemanticConcept:
    concept = _project_concept(db, project_id, concept_id)
    version = _latest_version(db, concept)
    if version is None:
        version = create_concept_version(db, concept=concept, project_id=project_id, version_no=1, values={"status": concept.status})
    if concept.status == "confirmed" or version.status == "confirmed":
        raise _error(
            "SEMANTIC_VERSION_IMMUTABLE",
            "Confirmed semantic version is immutable; create a new version for changed meaning",
            semantic_concept_id=concept.id,
            version_id=version.id,
        )
    payload = dict(values)
    if "concept_code" in payload:
        concept.concept_code = str(payload.pop("concept_code")).strip().upper()
    if "concept_type" in payload:
        concept.concept_type = payload.pop("concept_type")
    for key, value in payload.items():
        if key in _VERSION_FIELDS and key not in {"status", "effective_from", "effective_to", "confirmed_by", "confirmed_at", "created_by"}:
            setattr(version, key, value)
    concept.version += 1
    sync_legacy_concept_projection(concept, version)
    try:
        db.flush()
    except IntegrityError as exc:
        raise _error("SEMANTIC_CONCEPT_DUPLICATE", "Semantic concept code already exists in this project and type") from exc
    return concept


def resolve_effective_version(
    db: Session,
    concept_id: int,
    as_of: date | datetime | str,
    *,
    project_id: int | None = None,
) -> SemanticConceptVersion | None:
    target_date = _as_date(as_of)
    statement = select(SemanticConceptVersion).where(
        SemanticConceptVersion.semantic_concept_id == concept_id,
        status_predicate(SemanticConceptVersion.status, SemanticVisibilityMode.TRUSTED),
        SemanticConceptVersion.effective_from <= target_date,
        or_(SemanticConceptVersion.effective_to.is_(None), SemanticConceptVersion.effective_to >= target_date),
    ).order_by(SemanticConceptVersion.version_no)
    if project_id is not None:
        statement = statement.where(SemanticConceptVersion.project_id == project_id)
    matches = list(db.scalars(statement).all())
    if len(matches) > 1:
        raise _error(
            "SEMANTIC_VERSION_AMBIGUOUS",
            "Multiple confirmed semantic versions match the effective date",
            semantic_concept_id=concept_id,
            as_of=target_date.isoformat(),
        )
    return matches[0] if matches else None


def transition_version_status(
    db: Session,
    version: SemanticConceptVersion | int,
    new_status: str,
    actor: str,
    *,
    project_id: int | None = None,
) -> SemanticConceptVersion:
    row = version if isinstance(version, SemanticConceptVersion) else db.get(SemanticConceptVersion, version)
    if row is None or (project_id is not None and row.project_id != project_id):
        raise HTTPException(status_code=404, detail="SemanticConceptVersion not found")
    concept = _concept_for_version(db, row)
    if new_status == "confirmed":
        _assert_confirmed_interval_available(db, row.semantic_concept_id, row.effective_from, row.effective_to, exclude_version_id=row.id)
    apply_status_transition(row, new_status, actor)
    sync_legacy_concept_projection(concept, row)
    db.flush()
    return row


def transition_concept_status(
    db: Session,
    *,
    project_id: int,
    concept_id: int,
    new_status: str,
    actor: str,
) -> SemanticConcept:
    concept = _project_concept(db, project_id, concept_id)
    version = _latest_version(db, concept)
    if version is None:
        version = create_concept_version(
            db, concept=concept, project_id=project_id, version_no=1,
            values={"status": concept.status}, effective_from=date.today(),
        )
    transition_version_status(db, version, new_status, actor, project_id=project_id)
    return sync_legacy_concept_projection(concept, version)


__all__ = [
    "_assert_confirmed_interval_available",
    "create_concept_with_initial_version",
    "create_concept_version",
    "patch_concept_via_version_service",
    "resolve_effective_version",
    "sync_legacy_concept_projection",
    "transition_concept_status",
    "transition_version_status",
]
