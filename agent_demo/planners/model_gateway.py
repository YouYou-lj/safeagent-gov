"""Validated Agent planner backed by the unified Model Gateway."""

from __future__ import annotations

import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pydantic import ValidationError

from safeagent_gov.audit import create_trace
from safeagent_gov.contracts import AgentPlan
from safeagent_gov.errors import PlanningError, SafeAgentError
from safeagent_gov.model_gateway import (
    ModelCallContext,
    ModelCapability,
    ModelMessage,
    ModelRequest,
)
from safeagent_gov.model_gateway.defaults import DEFAULT_MODEL_GATEWAY
from safeagent_gov.model_gateway.service import ModelGateway

from .validation import validate_plan_payload

SYSTEM_PROMPT = """你是 planning-only Agent。只返回一个 JSON 对象，字段必须严格为：
{"summary":"字符串","steps":[{"step_index":1,"tool_name":"已注册工具名","tool_args":{},"predecessors":[]}]}
不得执行工具，不得添加 Markdown，不得添加未知字段。"""
SAFE_CONTEXT_KEYS = {"scenario", "user_role", "input_risk", "document_attached"}


def _run_chat(gateway: ModelGateway, request: ModelRequest, context: ModelCallContext):
    coroutine = gateway.chat(request, context)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="model-gateway-planner") as pool:
        return pool.submit(asyncio.run, coroutine).result()


class ModelGatewayPlanner:
    planner_type = "model_gateway"

    def __init__(self, gateway: ModelGateway = DEFAULT_MODEL_GATEWAY, *, provider_id: str | None = None) -> None:
        self.gateway = gateway
        self.provider_id = provider_id

    def plan(self, task: str, context: dict[str, Any]) -> AgentPlan:
        safe_context = {key: context[key] for key in SAFE_CONTEXT_KEYS if key in context}
        trace_id = context.get("trace_id")
        tenant_id = context.get("tenant_id", "demo-government")
        actor_id = context.get("user_id", "model-gateway-planner")
        if not isinstance(trace_id, str) or not trace_id:
            trace_id = create_trace(
                task,
                "model_planning",
                tenant_id=str(tenant_id),
                user_id=str(actor_id),
                agent_id="model-gateway-planner",
            )
        user_payload = json.dumps(
            {"task": task, "context": safe_context}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        request = ModelRequest(
            messages=[
                ModelMessage(role="system", content=SYSTEM_PROMPT),
                ModelMessage(role="user", content=user_payload),
            ],
            task_type="tool_planning",
            requested_provider=self.provider_id,
            max_output_tokens=2048,
            temperature=0.0,
            required_capabilities=frozenset(
                {ModelCapability.STRUCTURED_OUTPUT, ModelCapability.TOOL_PLANNING}
            ),
            cache_enabled=True,
        )
        try:
            response = _run_chat(
                self.gateway,
                request,
                ModelCallContext(trace_id=trace_id, tenant_id=str(tenant_id), actor_id=str(actor_id)),
            )
            payload = json.loads(response.content)
        except (SafeAgentError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise PlanningError("Model Gateway 不可用或返回了无效规划 JSON") from exc
        raw_hash = hashlib.sha256(response.content.encode("utf-8")).hexdigest()
        plan = validate_plan_payload(
            task,
            payload,
            planner_type=self.planner_type,
            model_name=f"{response.provider_id}/{response.model}",
            raw_response_hash=raw_hash,
        )
        warnings = ["model_output_untrusted_and_schema_validated"]
        fallback_from = ",".join(response.fallback_from) or None
        return plan.model_copy(update={"fallback_from": fallback_from, "warnings": warnings})
