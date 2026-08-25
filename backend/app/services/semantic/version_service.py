"""Transactional lifecycle and effective-date services for semantic versions."""

from datetime import UTC, date, datetime

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models import Project, SemanticConcept, SemanticConceptVersion
from app.services.semantic.binding_service import apply_status_transition
from app.services.semantic.status_policy import (
    SemanticVisibilityMode,
    audit_only_statuses,
    candidate_statuses,
    status_predicate,
)


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


class _UnscopedInstitution:
    __slots__ = ()


UNSCOPED_INSTITUTION = _UnscopedInstitution()


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
    """Serialize interval writers on the stable identity row.

    PostgreSQL's row lock is explicit.  SQLite has no ``FOR UPDATE`` support,
    so a no-op update starts a write transaction and acquires SQLite's
    database-level writer lock before the overlap query.  A busy SQLite
    database is a domain conflict, not an empty overlap result.
    """

    bind = db.get_bind()
    try:
        if bind is not None and bind.dialect.name == "postgresql":
            return db.scalar(select(SemanticConcept).where(SemanticConcept.id == concept_id).with_for_update())
        if bind is not None and bind.dialect.name == "sqlite":
            db.execute(update(SemanticConcept).where(
                SemanticConcept.id == concept_id,
            ).values(id=SemanticConcept.id))
        return db.get(SemanticConcept, concept_id)
    except OperationalError as exc:
        raise _error(
            "SEMANTIC_VERSION_LOCKED",
            "Semantic concept is locked by another version confirmation; retry the operation",
            semantic_concept_id=concept_id,
        ) from exc


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
    try:
        existing = list(db.scalars(statement.order_by(SemanticConceptVersion.version_no)).all())
    except OperationalError as exc:
        raise _error(
            "SEMANTIC_VERSION_LOCKED",
            "Semantic concept is locked by another version confirmation; retry the operation",
            semantic_concept_id=concept_id,
        ) from exc
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
    db: Session,
    concept: SemanticConcept,
) -> SemanticConcept:
    """Project the governed canonical meaning onto the legacy Concept row.

    A newer working or audit row must not hide an already confirmed meaning.
    If no confirmed row exists, the latest working candidate is the useful
    compatibility projection; audit rows are used only as a final fallback.
    ``Concept.version`` always tracks the greatest canonical version number,
    independently of which row supplies the compatibility projection.
    """

    rows = list(db.scalars(select(SemanticConceptVersion).where(
        SemanticConceptVersion.semantic_concept_id == concept.id,
        SemanticConceptVersion.project_id == concept.project_id,
    ).order_by(
        SemanticConceptVersion.version_no.desc(),
        SemanticConceptVersion.id.desc(),
    )).all())
    if not rows:
        return concept

    concept.version = max(row.version_no for row in rows)
    projected = next((row for row in rows if row.status in {"confirmed"}), None)
    if projected is None:
        projected = next((row for row in rows if row.status in candidate_statuses()), None)
    if projected is None:
        projected = next((row for row in rows if row.status in audit_only_statuses()), rows[0])

    concept.concept_name = projected.concept_name
    concept.definition = projected.definition
    concept.description = projected.description
    concept.aliases_json = list(projected.aliases_json or [])
    concept.business_domain = projected.business_domain
    concept.owner_department = projected.owner_department
    concept.status = projected.status
    concept.confidence_level = projected.confidence_level
    concept.source_type = projected.source_type
    concept.source_id = projected.source_id
    if projected.status == "confirmed":
        concept.confirmed_by = projected.confirmed_by
        concept.confirmed_at = projected.confirmed_at
    else:
        concept.confirmed_by = None
        concept.confirmed_at = None
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
    latest = _latest_version(db, concept)
    if version_no is None:
        version_no = (latest.version_no + 1) if latest is not None else 1
    inherited = latest if latest is not None else concept
    raw_status = payload.get("status") if payload.get("status") is not None else status
    resolved_status = str(raw_status or "draft")
    start_value = payload["effective_from"] if "effective_from" in payload else effective_from
    if start_value is None and latest is not None:
        start_value = inherited.effective_from
    start = _as_date(start_value, default=date.today())
    if "effective_to" in payload:
        end_value = payload["effective_to"]
    elif effective_to is not None:
        end_value = effective_to
    elif latest is not None:
        end_value = inherited.effective_to
    else:
        end_value = None
    end = _as_date(end_value) if end_value is not None else None
    if resolved_status == "confirmed":
        _assert_confirmed_interval_available(db, concept.id, start, end)
    canonical = {
        "semantic_concept_id": concept.id,
        "project_id": project_id,
        "institution_id": inherited.institution_id,
        "version_no": version_no,
        "concept_name": payload.get("concept_name", inherited.concept_name),
        "definition": payload.get("definition", inherited.definition),
        "description": payload.get("description", inherited.description),
        "aliases_json": list(payload.get("aliases_json", inherited.aliases_json or []) or []),
        "business_domain": payload.get("business_domain", inherited.business_domain),
        "owner_department": payload.get("owner_department", inherited.owner_department),
        "provenance_json": dict(payload.get("provenance_json", getattr(inherited, "provenance_json", {}) or {}) or {}),
        "status": resolved_status,
        "confidence_level": payload.get("confidence_level", inherited.confidence_level),
        "source_type": payload.get("source_type", inherited.source_type),
        "source_id": payload.get("source_id", inherited.source_id),
        "created_by": payload.get("created_by", created_by or inherited.created_by),
        "confirmed_by": payload.get("confirmed_by", getattr(inherited, "confirmed_by", None)) if resolved_status == "confirmed" else None,
        "confirmed_at": payload.get("confirmed_at", getattr(inherited, "confirmed_at", None)) if resolved_status == "confirmed" else None,
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
    sync_legacy_concept_projection(db, concept)
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
    if version.status == "confirmed":
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
    try:
        db.flush()
        sync_legacy_concept_projection(db, concept)
        db.flush()
    except IntegrityError as exc:
        raise _error("SEMANTIC_CONCEPT_DUPLICATE", "Semantic concept code already exists in this project and type") from exc
    return concept


def resolve_effective_versions(
    db: Session,
    concept_ids: list[int] | tuple[int, ...] | set[int],
    as_of: date | datetime | str,
    *,
    project_id: int | None = None,
    institution_id: int | None | _UnscopedInstitution = UNSCOPED_INSTITUTION,
) -> dict[int, SemanticConceptVersion]:
    """Resolve many concepts with the exact trusted inclusive-date policy."""

    target_date = _as_date(as_of)
    normalized_ids = sorted({int(concept_id) for concept_id in concept_ids})
    if not normalized_ids:
        return {}
    statement = select(SemanticConceptVersion).join(
        SemanticConcept,
        SemanticConcept.id == SemanticConceptVersion.semantic_concept_id,
    ).where(
        SemanticConceptVersion.semantic_concept_id.in_(normalized_ids),
        SemanticConcept.project_id == SemanticConceptVersion.project_id,
        status_predicate(SemanticConcept.status, SemanticVisibilityMode.TRUSTED),
        status_predicate(SemanticConceptVersion.status, SemanticVisibilityMode.TRUSTED),
        SemanticConceptVersion.effective_from <= target_date,
        or_(SemanticConceptVersion.effective_to.is_(None), SemanticConceptVersion.effective_to >= target_date),
    ).order_by(
        SemanticConceptVersion.semantic_concept_id,
        SemanticConceptVersion.version_no,
    )
    if project_id is not None:
        statement = statement.where(SemanticConceptVersion.project_id == project_id)
    if institution_id is not UNSCOPED_INSTITUTION:
        if institution_id is None:
            statement = statement.where(
                SemanticConcept.institution_id.is_(None),
                SemanticConceptVersion.institution_id.is_(None),
            )
        else:
            statement = statement.where(
                SemanticConcept.institution_id == institution_id,
                SemanticConceptVersion.institution_id == institution_id,
            )
    matches_by_concept: dict[int, list[SemanticConceptVersion]] = {}
    for version in db.scalars(statement).all():
        matches_by_concept.setdefault(int(version.semantic_concept_id), []).append(version)

    resolved: dict[int, SemanticConceptVersion] = {}
    for concept_id in normalized_ids:
        matches = matches_by_concept.get(concept_id, [])
        if len(matches) > 1:
            raise _error(
                "SEMANTIC_VERSION_AMBIGUOUS",
                "Multiple confirmed semantic versions match the effective date",
                semantic_concept_id=concept_id,
                as_of=target_date.isoformat(),
            )
        if matches:
            resolved[concept_id] = matches[0]
    return resolved


def resolve_effective_version(
    db: Session,
    concept_id: int,
    as_of: date | datetime | str,
    *,
    project_id: int | None = None,
    institution_id: int | None | _UnscopedInstitution = UNSCOPED_INSTITUTION,
) -> SemanticConceptVersion | None:
    return resolve_effective_versions(
        db,
        [concept_id],
        as_of,
        project_id=project_id,
        institution_id=institution_id,
    ).get(int(concept_id))


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
    sync_legacy_concept_projection(db, concept)
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
    return concept


__all__ = [
    "UNSCOPED_INSTITUTION",
    "_assert_confirmed_interval_available",
    "create_concept_with_initial_version",
    "create_concept_version",
    "patch_concept_via_version_service",
    "resolve_effective_version",
    "resolve_effective_versions",
    "sync_legacy_concept_projection",
    "transition_concept_status",
    "transition_version_status",
]
