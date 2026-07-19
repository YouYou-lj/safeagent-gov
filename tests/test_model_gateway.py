"""Model Gateway protocol, routing, resilience, isolation and API tests."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.api import model_api
from backend.main import app
from safeagent_gov.auth import issue_token
from safeagent_gov.errors import (
    ModelGatewayBudgetError,
    ModelGatewayConfigurationError,
    ModelGatewayInputError,
    ModelProviderError,
    ModelProviderTransportError,
)
from safeagent_gov.model_gateway import (
    DataClassification,
    MessageRole,
    ModelCallContext,
    ModelMessage,
    ModelRegistry,
    ModelRequest,
    ProviderDefinition,
    ProviderProtocol,
    ProviderResult,
)
from safeagent_gov.model_gateway.providers import build_provider_payload, parse_provider_response
from safeagent_gov.model_gateway.service import ModelGateway

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


async def _noop_audit(_: str, __: str, ___: dict[str, Any]) -> None:
    return None


def _profile(
    provider_id: str,
    *,
    private: bool = True,
    cost: float = 0.0,
    attempts: int = 1,
    threshold: int = 1,
) -> dict[str, Any]:
    return {
        "display_name": provider_id,
        "protocol": "internal",
        "model": f"{provider_id}-model",
        "endpoint": None,
        "credential_env": None,
        "enabled": True,
        "network_access": False,
        "private_deployment": private,
        "capabilities": ["chat", "structured_output"],
        "task_types": ["general"],
        "max_context_tokens": 10000,
        "max_output_tokens": 1000,
        "prompt_cost_per_million_usd": cost,
        "completion_cost_per_million_usd": cost,
        "priority": 1,
        "timeout_seconds": 0.2,
        "max_attempts": attempts,
        "circuit_failure_threshold": threshold,
        "circuit_recovery_seconds": 30.0,
    }


def _registry(
    tmp_path: Path,
    *,
    providers: dict[str, dict[str, Any]] | None = None,
    candidates: list[str] | None = None,
    max_concurrency: int = 2,
    server_max_cost_usd: float = 1.0,
) -> ModelRegistry:
    profiles = providers or {"primary": _profile("primary"), "fallback": _profile("fallback")}
    path = tmp_path / "model_gateway.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "version": "1.0.0",
                "default_provider": next(iter(profiles)),
                "max_concurrency": max_concurrency,
                "cache_ttl_seconds": 60,
                "max_cache_entries": 20,
                "server_max_cost_usd": server_max_cost_usd,
                "providers": profiles,
                "routing_rules": {
                    "general": {
                        "candidates": candidates or list(profiles),
                        "required_capabilities": ["chat"],
                        "private_only": False,
                        "max_latency_ms": None,
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    registry = ModelRegistry(path)
    registry.load()
    return registry


def _request(**updates: Any) -> ModelRequest:
    values: dict[str, Any] = {
        "messages": [ModelMessage(role=MessageRole.USER, content="请总结公开政策")],
        "cache_enabled": False,
    }
    values.update(updates)
    return ModelRequest(**values)


def _context(actor: str = "alice", tenant: str = "tenant-a") -> ModelCallContext:
    return ModelCallContext(trace_id=f"TRACE-{actor}", tenant_id=tenant, actor_id=actor)


class ScriptedProvider:
    def __init__(
        self,
        results: list[ProviderResult | Exception],
        *,
        delay: float = 0.0,
        concurrency: dict[str, int] | None = None,
    ) -> None:
        self.results = list(results)
        self.delay = delay
        self.calls = 0
        self.concurrency = concurrency

    async def generate(self, _: ModelRequest, __: ProviderDefinition) -> ProviderResult:
        self.calls += 1
        if self.concurrency is not None:
            self.concurrency["active"] += 1
            self.concurrency["observed"] = max(self.concurrency["observed"], self.concurrency["active"])
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            result = self.results[min(self.calls - 1, len(self.results) - 1)]
            if isinstance(result, Exception):
                raise result
            return result
        finally:
            if self.concurrency is not None:
                self.concurrency["active"] -= 1


SUCCESS = ProviderResult(content="安全归一化输出", prompt_tokens=12, completion_tokens=6)


def test_repository_registry_is_secret_free_and_covers_required_protocols():
    registry = ModelRegistry(REPOSITORY_ROOT / "configs" / "model_gateway.yaml")
    snapshot = registry.load()
    assert snapshot.provider_count == 13
    assert snapshot.enabled_count == 1
    assert snapshot.default_provider == "deterministic"
    assert {record.protocol for record in snapshot.providers} == set(ProviderProtocol)
    raw = (REPOSITORY_ROOT / "configs" / "model_gateway.yaml").read_text(encoding="utf-8")
    assert "sk-" not in raw and "credential_env" in raw


def test_registry_reload_is_atomic_and_rejects_symlink(tmp_path: Path):
    registry = _registry(tmp_path)
    original = registry.snapshot()
    path = tmp_path / "model_gateway.yaml"
    invalid = yaml.safe_load(path.read_text(encoding="utf-8"))
    invalid["routing_rules"]["general"]["candidates"] = ["missing"]
    path.write_text(yaml.safe_dump(invalid), encoding="utf-8")
    with pytest.raises(ModelGatewayConfigurationError, match="Schema"):
        registry.load()
    assert registry.snapshot().source_digest == original.source_digest

    target = tmp_path / "target.yaml"
    target.write_text("version: bad", encoding="utf-8")
    link = tmp_path / "link.yaml"
    link.symlink_to(target)
    with pytest.raises(ModelGatewayConfigurationError, match="符号链接"):
        ModelRegistry(link).load()


@pytest.mark.parametrize(
    ("protocol", "response", "expected"),
    [
        (
            ProviderProtocol.OPENAI_CHAT,
            {"choices": [{"message": {"content": "openai"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 2, "completion_tokens": 1}},
            "openai",
        ),
        (
            ProviderProtocol.OPENAI_RESPONSES,
            {"output_text": "responses", "status": "completed", "usage": {"input_tokens": 2, "output_tokens": 1}},
            "responses",
        ),
        (
            ProviderProtocol.ANTHROPIC_MESSAGES,
            {"content": [{"type": "text", "text": "claude"}], "stop_reason": "end_turn", "usage": {"input_tokens": 2, "output_tokens": 1}},
            "claude",
        ),
        (
            ProviderProtocol.GEMINI_GENERATE_CONTENT,
            {"candidates": [{"content": {"parts": [{"text": "gemini"}]}, "finishReason": "STOP"}], "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 1}},
            "gemini",
        ),
        (
            ProviderProtocol.AZURE_OPENAI,
            {"choices": [{"message": {"content": "azure"}}], "usage": {}},
            "azure",
        ),
        (
            ProviderProtocol.AWS_BEDROCK,
            {"content": [{"text": "bedrock"}], "usage": {}},
            "bedrock",
        ),
        (
            ProviderProtocol.VERTEX_AI,
            {"candidates": [{"content": {"parts": [{"text": "vertex"}]}}], "usageMetadata": {}},
            "vertex",
        ),
        (
            ProviderProtocol.OLLAMA_CHAT,
            {"message": {"content": "ollama"}, "prompt_eval_count": 2, "eval_count": 1},
            "ollama",
        ),
        (
            ProviderProtocol.VLLM_OPENAI,
            {"choices": [{"message": {"content": "vllm"}}], "usage": {}},
            "vllm",
        ),
    ],
)
def test_protocol_payloads_and_responses_are_normalized(
    protocol: ProviderProtocol, response: Mapping[str, Any], expected: str
):
    definition = ProviderDefinition(
        provider_id="test-provider",
        display_name="test",
        protocol=protocol,
        model="test-model",
        endpoint="http://127.0.0.1:9000/v1/chat",
        enabled=True,
        network_access=True,
        private_deployment=True,
    )
    payload = build_provider_payload(definition, _request())
    assert payload
    assert parse_provider_response(protocol, response).content == expected


def test_gateway_retries_falls_back_opens_circuit_and_caches_per_identity(tmp_path: Path):
    registry = _registry(tmp_path)
    primary = ScriptedProvider([ModelProviderTransportError("down")])
    fallback = ScriptedProvider([SUCCESS])
    gateway = ModelGateway(
        registry,
        providers={"primary": primary, "fallback": fallback},
        audit_hook=_noop_audit,
    )
    request = _request(cache_enabled=True)
    first = asyncio.run(gateway.chat(request, _context()))
    second = asyncio.run(gateway.chat(request, _context()))
    third = asyncio.run(gateway.chat(request, _context(actor="bob")))

    assert first.status == "fallback" and first.fallback_from == ("primary",)
    assert second.status == "cache_hit" and second.estimated_cost_usd == 0
    assert third.status == "fallback"
    assert primary.calls == 1  # circuit-open on the second identity, cache on the second call
    assert fallback.calls == 2
    metrics = gateway.metrics()
    assert metrics.total_requests == 3
    assert metrics.successful_requests == 3
    assert metrics.fallback_requests == 2
    assert metrics.cache_hits == 1
    assert next(item for item in metrics.providers if item.provider_id == "primary").circuit_state == "open"


def test_gateway_enforces_budget_private_routing_and_unknown_provider(tmp_path: Path):
    expensive = _profile("expensive", private=False, cost=1000.0)
    private = _profile("private", private=True, cost=0.0)
    registry = _registry(
        tmp_path,
        providers={"expensive": expensive, "private": private},
        candidates=["expensive", "private"],
    )
    private_provider = ScriptedProvider([SUCCESS])
    gateway = ModelGateway(registry, providers={"private": private_provider}, audit_hook=_noop_audit)
    response = asyncio.run(
        gateway.chat(
            _request(data_classification=DataClassification.RESTRICTED, max_cost_usd=0.001),
            _context(),
        )
    )
    assert response.provider_id == "private"

    with pytest.raises(ModelGatewayInputError, match="未知 Provider"):
        asyncio.run(gateway.chat(_request(requested_provider="missing"), _context()))

    expensive_registry = _registry(
        tmp_path / "budget",
        providers={"expensive": expensive},
        candidates=["expensive"],
        server_max_cost_usd=0.0001,
    )
    expensive_gateway = ModelGateway(expensive_registry, audit_hook=_noop_audit)
    with pytest.raises(ModelGatewayBudgetError):
        asyncio.run(expensive_gateway.chat(_request(), _context()))
    with pytest.raises(ModelGatewayBudgetError):
        asyncio.run(expensive_gateway.chat(_request(max_cost_usd=0.0), _context()))


def test_gateway_bounds_concurrency_and_fails_closed_when_audit_is_down(tmp_path: Path):
    registry = _registry(
        tmp_path,
        providers={"primary": _profile("primary")},
        candidates=["primary"],
        max_concurrency=2,
    )
    concurrency = {"active": 0, "observed": 0}
    provider = ScriptedProvider([SUCCESS], delay=0.03, concurrency=concurrency)
    gateway = ModelGateway(registry, providers={"primary": provider}, audit_hook=_noop_audit)

    async def run_many():
        return await asyncio.gather(
            *[
                gateway.chat(
                    _request(messages=[ModelMessage(role=MessageRole.USER, content=f"task-{index}")]),
                    _context(actor=f"actor-{index}"),
                )
                for index in range(6)
            ]
        )

    results = asyncio.run(run_many())
    assert len(results) == 6
    assert concurrency["observed"] == 2
    assert gateway.metrics().max_observed_concurrency == 2

    calls = ScriptedProvider([SUCCESS])

    async def broken_audit(_: str, __: str, ___: dict[str, Any]) -> None:
        raise RuntimeError("audit down")

    closed = ModelGateway(registry, providers={"primary": calls}, audit_hook=broken_audit)
    with pytest.raises(ModelProviderError, match="审计失败"):
        asyncio.run(closed.chat(_request(), _context()))
    assert calls.calls == 0


def _headers(subject: str, tenant: str, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(subject, tenant, role)}"}


def test_model_gateway_api_auth_tenant_cache_and_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SAFEAGENT_DB_PATH", str(tmp_path / "model-api.db"))
    monkeypatch.setenv("SAFEAGENT_GATEWAY_DB_PATH", str(tmp_path / "model-api.db"))
    monkeypatch.setenv("SAFEAGENT_AUDIT_SIGNING_SECRET", "model-api-audit-secret-0123456789abcdef")
    model_api.DEFAULT_MODEL_GATEWAY.reset_metrics()
    model_api.DEFAULT_MODEL_GATEWAY.clear_cache()
    visitor_a = _headers("alice", "tenant-a", "visitor")
    visitor_b = _headers("bob", "tenant-b", "visitor")
    admin = _headers("admin", "tenant-a", "admin")

    with TestClient(app) as client:
        assert client.get("/api/model/providers").status_code == 401
        providers = client.get("/api/model/providers", headers=visitor_a)
        assert providers.status_code == 200
        assert providers.json()["provider_count"] == 13

        payload = {
            "messages": [{"role": "user", "content": "总结公开政策"}],
            "task_type": "general",
            "cache_enabled": True,
        }
        first = client.post("/api/model/chat", json=payload, headers=visitor_a)
        assert first.status_code == 200
        result = first.json()
        assert result["provider_id"] == "deterministic"
        assert result["output_trusted"] is False
        second = client.post("/api/model/chat", json=payload, headers=visitor_a)
        assert second.status_code == 200 and second.json()["status"] == "cache_hit"

        trace_id = result["trace_id"]
        cross_tenant = client.post(
            "/api/model/chat",
            json={**payload, "trace_id": trace_id},
            headers=visitor_b,
        )
        assert cross_tenant.status_code == 404
        assert client.get("/api/model/metrics", headers=visitor_a).status_code == 403
        metrics = client.get("/api/model/metrics", headers=admin)
        assert metrics.status_code == 200
        assert metrics.json()["total_requests"] == 2
        assert client.post("/api/model/providers/reload", headers=visitor_a).status_code == 403


def test_model_gateway_offline_mechanism_evaluation_passes():
    from benchmarks.runners.eval_model_gateway import evaluate

    metrics = evaluate()["metrics"]
    assert metrics["passed"]
    assert metrics["configured_protocol_coverage"] == 1.0
    assert metrics["remote_profiles_enabled_by_default"] == 0
    assert metrics["agent_gateway_integration_rate"] == 1.0
    assert metrics["dangerous_action_executions"] == 0
