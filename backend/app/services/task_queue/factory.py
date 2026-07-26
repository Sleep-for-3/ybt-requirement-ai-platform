from functools import lru_cache

from app.core.settings import get_settings
from app.services.task_queue.celery import CeleryTaskQueue
from app.services.task_queue.inline import InlineTaskQueue


@lru_cache
def get_task_queue():
    if get_settings().task_queue_provider == "celery":
        return CeleryTaskQueue()
    return InlineTaskQueue()
