"""Public dispatcher protocol shared by local and distributed runtimes."""

from __future__ import annotations

import builtins
from typing import Protocol

from .contracts import TaskIdentity, TaskRecord, TaskRuntimeMetrics, TaskSubmission


class TaskDispatcherProtocol(Protocol):
    async def start(self) -> None: ...

    async def stop(self, *, drain: bool = True) -> None: ...

    async def submit(
        self,
        submission: TaskSubmission,
        identity: TaskIdentity,
        trace_id: str,
    ) -> TaskRecord: ...

    async def wait(self, task_id: str, *, timeout_seconds: float = 30.0) -> TaskRecord: ...

    def get(self, task_id: str) -> TaskRecord: ...

    def list(self, tenant_id: str, *, limit: int = 100) -> builtins.list[TaskRecord]: ...

    def dead_letters(
        self,
        *,
        limit: int = 100,
        tenant_id: str | None = None,
    ) -> builtins.list[TaskRecord]: ...

    def metrics(self) -> TaskRuntimeMetrics: ...
