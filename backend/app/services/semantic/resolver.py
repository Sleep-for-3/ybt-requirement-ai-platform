"""Deterministic semantic concept resolver over bounded entity descriptors."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project, SemanticBinding, SemanticConcept
from app.schemas.semantic import SemanticCandidateProvenance, SemanticMatchEvidence
from app.services.semantic.entity_adapter import SemanticEntityAdapter, SemanticEntityDescriptor
from app.services.semantic.status_policy import SemanticVisibilityMode, status_predicate


_MAX_EVIDENCE = 3
_MAX_EXCERPT = 500


class SemanticResolver:
    def __init__(self, db: Session, project_id: int):
        self.db = db
        self.project_id = project_id

    def resolve(
        self,
        entity_type: str,
        entity_id: int,
        *,
        mode: SemanticVisibilityMode | str = SemanticVisibilityMode.TRUSTED,
        visibility_mode: SemanticVisibilityMode | str | None = None,
        query_code: str | None = None,
        query_name: str | None = None,
        comment: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        selected_mode = visibility_mode if visibility_mode is not None else mode
        if not isinstance(selected_mode, SemanticVisibilityMode):
            selected_mode = SemanticVisibilityMode(selected_mode)
        descriptor = SemanticEntityAdapter.describe(self.db, self.project_id, entity_type, entity_id)
        project = self.db.get(Project, self.project_id)
        institution_id = project.institution_id if project is not None else descriptor.institution_id

        concepts = list(self.db.scalars(
            select(SemanticConcept).where(
                SemanticConcept.project_id == self.project_id,
                status_predicate(SemanticConcept.status, selected_mode),
            ).order_by(SemanticConcept.id)
        ).all())
        confirmed_ids = set(self.db.scalars(select(SemanticBinding.semantic_concept_id).where(
            SemanticBinding.project_id == self.project_id,
            SemanticBinding.entity_type == entity_type,
            SemanticBinding.entity_id == entity_id,
            status_predicate(SemanticBinding.status, SemanticVisibilityMode.TRUSTED),
        )).all())

        code = self._first(query_code, descriptor.code)
        name = self._first(query_name, descriptor.name)
        description = self._first(comment, descriptor.semantic_text)
        candidates: list[tuple[tuple[object, ...], dict]] = []
        for concept in concepts:
            score, tier, reason, evidence = self._match(
                concept,
                descriptor,
                code=code,
                name=name,
                comment=description,
                confirmed_ids=confirmed_ids,
            )
            if score <= 0:
                continue
            evidence_dicts = [item.model_dump() for item in evidence[:_MAX_EVIDENCE]]
            source_refs = descriptor.source_refs[:8]
            source_ids = [ref.source_id for ref in source_refs if ref.source_id is not None]
            provenance = SemanticCandidateProvenance(
                project_id=self.project_id,
                institution_id=institution_id,
                entity_type=entity_type,
                entity_id=entity_id,
                semantic_concept_id=concept.id,
                resolver_rule="confirmed_binding>exact_code>canonical_name>alias>regulatory_text>metadata_text",
                source_type=source_refs[0].source_type if source_refs else None,
                source_id=source_refs[0].source_id if source_refs else None,
                source_ids=source_ids,
                evidence_ids=source_ids[:8],
                retrieval_metadata={
                    "mode": selected_mode.value,
                    "descriptor_type": entity_type,
                    "limit": min(max(int(limit), 1), 50),
                },
            )
            candidate = {
                "semantic_concept_id": concept.id,
                "score": score,
                "match_reason": reason,
                "evidence": evidence_dicts,
                "provenance": provenance.model_dump(),
                "status": "ai_suggested",
            }
            candidates.append(((tier, -score, reason, concept.id), candidate))
        candidates.sort(key=lambda item: item[0])
        return [candidate for _, candidate in candidates[: min(max(int(limit), 1), 50)]]

    @classmethod
    def _match(
        cls,
        concept: SemanticConcept,
        descriptor: SemanticEntityDescriptor,
        *,
        code: str | None,
        name: str | None,
        comment: str | None,
        confirmed_ids: set[int],
    ) -> tuple[float, int, str, list[SemanticMatchEvidence]]:
        matches: list[tuple[int, float, str, SemanticMatchEvidence]] = []
        if concept.id in confirmed_ids:
            matches.append((0, 1.0, "confirmed_binding", SemanticMatchEvidence(
                match_reason="confirmed_binding",
                matched_field="semantic_binding.status",
                excerpt="confirmed binding",
                source_type="semantic_binding",
                source_id=concept.id,
                score=1.0,
            )))

        normalized_code = cls._normalize(code)
        concept_code = cls._normalize(concept.concept_code)
        if normalized_code and normalized_code == concept_code:
            matches.append((1, 0.98, "exact_code", SemanticMatchEvidence(
                match_reason="exact_code",
                matched_field="concept_code",
                excerpt=cls._excerpt(concept.concept_code),
                source_type="semantic_concept",
                source_id=concept.id,
                score=0.98,
            )))

        normalized_name = cls._normalize(name)
        if normalized_name and normalized_name == cls._normalize(concept.concept_name):
            matches.append((2, 0.95, "exact_name", SemanticMatchEvidence(
                match_reason="exact_name",
                matched_field="concept_name",
                excerpt=cls._excerpt(concept.concept_name),
                source_type="semantic_concept",
                source_id=concept.id,
                score=0.95,
            )))

        aliases = tuple(concept.aliases_json or ())
        if normalized_name:
            alias = next((item for item in aliases if normalized_name == cls._normalize(item)), None)
            if alias:
                matches.append((3, 0.90, "exact_alias", SemanticMatchEvidence(
                    match_reason="exact_alias",
                    matched_field="aliases_json",
                    excerpt=cls._excerpt(alias),
                    source_type="semantic_concept",
                    source_id=concept.id,
                    score=0.90,
                )))

        terms = tuple(dict.fromkeys(
            item for item in (concept.concept_name, *aliases, concept.concept_code)
            if cls._normalize(item)
        ))
        normalized_comment = cls._normalize(comment)
        for field_name, field_value in descriptor.text_fields:
            normalized_field = cls._normalize(field_value)
            matched_term = next((term for term in terms if cls._normalize(term) in normalized_field), None)
            if not matched_term:
                continue
            reason = "regulatory_text" if cls._is_regulatory_field(field_name) else "metadata_text"
            tier = 4 if reason == "regulatory_text" else 5
            score = 0.85 if reason == "regulatory_text" else 0.80
            matches.append((tier, score, reason, SemanticMatchEvidence(
                match_reason=reason,
                matched_field=field_name,
                excerpt=cls._excerpt(field_value),
                source_type=descriptor.entity_type,
                source_id=descriptor.entity_id,
                score=score,
            )))

        if normalized_comment:
            for term in terms:
                if cls._normalize(term) and cls._normalize(term) in normalized_comment:
                    matches.append((5, 0.80, "metadata_text", SemanticMatchEvidence(
                        match_reason="metadata_text",
                        matched_field="query_comment",
                        excerpt=cls._excerpt(comment),
                        source_type=descriptor.entity_type,
                        source_id=descriptor.entity_id,
                        score=0.80,
                    )))
                    break

        if not matches:
            return 0.0, 99, "no_match", []
        matches.sort(key=lambda item: (item[0], -item[1], item[2], item[3].source_id or 0, item[3].matched_field))
        best_tier, best_score, best_reason, _ = matches[0]
        evidence = [item[3] for item in matches[:_MAX_EVIDENCE]]
        return best_score, best_tier, best_reason, evidence

    @staticmethod
    def _is_regulatory_field(field_name: str) -> bool:
        return any(token in field_name for token in (
            "regulatory", "definition", "rule", "content", "question", "processing", "lineage",
        ))

    @staticmethod
    def _normalize(value: object | None) -> str:
        return "".join(str(value or "").strip().casefold().split())

    @staticmethod
    def _excerpt(value: object | None) -> str:
        return str(value or "").strip()[:_MAX_EXCERPT]

    @staticmethod
    def _first(*values: object | None) -> str | None:
        return next((str(value) for value in values if value is not None and str(value).strip()), None)


__all__ = ["SemanticResolver"]
