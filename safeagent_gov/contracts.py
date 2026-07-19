"""Versioned cross-module security contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Decision(str, Enum):
    ALLOW = "allow"
    ALLOW_WITH_LOG = "allow_with_log"
    MASK_AND_ALLOW = "mask_and_allow"
    REQUIRE_APPROVAL = "require_approval"
    BLOCK = "block"


class RiskLevel(str, Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SourceType(str, Enum):
    USER_INPUT = "user_input"
    WEB_PAGE = "web_page"
    UPLOADED_PDF = "uploaded_pdf"
    UPLOADED_DOC = "uploaded_doc"
    RAG_RESULT = "rag_result"
    HISTORY_MEMORY = "history_memory"


class SourceEnvelope(BaseModel):
    """Normalized provenance envelope for one untrusted input source."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=160)
    source_type: SourceType
    origin: str = Field(min_length=1, max_length=2048)
    trust_score: float = Field(ge=0.0, le=1.0)
    content: str = Field(max_length=1_000_000)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_content: str = Field(max_length=1_000_000)
    normalized_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalization_flags: list[str] = Field(default_factory=list)
    session_id: str | None = Field(default=None, max_length=160)
    parent_source_id: str | None = Field(default=None, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContentChunk(BaseModel):
    """Stable, offset-preserving chunk derived from a source envelope."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1, max_length=180)
    source_id: str
    source_type: SourceType
    index: int = Field(ge=0)
    text: str
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    trust_score: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TextSourceInput(BaseModel):
    """Strict serialized text source accepted by the PromptShield runtime bundle."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=1_000_000)
    source: SourceType
    origin: str | None = Field(default=None, max_length=2048)
    trust_score: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalStatus(str, Enum):
    REQUESTED = "requested"
    APPROVED = "approved"
    MASKED_AND_APPROVED = "masked_and_approved"
    DENIED = "denied"
    EXPIRED = "expired"
    REVOKED = "revoked"
    CONSUMED = "consumed"


class DataLabel(str, Enum):
    """Ordered data sensitivity labels propagated across Agent/tool steps."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
    CREDENTIAL = "credential"


class PrincipalIdentity(BaseModel):
    """Tenant-scoped user or Agent identity used by gateway authorization."""

    model_config = ConfigDict(extra="forbid")

    principal_id: str = Field(min_length=1, max_length=160)
    principal_type: Literal["user", "agent", "service"]
    role: str = Field(min_length=1, max_length=80)
    tenant_id: str = Field(default="default", min_length=1, max_length=160)
    attributes: dict[str, str] = Field(default_factory=dict)


class InputReference(BaseModel):
    """Minimal provenance reference attached to a tool request."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=180)
    source_type: SourceType
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    trust_score: float = Field(default=0.5, ge=0.0, le=1.0)
    data_labels: list[DataLabel] = Field(default_factory=list)


class PlannedToolStep(BaseModel):
    """One immutable tool intent in an Agent task graph."""

    model_config = ConfigDict(extra="forbid")

    step_index: int = Field(ge=1)
    tool_name: str = Field(min_length=1, max_length=120)
    args_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    predecessors: list[int] = Field(default_factory=list)
    max_calls: int = Field(default=1, ge=1, le=100)


class TaskGraph(BaseModel):
    """Declared execution graph used to detect plan mutation and loops."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=1, max_length=160)
    steps: list[PlannedToolStep] = Field(min_length=1, max_length=200)


class ProposedToolCall(BaseModel):
    """Untrusted planner output before task-graph and gateway authorization."""

    model_config = ConfigDict(extra="forbid")

    step_index: int = Field(ge=1, le=32)
    tool_name: str = Field(min_length=1, max_length=120)
    tool_args: dict[str, Any] = Field(default_factory=dict)
    predecessors: list[int] = Field(default_factory=list, max_length=32)


class AgentPlan(BaseModel):
    """Validated plan envelope shared by deterministic and remote planners."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=1, max_length=160)
    planner_type: Literal["deterministic", "model_gateway", "openai_compatible", "dify", "external_agent"]
    planner_version: str = Field(min_length=1, max_length=80)
    model_name: str = Field(min_length=1, max_length=160)
    summary: str = Field(default="", max_length=1000)
    steps: list[ProposedToolCall] = Field(default_factory=list, max_length=16)
    raw_response_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    fallback_from: str | None = Field(default=None, max_length=160)
    warnings: list[str] = Field(default_factory=list, max_length=20)


class GatewayContext(BaseModel):
    """Typed task context shared by policy, capability and taint controls."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str | None = Field(default=None, max_length=160)
    task_id: str | None = Field(default=None, max_length=160)
    user: PrincipalIdentity | None = None
    agent: PrincipalIdentity | None = None
    # Compatibility fields for the first prototype API. New integrations should
    # populate ``user`` and ``agent`` instead.
    user_role: str | None = Field(default=None, max_length=80)
    scenario: str | None = Field(default=None, max_length=160)
    input_sources: list[InputReference] = Field(default_factory=list)
    data_labels: list[DataLabel] = Field(default_factory=list)
    data_scopes: list[str] = Field(default_factory=list)
    authorized_recipients: list[str] = Field(default_factory=list)
    authorized_domains: list[str] = Field(default_factory=list)
    policy_version: str | None = Field(default=None, max_length=80)
    capability_ticket: str | None = Field(default=None, max_length=16_384)
    parent_request_id: str | None = Field(default=None, max_length=160)
    task_step: int = Field(default=0, ge=0)
    task_graph: TaskGraph | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityScope(BaseModel):
    """Least-privilege scope encoded in a signed capability ticket."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1, max_length=120)
    exact_args: dict[str, Any] = Field(default_factory=dict)
    path_prefixes: list[str] = Field(default_factory=list)
    url_domains: list[str] = Field(default_factory=list)
    recipient_domains: list[str] = Field(default_factory=list)
    data_scopes: list[str] = Field(default_factory=list)
    allowed_data_labels: list[DataLabel] = Field(default_factory=list)


class CapabilityGrant(BaseModel):
    """Signed, task-bound authorization claim with bounded usage."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: str = Field(min_length=1, max_length=160)
    issuer: str = Field(min_length=1, max_length=160)
    subject_id: str = Field(min_length=1, max_length=160)
    tenant_id: str = Field(min_length=1, max_length=160)
    trace_id: str = Field(min_length=1, max_length=160)
    task_id: str | None = Field(default=None, max_length=160)
    scope: CapabilityScope
    issued_at: datetime
    expires_at: datetime
    max_uses: int = Field(default=1, ge=1, le=1000)
    policy_version: str = Field(min_length=1, max_length=80)
    nonce: str = Field(min_length=16, max_length=160)


class RiskEvidence(BaseModel):
    """Evidence emitted by any input or supply-chain detector."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    risk_type: str = Field(min_length=1)
    risk_level: RiskLevel
    score: float = Field(ge=0.0, le=1.0)
    excerpt: str = ""
    rule_hits: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolRequest(BaseModel):
    """Normalized gateway input; unknown top-level fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1, max_length=120)
    tool_args: dict[str, Any] = Field(default_factory=dict)
    context: GatewayContext = Field(default_factory=GatewayContext)


class PolicyDecision(BaseModel):
    """Stable decision returned by policy evaluation."""

    model_config = ConfigDict(extra="forbid")

    decision: Decision
    risk_level: RiskLevel
    reason: str
    policy_hit: str
    policy_version: str = "unknown"


class ApprovalState(BaseModel):
    """Serializable state for a resumable, replay-safe approval."""

    model_config = ConfigDict(extra="forbid")

    approval_id: str
    trace_id: str
    request_id: str
    status: ApprovalStatus
    actor: str | None = None
    idempotency_key: str
    requested_at: datetime
    expires_at: datetime
    decided_at: datetime | None = None
    consumed_at: datetime | None = None
    revoked_at: datetime | None = None
    tool_name: str = ""
    request_hash: str = ""
    masked_args: dict[str, Any] = Field(default_factory=dict)


class AuditEvent(BaseModel):
    """Version-ready event envelope shared by audit and replay components."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str
    stage: str
    event: dict[str, Any]
    created_at: datetime
    sequence: int | None = Field(default=None, ge=1)
    event_version: str = "2.0.0"
    policy_version: str = "unknown"
    model_version: str = "none"
    dataset_version: str = "unknown"
    actor_id: str | None = None
    prev_hash: str | None = None
    event_hash: str | None = None
    event_signature: str | None = None
