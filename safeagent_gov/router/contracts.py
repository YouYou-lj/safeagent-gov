"""Strict contracts for SafeRouter-Gov plans and fan-out/fan-in results."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from safeagent_gov.contracts import Decision, RiskLevel


class RouterPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1, max_length=50_000)
    scenario: str = Field(default="government_office", max_length=160)
    user_role: str = Field(default="staff", max_length=80)
    enable_parallel_agents: bool = True
    max_sub_agents: int = Field(default=8, ge=2, le=16)
    token_budget: int = Field(default=1200, ge=200, le=20_000)


class RoutedSubTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(pattern=r"^subtask_[0-9a-f]{16}$")
    agent_id: str = Field(pattern=r"^agent\.[a-z0-9_]+$")
    agent_name: str = Field(min_length=1, max_length=160)
    task: str = Field(min_length=1, max_length=2000)
    priority: Literal["critical", "high", "medium", "low"]
    timeout_seconds: float = Field(ge=0.01, le=120.0)
    parallel_group: str = Field(min_length=1, max_length=120)
    required_skills: list[str] = Field(default_factory=list, max_length=32)
    allowed_tools: list[str] = Field(default_factory=list, max_length=64)
    predecessors: list[str] = Field(default_factory=list, max_length=32)
    mandatory: bool = False
    always_run: bool = False


class RouterPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=160)
    plan_id: str = Field(pattern=r"^router_[0-9a-f]{24}$")
    intent: str
    intent_score: float = Field(ge=0.0, le=1.0)
    risk_baseline: RiskLevel
    enable_parallel_agents: bool
    mandatory_prechecks: list[str]
    mandatory_tool_guards: list[str]
    mandatory_context_guards: list[str]
    mandatory_postchecks: list[str]
    sub_tasks: list[RoutedSubTask] = Field(min_length=1, max_length=16)
    graph_version: str
    graph_source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    estimated_prompt_tokens: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_task_graph(self) -> RouterPlan:
        task_ids = [task.task_id for task in self.sub_tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("RouterPlan task_id 必须唯一")
        known = set(task_ids)
        for task in self.sub_tasks:
            unknown = set(task.predecessors) - known
            if unknown:
                raise ValueError(f"RouterPlan predecessor 不存在: {sorted(unknown)}")
            if task.task_id in task.predecessors:
                raise ValueError("RouterPlan 子任务不能依赖自身")
        return self


class SubAgentOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Decision = Decision.ALLOW
    risk_level: RiskLevel = RiskLevel.SAFE
    output: dict[str, Any] = Field(default_factory=dict)


class SubAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    agent_id: str
    status: Literal["completed", "failed", "timeout", "skipped"]
    decision: Decision
    risk_level: RiskLevel
    output: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = Field(ge=0.0)
    error_code: str | None = Field(default=None, max_length=160)
    audit_recorded: bool = False


class RouterExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    plan_id: str
    status: Literal["completed", "masked", "pending_approval", "blocked"]
    final_decision: Decision
    risk_level: RiskLevel
    sub_agent_results: list[SubAgentResult]
    latency_ms: float = Field(ge=0.0)
    max_observed_concurrency: int = Field(ge=0)
    audit_complete: bool
