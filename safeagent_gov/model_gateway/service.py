"""Policy routing, budget control, cache, fallback and audit for model calls."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from safeagent_gov.audit import log_event
from safeagent_gov.errors import (
    ModelGatewayBudgetError,
    ModelGatewayInputError,
    ModelProviderError,
    ModelProviderResponseError,
    ModelProviderTransportError,
    ModelProviderUnavailableError,
)

from .contracts import (
    DataClassification,
    GatewayMetricsSnapshot,
    ModelCallContext,
    ModelCapability,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    ProviderDefinition,
    ProviderMetric,
    ProviderProtocol,
)
from .providers import DeterministicProvider, ModelProvider, ProtocolProvider
from .registry import MemoryModelRegistry, ModelRegistry
from .resilience import ProviderCircuitBreaker

AuditHook = Callable[[str, str, dict[str, Any]], None | Awaitable[None]]


def _default_audit(trace_id: str, stage: str, event: dict[str, Any]) -> None:
    log_event(trace_id, stage, event, actor_id=str(event.get("actor_id") or "model-gateway"))


@dataclass
class _ProviderCounters:
    calls: int = 0
    successes: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    response: ModelResponse


class ModelGateway:
    """Treat every remote model as untrusted text generation without execution authority."""

    def __init__(
        self,
        registry: ModelRegistry | MemoryModelRegistry,
        *,
        providers: Mapping[str, ModelProvider] | None = None,
        protocol_provider: ModelProvider | None = None,
        audit_hook: AuditHook = _default_audit,
        audit_timeout_seconds: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        config = registry.config()
        self.registry = registry
        self._providers = dict(providers or {})
        self._protocol_provider = protocol_provider or ProtocolProvider()
        self._deterministic_provider = DeterministicProvider()
        self._audit_hook = audit_hook
        self._audit_timeout_seconds = audit_timeout_seconds
        self._clock = clock
        self._semaphore = threading.BoundedSemaphore(config.max_concurrency)
        self._semaphore_limit = config.max_concurrency
        self._runtime_lock = threading.Lock()
        self._metrics_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._breakers: dict[str, ProviderCircuitBreaker] = {}
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._provider_counters: dict[str, _ProviderCounters] = {}
        self._active_requests = 0
        self.reset_metrics()

    def reset_metrics(self) -> None:
        with self._metrics_lock:
            self._metrics: dict[str, int | float] = {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "fallback_requests": 0,
                "cache_hits": 0,
                "max_observed_concurrency": 0,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "estimated_cost_usd": 0.0,
            }
            self._provider_counters = {}

    def refresh(self) -> None:
        """Apply a newly loaded registry only while no request owns a slot."""
        config = self.registry.config()
        with self._runtime_lock:
            if self._active_requests:
                raise ModelProviderUnavailableError("Model Gateway 正在处理请求，不能刷新运行时")
            self._semaphore = threading.BoundedSemaphore(config.max_concurrency)
            self._semaphore_limit = config.max_concurrency
            self._breakers = {}
        self.clear_cache()

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()

    def _increment(self, name: str, value: int | float = 1) -> None:
        with self._metrics_lock:
            self._metrics[name] += value

    def _provider_counter(self, provider_id: str) -> _ProviderCounters:
        with self._metrics_lock:
            return self._provider_counters.setdefault(provider_id, _ProviderCounters())

    def _record_provider_failure(self, provider_id: str) -> None:
        with self._metrics_lock:
            counter = self._provider_counters.setdefault(provider_id, _ProviderCounters())
            counter.calls += 1
            counter.failures += 1

    def _record_provider_success(self, provider: ProviderDefinition, usage: ModelUsage, cost: float) -> None:
        with self._metrics_lock:
            counter = self._provider_counters.setdefault(provider.provider_id, _ProviderCounters())
            counter.calls += 1
            counter.successes += 1
            counter.prompt_tokens += usage.prompt_tokens
            counter.completion_tokens += usage.completion_tokens
            counter.estimated_cost_usd += cost
            self._metrics["total_prompt_tokens"] += usage.prompt_tokens
            self._metrics["total_completion_tokens"] += usage.completion_tokens
            self._metrics["estimated_cost_usd"] += cost

    @asynccontextmanager
    async def _slot(self):
        while not self._semaphore.acquire(blocking=False):
            await asyncio.sleep(0.001)
        with self._runtime_lock:
            self._active_requests += 1
            active = self._active_requests
        with self._metrics_lock:
            self._metrics["max_observed_concurrency"] = max(
                int(self._metrics["max_observed_concurrency"]), active
            )
        try:
            yield
        finally:
            with self._runtime_lock:
                self._active_requests -= 1
            self._semaphore.release()

    async def _audit(self, trace_id: str, stage: str, event: dict[str, Any]) -> None:
        async def invoke() -> None:
            if inspect.iscoroutinefunction(self._audit_hook):
                await self._audit_hook(trace_id, stage, event)
                return
            result = await asyncio.to_thread(self._audit_hook, trace_id, stage, event)
            if inspect.isawaitable(result):
                await result

        await asyncio.wait_for(invoke(), timeout=self._audit_timeout_seconds)

    def _breaker(self, provider: ProviderDefinition) -> ProviderCircuitBreaker:
        with self._runtime_lock:
            breaker = self._breakers.get(provider.provider_id)
            if breaker is None:
                breaker = ProviderCircuitBreaker(
                    failure_threshold=provider.circuit_failure_threshold,
                    recovery_seconds=provider.circuit_recovery_seconds,
                    clock=self._clock,
                )
                self._breakers[provider.provider_id] = breaker
            return breaker

    def _provider(self, definition: ProviderDefinition) -> ModelProvider:
        explicit = self._providers.get(definition.provider_id)
        if explicit is not None:
            return explicit
        if definition.protocol == ProviderProtocol.INTERNAL:
            return self._deterministic_provider
        return self._protocol_provider

    @staticmethod
    def _prompt_tokens(request: ModelRequest) -> int:
        # Conservative tokenizer-independent budget: one Unicode code point is at
        # most one budget token. Vendor-reported usage replaces this after a call.
        return max(1, sum(len(message.content) for message in request.messages))

    @staticmethod
    def _worst_case_cost(provider: ProviderDefinition, prompt_tokens: int, output_tokens: int) -> float:
        return (
            prompt_tokens * provider.prompt_cost_per_million_usd
            + output_tokens * provider.completion_cost_per_million_usd
        ) / 1_000_000

    @staticmethod
    def _actual_cost(provider: ProviderDefinition, usage: ModelUsage) -> float:
        return round(
            (
                usage.prompt_tokens * provider.prompt_cost_per_million_usd
                + usage.completion_tokens * provider.completion_cost_per_million_usd
            )
            / 1_000_000,
            10,
        )

    def _candidate_ids(
        self, request: ModelRequest
    ) -> tuple[list[str], frozenset[ModelCapability], bool, int | None]:
        config = self.registry.config()
        rule = config.routing_rules.get(request.task_type) or config.routing_rules.get("general")
        candidates: list[str] = []
        if request.requested_provider:
            candidates.append(request.requested_provider)
        if rule:
            candidates.extend(rule.candidates)
        else:
            candidates.append(config.default_provider)
        if not request.allow_fallback:
            candidates = candidates[:1]
        unique = list(dict.fromkeys(candidates))
        required = request.required_capabilities | (rule.required_capabilities if rule else frozenset())
        private_only = request.private_only or bool(rule and rule.private_only)
        max_latency_ms = rule.max_latency_ms if rule else None
        return unique, required, private_only, max_latency_ms

    def _eligible_candidates(self, request: ModelRequest) -> list[ProviderDefinition]:
        config = self.registry.config()
        candidate_ids, required, private_only, max_latency_ms = self._candidate_ids(request)
        if request.data_classification == DataClassification.RESTRICTED:
            private_only = True
        prompt_tokens = self._prompt_tokens(request)
        requested_budget = config.server_max_cost_usd if request.max_cost_usd is None else request.max_cost_usd
        budget = min(config.server_max_cost_usd, requested_budget)
        eligible: list[ProviderDefinition] = []
        budget_rejections = 0
        for provider_id in candidate_ids:
            provider = config.providers.get(provider_id)
            if provider is None:
                if request.requested_provider == provider_id:
                    raise ModelGatewayInputError(f"请求了未知 Provider: {provider_id}")
                continue
            if not provider.enabled:
                continue
            if private_only and not provider.private_deployment:
                continue
            if required - provider.capabilities:
                continue
            if request.task_type not in provider.task_types and "general" not in provider.task_types:
                continue
            if request.max_output_tokens > provider.max_output_tokens:
                continue
            if prompt_tokens + request.max_output_tokens > provider.max_context_tokens:
                continue
            if max_latency_ms is not None and provider.timeout_seconds * 1000 > max_latency_ms:
                continue
            if self._worst_case_cost(provider, prompt_tokens, request.max_output_tokens) > budget:
                budget_rejections += 1
                continue
            eligible.append(provider)
        if not eligible and budget_rejections:
            raise ModelGatewayBudgetError("所有候选模型的最坏情况费用都超过服务端预算")
        if not eligible:
            raise ModelProviderUnavailableError("没有满足协议、能力、数据等级和上下文约束的可用模型")
        return eligible

    def _cache_key(self, request: ModelRequest, context: ModelCallContext) -> str:
        payload = request.model_dump(mode="json")
        payload["required_capabilities"] = sorted(payload["required_capabilities"])
        encoded = json.dumps(
            {
                "registry": self.registry.snapshot().source_digest,
                "tenant_id": context.tenant_id,
                "actor_id": context.actor_id,
                "request": payload,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _cache_get(self, key: str) -> ModelResponse | None:
        now = self._clock()
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return entry.response

    def _cache_put(self, key: str, response: ModelResponse) -> None:
        config = self.registry.config()
        if config.max_cache_entries == 0 or config.cache_ttl_seconds == 0:
            return
        with self._cache_lock:
            self._cache[key] = _CacheEntry(self._clock() + config.cache_ttl_seconds, response)
            self._cache.move_to_end(key)
            while len(self._cache) > config.max_cache_entries:
                self._cache.popitem(last=False)

    def metrics(self) -> GatewayMetricsSnapshot:
        with self._metrics_lock:
            values = dict(self._metrics)
            counters = {
                provider_id: _ProviderCounters(**vars(counter))
                for provider_id, counter in self._provider_counters.items()
            }
        records: list[ProviderMetric] = []
        with self._runtime_lock:
            breakers = dict(self._breakers)
        for provider_id in sorted(set(self.registry.config().providers) | set(counters)):
            counter = counters.get(provider_id, _ProviderCounters())
            breaker = breakers.get(provider_id)
            records.append(
                ProviderMetric(
                    provider_id=provider_id,
                    calls=counter.calls,
                    successes=counter.successes,
                    failures=counter.failures,
                    circuit_state=breaker.snapshot().state if breaker else "closed",
                    prompt_tokens=counter.prompt_tokens,
                    completion_tokens=counter.completion_tokens,
                    estimated_cost_usd=round(counter.estimated_cost_usd, 10),
                )
            )
        with self._runtime_lock:
            active = self._active_requests
        return GatewayMetricsSnapshot(
            total_requests=int(values["total_requests"]),
            successful_requests=int(values["successful_requests"]),
            failed_requests=int(values["failed_requests"]),
            fallback_requests=int(values["fallback_requests"]),
            cache_hits=int(values["cache_hits"]),
            active_requests=active,
            max_observed_concurrency=int(values["max_observed_concurrency"]),
            total_prompt_tokens=int(values["total_prompt_tokens"]),
            total_completion_tokens=int(values["total_completion_tokens"]),
            estimated_cost_usd=round(float(values["estimated_cost_usd"]), 10),
            providers=tuple(records),
        )

    async def chat(self, request: ModelRequest, context: ModelCallContext) -> ModelResponse:
        started = time.perf_counter()
        request_id = f"model-{uuid.uuid4().hex}"
        self._increment("total_requests")
        input_hash = hashlib.sha256(
            json.dumps(
                [message.model_dump(mode="json") for message in request.messages],
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        try:
            candidates = self._eligible_candidates(request)
            cache_key = self._cache_key(request, context)
            if request.cache_enabled:
                cached = self._cache_get(cache_key)
                if cached is not None:
                    response = cached.model_copy(
                        update={
                            "request_id": request_id,
                            "trace_id": context.trace_id,
                            "status": "cache_hit",
                            "estimated_cost_usd": 0.0,
                            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                            "attempts": 0,
                            "fallback_from": (),
                            "cached": True,
                        }
                    )
                    await self._audit(
                        context.trace_id,
                        "model_cache_hit",
                        {
                            "request_id": request_id,
                            "provider_id": response.provider_id,
                            "input_hash": input_hash,
                            "actor_id": context.actor_id,
                        },
                    )
                    self._increment("successful_requests")
                    self._increment("cache_hits")
                    return response

            await self._audit(
                context.trace_id,
                "model_request_routed",
                {
                    "request_id": request_id,
                    "task_type": request.task_type,
                    "requested_provider": request.requested_provider,
                    "candidate_providers": [provider.provider_id for provider in candidates],
                    "data_classification": request.data_classification.value,
                    "input_hash": input_hash,
                    "actor_id": context.actor_id,
                },
            )
            attempts = 0
            fallback_from: list[str] = []
            last_error: Exception | None = None
            async with self._slot():
                for provider in candidates:
                    breaker = self._breaker(provider)
                    if not breaker.allow_call():
                        fallback_from.append(provider.provider_id)
                        last_error = ModelProviderUnavailableError(
                            f"Provider {provider.provider_id} 熔断器未放行"
                        )
                        await self._audit(
                            context.trace_id,
                            "model_provider_skipped",
                            {
                                "request_id": request_id,
                                "provider_id": provider.provider_id,
                                "reason": "circuit_not_ready",
                                "actor_id": context.actor_id,
                            },
                        )
                        continue
                    client = self._provider(provider)
                    provider_succeeded = False
                    for provider_attempt in range(1, provider.max_attempts + 1):
                        attempts += 1
                        try:
                            await self._audit(
                                context.trace_id,
                                "model_provider_attempt",
                                {
                                    "request_id": request_id,
                                    "provider_id": provider.provider_id,
                                    "attempt": provider_attempt,
                                    "actor_id": context.actor_id,
                                },
                            )
                            result = await asyncio.wait_for(
                                client.generate(request, provider), timeout=provider.timeout_seconds
                            )
                            usage = ModelUsage(
                                prompt_tokens=result.prompt_tokens,
                                completion_tokens=result.completion_tokens,
                                total_tokens=result.prompt_tokens + result.completion_tokens,
                            )
                            cost = self._actual_cost(provider, usage)
                            response = ModelResponse(
                                request_id=request_id,
                                trace_id=context.trace_id,
                                status="fallback" if fallback_from else "completed",
                                provider_id=provider.provider_id,
                                model=provider.model,
                                protocol=provider.protocol,
                                content=result.content,
                                finish_reason=result.finish_reason,
                                usage=usage,
                                estimated_cost_usd=cost,
                                latency_ms=round((time.perf_counter() - started) * 1000, 3),
                                attempts=attempts,
                                fallback_from=tuple(fallback_from),
                                cached=False,
                                audit_complete=True,
                                output_trusted=False,
                            )
                            await self._audit(
                                context.trace_id,
                                "model_response_received",
                                {
                                    "request_id": request_id,
                                    "provider_id": provider.provider_id,
                                    "protocol": provider.protocol.value,
                                    "model": provider.model,
                                    "usage": usage.model_dump(mode="json"),
                                    "estimated_cost_usd": cost,
                                    "latency_ms": response.latency_ms,
                                    "output_hash": hashlib.sha256(result.content.encode("utf-8")).hexdigest(),
                                    "fallback_from": fallback_from,
                                    "output_trusted": False,
                                    "actor_id": context.actor_id,
                                },
                            )
                            breaker.record_success()
                            self._record_provider_success(provider, usage, cost)
                            provider_succeeded = True
                            if request.cache_enabled:
                                self._cache_put(cache_key, response)
                            self._increment("successful_requests")
                            if fallback_from:
                                self._increment("fallback_requests")
                            return response
                        except TimeoutError as exc:
                            last_error = ModelProviderTransportError("Provider 调用超时")
                            last_error.__cause__ = exc
                            breaker.record_failure()
                            self._record_provider_failure(provider.provider_id)
                        except ModelProviderTransportError as exc:
                            last_error = exc
                            breaker.record_failure()
                            self._record_provider_failure(provider.provider_id)
                        except ModelProviderUnavailableError as exc:
                            last_error = exc
                            self._record_provider_failure(provider.provider_id)
                            break
                        except ModelProviderResponseError as exc:
                            last_error = exc
                            breaker.record_failure()
                            self._record_provider_failure(provider.provider_id)
                            break
                        except Exception:
                            # Audit failures and unexpected implementation errors fail
                            # closed immediately; they are not provider fallback signals.
                            raise
                        if provider_attempt >= provider.max_attempts or not breaker.allow_call():
                            break
                        await self._audit(
                            context.trace_id,
                            "model_provider_retry",
                            {
                                "request_id": request_id,
                                "provider_id": provider.provider_id,
                                "attempt": provider_attempt,
                                "error_code": type(last_error).__name__,
                                "actor_id": context.actor_id,
                            },
                        )
                    if not provider_succeeded:
                        await self._audit(
                            context.trace_id,
                            "model_provider_failed",
                            {
                                "request_id": request_id,
                                "provider_id": provider.provider_id,
                                "error_code": type(last_error).__name__ if last_error else "unavailable",
                                "actor_id": context.actor_id,
                            },
                        )
                        fallback_from.append(provider.provider_id)
                    if not request.allow_fallback:
                        break
            raise ModelProviderUnavailableError(
                f"Model Gateway 候选全部失败: {type(last_error).__name__ if last_error else 'unavailable'}"
            ) from last_error
        except Exception as exc:
            self._increment("failed_requests")
            try:
                await self._audit(
                    context.trace_id,
                    "model_request_failed",
                    {
                        "request_id": request_id,
                        "error_code": type(exc).__name__,
                        "input_hash": input_hash,
                        "actor_id": context.actor_id,
                    },
                )
            except Exception as audit_error:
                raise ModelProviderError("Model Gateway 审计失败，调用已关闭") from audit_error
            raise
