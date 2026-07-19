"""Recompute offline Model Gateway governance and integration evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from safeagent_gov.errors import ModelGatewayBudgetError, ModelProviderTransportError
from safeagent_gov.model_gateway import (
    DataClassification,
    ModelCallContext,
    ModelMessage,
    ModelRegistry,
    ModelRequest,
    ProviderDefinition,
    ProviderProtocol,
    ProviderResult,
)
from safeagent_gov.model_gateway.service import ModelGateway


class _Provider:
    def __init__(self, result: ProviderResult | Exception) -> None:
        self.result = result
        self.calls = 0

    async def generate(self, _: ModelRequest, __: ProviderDefinition) -> ProviderResult:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def _noop_audit(_: str, __: str, ___: dict[str, Any]) -> None:
    return None


def _evaluate_agent_integration() -> tuple[dict[str, Any], set[str]]:
    # Default registries and stores are process singletons. Run this integration
    # probe in a clean interpreter so prior imports (for example FastAPI test
    # collection) cannot bind it to another database or signing key.
    with tempfile.TemporaryDirectory(prefix="safeagent-model-agent-eval-") as temporary:
        root = Path(temporary)
        environment = os.environ.copy()
        environment.update(
            {
                "SAFEAGENT_DB_PATH": str(root / "audit.db"),
                "SAFEAGENT_GATEWAY_DB_PATH": str(root / "gateway.db"),
                "SAFEAGENT_GRAPHIFY_DB_PATH": str(root / "graphify.db"),
                "SAFEAGENT_AUDIT_SIGNING_SECRET": "model-gateway-evaluation-audit-secret",
                "PYTHONWARNINGS": "ignore",
            }
        )
        probe = """
