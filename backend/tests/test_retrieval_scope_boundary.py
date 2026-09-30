import pytest
from sqlalchemy import func, select

from app.models import Project, TargetTable, TargetField, ProductScenario, RetrievalLog
from app.services.retrieval import hybrid_retriever


@pytest.mark.parametrize("selector", ["foreign_target", "missing_target", "foreign_scenario", "missing_scenario"])
def test_target_and_scenario_scope_are_checked_before_embedding_or_retrieval(db_session, monkeypatch, selector):
    db = db_session
    projects = [Project(name="授权项目"), Project(name="其他项目")]
    db.add_all(projects); db.flush()
    table = TargetTable(project_id=projects[1].id, table_code="PRIVATE", table_name="不可见表")
    scenario = ProductScenario(project_id=projects[1].id, scenario_code="PRIVATE", scenario_name="不可见场景")
    db.add_all([table, scenario]); db.flush()
    field = TargetField(project_id=projects[1].id, target_table_id=table.id, field_code="SECRET", field_name="不可见字段")
    db.add(field); db.flush()
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid scope must not tokenize private facts or initialize an external service")
    monkeypatch.setattr(hybrid_retriever, "tokenize", forbidden)
    monkeypatch.setattr(hybrid_retriever, "get_embedding_service", forbidden)
    monkeypatch.setattr(hybrid_retriever, "get_vector_store", forbidden)
    kwargs = {"target_field_id": field.id if selector == "foreign_target" else 999999} if "target" in selector else {
        "scenario_id": scenario.id if selector == "foreign_scenario" else 999999}
    before = db.scalar(select(func.count()).select_from(RetrievalLog))
    with pytest.raises(ValueError, match="not found in project"):
        hybrid_retriever.HybridRetriever(db).search(projects[0].id, "公开查询", **kwargs)
    assert db.scalar(select(func.count()).select_from(RetrievalLog)) == before
