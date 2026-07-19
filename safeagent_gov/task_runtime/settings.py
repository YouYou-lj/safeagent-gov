"""Versioned task runtime pool defaults shared by web and worker processes."""

from .contracts import PoolSettings, TaskPool, TaskRuntimeSettings

DEFAULT_TASK_SETTINGS = TaskRuntimeSettings(
    pools={
        TaskPool.SECURITY: PoolSettings(workers=16, queue_capacity=1200),
        TaskPool.AGENT: PoolSettings(workers=8, queue_capacity=256),
        TaskPool.EVALUATION: PoolSettings(workers=1, queue_capacity=32),
    },
    max_records=20_000,
)
