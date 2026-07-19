"""OpenAI-compatible structured planner with strict endpoint and output validation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from safeagent_gov.contracts import AgentPlan
from safeagent_gov.errors import PlannerTransportError, PlanningError

from .tool_schemas import tool_schema_catalog
from .validation import validate_plan_payload

Transport = Callable[[str, dict[str, str], bytes, float], bytes]
MAX_RESPONSE_BYTES = 1_000_000


def validate_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").casefold()
    if not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise PlanningError("LLM endpoint 格式无效")
    loopback = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise PlanningError("LLM endpoint 仅允许 HTTPS 或本机环回 HTTP")
    if not parsed.path.endswith("/chat/completions"):
        raise PlanningError("LLM endpoint 必须指向 /chat/completions")
    return endpoint


def _http_transport(endpoint: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
    request = Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - endpoint is operator-validated.
            declared_length = int(response.headers.get("Content-Length", "0") or "0")
            if declared_length > MAX_RESPONSE_BYTES:
                raise PlanningError("LLM 响应超过 1 MB")
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        if exc.code == 429 or exc.code >= 500:
            raise PlannerTransportError(f"LLM 规划请求暂时失败: HTTP {exc.code}") from exc
        raise PlanningError(f"LLM 规划请求被拒绝: HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise PlannerTransportError(f"LLM 规划请求失败: {type(exc).__name__}") from exc
    if len(payload) > MAX_RESPONSE_BYTES:
        raise PlanningError("LLM 响应超过 1 MB")
    return payload


class OpenAICompatiblePlanner:
    planner_type = "openai_compatible"

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 15.0,
        transport: Transport | None = None,
    ) -> None:
        self.endpoint = validate_endpoint(endpoint)
        if not api_key or len(api_key) > 8192:
            raise PlanningError("LLM API key 未配置或长度无效")
        if not model or len(model) > 160:
            raise PlanningError("LLM model 未配置或长度无效")
        if timeout_seconds <= 0 or timeout_seconds > 60:
            raise PlanningError("LLM timeout 必须在 0—60 秒之间")
        self.api_key = api_key
        self.model = model
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
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a planning component with no execution authority. Return only a JSON object "
                        "with keys summary and steps. Each step must contain step_index, tool_name, tool_args, "
                        "and predecessors. Never invent tools or fields. Empty steps are valid."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"task": task[:50_000], "context": safe_context, "tool_schemas": tool_schema_catalog()},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ],
        }
        raw = self.transport(
            self.endpoint,
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            self.timeout_seconds,
        )
        if len(raw) > MAX_RESPONSE_BYTES:
            raise PlanningError("LLM 响应超过 1 MB")
        raw_hash = hashlib.sha256(raw).hexdigest()
        try:
            response = json.loads(raw.decode("utf-8"))
            content = response["choices"][0]["message"]["content"]
            payload = json.loads(content) if isinstance(content, str) else content
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise PlanningError("LLM 响应不符合 OpenAI JSON 契约") from exc
        return validate_plan_payload(
            task,
            payload,
            planner_type=self.planner_type,
            model_name=self.model,
            raw_response_hash=raw_hash,
        )
