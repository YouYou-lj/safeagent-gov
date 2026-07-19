"""Explicit protocol adapters and bounded HTTP transport for Model Gateway."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from safeagent_gov.errors import (
    ModelProviderResponseError,
    ModelProviderTransportError,
    ModelProviderUnavailableError,
)
from safeagent_gov.planning import infer_deterministic_plan_payload

from .contracts import (
    MessageRole,
    ModelCapability,
    ModelRequest,
    ProviderDefinition,
    ProviderProtocol,
    ProviderResult,
)

MAX_PROVIDER_RESPONSE_BYTES = 4 * 1024 * 1024


class ProviderTransport(Protocol):
    async def send(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]: ...


class ModelProvider(Protocol):
    async def generate(self, request: ModelRequest, definition: ProviderDefinition) -> ProviderResult: ...


class UrllibJSONTransport:
    """Dependency-free JSON POST transport with a fixed response-size ceiling."""

    async def send(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        return await asyncio.to_thread(self._send_sync, endpoint, headers, payload, timeout_seconds)

    @staticmethod
    def _send_sync(
        endpoint: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json", **dict(headers)},
            method="POST",
        )
        try:
            opener = build_opener(_RejectRedirects())
            with opener.open(request, timeout=timeout_seconds) as response:  # noqa: S310 - endpoint is validated
                declared = int(response.headers.get("Content-Length", "0") or "0")
                if declared > MAX_PROVIDER_RESPONSE_BYTES:
                    raise ModelProviderResponseError("Provider 响应超过大小上限")
                raw = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            if exc.code == 429 or exc.code in {408, 425} or exc.code >= 500:
                raise ModelProviderTransportError(f"Provider HTTP 暂态错误: {exc.code}") from exc
            raise ModelProviderResponseError(f"Provider HTTP 拒绝请求: {exc.code}") from exc
        except (TimeoutError, URLError, OSError) as exc:
            raise ModelProviderTransportError("Provider 网络连接或超时失败") from exc
        if len(raw) > MAX_PROVIDER_RESPONSE_BYTES:
            raise ModelProviderResponseError("Provider 响应超过大小上限")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ModelProviderResponseError("Provider 返回的不是有效 JSON") from exc
        if not isinstance(decoded, dict):
            raise ModelProviderResponseError("Provider JSON 根节点必须是对象")
        return decoded


def _messages(request: ModelRequest) -> list[dict[str, str]]:
    return [{"role": message.role.value, "content": message.content} for message in request.messages]


def _google_contents(request: ModelRequest) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    contents: list[dict[str, Any]] = []
    system_parts: list[dict[str, str]] = []
    for message in request.messages:
        if message.role == MessageRole.SYSTEM:
            system_parts.append({"text": message.content})
        else:
            contents.append(
                {
                    "role": "model" if message.role == MessageRole.ASSISTANT else "user",
                    "parts": [{"text": message.content}],
                }
            )
    system = {"parts": system_parts} if system_parts else None
    return contents, system


def build_provider_payload(definition: ProviderDefinition, request: ModelRequest) -> dict[str, Any]:
    protocol = definition.protocol
    if protocol in {ProviderProtocol.OPENAI_CHAT, ProviderProtocol.VLLM_OPENAI, ProviderProtocol.AZURE_OPENAI}:
        return {
            "model": definition.model,
            "messages": _messages(request),
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
        }
    if protocol == ProviderProtocol.OPENAI_RESPONSES:
        return {
            "model": definition.model,
            "input": _messages(request),
            "max_output_tokens": request.max_output_tokens,
            "temperature": request.temperature,
        }
    if protocol in {ProviderProtocol.ANTHROPIC_MESSAGES, ProviderProtocol.AWS_BEDROCK}:
        systems = [message.content for message in request.messages if message.role == MessageRole.SYSTEM]
        payload: dict[str, Any] = {
            "model": definition.model,
            "messages": [item for item in _messages(request) if item["role"] != "system"],
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
        }
        if systems:
            payload["system"] = "\n".join(systems)
        if protocol == ProviderProtocol.AWS_BEDROCK:
            payload["anthropic_version"] = "bedrock-2023-05-31"
        return payload
    if protocol in {ProviderProtocol.GEMINI_GENERATE_CONTENT, ProviderProtocol.VERTEX_AI}:
        contents, system = _google_contents(request)
        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": request.max_output_tokens,
                "temperature": request.temperature,
            },
        }
        if system:
            payload["systemInstruction"] = system
        return payload
    if protocol == ProviderProtocol.OLLAMA_CHAT:
        return {
            "model": definition.model,
            "messages": _messages(request),
            "stream": False,
            "options": {"temperature": request.temperature, "num_predict": request.max_output_tokens},
        }
    raise ModelProviderResponseError(f"没有可用的协议序列化器: {protocol.value}")


def _integer(mapping: Mapping[str, Any], key: str) -> int:
    value = mapping.get(key, 0)
    return value if isinstance(value, int) and value >= 0 else 0


def _text_parts(parts: Any) -> str:
    if not isinstance(parts, list):
        raise ModelProviderResponseError("Provider 文本分片不是数组")
    text = "".join(
        str(part.get("text", ""))
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text", ""), str)
    )
    if not text:
        raise ModelProviderResponseError("Provider 响应缺少文本内容")
    return text


def parse_provider_response(protocol: ProviderProtocol, payload: Mapping[str, Any]) -> ProviderResult:
    try:
        if protocol in {ProviderProtocol.OPENAI_CHAT, ProviderProtocol.VLLM_OPENAI, ProviderProtocol.AZURE_OPENAI}:
            choices = payload["choices"]
            first = choices[0]
            content = first["message"]["content"]
            usage = payload.get("usage", {})
            if not isinstance(content, str) or not isinstance(usage, dict):
                raise TypeError
            return ProviderResult(
                content=content,
                finish_reason=str(first.get("finish_reason", "stop")),
                prompt_tokens=_integer(usage, "prompt_tokens"),
                completion_tokens=_integer(usage, "completion_tokens"),
            )
        if protocol == ProviderProtocol.OPENAI_RESPONSES:
            content = payload.get("output_text")
            if not isinstance(content, str) or not content:
                output = payload["output"]
                content = _text_parts(output[0]["content"])
            usage = payload.get("usage", {})
            if not isinstance(usage, dict):
                raise TypeError
            return ProviderResult(
                content=content,
                finish_reason=str(payload.get("status", "completed")),
                prompt_tokens=_integer(usage, "input_tokens"),
                completion_tokens=_integer(usage, "output_tokens"),
            )
        if protocol in {ProviderProtocol.ANTHROPIC_MESSAGES, ProviderProtocol.AWS_BEDROCK}:
            usage = payload.get("usage", {})
            if not isinstance(usage, dict):
                raise TypeError
            return ProviderResult(
                content=_text_parts(payload["content"]),
                finish_reason=str(payload.get("stop_reason", "end_turn")),
                prompt_tokens=_integer(usage, "input_tokens"),
                completion_tokens=_integer(usage, "output_tokens"),
            )
        if protocol in {ProviderProtocol.GEMINI_GENERATE_CONTENT, ProviderProtocol.VERTEX_AI}:
            candidate = payload["candidates"][0]
            usage = payload.get("usageMetadata", {})
            if not isinstance(usage, dict):
                raise TypeError
            return ProviderResult(
                content=_text_parts(candidate["content"]["parts"]),
                finish_reason=str(candidate.get("finishReason", "STOP")),
                prompt_tokens=_integer(usage, "promptTokenCount"),
                completion_tokens=_integer(usage, "candidatesTokenCount"),
            )
        if protocol == ProviderProtocol.OLLAMA_CHAT:
            content = payload["message"]["content"]
            if not isinstance(content, str):
                raise TypeError
            return ProviderResult(
                content=content,
                finish_reason=str(payload.get("done_reason", "stop")),
                prompt_tokens=_integer(payload, "prompt_eval_count"),
                completion_tokens=_integer(payload, "eval_count"),
            )
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelProviderResponseError(f"{protocol.value} 响应不符合归一化契约") from exc
    raise ModelProviderResponseError(f"没有可用的协议解析器: {protocol.value}")


class _RejectRedirects(HTTPRedirectHandler):
    """Model API calls never follow redirects across the endpoint trust boundary."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


