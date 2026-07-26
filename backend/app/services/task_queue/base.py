from collections.abc import Callable
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.models import BackgroundJob


JobHandler = Callable[[Session, BackgroundJob], dict[str, Any]]


class TaskQueue(Protocol):
    def enqueue(self, db: Session, *, job_type: str, institution_id: int | None, project_id: int | None, created_by: int, idempotency_key: str, payload_summary: dict[str, Any], handler: JobHandler | None = None) -> BackgroundJob: ...
    def get_status(self, db: Session, job_id: int) -> BackgroundJob | None: ...
    def cancel(self, db: Session, job: BackgroundJob) -> BackgroundJob: ...
    def retry(self, db: Session, job: BackgroundJob) -> BackgroundJob: ...
