"""Three isolated Dramatiq wake actors backed by Redis priority queues."""

from __future__ import annotations

import dramatiq

from .contracts import TaskPool
from .dramatiq_broker import BROKER
from .worker_runtime import process_next

_ACTOR_OPTIONS = {"max_retries": 0, "time_limit": 660_000}


@dramatiq.actor(broker=BROKER, queue_name="security", actor_name="safeagent_security_wake", **_ACTOR_OPTIONS)
def security_wake() -> None:
    process_next(TaskPool.SECURITY)


@dramatiq.actor(broker=BROKER, queue_name="agent", actor_name="safeagent_agent_wake", **_ACTOR_OPTIONS)
def agent_wake() -> None:
    process_next(TaskPool.AGENT)


@dramatiq.actor(
    broker=BROKER,
    queue_name="evaluation",
    actor_name="safeagent_evaluation_wake",
    **_ACTOR_OPTIONS,
)
def evaluation_wake() -> None:
    process_next(TaskPool.EVALUATION)


_ACTORS = {
    TaskPool.SECURITY: security_wake,
    TaskPool.AGENT: agent_wake,
    TaskPool.EVALUATION: evaluation_wake,
}


def notify_pool(pool: TaskPool) -> None:
    _ACTORS[pool].send()