import json
from agent_demo.langgraph_agent.agent import run_agent
from safeagent_gov.audit import get_audit_trace
agent = run_agent('总结公开政策', scenario='knowledge_service', user_role='visitor')
trace = get_audit_trace(agent['trace_id'])
print(json.dumps({'agent': agent, 'stages': sorted({event['stage'] for event in trace['events']})}, ensure_ascii=False))
"""
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=ROOT.parent,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        payload = json.loads(completed.stdout)
        return payload["agent"], set(payload["stages"])


def _profile(provider_id: str, *, private: bool, cost: float = 0.0) -> dict[str, Any]:
    return {
        "display_name": provider_id,
        "protocol": "internal",
        "model": f"{provider_id}-model",
        "endpoint": None,
        "credential_env": None,
        "enabled": True,
        "network_access": False,
        "private_deployment": private,
        "capabilities": ["chat"],
        "task_types": ["general"],
        "max_context_tokens": 10000,
        "max_output_tokens": 1000,
        "prompt_cost_per_million_usd": cost,
        "completion_cost_per_million_usd": cost,
        "priority": 1,
        "timeout_seconds": 0.2,
        "max_attempts": 1,
        "circuit_failure_threshold": 1,
        "circuit_recovery_seconds": 30.0,
    }


def _test_registry(path: Path) -> ModelRegistry:
    path.write_text(
        yaml.safe_dump(
            {
                "version": "1.0.0",
                "default_provider": "primary",
                "max_concurrency": 2,
                "cache_ttl_seconds": 60,
                "max_cache_entries": 20,
                "server_max_cost_usd": 1.0,
                "providers": {
                    "primary": _profile("primary", private=False, cost=10.0),
                    "private": _profile("private", private=True),
                },
                "routing_rules": {
                    "general": {
                        "candidates": ["primary", "private"],
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


def evaluate() -> dict[str, Any]:
    started = time.perf_counter()
    registry = ModelRegistry(ROOT.parent / "configs" / "model_gateway.yaml")
    snapshot = registry.load()
    configured_protocols = {record.protocol for record in snapshot.providers}
    remote_enabled = sum(
        record.enabled and record.protocol != ProviderProtocol.INTERNAL for record in snapshot.providers
    )
    success = ProviderResult(content="normalized", prompt_tokens=10, completion_tokens=2)
    latencies: list[float] = []
    with tempfile.TemporaryDirectory(prefix="safeagent-model-eval-") as temporary:
        test_registry = _test_registry(Path(temporary) / "model_gateway.yaml")
        primary = _Provider(ModelProviderTransportError("simulated outage"))
        private = _Provider(success)
        gateway = ModelGateway(
            test_registry,
            providers={"primary": primary, "private": private},
            audit_hook=_noop_audit,
        )
        request = ModelRequest(messages=[ModelMessage(role="user", content="公开任务")], cache_enabled=True)
        mark = time.perf_counter()
        fallback = asyncio.run(
            gateway.chat(request, ModelCallContext(trace_id="EVAL-FALLBACK", tenant_id="eval", actor_id="a"))
        )
        latencies.append((time.perf_counter() - mark) * 1000)
        cached = asyncio.run(
            gateway.chat(request, ModelCallContext(trace_id="EVAL-CACHE", tenant_id="eval", actor_id="a"))
        )
        private_route = asyncio.run(
            gateway.chat(
                ModelRequest(
                    messages=[ModelMessage(role="user", content="受限任务")],
                    data_classification=DataClassification.RESTRICTED,
                    cache_enabled=False,
                    max_cost_usd=0.0,
                ),
                ModelCallContext(trace_id="EVAL-PRIVATE", tenant_id="eval", actor_id="a"),
            )
        )
        budget_blocked = False
        expensive_gateway = ModelGateway(
            test_registry,
            providers={"primary": _Provider(success), "private": _Provider(success)},
            audit_hook=_noop_audit,
        )
        try:
            asyncio.run(
                expensive_gateway.chat(
                    ModelRequest(
                        messages=[ModelMessage(role="user", content="预算任务")],
                        requested_provider="primary",
                        allow_fallback=False,
                        max_cost_usd=0.0,
                        cache_enabled=False,
                    ),
                    ModelCallContext(trace_id="EVAL-BUDGET", tenant_id="eval", actor_id="a"),
                )
            )
        except ModelGatewayBudgetError:
            budget_blocked = True

    agent, stages = _evaluate_agent_integration()
    metrics = {
        "configured_provider_count": snapshot.provider_count,
        "configured_protocol_coverage": len(configured_protocols) / len(ProviderProtocol),
        "remote_profiles_enabled_by_default": remote_enabled,
        "fallback_success_rate": float(fallback.status == "fallback" and fallback.provider_id == "private"),
        "identity_scoped_cache_hit_rate": float(cached.status == "cache_hit"),
        "restricted_private_route_rate": float(private_route.provider_id == "private"),
        "zero_budget_block_rate": float(budget_blocked),
        "agent_gateway_integration_rate": float(agent.get("planner_info", {}).get("planner_type") == "model_gateway"),
        "model_audit_event_rate": float(
            {"model_request_routed", "model_provider_attempt", "model_response_received"} <= stages
        ),
        "untrusted_output_mark_rate": float(not fallback.output_trusted),
        "dangerous_action_executions": sum(bool(item.get("executed")) for item in agent.get("tool_results", [])),
        "average_mechanism_latency_ms": round(statistics.fmean(latencies), 3),
    }
    passed = (
        metrics["configured_provider_count"] == 13
        and metrics["configured_protocol_coverage"] == 1.0
        and metrics["remote_profiles_enabled_by_default"] == 0
        and all(
            metrics[name] == 1.0
            for name in (
                "fallback_success_rate",
                "identity_scoped_cache_hit_rate",
                "restricted_private_route_rate",
                "zero_budget_block_rate",
                "agent_gateway_integration_rate",
                "model_audit_event_rate",
                "untrusted_output_mark_rate",
            )
        )
        and metrics["dangerous_action_executions"] == 0
    )
    metrics["passed"] = passed
    return {
        "schema_version": "1.0.0",
        "benchmark": "model_gateway_offline_mechanism",
        "scope": "protocol/config contracts and injected deterministic providers; no commercial account claim",
        "metrics": metrics,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "benchmarks" / "results" / "model_gateway_eval_v1.json",
    )
    args = parser.parse_args()
    result = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if not result["metrics"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
