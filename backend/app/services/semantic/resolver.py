from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SemanticBinding, SemanticConcept
from app.services.semantic.binding_service import get_project_entity


class SemanticResolver:
    def __init__(self, db: Session, project_id: int):
        self.db = db
        self.project_id = project_id

    def resolve(
        self,
        entity_type: str,
        entity_id: int,
        *,
        query_code: str | None = None,
        query_name: str | None = None,
        comment: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        entity = get_project_entity(self.db, self.project_id, entity_type, entity_id)
        code = self._first(query_code, getattr(entity, "field_code", None), getattr(entity, "table_code", None), getattr(entity, "scenario_code", None))
        name = self._first(query_name, getattr(entity, "field_name", None), getattr(entity, "table_name", None), getattr(entity, "scenario_name", None), getattr(entity, "title", None))
        description = self._first(
            comment,
            getattr(entity, "field_comment", None),
            getattr(entity, "description", None),
            getattr(entity, "field_definition", None),
            getattr(entity, "content", None),
        )
        concepts = list(self.db.scalars(select(SemanticConcept).where(
            SemanticConcept.project_id == self.project_id,
            SemanticConcept.status != "deprecated",
        ).order_by(SemanticConcept.id)).all())
        confirmed_ids = set(self.db.scalars(select(SemanticBinding.semantic_concept_id).where(
            SemanticBinding.project_id == self.project_id,
            SemanticBinding.entity_type == entity_type,
            SemanticBinding.entity_id == entity_id,
            SemanticBinding.status == "confirmed",
        )).all())

        candidates: list[dict] = []
        for concept in concepts:
            score, reason, evidence = self._match(concept, code, name, description, confirmed_ids)
            if score <= 0:
                continue
            candidates.append({
                "semantic_concept_id": concept.id,
                "score": score,
                "match_reason": reason,
                "evidence": evidence,
                "status": "ai_suggested",
            })
        candidates.sort(key=lambda item: (-item["score"], item["semantic_concept_id"]))
        return candidates[:limit]

    @staticmethod
    def _match(concept, code: str | None, name: str | None, comment: str | None, confirmed_ids: set[int]):
        normalized_code = SemanticResolver._normalize(code)
        normalized_name = SemanticResolver._normalize(name)
        if normalized_code and normalized_code == SemanticResolver._normalize(concept.concept_code):
            return 1.0, "exact_code", {"query_code": code, "concept_code": concept.concept_code}
        if normalized_name and normalized_name == SemanticResolver._normalize(concept.concept_name):
            return 0.95, "exact_name", {"query_name": name, "concept_name": concept.concept_name}
        aliases = {SemanticResolver._normalize(alias) for alias in (concept.aliases_json or [])}
        if normalized_name and normalized_name in aliases:
            return 0.9, "exact_alias", {"query_name": name, "alias": name}
        text = SemanticResolver._normalize(comment)
        terms = [SemanticResolver._normalize(concept.concept_name), *(SemanticResolver._normalize(alias) for alias in (concept.aliases_json or []))]
        matched = next((term for term in terms if term and text and term in text), None)
        if matched:
            return 0.75, "metadata_comment", {"matched_text": matched}
        if concept.id in confirmed_ids:
            return 0.7, "confirmed_historical_binding", {"entity_binding_status": "confirmed"}
        return 0.0, "no_match", {}

    @staticmethod
    def _normalize(value: object | None) -> str:
        return "".join(str(value or "").strip().casefold().split())

    @staticmethod
    def _first(*values):
        return next((str(value) for value in values if value is not None and str(value).strip()), None)
