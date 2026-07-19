"""Strict adapter for a vendor-neutral, planning-only external Agent service."""

from __future__ import annotations

import hashlib
import json
import secrets
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
PROTOCOL_VERSION = "1.0.0"


def validate_external_agent_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").casefold()
    if not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise PlanningError("外部 Agent endpoint 格式无效")
    loopback = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise PlanningError("外部 Agent endpoint 仅允许 HTTPS 或本机环回 HTTP")
    if parsed.path != "/v1/agent/plan":
        raise PlanningError("外部 Agent endpoint 必须指向 /v1/agent/plan")
    return endpoint


def _http_transport(endpoint: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
    request = Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-validated endpoint.
            declared_length = int(response.headers.get("Content-Length", "0") or "0")
            if declared_length > MAX_RESPONSE_BYTES:
                raise PlanningError("外部 Agent 响应超过 1 MB")
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        status = exc.code
        exc.close()
        if status == 429 or status >= 500:
            raise PlannerTransportError(f"外部 Agent 暂时失败: HTTP {status}") from exc
        raise PlanningError(f"外部 Agent 请求被拒绝: HTTP {status}") from exc
    except (URLError, TimeoutError) as exc:
        raise PlannerTransportError(f"外部 Agent 请求失败: {type(exc).__name__}") from exc
    if len(payload) > MAX_RESPONSE_BYTES:
        raise PlanningError("外部 Agent 响应超过 1 MB")
    return payload


class ExternalAgentPlanner:
    """Treat a remote tool-capable Agent as an untrusted plan provider only."""

    planner_type = "external_agent"

    def __init__(
        self,
        *,
        endpoint: str,
        token: str,
        expected_agent_name: str,
        timeout_seconds: float = 15.0,
        transport: Transport | None = None,
    ) -> None:
        self.endpoint = validate_external_agent_endpoint(endpoint)
        if len(token) < 16 or len(token) > 8192:
            raise PlanningError("外部 Agent token 未配置或长度无效")
        if not expected_agent_name or len(expected_agent_name) > 160:
            raise PlanningError("外部 Agent name 未配置或长度无效")
        if timeout_seconds <= 0 or timeout_seconds > 60:
            raise PlanningError("外部 Agent timeout 必须在 0—60 秒之间")
        self.token = token
        self.expected_agent_name = expected_agent_name
        self.timeout_seconds = timeout_seconds
        self.transport = transport or _http_transport

    def plan(self, task: str, context: dict[str, Any]) -> AgentPlan:
        request_id = f"PLANREQ-{secrets.token_hex(8).upper()}"
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
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "task": task[:50_000],
            "context": safe_context,
            "tool_schemas": tool_schema_catalog(),
        }
        raw = self.transport(
            self.endpoint,
            {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            self.timeout_seconds,
        )
        if len(raw) > MAX_RESPONSE_BYTES:
            raise PlanningError("外部 Agent 响应超过 1 MB")
        raw_hash = hashlib.sha256(raw).hexdigest()
        try:
            response = json.loads(raw.decode("utf-8"))
            if set(response) != {"protocol_version", "request_id", "agent", "plan"}:
                raise PlanningError("外部 Agent 响应包含未知字段")
            if response["protocol_version"] != PROTOCOL_VERSION or response["request_id"] != request_id:
                raise PlanningError("外部 Agent 协议版本或 request_id 不匹配")
            agent = response["agent"]
            if set(agent) != {"name", "version", "execution_authority"}:
                raise PlanningError("外部 Agent 身份字段无效")
            if agent["name"] != self.expected_agent_name or agent["execution_authority"] is not False:
                raise PlanningError("外部 Agent 身份不匹配或声明了执行权限")
            version = str(agent["version"])
            if not version or len(version) > 80:
                raise PlanningError("外部 Agent 版本无效")
            payload = response["plan"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise PlanningError("外部 Agent 响应不符合 planning-only 契约") from exc
        return validate_plan_payload(
            task,
            payload,
            planner_type=self.planner_type,
            model_name=f"{self.expected_agent_name}@{version}",
            raw_response_hash=raw_hash,
        )
