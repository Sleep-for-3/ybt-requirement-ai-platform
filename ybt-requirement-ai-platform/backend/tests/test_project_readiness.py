from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app


def test_readiness_uses_critical_blockers_instead_of_simple_average() -> None:
    with _client() as client:
        project = _post(client, "/api/projects", {"name": "准备度示例项目"})

        readiness = client.get(f"/api/projects/{project['id']}/readiness")

        assert readiness.status_code == 200
        body = readiness.json()
        assert body["overall_status"] == "blocked"
        assert len(body["dimensions"]) == 17
        assert body["dimensions"]["target_field_definition"]["status"] == "blocked"
        assert any(item["code"] == "target_fields_missing" for item in body["critical_blockers"])
        assert any(item["code"] == "database_revision_not_head" for item in body["critical_blockers"])
        assert body["dimensions"]["project_configuration"]["status"] == "ready"
        assert all(set(item) == {"status", "score", "completed_count", "required_count", "blocking_reasons", "recommended_actions", "links"} for item in body["dimensions"].values())

        onboarding = client.get(f"/api/projects/{project['id']}/onboarding")
        assert onboarding.status_code == 200
        steps = onboarding.json()["steps"]
        assert len(steps) == 10
        assert steps[0]["status"] == "completed"
        assert steps[1]["status"] == "blocked"
        assert steps[1]["blocking_reasons"]


@contextmanager
def _client() -> Iterator[TestClient]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)

    def override() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def _post(client: TestClient, path: str, payload: dict) -> dict:
    response = client.post(path, json=payload)
    assert response.status_code in {200, 201}, response.text
    return response.json()
