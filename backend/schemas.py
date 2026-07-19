"""Pydantic request models used by the public API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from safeagent_gov.contracts import SourceType


class RiskRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    source: SourceType = SourceType.USER_INPUT
    origin: str | None = Field(default=None, max_length=2048)
    session_id: str | None = Field(default=None, max_length=160)
    trust_score: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    mode: Literal["disabled", "rules", "rules_classifier", "full"] = "full"
    trace_id: str | None = None


class ToolCheckRequest(BaseModel):
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class MCPCallRequest(BaseModel):
    """Server-context MCP call; clients cannot supply identities or tickets."""

    tool_name: str = Field(min_length=1, max_length=120, pattern=r"^[a-z][a-z0-9_]{1,119}$")
    tool_args: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = Field(default=None, min_length=1, max_length=160)
    scenario: str = Field(default="government_office", min_length=1, max_length=160)


class MCPManifestScanRequest(BaseModel):
    """Untrusted MCP description text; the API never executes or connects to it."""

    content: str = Field(min_length=1, max_length=200_000)
    format: Literal["auto", "json", "yaml"] = "auto"
    source_name: str = Field(default="uploaded-manifest", min_length=1, max_length=160)


class ApprovalRequest(BaseModel):
    trace_id: str
    request_id: str
    decision: Literal["allow", "deny", "mask_and_allow"]
    comment: str = ""
    masked_args: dict[str, Any] = Field(default_factory=dict)
    actor: str = Field(default="human_reviewer", min_length=1, max_length=160)
    decision_key: str | None = Field(default=None, min_length=1, max_length=240)


class ApprovalResumeRequest(BaseModel):
    approval_id: str = Field(min_length=1, max_length=160)
    capability_ticket: str = Field(min_length=1, max_length=16_384)


class EvalRequest(BaseModel):
    eval_type: Literal["all", "prompt", "tool", "skill", "audit"] = "all"


class AgentRunRequest(BaseModel):
    task: str = Field(min_length=1, max_length=50_000)
    scenario: str = "government_office"
    # Compatibility-only display field. Authorization always comes from the
    # signed bearer identity and this value is never trusted by the API.
    user_role: str | None = None
    document_text: str = ""
    document_source: str = "uploaded_doc"
    skill_package_path: str | None = Field(default=None, min_length=1, max_length=160)


class PolicyCanaryRequest(BaseModel):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    rollout_percent: int = Field(ge=1, le=100)
