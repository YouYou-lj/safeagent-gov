"""Planner protocol shared by offline and remote implementations."""

from __future__ import annotations

from typing import Any, Protocol

from safeagent_gov.contracts import AgentPlan


class Planner(Protocol):
    planner_type: str

    def plan(self, task: str, context: dict[str, Any]) -> AgentPlan:
        """Return a validated proposal; execution remains owned by MCPGuard."""
