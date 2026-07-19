"""Bounded concurrent SafeRouter fan-out/fan-in execution with fail-closed audit."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from time import perf_counter

import networkx as nx

from safeagent_gov.contracts import Decision, RiskLevel
from safeagent_gov.errors import PlanningError

from .contracts import RoutedSubTask, RouterExecutionResult, RouterPlan, SubAgentOutcome, SubAgentResult

SubAgentHandler = Callable[[RoutedSubTask], Awaitable[SubAgentOutcome]]
AuditCallback = Callable[[SubAgentResult], Awaitable[None]]

DECISION_RANK = {
    Decision.ALLOW: 0,
    Decision.ALLOW_WITH_LOG: 1,
    Decision.MASK_AND_ALLOW: 2,
    Decision.REQUIRE_APPROVAL: 3,
    Decision.BLOCK: 4,
}
RISK_RANK = {
    RiskLevel.SAFE: 0,
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


class SafeRouterExecutor:
    """Execute analysis-only subagents with DAG dependencies and bounded concurrency."""

    def __init__(self, max_concurrency: int = 8):
        if not 1 <= max_concurrency <= 64:
            raise ValueError("max_concurrency 必须位于 1..64")
        self.max_concurrency = max_concurrency

    @staticmethod
    def _generations(plan: RouterPlan) -> list[list[RoutedSubTask]]:
        graph = nx.DiGraph()
        tasks = {task.task_id: task for task in plan.sub_tasks}
        graph.add_nodes_from(tasks)
        for task in plan.sub_tasks:
            graph.add_edges_from((predecessor, task.task_id) for predecessor in task.predecessors)
        if not nx.is_directed_acyclic_graph(graph):
            raise PlanningError("RouterPlan 子任务依赖必须构成 DAG")
        return [[tasks[task_id] for task_id in generation] for generation in nx.topological_generations(graph)]

    async def execute(
        self,
        plan: RouterPlan,
        handlers: Mapping[str, SubAgentHandler],
        audit_callback: AuditCallback,
    ) -> RouterExecutionResult:
        started = perf_counter()
        semaphore = asyncio.Semaphore(self.max_concurrency if plan.enable_parallel_agents else 1)
        active = 0
        max_active = 0
        results: dict[str, SubAgentResult] = {}

        async def run_one(task: RoutedSubTask) -> SubAgentResult:
            nonlocal active, max_active
            blocked_predecessor = any(
                results[predecessor].decision == Decision.BLOCK for predecessor in task.predecessors
            )
            if blocked_predecessor and not task.always_run:
                result = SubAgentResult(
                    task_id=task.task_id,
                    agent_id=task.agent_id,
                    status="skipped",
                    decision=Decision.BLOCK if task.mandatory else Decision.REQUIRE_APPROVAL,
                    risk_level=RiskLevel.HIGH if task.mandatory else RiskLevel.MEDIUM,
                    error_code="blocked_predecessor",
                    latency_ms=0.0,
                )
                return await record_audit(result)

            handler = handlers.get(task.agent_id)
            if handler is None:
                result = SubAgentResult(
                    task_id=task.task_id,
                    agent_id=task.agent_id,
                    status="failed",
                    decision=Decision.BLOCK if task.mandatory else Decision.REQUIRE_APPROVAL,
                    risk_level=RiskLevel.CRITICAL if task.mandatory else RiskLevel.MEDIUM,
                    error_code="handler_not_registered",
                    latency_ms=0.0,
                )
                return await record_audit(result)

            task_started = perf_counter()
            async with semaphore:
                active += 1
                max_active = max(max_active, active)
                try:
                    outcome = await asyncio.wait_for(handler(task), timeout=task.timeout_seconds)
                    result = SubAgentResult(
                        task_id=task.task_id,
                        agent_id=task.agent_id,
                        status="completed",
                        decision=outcome.decision,
                        risk_level=outcome.risk_level,
                        output=outcome.output,
                        latency_ms=(perf_counter() - task_started) * 1000,
                    )
                except TimeoutError:
                    result = SubAgentResult(
                        task_id=task.task_id,
                        agent_id=task.agent_id,
                        status="timeout",
                        decision=Decision.BLOCK if task.mandatory else Decision.REQUIRE_APPROVAL,
                        risk_level=RiskLevel.CRITICAL if task.mandatory else RiskLevel.MEDIUM,
                        error_code="subagent_timeout",
                        latency_ms=(perf_counter() - task_started) * 1000,
                    )
                except Exception as exc:
                    result = SubAgentResult(
                        task_id=task.task_id,
                        agent_id=task.agent_id,
                        status="failed",
                        decision=Decision.BLOCK if task.mandatory else Decision.REQUIRE_APPROVAL,
                        risk_level=RiskLevel.CRITICAL if task.mandatory else RiskLevel.MEDIUM,
                        error_code=f"subagent_error:{type(exc).__name__}",
                        latency_ms=(perf_counter() - task_started) * 1000,
                    )
                finally:
                    active -= 1
            return await record_audit(result)

        async def record_audit(result: SubAgentResult) -> SubAgentResult:
            try:
                await audit_callback(result)
                return result.model_copy(update={"audit_recorded": True})
            except Exception as exc:
                return result.model_copy(
                    update={
                        "status": "failed",
                        "decision": Decision.BLOCK,
                        "risk_level": RiskLevel.CRITICAL,
                        "error_code": f"audit_error:{type(exc).__name__}",
                        "audit_recorded": False,
                    }
                )

        for generation in self._generations(plan):
            generation_results = await asyncio.gather(*(run_one(task) for task in generation))
            results.update((result.task_id, result) for result in generation_results)

        ordered = [results[task.task_id] for task in plan.sub_tasks]
        audit_complete = all(result.audit_recorded for result in ordered)
        final_decision = max((result.decision for result in ordered), key=DECISION_RANK.__getitem__)
        risk_level = max((result.risk_level for result in ordered), key=RISK_RANK.__getitem__)
        if not audit_complete:
            final_decision = Decision.BLOCK
            risk_level = RiskLevel.CRITICAL
        status = {
            Decision.BLOCK: "blocked",
            Decision.REQUIRE_APPROVAL: "pending_approval",
            Decision.MASK_AND_ALLOW: "masked",
        }.get(final_decision, "completed")
        return RouterExecutionResult(
            trace_id=plan.trace_id,
            plan_id=plan.plan_id,
            status=status,
            final_decision=final_decision,
            risk_level=risk_level,
            sub_agent_results=ordered,
            latency_ms=(perf_counter() - started) * 1000,
            max_observed_concurrency=max_active,
            audit_complete=audit_complete,
        )
