"""Authenticated control plane and chat endpoint for Model Gateway."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from backend.auth import enforce_tenant, require_roles
from safeagent_gov.audit import create_trace, get_trace_identity, log_event
from safeagent_gov.auth import AuthClaims
from safeagent_gov.errors import (
    ModelGatewayBudgetError,
    ModelGatewayConfigurationError,
    ModelGatewayInputError,
    ModelProviderError,
    ModelProviderUnavailableError,
    UnknownTraceError,
)
from safeagent_gov.input_security import detect_input_risk
from safeagent_gov.model_gateway import (
    DataClassification,
    GatewayMetricsSnapshot,
    MemoryModelRegistry,
    ModelCallContext,
    ModelCapability,
    ModelGatewayConfig,
    ModelMessage,
    ModelRegistry,
    ModelRegistrySnapshot,
    ModelRequest,
    ModelResponse,
    ProviderDefinition,
    ProviderProtocol,
    RoutingRule,
)
from safeagent_gov.model_gateway.defaults import DEFAULT_MODEL_GATEWAY, DEFAULT_MODEL_REGISTRY
from safeagent_gov.model_gateway.providers import ProtocolProvider, ProviderTransport, UrllibJSONTransport
from safeagent_gov.model_gateway.service import ModelGateway

router = APIRouter(prefix="/api/model", tags=["Model Gateway"])
CHAT_ROLES = ("admin", "manager", "staff", "operator", "visitor", "security_reviewer", "reviewer")


class ModelChatAPIRequest(ModelRequest):
    trace_id: str | None = Field(default=None, min_length=1, max_length=160)


EphemeralProviderKind = Literal[
    "openai",
    "openai-responses",
    "anthropic",
    "gemini",
    "azure-openai",
    "aws-bedrock",
    "vertex-ai",
    "deepseek",
    "qwen",
    "kimi",
    "ollama",
    "vllm",
]


class EphemeralProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: EphemeralProviderKind
    model: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:/-]+$")
    endpoint: str | None = Field(default=None, min_length=1, max_length=1000)
    api_key: SecretStr | None = None
    timeout_seconds: float = Field(default=15.0, ge=1.0, le=30.0)


class EphemeralConnectionRequest(EphemeralProviderRequest):
    pass


class EphemeralChatRequest(EphemeralProviderRequest):
    messages: list[ModelMessage] = Field(min_length=1, max_length=32)
    max_output_tokens: int = Field(default=512, ge=1, le=4096)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    data_classification: DataClassification = DataClassification.INTERNAL


PROVIDER_SETTINGS: dict[str, tuple[ProviderProtocol, str | None, bool, bool]] = {
    "openai": (ProviderProtocol.OPENAI_CHAT, "https://api.openai.com/v1/chat/completions", False, True),
    "openai-responses": (ProviderProtocol.OPENAI_RESPONSES, "https://api.openai.com/v1/responses", False, True),
    "anthropic": (ProviderProtocol.ANTHROPIC_MESSAGES, "https://api.anthropic.com/v1/messages", False, True),
    "gemini": (ProviderProtocol.GEMINI_GENERATE_CONTENT, None, False, True),
    "azure-openai": (ProviderProtocol.AZURE_OPENAI, None, True, True),
    "aws-bedrock": (ProviderProtocol.AWS_BEDROCK, None, True, True),
    "vertex-ai": (ProviderProtocol.VERTEX_AI, None, True, True),
    "deepseek": (ProviderProtocol.OPENAI_CHAT, "https://api.deepseek.com/chat/completions", False, True),
    "qwen": (ProviderProtocol.OPENAI_CHAT, "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", False, True),
    "kimi": (ProviderProtocol.OPENAI_CHAT, "https://api.moonshot.cn/v1/chat/completions", False, True),
    "ollama": (ProviderProtocol.OLLAMA_CHAT, "http://127.0.0.1:11434/api/chat", True, False),
    "vllm": (ProviderProtocol.VLLM_OPENAI, "http://127.0.0.1:8000/v1/chat/completions", True, False),
}


def get_ephemeral_transport() -> ProviderTransport:
    return UrllibJSONTransport()


def _allowed_endpoint(provider: str, endpoint: str) -> bool:
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError:
        return False
    if parsed.username or parsed.password or parsed.fragment or not parsed.hostname:
        return False
    host = parsed.hostname.casefold()
    path = parsed.path
    if provider in {"ollama", "vllm"}:
        expected_path = "/api/chat" if provider == "ollama" else "/v1/chat/completions"
        return parsed.scheme in {"http", "https"} and host in {"127.0.0.1", "localhost", "::1"} and path == expected_path
    if parsed.scheme != "https" or port not in {None, 443}:
        return False
    checks = {
        "openai": host == "api.openai.com" and path == "/v1/chat/completions",
        "openai-responses": host == "api.openai.com" and path == "/v1/responses",
        "anthropic": host == "api.anthropic.com" and path == "/v1/messages",
        "gemini": host == "generativelanguage.googleapis.com" and bool(re.fullmatch(r"/v1(?:beta)?/models/[^/]+:generateContent", path)),
        "azure-openai": host.endswith(".openai.azure.com") and "/openai/deployments/" in path and path.endswith("/chat/completions"),
        "aws-bedrock": bool(re.fullmatch(r"bedrock-runtime\.[a-z0-9-]+\.amazonaws\.com", host)) and path.startswith("/model/") and path.endswith("/invoke"),
        "vertex-ai": bool(re.fullmatch(r"[a-z0-9-]+-aiplatform\.googleapis\.com", host)) and path.startswith("/v1/projects/") and path.endswith(":generateContent"),
        "deepseek": host == "api.deepseek.com" and path in {"/chat/completions", "/v1/chat/completions"},
        "qwen": host == "dashscope.aliyuncs.com" and path == "/compatible-mode/v1/chat/completions",
        "kimi": host == "api.moonshot.cn" and path == "/v1/chat/completions",
    }
    return checks.get(provider, False)


def _ephemeral_definition(request: EphemeralProviderRequest) -> tuple[ProviderDefinition, str | None]:
    protocol, default_endpoint, private_deployment, requires_key = PROVIDER_SETTINGS[request.provider]
    endpoint = request.endpoint or default_endpoint
    if endpoint is None and request.provider == "gemini":
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{request.model}:generateContent"
    if endpoint is None or not _allowed_endpoint(request.provider, endpoint):
        raise ModelGatewayInputError("临时 Provider endpoint 不在允许的厂商 API 或本机回环范围内")
    credential = request.api_key.get_secret_value() if request.api_key else None
    if requires_key and not credential:
        raise ModelGatewayInputError("该临时 Provider 必须提供仅用于本次请求的 API Key")
    provider_id = f"session-{request.provider}"
    return (
        ProviderDefinition(
            provider_id=provider_id,
            display_name=f"Temporary {request.provider}",
            protocol=protocol,
            model=request.model,
            endpoint=endpoint,
            credential_env="SAFEAGENT_EPHEMERAL_API_KEY" if credential else None,
            enabled=True,
            network_access=True,
            private_deployment=private_deployment,
            capabilities=frozenset({ModelCapability.CHAT}),
            task_types=frozenset({"connection_test", "interactive_chat"}),
            max_context_tokens=200_000,
            max_output_tokens=4096,
            timeout_seconds=request.timeout_seconds,
            max_attempts=1,
            circuit_failure_threshold=1,
            circuit_recovery_seconds=30.0,
        ),
        credential,
    )


async def _ephemeral_call(
    config_request: EphemeralProviderRequest,
    model_request: ModelRequest,
    principal: AuthClaims,
    transport: ProviderTransport,
    mode: str,
) -> dict:
    definition, credential = _ephemeral_definition(config_request)
    if model_request.data_classification in {DataClassification.CONFIDENTIAL, DataClassification.RESTRICTED} and not definition.private_deployment:
        raise ModelGatewayInputError("机密或受限数据只能发送到本机或组织私有 Provider")
    registry = MemoryModelRegistry(
        ModelGatewayConfig(
            version="1.0.0",
            default_provider=definition.provider_id,
            max_concurrency=1,
            cache_ttl_seconds=0,
            max_cache_entries=0,
            server_max_cost_usd=0.0,
            providers={definition.provider_id: definition},
            routing_rules={
                model_request.task_type: RoutingRule(
                    candidates=(definition.provider_id,),
                    required_capabilities=frozenset({ModelCapability.CHAT}),
                    private_only=False,
                )
            },
        )
    )
    trace_id = create_trace(
        "临时模型连接测试" if mode == "connection" else "临时模型受治理会话",
        "ephemeral_model_session",
        context={
            "mode": mode,
            "provider": config_request.provider,
            "model": config_request.model,
            "data_classification": model_request.data_classification.value,
        },
        tenant_id=principal.tenant_id,
        user_id=principal.sub,
        agent_id="ephemeral-model-api",
    )
    gateway = ModelGateway(
        registry,
        protocol_provider=ProtocolProvider(transport=transport, credential_override=credential),
    )
    input_text = "\n".join(message.content for message in model_request.messages)
    input_risk = detect_input_risk(input_text, source="user_input")
    try:
        response = await gateway.chat(
            model_request,
            ModelCallContext(trace_id=trace_id, tenant_id=principal.tenant_id, actor_id=principal.sub),
        )
    except (ModelGatewayInputError, ModelGatewayBudgetError, ModelProviderUnavailableError, ModelProviderError) as exc:
        log_event(
            trace_id,
            "final_output",
            {"status": "blocked", "error_code": type(exc).__name__, "mode": mode},
            actor_id=principal.sub,
        )
        raise
    output_risk = detect_input_risk(response.content, source="rag_result")
    log_event(
        trace_id,
        "final_output",
        {
            "status": response.status,
            "provider_id": response.provider_id,
            "mode": mode,
            "output_trusted": False,
            "output_risk_level": output_risk["risk_level"],
        },
        actor_id=principal.sub,
    )
    return {
        "trace_id": trace_id,
        "mode": mode,
        "provider": config_request.provider,
        "endpoint_host": urlsplit(definition.endpoint or "").hostname,
        "input_risk": input_risk,
        "output_risk": output_risk,
        "response": response,
        "credential_persisted": False,
        "output_trusted": False,
    }


def _ephemeral_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ModelGatewayInputError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, ModelGatewayBudgetError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


def get_model_registry() -> ModelRegistry:
    return DEFAULT_MODEL_REGISTRY


def get_model_gateway() -> ModelGateway:
    return DEFAULT_MODEL_GATEWAY


@router.post("/test-connection")
async def test_ephemeral_connection(
    request: EphemeralConnectionRequest,
    principal: AuthClaims = Depends(require_roles(*CHAT_ROLES)),
    transport: ProviderTransport = Depends(get_ephemeral_transport),
):
    provider_id = f"session-{request.provider}"
    normalized = ModelRequest(
        messages=[ModelMessage(role="user", content="Reply with OK only.")],
        task_type="connection_test",
        requested_provider=provider_id,
        max_output_tokens=16,
        temperature=0.0,
        required_capabilities=frozenset({ModelCapability.CHAT}),
        data_classification=DataClassification.PUBLIC,
        private_only=False,
        allow_fallback=False,
        cache_enabled=False,
        max_cost_usd=0.0,
    )
    try:
        return await _ephemeral_call(request, normalized, principal, transport, "connection")
    except (ModelGatewayInputError, ModelGatewayBudgetError, ModelProviderUnavailableError, ModelProviderError) as exc:
        raise _ephemeral_http_error(exc) from exc


@router.post("/session/chat")
async def ephemeral_chat(
    request: EphemeralChatRequest,
    principal: AuthClaims = Depends(require_roles(*CHAT_ROLES)),
    transport: ProviderTransport = Depends(get_ephemeral_transport),
):
    normalized = ModelRequest(
        messages=request.messages,
        task_type="interactive_chat",
        requested_provider=f"session-{request.provider}",
        max_output_tokens=request.max_output_tokens,
        temperature=request.temperature,
        required_capabilities=frozenset({ModelCapability.CHAT}),
        data_classification=request.data_classification,
        private_only=request.data_classification == DataClassification.RESTRICTED,
        allow_fallback=False,
        cache_enabled=False,
        max_cost_usd=0.0,
    )
    try:
        return await _ephemeral_call(request, normalized, principal, transport, "chat")
    except (ModelGatewayInputError, ModelGatewayBudgetError, ModelProviderUnavailableError, ModelProviderError) as exc:
        raise _ephemeral_http_error(exc) from exc


@router.get("/providers", response_model=ModelRegistrySnapshot)
def list_providers(
    _: AuthClaims = Depends(require_roles(*CHAT_ROLES)),
    registry: ModelRegistry = Depends(get_model_registry),
):
    return registry.snapshot()


@router.post("/providers/reload", response_model=ModelRegistrySnapshot)
def reload_providers(
    principal: AuthClaims = Depends(require_roles("admin", "security_reviewer")),
    registry: ModelRegistry = Depends(get_model_registry),
    gateway: ModelGateway = Depends(get_model_gateway),
):
    trace_id = create_trace(
        "重新加载 Model Gateway Registry",
        "model_gateway_control",
        tenant_id=principal.tenant_id,
        user_id=principal.sub,
        agent_id="model-gateway-api",
    )
    try:
        snapshot = registry.load()
        gateway.refresh()
    except (ModelGatewayConfigurationError, ModelProviderUnavailableError) as exc:
        log_event(
            trace_id,
            "final_output",
            {"status": "blocked", "error_code": type(exc).__name__},
            actor_id=principal.sub,
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    log_event(
        trace_id,
        "final_output",
        {
            "status": "registry_reloaded",
            "source_digest": snapshot.source_digest,
            "provider_count": snapshot.provider_count,
        },
        actor_id=principal.sub,
    )
    return snapshot


@router.post("/chat", response_model=ModelResponse)
async def chat(
    request: ModelChatAPIRequest,
    principal: AuthClaims = Depends(require_roles(*CHAT_ROLES)),
    gateway: ModelGateway = Depends(get_model_gateway),
):
    trace_id = request.trace_id
    if trace_id:
        try:
            identity = get_trace_identity(trace_id)
        except UnknownTraceError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="trace not found") from exc
        enforce_tenant(identity["tenant_id"], principal)
    else:
        trace_id = create_trace(
            "统一模型调用",
            "model_gateway",
            context={
                "task_type": request.task_type,
                "data_classification": request.data_classification.value,
            },
            tenant_id=principal.tenant_id,
            user_id=principal.sub,
            agent_id="model-gateway-api",
        )
    normalized = ModelRequest.model_validate(request.model_dump(exclude={"trace_id"}))
    try:
        response = await gateway.chat(
            normalized,
            ModelCallContext(
                trace_id=trace_id,
                tenant_id=principal.tenant_id,
                actor_id=principal.sub,
            ),
        )
    except ModelGatewayInputError as exc:
        log_event(trace_id, "final_output", {"status": "blocked", "error_code": type(exc).__name__})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ModelGatewayBudgetError as exc:
        log_event(trace_id, "final_output", {"status": "blocked", "error_code": type(exc).__name__})
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (ModelProviderUnavailableError, ModelProviderError) as exc:
        log_event(trace_id, "final_output", {"status": "blocked", "error_code": type(exc).__name__})
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    log_event(
        trace_id,
        "final_output",
        {
            "status": response.status,
            "request_id": response.request_id,
            "provider_id": response.provider_id,
            "output_hash_recorded": True,
        },
        actor_id=principal.sub,
    )
    return response


@router.get("/metrics", response_model=GatewayMetricsSnapshot)
def metrics(
    _: AuthClaims = Depends(require_roles("admin", "security_reviewer", "auditor")),
    gateway: ModelGateway = Depends(get_model_gateway),
):
    return gateway.metrics()
