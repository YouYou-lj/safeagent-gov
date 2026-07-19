"""Dify workflow adapter used only as an untrusted plan provider."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from agent_demo.planners.tool_schemas import tool_schema_catalog
from agent_demo.planners.validation import validate_plan_payload
from safeagent_gov.contracts import AgentPlan
from safeagent_gov.errors import PlannerTransportError, PlanningError

Transport = Callable[[str, dict[str, str], bytes, float], bytes]
MAX_RESPONSE_BYTES = 1_000_000


def validate_dify_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").casefold()
    if not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise PlanningError("Dify endpoint 格式无效")
    loopback = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise PlanningError("Dify endpoint 仅允许 HTTPS 或本机环回 HTTP")
    if not parsed.path.endswith("/v1/workflows/run"):
        raise PlanningError("Dify endpoint 必须指向 /v1/workflows/run")
    return endpoint


def _http_transport(endpoint: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
    request = Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-validated endpoint.
            declared_length = int(response.headers.get("Content-Length", "0") or "0")
            if declared_length > MAX_RESPONSE_BYTES:
                raise PlanningError("Dify 响应超过 1 MB")
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        if exc.code == 429 or exc.code >= 500:
            raise PlannerTransportError(f"Dify 工作流暂时失败: HTTP {exc.code}") from exc
        raise PlanningError(f"Dify 工作流被拒绝: HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise PlannerTransportError(f"Dify 工作流请求失败: {type(exc).__name__}") from exc
    if len(payload) > MAX_RESPONSE_BYTES:
        raise PlanningError("Dify 响应超过 1 MB")
    return payload


class DifyWorkflowPlanner:
    """Call a blocking Dify workflow and validate its output as AgentPlan."""

    planner_type = "dify"

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        workflow_name: str = "safeagent-planner",
        timeout_seconds: float = 20.0,
        transport: Transport | None = None,
    ) -> None:
        self.endpoint = validate_dify_endpoint(endpoint)
        if not api_key or len(api_key) > 8192:
            raise PlanningError("Dify API key 未配置或长度无效")
        if not workflow_name or len(workflow_name) > 160:
            raise PlanningError("Dify workflow_name 未配置或长度无效")
        if timeout_seconds <= 0 or timeout_seconds > 60:
            raise PlanningError("Dify timeout 必须在 0—60 秒之间")
        self.api_key = api_key
        self.workflow_name = workflow_name
        self.timeout_seconds = timeout_seconds
        self.transport = transport or _http_transport

    def plan(self, task: str, context: dict[str, Any]) -> AgentPlan:
        safe_context = {
            "scenario": str(context.get("scenario", ""))[:160],
            "user_role": str(context.get("user_role", "staff"))[:80],
            "input_risk": {
                key: context.get("input_risk", {}).get(key)
                for key in ("risk_type", "risk_level", "action")
            },
            "document_attached": bool(context.get("document_attached")),
        }
        request_payload = {
            "inputs": {
                "task": task[:50_000],
                "safeagent_context_json": json.dumps(safe_context, ensure_ascii=False, separators=(",", ":")),
                "safeagent_tool_schemas_json": json.dumps(
                    tool_schema_catalog(), ensure_ascii=False, separators=(",", ":")
                ),
            },
            "response_mode": "blocking",
            "user": "safeagent-gov-planner",
        }
        raw = self.transport(
            self.endpoint,
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            self.timeout_seconds,
        )
        if len(raw) > MAX_RESPONSE_BYTES:
            raise PlanningError("Dify 响应超过 1 MB")
        raw_hash = hashlib.sha256(raw).hexdigest()
        try:
            response = json.loads(raw.decode("utf-8"))
            outputs = response["data"]["outputs"]
            plan_value = outputs["plan"] if "plan" in outputs else outputs
            payload = json.loads(plan_value) if isinstance(plan_value, str) else plan_value
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise PlanningError("Dify 响应不符合 blocking workflow 契约") from exc
        return validate_plan_payload(
            task,
            payload,
            planner_type=self.planner_type,
            model_name=self.workflow_name,
            raw_response_hash=raw_hash,
        )
