"""Dependency-free deterministic planner used for offline and test execution."""

from __future__ import annotations

from typing import Any

from safeagent_gov.contracts import AgentPlan
from safeagent_gov.planning import infer_deterministic_plan_payload

from .validation import validate_plan_payload


class DeterministicPlanner:
    planner_type = "deterministic"

    def plan(self, task: str, context: dict[str, Any]) -> AgentPlan:
        del context
        return validate_plan_payload(
            task,
            infer_deterministic_plan_payload(task),
            planner_type=self.planner_type,
            model_name="safeagent-deterministic-v1",
        )
