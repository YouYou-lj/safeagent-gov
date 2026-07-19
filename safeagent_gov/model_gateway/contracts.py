"""Strict public contracts for the vendor-neutral model gateway."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProviderProtocol(str, Enum):
    INTERNAL = "internal"
    OPENAI_CHAT = "openai_chat_completions"
    OPENAI_RESPONSES = "openai_responses"
    ANTHROPIC_MESSAGES = "anthropic_messages"
    GEMINI_GENERATE_CONTENT = "gemini_generate_content"
    AZURE_OPENAI = "azure_openai"
    AWS_BEDROCK = "aws_bedrock"
    VERTEX_AI = "vertex_ai"
    OLLAMA_CHAT = "ollama_chat"
    VLLM_OPENAI = "vllm_openai_compatible"


class ModelCapability(str, Enum):
    CHAT = "chat"
    STRUCTURED_OUTPUT = "structured_output"
    LONG_CONTEXT = "long_context"
    TOOL_PLANNING = "tool_planning"
    CODE = "code"


class DataClassification(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ModelMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: MessageRole
    content: str = Field(min_length=1, max_length=200_000)


class ModelRequest(BaseModel):
    """Normalized request. Identity and trace ownership are supplied out of band."""

    model_config = ConfigDict(extra="forbid")

    messages: list[ModelMessage] = Field(min_length=1, max_length=128)
    task_type: str = Field(default="general", pattern=r"^[a-z][a-z0-9_]{1,63}$")
    requested_provider: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{1,79}$")
    max_output_tokens: int = Field(default=512, ge=1, le=32_768)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    required_capabilities: frozenset[ModelCapability] = Field(default_factory=frozenset)
    data_classification: DataClassification = DataClassification.INTERNAL
    private_only: bool = False
    allow_fallback: bool = True
    cache_enabled: bool = True
    max_cost_usd: float | None = Field(default=None, ge=0.0, le=100.0)

    @model_validator(mode="after")
    def validate_conversation(self) -> ModelRequest:
        if not any(message.role == MessageRole.USER for message in self.messages):
            raise ValueError("messages 至少包含一条 user 消息")
        return self


class ModelCallContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: str = Field(min_length=1, max_length=160)
    tenant_id: str = Field(min_length=1, max_length=120)
    actor_id: str = Field(min_length=1, max_length=120)


class ProviderDefinition(BaseModel):
    """Immutable, secret-free provider profile loaded from trusted YAML."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,79}$")
    display_name: str = Field(min_length=1, max_length=160)
    protocol: ProviderProtocol
    model: str = Field(min_length=1, max_length=200)
    endpoint: str | None = Field(default=None, max_length=1000)
    credential_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    enabled: bool = False
    network_access: bool = True
    private_deployment: bool = False
    capabilities: frozenset[ModelCapability] = Field(default_factory=lambda: frozenset({ModelCapability.CHAT}))
    task_types: frozenset[str] = Field(default_factory=lambda: frozenset({"general"}))
    max_context_tokens: int = Field(default=8192, ge=256, le=10_000_000)
    max_output_tokens: int = Field(default=4096, ge=1, le=1_000_000)
    prompt_cost_per_million_usd: float = Field(default=0.0, ge=0.0, le=10_000.0)
    completion_cost_per_million_usd: float = Field(default=0.0, ge=0.0, le=10_000.0)
    priority: int = Field(default=100, ge=0, le=10_000)
    timeout_seconds: float = Field(default=10.0, gt=0.0, le=300.0)
    max_attempts: int = Field(default=2, ge=1, le=3)
    circuit_failure_threshold: int = Field(default=3, ge=1, le=100)
    circuit_recovery_seconds: float = Field(default=30.0, gt=0.0, le=3600.0)

    @model_validator(mode="after")
    def validate_transport_boundary(self) -> ProviderDefinition:
        if self.protocol == ProviderProtocol.INTERNAL:
            if self.endpoint is not None or self.network_access or self.credential_env is not None:
                raise ValueError("internal Provider 不得配置网络端点或凭据")
            return self
        if not self.endpoint or not self.network_access:
            raise ValueError("远端 Provider 必须声明固定 endpoint 和 network_access")
        if self.endpoint.startswith("http://"):
            loopback = self.endpoint.startswith(("http://127.0.0.1:", "http://localhost:"))
            if not loopback or not self.private_deployment:
                raise ValueError("明文 HTTP 仅允许私有 loopback Provider")
        elif not self.endpoint.startswith("https://"):
            raise ValueError("Provider endpoint 仅允许 HTTPS 或私有 loopback HTTP")
        return self


class RoutingRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidates: tuple[str, ...] = Field(min_length=1, max_length=32)
    required_capabilities: frozenset[ModelCapability] = Field(default_factory=frozenset)
    private_only: bool = False
    max_latency_ms: int | None = Field(default=None, ge=1, le=300_000)


class ModelGatewayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    default_provider: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,79}$")
    max_concurrency: int = Field(default=32, ge=1, le=1000)
    cache_ttl_seconds: int = Field(default=300, ge=0, le=86_400)
    max_cache_entries: int = Field(default=512, ge=0, le=100_000)
    server_max_cost_usd: float = Field(default=1.0, ge=0.0, le=1000.0)
    providers: dict[str, ProviderDefinition] = Field(min_length=1, max_length=128)
    routing_rules: dict[str, RoutingRule] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> ModelGatewayConfig:
        if self.default_provider not in self.providers:
            raise ValueError("default_provider 不存在")
        for key, provider in self.providers.items():
            if key != provider.provider_id:
                raise ValueError(f"Provider key 与 provider_id 不一致: {key}")
        for task_type, rule in self.routing_rules.items():
            if not task_type or any(candidate not in self.providers for candidate in rule.candidates):
                raise ValueError(f"路由规则引用不存在的 Provider: {task_type}")
        return self


class ProviderRegistryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str
    display_name: str
    protocol: ProviderProtocol
    model: str
    enabled: bool
    private_deployment: bool
    capabilities: frozenset[ModelCapability]
    task_types: frozenset[str]
    max_context_tokens: int
    max_output_tokens: int


class ModelRegistrySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    default_provider: str
    provider_count: int
    enabled_count: int
    providers: tuple[ProviderRegistryRecord, ...]


class ProviderResult(BaseModel):
    """Normalized provider output; content remains untrusted data."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(max_length=1_000_000)
    finish_reason: str = Field(default="stop", min_length=1, max_length=80)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)


class ModelUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=160)
    trace_id: str = Field(min_length=1, max_length=160)
    status: str = Field(pattern=r"^(completed|fallback|cache_hit)$")
    provider_id: str
    model: str
    protocol: ProviderProtocol
    content: str
    finish_reason: str
    usage: ModelUsage
    estimated_cost_usd: float = Field(ge=0.0)
    latency_ms: float = Field(ge=0.0)
    attempts: int = Field(ge=0)
    fallback_from: tuple[str, ...] = ()
    cached: bool = False
    audit_complete: bool = True
    output_trusted: bool = False


class ProviderMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str
    calls: int
    successes: int
    failures: int
    circuit_state: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float


class GatewayMetricsSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_requests: int
    successful_requests: int
    failed_requests: int
    fallback_requests: int
    cache_hits: int
    active_requests: int
    max_observed_concurrency: int
    total_prompt_tokens: int
    total_completion_tokens: int
    estimated_cost_usd: float
    providers: tuple[ProviderMetric, ...]
