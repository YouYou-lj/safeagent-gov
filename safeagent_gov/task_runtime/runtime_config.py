"""Strict environment configuration for Redis task state and workers."""

from __future__ import annotations

import os
from functools import lru_cache

from .redis_store import RedisTaskStore
from .settings import DEFAULT_TASK_SETTINGS


def _bounded_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是数字") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} 必须介于 {minimum}—{maximum}")
    return value


def redis_url() -> str:
    value = os.getenv("SAFEAGENT_REDIS_URL", "redis://redis:6379/0").strip()
    if not value.startswith(("redis://", "rediss://", "unix://")):
        raise RuntimeError("SAFEAGENT_REDIS_URL 仅支持 redis/rediss/unix 协议")
    return value


def redis_namespace() -> str:
    return os.getenv("SAFEAGENT_TASK_REDIS_NAMESPACE", "safeagent:tasks:v1").strip()


def lease_seconds() -> float:
    return _bounded_float("SAFEAGENT_TASK_LEASE_SECONDS", 15.0, minimum=1.0, maximum=3600.0)


def staging_timeout_seconds() -> float:
    return _bounded_float("SAFEAGENT_TASK_STAGING_TIMEOUT_SECONDS", 30.0, minimum=1.0, maximum=3600.0)


@lru_cache(maxsize=1)
def get_redis_task_store() -> RedisTaskStore:
    return RedisTaskStore.from_url(
        redis_url(),
        DEFAULT_TASK_SETTINGS,
        namespace=redis_namespace(),
        lease_seconds=lease_seconds(),
        staging_timeout_seconds=staging_timeout_seconds(),
    )
