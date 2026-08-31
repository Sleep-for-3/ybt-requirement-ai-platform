from collections.abc import Iterator
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# A developer's ignored ``backend/.env`` may intentionally enable the real
# Product 5.1 runtime.  Unit and API tests must never inherit that runtime or
# spend external-model quota during collection.  Set the isolated defaults
# before importing application modules; individual runtime tests can still
# override them with ``monkeypatch`` or explicit ``Settings`` values.
for _name, _value in {
    "LLM_PROVIDER": "mock",
    "LLM_BASE_URL": "",
    "LLM_MODEL": "",
    "LLM_API_KEY_ENV_NAME": "",
    "EMBEDDING_PROVIDER": "mock",
    "EMBEDDING_BASE_URL": "",
    "EMBEDDING_MODEL": "",
    "EMBEDDING_DIMENSION": "0",
    "EMBEDDING_API_KEY_ENV_NAME": "",
    "VECTOR_STORE_PROVIDER": "mock",
    "MILVUS_URI": "",
}.items():
    os.environ[_name] = _value

from app.core.database import Base
from app.core.observability import _lock, _rate_windows


@pytest.fixture(autouse=True)
def reset_rate_limit_state() -> Iterator[None]:
    """Keep each test independent from process-global request throttling state."""
    with _lock:
        _rate_windows.clear()
    yield
    with _lock:
        _rate_windows.clear()


@pytest.fixture()
def db_session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
