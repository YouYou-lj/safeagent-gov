"""Strict contracts for the versioned Skill Registry and unified executor."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SkillCategory(str, Enum):
    SECURITY = "security"
    BUSINESS = "business"


class SkillExecutionMode(str, Enum):
    MANDATORY = "mandatory"
    ROUTED = "routed"


class SkillFailurePolicy(str, Enum):
    BLOCK = "block"
    CONTINUE_WITH_WARNING = "continue_with_warning"


class SkillTriggerStage(str, Enum):
    DIRECT = "direct"
    USER_INPUT = "user_input"
    DOCUMENT_UPLOAD = "document_upload"
    RAG_RESULT = "rag_result"
    BEFORE_TOOL_CALL = "before_tool_call"
    BEFORE_SKILL_REGISTER = "before_skill_register"
    BEFORE_MCP_REGISTER = "before_mcp_register"
    BEFORE_EXTERNAL_SEND = "before_external_send"
    BEFORE_DATA_EXPORT = "before_data_export"
    BEFORE_PROCESS_ACTION = "before_process_action"
    TASK_COMPLETED = "task_completed"
    TASK_BLOCKED = "task_blocked"
    APPROVAL = "approval"


class SkillDefinition(BaseModel):
    """Validated, executable governance fields from one Skill manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,79}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    category: SkillCategory
    execution_mode: SkillExecutionMode
    trigger_stages: list[SkillTriggerStage] = Field(min_length=1, max_length=20)
    entrypoint: str = Field(pattern=r"^[A-Za-z0-9_./-]+:[A-Za-z_][A-Za-z0-9_]*$", max_length=500)
    baseline_entrypoint: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_./-]+:[A-Za-z_][A-Za-z0-9_]*$",
        max_length=500,
    )
    inputs: list[str] = Field(min_length=1, max_length=100)
    required_inputs: list[str] = Field(min_length=1, max_length=100)
    outputs: list[str] = Field(min_length=1, max_length=100)
    required_outputs: list[str] = Field(min_length=1, max_length=100)
    timeout_seconds: float = Field(ge=0.01, le=120.0)
    retries: int = Field(ge=0, le=3)
    failure_policy: SkillFailurePolicy
    enabled: bool
    policies: dict[str, str] = Field(default_factory=dict)
    permissions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> SkillDefinition:
        if len(set(self.inputs)) != len(self.inputs) or len(set(self.outputs)) != len(self.outputs):
            raise ValueError("Skill inputs/outputs 不能重复")
        if len(set(self.trigger_stages)) != len(self.trigger_stages):
            raise ValueError("Skill trigger_stages 不能重复")
        if not set(self.required_inputs) <= set(self.inputs):
            raise ValueError("required_inputs 必须是 inputs 的子集")
        if not set(self.required_outputs) <= set(self.outputs):
            raise ValueError("required_outputs 必须是 outputs 的子集")
        if self.execution_mode == SkillExecutionMode.MANDATORY and self.failure_policy != SkillFailurePolicy.BLOCK:
            raise ValueError("强制 Skill 必须使用 block 失败策略")
        return self


class RegisteredSkill(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    definition: SkillDefinition
    manifest_path: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class SkillRegistrySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    skill_count: int = Field(ge=0)
    enabled_count: int = Field(ge=0)
    mandatory_count: int = Field(ge=0)
    skills: list[RegisteredSkill]


class SkillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=160)
    skill_name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,79}$")
    input_data: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    trigger_stage: SkillTriggerStage = SkillTriggerStage.DIRECT


class SkillResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    success: bool
    status: Literal["completed", "blocked", "completed_with_warning"]
    skill_name: str
    skill_version: str
    mandatory: bool
    trigger_stage: SkillTriggerStage
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    latency_ms: float = Field(ge=0.0)
    attempts: int = Field(ge=0)
    parameter_complete: bool
    audit_complete: bool


class SkillMetricsSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_calls: int = Field(ge=0)
    actual_calls: int = Field(ge=0)
    expected_calls: int = Field(ge=0)
    expected_actual_calls: int = Field(ge=0)
    started_calls: int = Field(ge=0)
    successful_calls: int = Field(ge=0)
    failed_calls: int = Field(ge=0)
    parameter_complete_calls: int = Field(ge=0)
    erroneous_calls: int = Field(ge=0)
    mandatory_expected_calls: int = Field(ge=0)
    mandatory_completed_calls: int = Field(ge=0)
    audit_failures: int = Field(ge=0)
    max_observed_concurrency: int = Field(ge=0)
    expected_call_recall: float = Field(ge=0.0, le=1.0)
    success_rate: float = Field(ge=0.0, le=1.0)
    parameter_completeness_rate: float = Field(ge=0.0, le=1.0)
    erroneous_call_rate: float = Field(ge=0.0, le=1.0)
    mandatory_skill_coverage: float = Field(ge=0.0, le=1.0)
    average_latency_ms: float = Field(ge=0.0)
