"""Retry, circuit-breaker and per-identity rate-limit tests."""

from __future__ import annotations

import pytest

from agent_demo.planners.deterministic import DeterministicPlanner
from agent_demo.planners.resilience import CircuitBreaker, ResilientPlanner
from backend.rate_limit import RateLimitExceeded, SlidingWindowLimiter
from safeagent_gov.errors import PlannerTransportError, PlanningError


class FlakyPlanner:
    planner_type = "openai_compatible"

    def __init__(self, failures: int, *, invalid: bool = False) -> None:
        self.failures = failures
        self.invalid = invalid
        self.calls = 0

    def plan(self, task, context):
        self.calls += 1
        if self.invalid:
            raise PlanningError("invalid model output")
        if self.calls <= self.failures:
            raise PlannerTransportError("timeout")
        return DeterministicPlanner().plan(task, context)


def test_transient_planner_failure_is_retried_with_a_bound() -> None:
    flaky = FlakyPlanner(1)
    planner = ResilientPlanner(
        flaky,
        breaker=CircuitBreaker(failure_threshold=3),
        max_attempts=2,
        backoff_seconds=0,
        sleep=lambda _: None,
    )
    result = planner.plan("总结公开政策", {})
    assert result.planner_type == "deterministic"
    assert flaky.calls == 2


def test_invalid_model_output_is_not_retried() -> None:
    invalid = FlakyPlanner(0, invalid=True)
    planner = ResilientPlanner(
        invalid,
        breaker=CircuitBreaker(failure_threshold=2),
        max_attempts=3,
        backoff_seconds=0,
    )
    with pytest.raises(PlanningError):
        planner.plan("task", {})
    assert invalid.calls == 1


def test_circuit_opens_and_allows_one_recovery_probe() -> None:
    clock = [0.0]
    breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=10, clock=lambda: clock[0])
    flaky = FlakyPlanner(2)
    planner = ResilientPlanner(flaky, breaker=breaker, max_attempts=1, backoff_seconds=0)
    with pytest.raises(PlannerTransportError):
        planner.plan("task", {})
    with pytest.raises(PlannerTransportError):
        planner.plan("task", {})
    assert breaker.snapshot().state == "open"
    with pytest.raises(PlanningError, match="open"):
        planner.plan("task", {})
    clock[0] = 11.0
    result = planner.plan("task", {})
    assert result.steps == []
    assert breaker.snapshot().state == "closed"


def test_sliding_window_limiter_is_identity_scoped_and_recovers() -> None:
    clock = [0.0]
    limiter = SlidingWindowLimiter(limit=2, window_seconds=10, clock=lambda: clock[0])
    assert limiter.check("tenant-a:alice")["remaining"] == 1
    assert limiter.check("tenant-a:alice")["remaining"] == 0
    assert limiter.check("tenant-a:bob")["remaining"] == 1
    with pytest.raises(RateLimitExceeded):
        limiter.check("tenant-a:alice")
    clock[0] = 10.1
    assert limiter.check("tenant-a:alice")["remaining"] == 1
