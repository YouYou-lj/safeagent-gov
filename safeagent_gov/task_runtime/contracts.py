"""Strict contracts for the bounded asynchronous task runtime."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskKind(str, Enum):
    SECURITY_CHECK = "security_check"
    AGENT = "agent"
    SKILL_SCAN = "skill_scan"
    EVALUATION = "evaluation"


class TaskPool(str, Enum):
    SECURITY = "security"
    AGENT = "agent"
    EVALUATION = "evaluation"


class TaskPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


TERMINAL_STATUSES = frozenset({TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.REJECTED})
PRIORITY_RANK = {
    TaskPriority.CRITICAL: 0,
    TaskPriority.HIGH: 1,
    TaskPriority.MEDIUM: 2,
    TaskPriority.LOW: 3,
}
KIND_POOL = {
    TaskKind.SECURITY_CHECK: TaskPool.SECURITY,
    TaskKind.SKILL_SCAN: TaskPool.SECURITY,
    TaskKind.AGENT: TaskPool.AGENT,
    TaskKind.EVALUATION: TaskPool.EVALUATION,
}


class TaskSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: TaskKind
    priority: TaskPriority = TaskPriority.MEDIUM
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=160)
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=600.0)
    max_attempts: int = Field(default=1, ge=1, le=3)

    @model_validator(mode="after")
    def bound_payload(self) -> TaskSubmission:
        try:
            encoded = json.dumps(self.payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("任务 payload 必须可序列化为 JSON") from exc
        if len(encoded) > 256 * 1024:
            raise ValueError("任务 payload 超过 256 KiB 上限")
        return self


class TaskIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1, max_length=120)
    actor_id: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=80)


class TaskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=160)
    trace_id: str = Field(min_length=1, max_length=160)
    tenant_id: str = Field(min_length=1, max_length=120)
    actor_id: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=80)
    kind: TaskKind
    pool: TaskPool
    priority: TaskPriority
    payload: dict[str, Any]
    idempotency_key: str | None = None
    timeout_seconds: float
    max_attempts: int
    status: TaskStatus
    attempts: int = Field(default=0, ge=0, le=3)
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    audit_events: int = Field(default=0, ge=0)
    delivery_count: int = Field(default=0, ge=0)
    recovered_count: int = Field(default=0, ge=0)
    last_worker_id: str | None = Field(default=None, max_length=200)
    lease_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class PoolSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workers: int = Field(ge=1, le=256)
    queue_capacity: int = Field(ge=1, le=100_000)
    high_priority_enqueue_timeout_seconds: float = Field(default=0.2, ge=0.0, le=10.0)


class TaskRuntimeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pools: dict[TaskPool, PoolSettings]
    max_records: int = Field(default=20_000, ge=1000, le=1_000_000)

    @model_validator(mode="after")
    def require_all_pools(self) -> TaskRuntimeSettings:
        if set(self.pools) != set(TaskPool):
            raise ValueError("任务运行时必须配置 security/agent/evaluation 三个隔离池")
        return self


class PoolMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pool: TaskPool
    workers: int
    queue_capacity: int
    queue_depth: int
    active_tasks: int
    max_queue_depth: int
    max_active_tasks: int
    leased_tasks: int = Field(default=0, ge=0)
    dead_letters: int = Field(default=0, ge=0)


class TaskRuntimeMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    running: bool
    submitted: int
    accepted: int
    rejected: int
    started: int
    succeeded: int
    failed: int
    retried: int
    idempotent_replays: int
    audit_failures: int
    mode: Literal["in_memory", "redis_dramatiq"] = "in_memory"
    recovered: int = Field(default=0, ge=0)
    dead_lettered: int = Field(default=0, ge=0)
    pools: tuple[PoolMetrics, ...]
