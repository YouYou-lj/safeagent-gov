"""Bounded retry and circuit breaking for remote plan providers."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from safeagent_gov.contracts import AgentPlan
from safeagent_gov.errors import PlannerTransportError, PlanningError

from .protocol import Planner


@dataclass(frozen=True)
class CircuitSnapshot:
    state: str
    consecutive_failures: int
    opened_at: float | None


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        recovery_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1 or recovery_seconds <= 0:
            raise ValueError("invalid circuit breaker configuration")
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_probe = False
        self._lock = threading.Lock()

    def before_call(self) -> None:
        with self._lock:
            if self._opened_at is None:
                if self._half_open_probe:
                    raise PlanningError("远端规划器熔断器正在执行 half-open 探测")
                return
            if self.clock() - self._opened_at >= self.recovery_seconds:
                self._opened_at = None
                self._failures = self.failure_threshold - 1
                self._half_open_probe = True
                return
            raise PlanningError("远端规划器熔断器处于 open 状态")

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._half_open_probe = False

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            self._half_open_probe = False
            if self._failures >= self.failure_threshold:
                self._opened_at = self.clock()

    def snapshot(self) -> CircuitSnapshot:
        with self._lock:
            state = "open" if self._opened_at is not None else ("half_open" if self._half_open_probe else "closed")
            return CircuitSnapshot(state, self._failures, self._opened_at)


class ResilientPlanner:
    """Retry transient transport errors only; invalid model output is never retried."""

    def __init__(
        self,
        planner: Planner,
        *,
        breaker: CircuitBreaker,
        max_attempts: int = 2,
        backoff_seconds: float = 0.05,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1 or max_attempts > 3:
            raise ValueError("max_attempts must be between 1 and 3")
        if backoff_seconds < 0 or backoff_seconds > 1:
            raise ValueError("backoff_seconds must be between 0 and 1")
        self.planner = planner
        self.breaker = breaker
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.sleep = sleep
        self.planner_type = getattr(planner, "planner_type", "remote")

    def plan(self, task: str, context: dict[str, Any]) -> AgentPlan:
        self.breaker.before_call()
        for attempt in range(1, self.max_attempts + 1):
            try:
                plan = self.planner.plan(task, context)
            except PlannerTransportError:
                self.breaker.record_failure()
                if attempt >= self.max_attempts:
                    raise
                self.sleep(self.backoff_seconds * attempt)
                self.breaker.before_call()
            except PlanningError:
                # Schema/endpoint/configuration failures are deterministic and
                # retrying them would amplify cost without improving safety.
                raise
            else:
                self.breaker.record_success()
                return plan
        raise PlannerTransportError("远端规划器重试耗尽")


_BREAKERS: dict[str, CircuitBreaker] = {}
_BREAKERS_LOCK = threading.Lock()


def breaker_for(key: str) -> CircuitBreaker:
    with _BREAKERS_LOCK:
        return _BREAKERS.setdefault(key, CircuitBreaker())
