"""Audited, bounded and fail-closed unified Skill executor."""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any

from safeagent_gov.audit import log_event
from safeagent_gov.errors import SkillInputError, SkillOutputError, SkillTransientError

from .contracts import (
    SkillExecutionMode,
    SkillFailurePolicy,
    SkillMetricsSnapshot,
    SkillRequest,
    SkillResponse,
    SkillTriggerStage,
)
from .handlers import CoreSkillAdapter, core_skill_adapters
from .registry import SkillRegistry

AuditHook = Callable[[str, str, dict[str, Any]], None | Awaitable[None]]


def _default_audit(trace_id: str, stage: str, event: dict[str, Any]) -> None:
    actor = event.get("actor_id")
    log_event(trace_id, stage, event, actor_id=str(actor) if actor else None)


class SkillExecutor:
    """Execute only allowlisted adapters under manifest-defined governance."""

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        adapters: Mapping[str, CoreSkillAdapter] | None = None,
        max_concurrency: int = 16,
        audit_hook: AuditHook = _default_audit,
        audit_timeout_seconds: float = 2.0,
    ):
        if not 1 <= max_concurrency <= 256:
            raise ValueError("max_concurrency 必须在 1—256 之间")
        if not 0.01 <= audit_timeout_seconds <= 30:
            raise ValueError("audit_timeout_seconds 必须在 0.01—30 秒之间")
        self.registry = registry
        self.adapters = dict(adapters or core_skill_adapters())
        self._semaphore = threading.BoundedSemaphore(max_concurrency)
        self._audit_hook = audit_hook
        self._audit_timeout_seconds = audit_timeout_seconds
        self._metrics_lock = threading.Lock()
        self._metrics: dict[str, float | int] = {}
        self._active_calls = 0
        self.reset_metrics()

    def reset_metrics(self) -> None:
        with self._metrics_lock:
            self._metrics = {
                "selected_calls": 0,
                "actual_calls": 0,
                "expected_calls": 0,
                "expected_actual_calls": 0,
                "started_calls": 0,
                "successful_calls": 0,
                "failed_calls": 0,
                "parameter_complete_calls": 0,
                "erroneous_calls": 0,
                "mandatory_expected_calls": 0,
                "mandatory_completed_calls": 0,
                "audit_failures": 0,
                "max_observed_concurrency": 0,
                "total_latency_ms": 0.0,
            }
            self._active_calls = 0

    def _increment(self, name: str, amount: float | int = 1) -> None:
        with self._metrics_lock:
            self._metrics[name] += amount

    @asynccontextmanager
    async def _slot(self):
        while not self._semaphore.acquire(blocking=False):
            await asyncio.sleep(0.001)
        try:
            yield
        finally:
            self._semaphore.release()

    def metrics(self) -> SkillMetricsSnapshot:
        with self._metrics_lock:
            values = dict(self._metrics)
        actual = int(values["actual_calls"])
        expected = int(values["expected_calls"])
        mandatory = int(values["mandatory_expected_calls"])
        return SkillMetricsSnapshot(
            selected_calls=int(values["selected_calls"]),
            actual_calls=actual,
            expected_calls=expected,
            expected_actual_calls=int(values["expected_actual_calls"]),
            started_calls=int(values["started_calls"]),
            successful_calls=int(values["successful_calls"]),
            failed_calls=int(values["failed_calls"]),
            parameter_complete_calls=int(values["parameter_complete_calls"]),
            erroneous_calls=int(values["erroneous_calls"]),
            mandatory_expected_calls=mandatory,
            mandatory_completed_calls=int(values["mandatory_completed_calls"]),
            audit_failures=int(values["audit_failures"]),
            max_observed_concurrency=int(values["max_observed_concurrency"]),
            expected_call_recall=(int(values["expected_actual_calls"]) / expected) if expected else 1.0,
            success_rate=(int(values["successful_calls"]) / actual) if actual else 1.0,
            parameter_completeness_rate=(int(values["parameter_complete_calls"]) / actual) if actual else 1.0,
            erroneous_call_rate=(int(values["erroneous_calls"]) / actual) if actual else 0.0,
            mandatory_skill_coverage=(int(values["mandatory_completed_calls"]) / mandatory) if mandatory else 1.0,
            average_latency_ms=(float(values["total_latency_ms"]) / actual) if actual else 0.0,
        )

    async def _audit(self, trace_id: str, stage: str, event: dict[str, Any]) -> None:
        async def invoke() -> None:
            if inspect.iscoroutinefunction(self._audit_hook):
                await self._audit_hook(trace_id, stage, event)
                return
            result = await asyncio.to_thread(self._audit_hook, trace_id, stage, event)
            if inspect.isawaitable(result):
                await result

        await asyncio.wait_for(invoke(), timeout=self._audit_timeout_seconds)

    @staticmethod
    async def _invoke(adapter: CoreSkillAdapter, data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if inspect.iscoroutinefunction(adapter.handler):
            result = await adapter.handler(data, context)
        else:
            result = await asyncio.to_thread(adapter.handler, data, context)
            if inspect.isawaitable(result):
                result = await result
        if not isinstance(result, dict):
            raise SkillOutputError("Skill 输出必须是对象")
        return result

    @staticmethod
    def _missing(required: list[str], values: dict[str, Any], *, allow_empty_string: bool = False) -> list[str]:
        return [
            name
            for name in required
            if name not in values
            or values[name] is None
            or (not allow_empty_string and isinstance(values[name], str) and not values[name].strip())
        ]

    def _response(
        self,
        request: SkillRequest,
        *,
        version: str,
        mandatory: bool,
        started: float,
        success: bool,
        attempts: int,
        parameter_complete: bool,
        audit_complete: bool,
        result: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        failure_policy: SkillFailurePolicy = SkillFailurePolicy.BLOCK,
    ) -> SkillResponse:
        latency_ms = (time.perf_counter() - started) * 1000
        self._increment("total_latency_ms", latency_ms)
        if success:
            status = "completed"
        elif failure_policy == SkillFailurePolicy.BLOCK:
            status = "blocked"
        else:
            status = "completed_with_warning"
        return SkillResponse(
            trace_id=request.trace_id,
            success=success,
            status=status,
            skill_name=request.skill_name,
            skill_version=version,
            mandatory=mandatory,
            trigger_stage=request.trigger_stage,
            result=result,
            error_code=error_code,
            error_message=error_message,
            latency_ms=round(latency_ms, 3),
            attempts=attempts,
            parameter_complete=parameter_complete,
            audit_complete=audit_complete,
        )

    async def execute(self, request: SkillRequest) -> SkillResponse:
        started = time.perf_counter()
        record = self.registry.get(request.skill_name)
        definition = record.definition
        mandatory = definition.execution_mode == SkillExecutionMode.MANDATORY
        expected = request.trigger_stage == SkillTriggerStage.DIRECT or request.trigger_stage in definition.trigger_stages
        self._increment("selected_calls")
        self._increment("actual_calls")
        if expected:
            self._increment("expected_calls")
            self._increment("expected_actual_calls")
            if mandatory:
                self._increment("mandatory_expected_calls")
        else:
            self._increment("erroneous_calls")

        adapter = self.adapters.get(request.skill_name)
        error: Exception | None = None
        completed_input: dict[str, Any] = dict(request.input_data)
        unexpected = sorted(set(completed_input) - set(definition.inputs))
        try:
            if not definition.enabled:
                raise SkillInputError("Skill 已禁用")
            if not expected:
                raise SkillInputError(f"Skill 不适用于触发阶段 {request.trigger_stage.value}")
            if adapter is None:
                raise SkillInputError("Skill 未绑定可信核心适配器")
            if unexpected:
                raise SkillInputError(f"未声明输入参数: {unexpected}")
            completed_input = adapter.complete_input(completed_input, request.context, request.trace_id)
            missing = self._missing(definition.required_inputs, completed_input)
            if missing:
                raise SkillInputError(f"缺少必填参数: {missing}")
            self._increment("parameter_complete_calls")
        except Exception as exc:
            error = exc

        principal = request.context.get("principal")
        actor_id = principal.get("sub") if isinstance(principal, dict) else None
        if error is not None:
            self._increment("failed_calls")
            audit_error_code: str | None = None
            try:
                await self._audit(
                    request.trace_id,
                    "skill_execution_rejected",
                    {
                        "skill_name": request.skill_name,
                        "skill_version": definition.version,
                        "mandatory": mandatory,
                        "trigger_stage": request.trigger_stage.value,
                        "error_code": type(error).__name__,
                        "error_message": str(error),
                        "actor_id": actor_id,
                    },
                )
                audit_complete = True
            except Exception as audit_error:
                self._increment("audit_failures")
                audit_complete = False
                error = audit_error
                audit_error_code = f"audit_error:{type(audit_error).__name__}"
            return self._response(
                request,
                version=definition.version,
                mandatory=mandatory,
                started=started,
                success=False,
                attempts=0,
                parameter_complete=False,
                audit_complete=audit_complete,
                error_code=audit_error_code or type(error).__name__,
                error_message=str(error),
                failure_policy=definition.failure_policy if audit_complete else SkillFailurePolicy.BLOCK,
            )

        assert adapter is not None
        attempts = 0
        async with self._slot():
            with self._metrics_lock:
                self._active_calls += 1
                self._metrics["started_calls"] += 1
                self._metrics["max_observed_concurrency"] = max(
                    int(self._metrics["max_observed_concurrency"]), self._active_calls
                )
            try:
                try:
                    await self._audit(
                        request.trace_id,
                        "skill_execution_started",
                        {
                            "skill_name": request.skill_name,
                            "skill_version": definition.version,
                            "trigger_stage": request.trigger_stage.value,
                            "mandatory": mandatory,
                            "actor_id": actor_id,
                        },
                    )
                except Exception as exc:
                    self._increment("failed_calls")
                    self._increment("audit_failures")
                    return self._response(
                        request,
                        version=definition.version,
                        mandatory=mandatory,
                        started=started,
                        success=False,
                        attempts=0,
                        parameter_complete=True,
                        audit_complete=False,
                        error_code=f"audit_error:{type(exc).__name__}",
                        error_message=str(exc),
                        failure_policy=SkillFailurePolicy.BLOCK,
                    )

                result: dict[str, Any] | None = None
                last_error: Exception | None = None
                while attempts <= definition.retries:
                    attempts += 1
                    try:
                        result = await asyncio.wait_for(
                            self._invoke(adapter, completed_input, request.context),
                            timeout=definition.timeout_seconds,
                        )
                        missing_outputs = self._missing(
                            definition.required_outputs,
                            result,
                            allow_empty_string=True,
                        )
                        if missing_outputs:
                            raise SkillOutputError(f"Skill 输出缺少必填字段: {missing_outputs}")
                        last_error = None
                        break
                    except (TimeoutError, SkillTransientError) as exc:
                        last_error = exc
                        if attempts > definition.retries:
                            break
                        try:
                            await self._audit(
                                request.trace_id,
                                "skill_execution_retry",
                                {
                                    "skill_name": request.skill_name,
                                    "attempt": attempts,
                                    "error_code": type(exc).__name__,
                                    "actor_id": actor_id,
                                },
                            )
                        except Exception as audit_error:
                            last_error = audit_error
                            self._increment("audit_failures")
                            break
                    except Exception as exc:
                        last_error = exc
                        break

                if last_error is not None or result is None:
                    self._increment("failed_calls")
                    audit_complete = True
                    try:
                        await self._audit(
                            request.trace_id,
                            "skill_execution_failed",
                            {
                                "skill_name": request.skill_name,
                                "mandatory": mandatory,
                                "attempts": attempts,
                                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                                "error_code": type(last_error).__name__ if last_error else "unknown",
                                "error_message": str(last_error or "Skill 未返回结果"),
                                "failure_policy": definition.failure_policy.value,
                                "actor_id": actor_id,
                            },
                        )
                    except Exception as audit_error:
                        self._increment("audit_failures")
                        audit_complete = False
                        last_error = audit_error
                    return self._response(
                        request,
                        version=definition.version,
                        mandatory=mandatory,
                        started=started,
                        success=False,
                        attempts=attempts,
                        parameter_complete=True,
                        audit_complete=audit_complete,
                        error_code=type(last_error).__name__ if last_error else "unknown",
                        error_message=str(last_error or "Skill 未返回结果"),
                        failure_policy=definition.failure_policy if audit_complete else SkillFailurePolicy.BLOCK,
                    )

                try:
                    await self._audit(
                        request.trace_id,
                        "skill_execution_completed",
                        {
                            "skill_name": request.skill_name,
                            "skill_version": definition.version,
                            "mandatory": mandatory,
                            "attempts": attempts,
                            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                            "result_fields": sorted(result),
                            "actor_id": actor_id,
                        },
                    )
                except Exception as exc:
                    self._increment("failed_calls")
                    self._increment("audit_failures")
                    return self._response(
                        request,
                        version=definition.version,
                        mandatory=mandatory,
                        started=started,
                        success=False,
                        attempts=attempts,
                        parameter_complete=True,
                        audit_complete=False,
                        error_code=f"audit_error:{type(exc).__name__}",
                        error_message=str(exc),
                        failure_policy=SkillFailurePolicy.BLOCK,
                    )
                self._increment("successful_calls")
                if mandatory and expected:
                    self._increment("mandatory_completed_calls")
                return self._response(
                    request,
                    version=definition.version,
                    mandatory=mandatory,
                    started=started,
                    success=True,
                    attempts=attempts,
                    parameter_complete=True,
                    audit_complete=True,
                    result=result,
                    failure_policy=definition.failure_policy,
                )
            finally:
                with self._metrics_lock:
                    self._active_calls -= 1
