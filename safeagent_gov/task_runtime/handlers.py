"""Explicit default handlers for isolated Task Dispatcher pools."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from safeagent_gov.errors import TaskRuntimeError
from safeagent_gov.skill_runtime import SkillRequest, SkillTriggerStage
from safeagent_gov.skill_runtime.defaults import DEFAULT_SKILL_EXECUTOR

from .contracts import TaskKind, TaskRecord


class SecurityCheckPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=100_000)
    source: Literal["user_input", "uploaded_doc", "rag_result", "tool_result"] = "user_input"


class AgentTaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1, max_length=50_000)
    scenario: str = Field(default="government_office", max_length=160)
    document_text: str = Field(default="", max_length=200_000)
    document_source: str = Field(default="uploaded_doc", max_length=160)
    skill_package_path: str | None = Field(default=None, min_length=1, max_length=160)


class SkillScanTaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_path: str = Field(min_length=1, max_length=1000)


class EvaluationTaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eval_type: Literal["all", "prompt", "tool", "skill", "audit"] = "all"


PAYLOAD_MODELS: dict[TaskKind, type[BaseModel]] = {
    TaskKind.SECURITY_CHECK: SecurityCheckPayload,
    TaskKind.AGENT: AgentTaskPayload,
    TaskKind.SKILL_SCAN: SkillScanTaskPayload,
    TaskKind.EVALUATION: EvaluationTaskPayload,
}


def normalize_task_payload(kind: TaskKind, payload: dict[str, Any]) -> dict[str, Any]:
    return PAYLOAD_MODELS[kind].model_validate(payload).model_dump(mode="json")


async def security_check_handler(record: TaskRecord) -> dict[str, Any]:
    payload = SecurityCheckPayload.model_validate(record.payload)
    response = await DEFAULT_SKILL_EXECUTOR.execute(
        SkillRequest(
            trace_id=record.trace_id,
            skill_name="promptshield-gov",
            input_data={"text": payload.text, "source": payload.source},
            context={
                "principal": {
                    "sub": record.actor_id,
                    "tenant_id": record.tenant_id,
                    "role": record.role,
                    "scopes": [],
                }
            },
            trigger_stage=(
                SkillTriggerStage.USER_INPUT
                if payload.source == "user_input"
                else (
                    SkillTriggerStage.DOCUMENT_UPLOAD
                    if payload.source == "uploaded_doc"
                    else (SkillTriggerStage.RAG_RESULT if payload.source == "rag_result" else SkillTriggerStage.DIRECT)
                )
            ),
        )
    )
    if not response.success:
        raise TaskRuntimeError(f"PromptShield Runtime 失败: {response.error_code}")
    return {
        "skill_response": response.model_dump(mode="json"),
        "mandatory_skill_coverage": 1.0,
    }


async def agent_handler(record: TaskRecord) -> dict[str, Any]:
    from agent_demo.langgraph_agent.agent import run_agent

    payload = AgentTaskPayload.model_validate(record.payload)
    result = await asyncio.to_thread(
        run_agent,
        payload.task,
        scenario=payload.scenario,
        user_role=record.role,
        document_text=payload.document_text,
        document_source=payload.document_source,
        skill_package_path=payload.skill_package_path,
        tenant_id=record.tenant_id,
        user_id=record.actor_id,
        agent_id="task-runtime-agent",
    )
    return {
        "child_trace_id": result["trace_id"],
        "status": result["status"],
        "final_output": result["final_output"],
        "mandatory_skill_coverage": result.get("mandatory_skill_coverage", 0.0),
        "toolguard_coverage": result.get("toolguard_coverage", 0.0),
    }


async def skill_scan_handler(record: TaskRecord) -> dict[str, Any]:
    payload = SkillScanTaskPayload.model_validate(record.payload)
    response = await DEFAULT_SKILL_EXECUTOR.execute(
        SkillRequest(
            trace_id=record.trace_id,
            skill_name="skillscan-gov",
            input_data={"package_path": str(Path(payload.package_path))},
            context={
                "principal": {
                    "sub": record.actor_id,
                    "tenant_id": record.tenant_id,
                    "role": record.role,
                    "scopes": [],
                }
            },
            trigger_stage=SkillTriggerStage.BEFORE_SKILL_REGISTER,
        )
    )
    if not response.success:
        raise TaskRuntimeError(f"SkillScan Runtime 失败: {response.error_code}")
    return {"skill_response": response.model_dump(mode="json"), "mandatory_skill_coverage": 1.0}


async def evaluation_handler(record: TaskRecord) -> dict[str, Any]:
    from backend.core.evaluator import run_evaluations

    payload = EvaluationTaskPayload.model_validate(record.payload)
    summary = await asyncio.to_thread(run_evaluations, payload.eval_type)
    return {"status": "completed", "summary": summary}


def default_handlers():
    return {
        TaskKind.SECURITY_CHECK: security_check_handler,
        TaskKind.AGENT: agent_handler,
        TaskKind.SKILL_SCAN: skill_scan_handler,
        TaskKind.EVALUATION: evaluation_handler,
    }
