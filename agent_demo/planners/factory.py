"""Configuration-controlled planner selection and safe offline fallback."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from agent_demo.adapters.dify import DifyWorkflowPlanner
from agent_demo.adapters.external_agent import ExternalAgentPlanner
from safeagent_gov.contracts import AgentPlan
from safeagent_gov.errors import PlanningError

from .deterministic import DeterministicPlanner
from .model_gateway import ModelGatewayPlanner
from .openai_compatible import OpenAICompatiblePlanner
from .protocol import Planner
from .resilience import ResilientPlanner, breaker_for


class FallbackPlanner:
    planner_type = "remote_with_offline_fallback"

    def __init__(self, primary: Planner, fallback: Planner) -> None:
        self.primary = primary
        self.fallback = fallback

    def plan(self, task: str, context: dict[str, Any]) -> AgentPlan:
        try:
            return self.primary.plan(task, context)
        except PlanningError as exc:
            plan = self.fallback.plan(task, context)
            return plan.model_copy(
                update={
                    "fallback_from": getattr(self.primary, "planner_type", "remote"),
                    "warnings": [f"remote_planner_failed:{type(exc).__name__}"],
                }
            )


def _remote_from_environment(environment: Mapping[str, str]) -> OpenAICompatiblePlanner:
    try:
        timeout = float(environment.get("SAFEAGENT_LLM_TIMEOUT_SECONDS", "15"))
    except ValueError as exc:
        raise PlanningError("SAFEAGENT_LLM_TIMEOUT_SECONDS 必须是数值") from exc
    return OpenAICompatiblePlanner(
        endpoint=environment.get("SAFEAGENT_LLM_ENDPOINT", ""),
        api_key=environment.get("SAFEAGENT_LLM_API_KEY", ""),
        model=environment.get("SAFEAGENT_LLM_MODEL", ""),
        timeout_seconds=timeout,
    )


def _dify_from_environment(environment: Mapping[str, str]) -> DifyWorkflowPlanner:
    try:
        timeout = float(environment.get("SAFEAGENT_DIFY_TIMEOUT_SECONDS", "20"))
    except ValueError as exc:
        raise PlanningError("SAFEAGENT_DIFY_TIMEOUT_SECONDS 必须是数值") from exc
    return DifyWorkflowPlanner(
        endpoint=environment.get("SAFEAGENT_DIFY_ENDPOINT", ""),
        api_key=environment.get("SAFEAGENT_DIFY_API_KEY", ""),
        workflow_name=environment.get("SAFEAGENT_DIFY_WORKFLOW", "safeagent-planner"),
        timeout_seconds=timeout,
    )


def _external_agent_from_environment(environment: Mapping[str, str]) -> ExternalAgentPlanner:
    try:
        timeout = float(environment.get("SAFEAGENT_EXTERNAL_AGENT_TIMEOUT_SECONDS", "15"))
    except ValueError as exc:
        raise PlanningError("SAFEAGENT_EXTERNAL_AGENT_TIMEOUT_SECONDS 必须是数值") from exc
    return ExternalAgentPlanner(
        endpoint=environment.get("SAFEAGENT_EXTERNAL_AGENT_ENDPOINT", ""),
        token=environment.get("SAFEAGENT_EXTERNAL_AGENT_TOKEN", ""),
        expected_agent_name=environment.get(
            "SAFEAGENT_EXTERNAL_AGENT_NAME", "safeagent-reference-tool-agent"
        ),
        timeout_seconds=timeout,
    )


def _resilient(planner: Planner, key: str, environment: Mapping[str, str]) -> ResilientPlanner:
    try:
        attempts = int(environment.get("SAFEAGENT_PLANNER_MAX_ATTEMPTS", "2"))
        backoff = float(environment.get("SAFEAGENT_PLANNER_BACKOFF_SECONDS", "0.05"))
    except ValueError as exc:
        raise PlanningError("规划器重试配置必须是数值") from exc
    return ResilientPlanner(
        planner,
        breaker=breaker_for(key),
        max_attempts=attempts,
        backoff_seconds=backoff,
    )


def create_planner(
    mode: str | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> Planner:
    env = environment or os.environ
    selected = (mode or env.get("SAFEAGENT_PLANNER_MODE", "model_gateway")).strip().casefold()
    offline = DeterministicPlanner()
    if selected == "deterministic":
        return offline
    if selected == "model_gateway":
        return ModelGatewayPlanner(provider_id=env.get("SAFEAGENT_MODEL_GATEWAY_PROVIDER") or None)
    if selected == "openai_compatible":
        openai_planner = _remote_from_environment(env)
        return _resilient(openai_planner, f"openai:{openai_planner.endpoint}", env)
    if selected == "dify":
        dify_planner = _dify_from_environment(env)
        return _resilient(dify_planner, f"dify:{dify_planner.endpoint}", env)
    if selected == "external_agent":
        external_planner = _external_agent_from_environment(env)
        return _resilient(external_planner, f"external-agent:{external_planner.endpoint}", env)
    if selected == "auto":
        if all(
            env.get(key)
            for key in ("SAFEAGENT_EXTERNAL_AGENT_ENDPOINT", "SAFEAGENT_EXTERNAL_AGENT_TOKEN")
        ):
            external_planner = _external_agent_from_environment(env)
            return FallbackPlanner(
                _resilient(external_planner, f"external-agent:{external_planner.endpoint}", env), offline
            )
        if all(env.get(key) for key in ("SAFEAGENT_LLM_ENDPOINT", "SAFEAGENT_LLM_API_KEY", "SAFEAGENT_LLM_MODEL")):
            openai_planner = _remote_from_environment(env)
            return FallbackPlanner(
                _resilient(openai_planner, f"openai:{openai_planner.endpoint}", env), offline
            )
        if all(env.get(key) for key in ("SAFEAGENT_DIFY_ENDPOINT", "SAFEAGENT_DIFY_API_KEY")):
            dify_planner = _dify_from_environment(env)
            return FallbackPlanner(_resilient(dify_planner, f"dify:{dify_planner.endpoint}", env), offline)
        return offline
    raise PlanningError(f"不支持的规划器模式: {selected}")
