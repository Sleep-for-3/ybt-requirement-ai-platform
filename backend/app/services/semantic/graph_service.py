from collections import deque

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import SemanticBinding, SemanticConcept, SemanticRelation


class SemanticGraphService:
    def __init__(self, db: Session, project_id: int):
        self.db = db
        self.project_id = project_id

    def traverse(
        self,
        concept_id: int,
        *,
        direction: str = "both",
        max_depth: int = 1,
        max_nodes: int = 200,
        statuses: tuple[str, ...] = ("confirmed", "draft", "ai_suggested"),
    ) -> tuple[dict[int, int], list[tuple[SemanticRelation, str]], bool]:
        self._concept(concept_id)
        if direction not in {"incoming", "outgoing", "both"}:
            raise HTTPException(status_code=400, detail="Invalid graph direction")
        if max_depth < 1 or max_depth > 5:
            raise HTTPException(status_code=400, detail="max_depth must be between 1 and 5")
        if max_nodes < 1 or max_nodes > 1000:
            raise HTTPException(status_code=400, detail="max_nodes must be between 1 and 1000")

        depths = {concept_id: 0}
        frontier = {concept_id}
        edge_by_id: dict[int, tuple[SemanticRelation, str]] = {}
        truncated = False
        for depth in range(1, max_depth + 1):
            if not frontier:
                break
            clauses = []
            if direction in {"outgoing", "both"}:
                clauses.append(SemanticRelation.source_concept_id.in_(frontier))
            if direction in {"incoming", "both"}:
                clauses.append(SemanticRelation.target_concept_id.in_(frontier))
            rows = list(self.db.scalars(
                select(SemanticRelation).where(
                    SemanticRelation.project_id == self.project_id,
                    SemanticRelation.status.in_(statuses),
                    or_(*clauses),
                ).order_by(SemanticRelation.id)
            ).all())
            next_frontier: set[int] = set()
            for relation in rows:
                if relation.source_concept_id in frontier and direction in {"outgoing", "both"}:
                    neighbor, edge_direction = relation.target_concept_id, "outgoing"
                elif relation.target_concept_id in frontier and direction in {"incoming", "both"}:
                    neighbor, edge_direction = relation.source_concept_id, "incoming"
                else:
                    continue
                edge_by_id.setdefault(relation.id, (relation, edge_direction))
                if neighbor not in depths:
                    if len(depths) >= max_nodes:
                        truncated = True
                        continue
                    depths[neighbor] = depth
                    next_frontier.add(neighbor)
            frontier = next_frontier
        return depths, list(edge_by_id.values()), truncated

    def entity_concepts(self, entity_type: str, entity_id: int) -> list[SemanticConcept]:
        return list(self.db.scalars(
            select(SemanticConcept)
            .join(SemanticBinding, SemanticBinding.semantic_concept_id == SemanticConcept.id)
            .where(
                SemanticBinding.project_id == self.project_id,
                SemanticBinding.entity_type == entity_type,
                SemanticBinding.entity_id == entity_id,
                SemanticBinding.status != "deprecated",
                SemanticConcept.project_id == self.project_id,
                SemanticConcept.status != "deprecated",
            )
            .order_by(SemanticConcept.id)
        ).all())

    def shortest_path(
        self,
        source_concept_id: int,
        target_concept_id: int,
        *,
        direction: str = "outgoing",
        max_depth: int = 5,
        max_nodes: int = 500,
    ) -> tuple[list[int], list[int]]:
        self._concept(source_concept_id)
        self._concept(target_concept_id)
        if direction not in {"incoming", "outgoing", "both"}:
            raise HTTPException(status_code=400, detail="Invalid graph direction")
        if max_depth < 1 or max_depth > 5:
            raise HTTPException(status_code=400, detail="max_depth must be between 1 and 5")
        if source_concept_id == target_concept_id:
            return [source_concept_id], []

        queue = deque([(source_concept_id, [source_concept_id], [])])
        visited = {source_concept_id}
        while queue and len(visited) <= max_nodes:
            current, concept_path, relation_path = queue.popleft()
            if len(relation_path) >= max_depth:
                continue
            rows = self._adjacent(current, direction)
            for relation, neighbor in rows:
                if neighbor in visited:
                    continue
                next_concepts = [*concept_path, neighbor]
                next_relations = [*relation_path, relation.id]
                if neighbor == target_concept_id:
                    return next_concepts, next_relations
                visited.add(neighbor)
                queue.append((neighbor, next_concepts, next_relations))
        return [], []

    def concepts(self, concept_ids: set[int] | list[int]) -> list[SemanticConcept]:
        if not concept_ids:
            return []
        return list(self.db.scalars(
            select(SemanticConcept).where(
                SemanticConcept.project_id == self.project_id,
                SemanticConcept.id.in_(concept_ids),
            ).order_by(SemanticConcept.id)
        ).all())

    def _adjacent(self, concept_id: int, direction: str) -> list[tuple[SemanticRelation, int]]:
        clauses = []
        if direction in {"outgoing", "both"}:
            clauses.append(SemanticRelation.source_concept_id == concept_id)
        if direction in {"incoming", "both"}:
            clauses.append(SemanticRelation.target_concept_id == concept_id)
        rows = self.db.scalars(select(SemanticRelation).where(
            SemanticRelation.project_id == self.project_id,
            SemanticRelation.status != "deprecated",
            or_(*clauses),
        ).order_by(SemanticRelation.id)).all()
        result = []
        for relation in rows:
            if relation.source_concept_id == concept_id and direction in {"outgoing", "both"}:
                result.append((relation, relation.target_concept_id))
            elif relation.target_concept_id == concept_id and direction in {"incoming", "both"}:
                result.append((relation, relation.source_concept_id))
        return result

    def _concept(self, concept_id: int) -> SemanticConcept:
        concept = self.db.get(SemanticConcept, concept_id)
        if concept is None or concept.project_id != self.project_id:
            raise HTTPException(status_code=404, detail="SemanticConcept not found")
        return concept

