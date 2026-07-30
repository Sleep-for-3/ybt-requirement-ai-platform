from threading import Lock
from typing import Hashable


class InFlightOperationGuard:
    """Small process-local guard for synchronous operations that are not jobs."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._keys: set[Hashable] = set()

    def try_start(self, key: Hashable) -> bool:
        with self._lock:
            if key in self._keys:
                return False
            self._keys.add(key)
            return True

    def finish(self, key: Hashable) -> None:
        with self._lock:
            self._keys.discard(key)
