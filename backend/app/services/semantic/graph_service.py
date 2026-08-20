from collections import deque

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import SemanticBinding, SemanticConcept, SemanticRelation
from app.services.semantic.status_policy import SemanticVisibilityMode, status_predicate


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
        mode: SemanticVisibilityMode | str = SemanticVisibilityMode.TRUSTED,
    ) -> tuple[dict[int, int], list[tuple[SemanticRelation, str]], bool]:
        selected_mode = self._mode(mode)
        self._concept(concept_id, mode=selected_mode)
        self._validate_bounds(direction, max_depth, max_nodes)

        depths = {concept_id: 0}
        frontier = {concept_id}
        edge_by_id: dict[int, tuple[SemanticRelation, str]] = {}
        truncated = False
        for depth in range(1, max_depth + 1):
            if not frontier:
                break
            clauses = []
            if direction in {"incoming", "both"}:
                clauses.append(SemanticRelation.target_concept_id.in_(frontier))
            if direction in {"outgoing", "both"}:
                clauses.append(SemanticRelation.source_concept_id.in_(frontier))
            rows = list(self.db.scalars(select(SemanticRelation).where(
                SemanticRelation.project_id == self.project_id,
                status_predicate(SemanticRelation.status, selected_mode),
                or_(*clauses),
            ).order_by(SemanticRelation.id)).all())
            neighbor_ids = {
                relation.target_concept_id if relation.source_concept_id in frontier else relation.source_concept_id
                for relation in rows
            }
            visible_neighbors = set(self.db.scalars(select(SemanticConcept.id).where(
                SemanticConcept.project_id == self.project_id,
                SemanticConcept.id.in_(neighbor_ids),
                status_predicate(SemanticConcept.status, selected_mode),
            )).all()) if neighbor_ids else set()
            next_frontier: set[int] = set()
            for relation in rows:
                if relation.source_concept_id in frontier and direction in {"outgoing", "both"}:
                    neighbor, edge_direction = relation.target_concept_id, "outgoing"
                elif relation.target_concept_id in frontier and direction in {"incoming", "both"}:
                    neighbor, edge_direction = relation.source_concept_id, "incoming"
                else:
                    continue
                if neighbor not in visible_neighbors:
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

    def entity_concepts(
        self,
        entity_type: str,
        entity_id: int,
        *,
        mode: SemanticVisibilityMode | str = SemanticVisibilityMode.TRUSTED,
    ) -> list[SemanticConcept]:
        selected_mode = self._mode(mode)
        return list(self.db.scalars(select(SemanticConcept).join(
            SemanticBinding, SemanticBinding.semantic_concept_id == SemanticConcept.id,
        ).where(
            SemanticBinding.project_id == self.project_id,
            SemanticBinding.entity_type == entity_type,
            SemanticBinding.entity_id == entity_id,
            status_predicate(SemanticBinding.status, selected_mode),
            SemanticConcept.project_id == self.project_id,
            status_predicate(SemanticConcept.status, selected_mode),
        ).order_by(SemanticConcept.id)).all())

    def shortest_path(
        self,
        source_concept_id: int,
        target_concept_id: int,
        *,
        direction: str = "outgoing",
        max_depth: int = 5,
        max_nodes: int = 500,
        mode: SemanticVisibilityMode | str = SemanticVisibilityMode.TRUSTED,
    ) -> tuple[list[int], list[int]]:
        selected_mode = self._mode(mode)
        self._concept(source_concept_id, mode=selected_mode)
        self._concept(target_concept_id, mode=selected_mode)
        self._validate_bounds(direction, max_depth, max_nodes)
        if source_concept_id == target_concept_id:
            return [source_concept_id], []

        queue = deque([(source_concept_id, [source_concept_id], [])])
        visited = {source_concept_id}
        while queue and len(visited) < max_nodes:
            current, concept_path, relation_path = queue.popleft()
            if len(relation_path) >= max_depth:
                continue
            rows = self._adjacent(current, direction, mode=selected_mode)
            for relation, neighbor in rows:
                if neighbor in visited:
                    continue
                # ``max_nodes`` includes the source node.  Check the bound
                # before either adding or returning a newly discovered node.
                if len(visited) >= max_nodes:
                    continue
                next_concepts = [*concept_path, neighbor]
                next_relations = [*relation_path, relation.id]
                if neighbor == target_concept_id:
                    return next_concepts, next_relations
                visited.add(neighbor)
                queue.append((neighbor, next_concepts, next_relations))
        return [], []

    def concepts(
        self,
        concept_ids: set[int] | list[int],
        *,
        mode: SemanticVisibilityMode | str = SemanticVisibilityMode.TRUSTED,
    ) -> list[SemanticConcept]:
        if not concept_ids:
            return []
        selected_mode = self._mode(mode)
        return list(self.db.scalars(select(SemanticConcept).where(
            SemanticConcept.project_id == self.project_id,
            SemanticConcept.id.in_(concept_ids),
            status_predicate(SemanticConcept.status, selected_mode),
        ).order_by(SemanticConcept.id)).all())

    def _adjacent(
        self,
        concept_id: int,
        direction: str,
        *,
        mode: SemanticVisibilityMode | str = SemanticVisibilityMode.TRUSTED,
    ) -> list[tuple[SemanticRelation, int]]:
        selected_mode = self._mode(mode)
        clauses = []
        if direction in {"outgoing", "both"}:
            clauses.append(SemanticRelation.source_concept_id == concept_id)
        if direction in {"incoming", "both"}:
            clauses.append(SemanticRelation.target_concept_id == concept_id)
        rows = self.db.scalars(select(SemanticRelation).where(
            SemanticRelation.project_id == self.project_id,
            status_predicate(SemanticRelation.status, selected_mode),
            or_(*clauses),
        ).order_by(SemanticRelation.id)).all()
        neighbor_ids = {
            relation.target_concept_id if relation.source_concept_id == concept_id else relation.source_concept_id
            for relation in rows
        }
        visible_neighbors = set(self.db.scalars(select(SemanticConcept.id).where(
            SemanticConcept.project_id == self.project_id,
            SemanticConcept.id.in_(neighbor_ids),
            status_predicate(SemanticConcept.status, selected_mode),
        )).all()) if neighbor_ids else set()
        result = []
        for relation in rows:
            if relation.source_concept_id == concept_id and direction in {"outgoing", "both"}:
                neighbor = relation.target_concept_id
            elif relation.target_concept_id == concept_id and direction in {"incoming", "both"}:
                neighbor = relation.source_concept_id
            else:
                continue
            if neighbor in visible_neighbors:
                result.append((relation, neighbor))
        return result

    def _concept(
        self,
        concept_id: int,
        *,
        mode: SemanticVisibilityMode | str = SemanticVisibilityMode.TRUSTED,
    ) -> SemanticConcept:
        selected_mode = self._mode(mode)
        concept = self.db.scalar(select(SemanticConcept).where(
            SemanticConcept.id == concept_id,
            SemanticConcept.project_id == self.project_id,
            status_predicate(SemanticConcept.status, selected_mode),
        ))
        if concept is None:
            raise HTTPException(status_code=404, detail="SemanticConcept not found")
        return concept

    @staticmethod
    def _mode(mode: SemanticVisibilityMode | str) -> SemanticVisibilityMode:
        return mode if isinstance(mode, SemanticVisibilityMode) else SemanticVisibilityMode(mode)

    @staticmethod
    def _validate_bounds(direction: str, max_depth: int, max_nodes: int) -> None:
        if direction not in {"incoming", "outgoing", "both"}:
            raise HTTPException(status_code=400, detail="Invalid graph direction")
        if max_depth < 1 or max_depth > 5:
            raise HTTPException(status_code=400, detail="max_depth must be between 1 and 5")
        if max_nodes < 1 or max_nodes > 1000:
            raise HTTPException(status_code=400, detail="max_nodes must be between 1 and 1000")
