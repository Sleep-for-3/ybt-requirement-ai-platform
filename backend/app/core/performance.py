from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generator

from fastapi.encoders import jsonable_encoder
from sqlalchemy import event
from sqlalchemy.orm import Session


@dataclass
class QueryCount:
    value: int = 0


@contextmanager
def count_database_queries(db: Session, *, enabled: bool) -> Generator[QueryCount, None, None]:
    """Count statements for local diagnostics without logging SQL or bound parameters."""
    counter = QueryCount()
    if not enabled:
        yield counter
        return

    bind = db.get_bind()

    def before_cursor_execute(*_args) -> None:
        counter.value += 1

    event.listen(bind, "before_cursor_execute", before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(bind, "before_cursor_execute", before_cursor_execute)


def response_payload_bytes(payload: object) -> int:
    encoded = jsonable_encoder(payload)
    return len(json.dumps(encoded, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
