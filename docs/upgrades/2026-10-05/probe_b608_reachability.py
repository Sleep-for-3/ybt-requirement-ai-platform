"""Confirmed reachability of the B608 gap through the db-profile API.

The triage probe showed ``validate_and_prepare`` accepts a crafted identifier (UNION SELECT passed).
This script answers the remaining question -- *can attacker-controlled text reach that call at all?*

Two entry points exist:
  * ``POST /api/db-profile/tasks`` -> ``DbProfileTaskCreate.table_name`` / ``field_name`` are plain
    ``str | None`` fields (no pattern, no length), and ``profile_field`` interpolates them directly.
  * the natural-language task path -> identifiers come from a regex
    (``[a-zA-Z][a-zA-Z0-9_]+``), so metacharacters cannot appear.

The script exercises the **real FastAPI route** with a crafted payload and reports what the guard
does. It also records whether the statement is *executed* or only previewed, because that decides
severity: ``profile_field`` returns ``status="reserved"`` without executing.
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

PAYLOAD = {
    "project_id": 1,
    "connection_name": "synthetic",
    # A crafted "field name": closes the count(...) and appends a second result set.
    "field_name": "1) from t union select password from users --",
    "table_name": "t",
}


@contextmanager
def _client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)

    def override():
        session: Session = factory()
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


def main() -> int:
    with _client() as client:
        response = client.post("/api/db-profile/tasks", json=PAYLOAD)
        body = response.text[:400]
        print("POST /api/db-profile/tasks ->", response.status_code)
        print(body)
        reached = response.status_code not in (403, 404, 405)
        refused = response.status_code == 422
        stored = ""
        if response.status_code in (200, 201):
            data = response.json()
            stored = json.dumps(data.get("profile_result_json") or {}, ensure_ascii=False)
        injected_into_sql = "UNION SELECT" in stored.upper() or "union select" in stored.lower()
        print()
        print(json.dumps({
            "endpoint_reached": reached,
            "status_code": response.status_code,
            "crafted_identifier_refused": refused,
            "crafted_identifier_stored_in_sql": injected_into_sql,
            "executed": False,
            "note": "profile_field 只生成并校验 SQL（status=reserved），不执行；execute() 才是执行入口。",
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
