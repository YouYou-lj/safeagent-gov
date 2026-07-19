"""Dramatiq Redis broker configuration for GovSafeAgent workers."""

from __future__ import annotations

import os

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from .runtime_config import redis_url


def _bounded_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是整数") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} 必须介于 {minimum}—{maximum}")
    return value


BROKER = RedisBroker(
    url=redis_url(),
    namespace=os.getenv("SAFEAGENT_DRAMATIQ_NAMESPACE", "safeagent-dramatiq-v1"),
    heartbeat_timeout=_bounded_int("SAFEAGENT_DRAMATIQ_HEARTBEAT_TIMEOUT_MS", 10_000, minimum=1000, maximum=300_000),
    dead_message_ttl=_bounded_int(
        "SAFEAGENT_DRAMATIQ_DEAD_MESSAGE_TTL_MS", 604_800_000, minimum=60_000, maximum=2_592_000_000
    ),
)
dramatiq.set_broker(BROKER)