def _auth_headers(
    definition: ProviderDefinition,
    credential_override: str | None = None,
) -> dict[str, str]:
    credential = credential_override
    if definition.credential_env and credential is None:
        credential = os.getenv(definition.credential_env)
        if not credential:
            raise ModelProviderUnavailableError(f"Provider {definition.provider_id} 缺少运行时凭据")
    if definition.protocol == ProviderProtocol.ANTHROPIC_MESSAGES:
        return {"x-api-key": credential or "", "anthropic-version": "2023-06-01"}
    if definition.protocol == ProviderProtocol.GEMINI_GENERATE_CONTENT:
        return {"x-goog-api-key": credential or ""}
    if definition.protocol == ProviderProtocol.AZURE_OPENAI:
        return {"api-key": credential or ""}
    if definition.protocol in {
        ProviderProtocol.OPENAI_CHAT,
        ProviderProtocol.OPENAI_RESPONSES,
        ProviderProtocol.VLLM_OPENAI,
    }:
        return {"Authorization": f"Bearer {credential}"} if credential else {}
    if definition.protocol in {ProviderProtocol.AWS_BEDROCK, ProviderProtocol.VERTEX_AI}:
        return {"Authorization": f"Bearer {credential}"} if credential else {}
    return {}


class ProtocolProvider:
    def __init__(
        self,
        transport: ProviderTransport | None = None,
        *,
        credential_override: str | None = None,
    ) -> None:
        self.transport = transport or UrllibJSONTransport()
        self._credential_override = credential_override

    async def generate(self, request: ModelRequest, definition: ProviderDefinition) -> ProviderResult:
        if not definition.endpoint:
            raise ModelProviderUnavailableError(f"Provider {definition.provider_id} 没有网络端点")
        payload = build_provider_payload(definition, request)
        response = await self.transport.send(
            definition.endpoint,
            _auth_headers(definition, self._credential_override),
            payload,
            definition.timeout_seconds,
        )
        return parse_provider_response(definition.protocol, response)


class DeterministicProvider:
    """Offline baseline for reproducible tests and disconnected deployments."""

    async def generate(self, request: ModelRequest, definition: ProviderDefinition) -> ProviderResult:
        user_text = next(
            message.content for message in reversed(request.messages) if message.role == MessageRole.USER
        )
        excerpt = user_text[:240]
        if request.task_type == "tool_planning":
            try:
                planning_input = json.loads(user_text)
            except json.JSONDecodeError:
                planning_input = {}
            task = planning_input.get("task") if isinstance(planning_input, dict) else None
            content = json.dumps(
                infer_deterministic_plan_payload(task if isinstance(task, str) else user_text),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        elif ModelCapability.STRUCTURED_OUTPUT in request.required_capabilities:
            content = json.dumps(
                {"status": "offline_baseline", "summary": excerpt}, ensure_ascii=False, separators=(",", ":")
            )
        else:
            content = f"离线确定性模型已安全接收任务：{excerpt}"
        return ProviderResult(
            content=content,
            finish_reason="deterministic",
            prompt_tokens=max(1, sum(len(message.content) for message in request.messages) // 4),
            completion_tokens=max(1, len(content) // 4),
        )
