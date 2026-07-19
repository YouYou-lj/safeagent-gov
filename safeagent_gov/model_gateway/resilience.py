"""Thread-safe per-provider circuit breakers for Model Gateway."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class CircuitSnapshot:
    state: str
    consecutive_failures: int
    opened_at: float | None


class ProviderCircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int,
        recovery_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_active = False
        self._lock = threading.Lock()

    def allow_call(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return not self._probe_active
            if self.clock() - self._opened_at < self.recovery_seconds:
                return False
            if self._probe_active:
                return False
            self._opened_at = None
            self._probe_active = True
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._probe_active = False

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            self._probe_active = False
            if self._failures >= self.failure_threshold:
                self._opened_at = self.clock()

    def snapshot(self) -> CircuitSnapshot:
        with self._lock:
            state = "open" if self._opened_at is not None else ("half_open" if self._probe_active else "closed")
            return CircuitSnapshot(state, self._failures, self._opened_at)
