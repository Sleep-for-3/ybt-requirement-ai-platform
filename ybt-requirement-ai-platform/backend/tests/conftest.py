from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

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
