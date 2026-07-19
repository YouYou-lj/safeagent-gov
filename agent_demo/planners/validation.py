"""Fail-closed validation of planner output and task-graph topology."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import ValidationError

from safeagent_gov.contracts import AgentPlan, ProposedToolCall
from safeagent_gov.errors import PlanningError

from .tool_schemas import validate_tool_args

PLANNER_SCHEMA_VERSION = "1.0.0"


def _stable_plan_id(task: str, steps: list[ProposedToolCall]) -> str:
    payload = {
        "task_hash": hashlib.sha256(task.encode("utf-8", errors="replace")).hexdigest(),
        "steps": [step.model_dump(mode="json") for step in steps],
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"PLAN-{digest[:24].upper()}"


def validate_plan_payload(
    task: str,
    payload: dict[str, Any],
    *,
    planner_type: str,
    model_name: str,
    raw_response_hash: str | None = None,
) -> AgentPlan:
    if not isinstance(payload, dict):
        raise PlanningError("规划响应必须是 JSON 对象")
    unknown = set(payload) - {"summary", "steps"}
    if unknown:
        raise PlanningError(f"规划响应包含未知字段: {sorted(unknown)}")
    raw_steps = payload.get("steps", [])
    if not isinstance(raw_steps, list) or len(raw_steps) > 16:
        raise PlanningError("规划 steps 必须是最多 16 项的数组")
    steps: list[ProposedToolCall] = []
    for index, raw in enumerate(raw_steps, 1):
        if not isinstance(raw, dict):
            raise PlanningError(f"规划步骤 {index} 必须是对象")
        unknown_step = set(raw) - {"step_index", "tool_name", "tool_args", "predecessors"}
        if unknown_step:
            raise PlanningError(f"规划步骤 {index} 包含未知字段: {sorted(unknown_step)}")
        if raw.get("step_index", index) != index:
            raise PlanningError("规划 step_index 必须从 1 连续递增")
        tool_name = raw.get("tool_name")
        if not isinstance(tool_name, str):
            raise PlanningError(f"规划步骤 {index} 缺少 tool_name")
        args = raw.get("tool_args", {})
        if not isinstance(args, dict):
            raise PlanningError(f"规划步骤 {index} 的 tool_args 必须是对象")
        predecessors = raw.get("predecessors", [index - 1] if index > 1 else [])
        if not isinstance(predecessors, list) or any(
            not isinstance(item, int) or isinstance(item, bool) or item < 1 or item >= index
            for item in predecessors
        ):
            raise PlanningError(f"规划步骤 {index} 的 predecessors 必须引用先前步骤")
        if len(predecessors) != len(set(predecessors)):
            raise PlanningError(f"规划步骤 {index} 的 predecessors 不能重复")
        try:
            step = ProposedToolCall(
                step_index=index,
                tool_name=tool_name,
                tool_args=validate_tool_args(tool_name, args),
                predecessors=predecessors,
            )
        except ValidationError as exc:
            raise PlanningError(f"规划步骤 {index} 不符合契约") from exc
        steps.append(step)
    summary = payload.get("summary", "")
    if not isinstance(summary, str):
        raise PlanningError("规划 summary 必须是字符串")
    try:
        return AgentPlan(
            plan_id=_stable_plan_id(task, steps),
            planner_type=planner_type,
            planner_version=PLANNER_SCHEMA_VERSION,
            model_name=model_name,
            summary=summary[:1000],
            steps=steps,
            raw_response_hash=raw_response_hash,
        )
    except ValidationError as exc:
        raise PlanningError("规划响应不符合 AgentPlan 契约") from exc
