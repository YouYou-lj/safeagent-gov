"""Process-wide task dispatcher selected explicitly by deployment mode."""

import os

from safeagent_gov.errors import TaskRuntimeError

from .dispatcher import TaskDispatcher
from .distributed import RedisDistributedDispatcher
from .handlers import default_handlers
from .redis_store import RedisTaskStore
from .runtime_config import lease_seconds, redis_namespace, redis_url, staging_timeout_seconds
from .settings import DEFAULT_TASK_SETTINGS


def _build_default_dispatcher():
    mode = os.getenv("SAFEAGENT_TASK_RUNTIME_MODE", "in_memory").strip().lower()
    handlers = default_handlers()
    if mode == "in_memory":
        return TaskDispatcher(DEFAULT_TASK_SETTINGS, handlers=handlers)
    if mode == "redis_dramatiq":
        store = RedisTaskStore.from_url(
            redis_url(),
            DEFAULT_TASK_SETTINGS,
            namespace=redis_namespace(),
            lease_seconds=lease_seconds(),
            staging_timeout_seconds=staging_timeout_seconds(),
        )
        return RedisDistributedDispatcher(store, handlers=handlers)
    raise TaskRuntimeError("SAFEAGENT_TASK_RUNTIME_MODE 仅支持 in_memory/redis_dramatiq")


DEFAULT_TASK_DISPATCHER = _build_default_dispatcher()
