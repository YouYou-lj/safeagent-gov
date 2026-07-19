"""Graphify-backed SafeRouter-Gov structured planning service."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from safeagent_gov.contracts import RiskLevel
from safeagent_gov.graphify import GraphifyService, GraphSearchRequest
from safeagent_gov.graphify.contracts import EdgeRelation

from .contracts import RoutedSubTask, RouterPlan, RouterPlanRequest


@dataclass(frozen=True)
class AgentBehavior:
    task: str
    priority: Literal["critical", "high", "medium", "low"]
    timeout: float
    group: str
    mandatory: bool
    always_run: bool = False


AGENT_BEHAVIOR: dict[str, AgentBehavior] = {
    "agent.tool_risk_agent": AgentBehavior(
        task="评估候选 MCP 工具、参数、数据流向和最小权限边界",
        priority="critical",
        timeout=5.0,
        group="tool_risk",
        mandatory=True,
    ),
    "agent.compliance_agent": AgentBehavior(
        task="判断任务是否符合政企流程、外发和审批规则",
        priority="high",
        timeout=8.0,
        group="compliance",
        mandatory=True,
    ),
    "agent.skill_scan_agent": AgentBehavior(
        task="扫描待注册 Skill 或 MCP Server 的供应链与行为权限风险",
        priority="critical",
        timeout=15.0,
        group="supply_chain",
        mandatory=True,
    ),
    "agent.document_risk_agent": AgentBehavior(
        task="解析文档来源并检测间接提示注入与知识投毒",
        priority="critical",
        timeout=8.0,
        group="security_precheck",
        mandatory=True,
    ),
    "agent.gov_rag_agent": AgentBehavior(
        task="检索和汇总公开政务材料并保留引用来源",
        priority="medium",
        timeout=20.0,
        group="content_analysis",
        mandatory=False,
    ),
    "agent.audit_agent": AgentBehavior(
        task="汇总子任务状态、风险裁决和执行路径并完成审计",
        priority="critical",
        timeout=5.0,
        group="audit_finalize",
        mandatory=True,
        always_run=True,
    ),
}

RISK_BY_INTENT = {
    "intent.sensitive_external_send": RiskLevel.HIGH,
    "intent.skill_security_scan": RiskLevel.HIGH,
    "intent.operations_command": RiskLevel.CRITICAL,
    "intent.policy_summary": RiskLevel.LOW,
    "intent.general_task": RiskLevel.LOW,
}
PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class SafeRouterService:
    """Convert Graphify retrieval results into a bounded, auditable DAG plan."""

    def __init__(self, graphify: GraphifyService):
        self.graphify = graphify

    @staticmethod
    def _task_id(trace_id: str, agent_id: str, index: int) -> str:
        digest = hashlib.sha256(f"{trace_id}:{agent_id}:{index}".encode()).hexdigest()[:16]
        return f"subtask_{digest}"

    def plan(self, request: RouterPlanRequest, trace_id: str) -> RouterPlan:
        retrieval = self.graphify.search(
            GraphSearchRequest(
                query=request.task,
                scenario=request.scenario,
                user_role=request.user_role,
                token_budget=request.token_budget,
                top_k=request.max_sub_agents,
            )
        )
        graph = self.graphify.store.load_graph()
        stats = self.graphify.stats()
        candidate_agents = [item.node_id for item in retrieval.candidate_agents if item.node_id in AGENT_BEHAVIOR]
        audit_agent_id = "agent.audit_agent"
        analysis_agents = sorted(
            (agent_id for agent_id in candidate_agents if agent_id != audit_agent_id),
            key=lambda agent_id: (PRIORITY_RANK[AGENT_BEHAVIOR[agent_id].priority], agent_id),
        )
        reserve_audit = audit_agent_id in candidate_agents
        analysis_limit = request.max_sub_agents - int(reserve_audit)
        selected_agents = analysis_agents[:analysis_limit]
        if reserve_audit:
            selected_agents.append(audit_agent_id)
        task_specs: list[tuple[str, AgentBehavior]] = [
            (agent_id, AGENT_BEHAVIOR[agent_id]) for agent_id in selected_agents if agent_id in AGENT_BEHAVIOR
        ]
        if not task_specs:
            task_specs = [("agent.audit_agent", AGENT_BEHAVIOR["agent.audit_agent"])]

        tasks: list[RoutedSubTask] = []
        for index, (agent_id, behavior) in enumerate(task_specs, 1):
            if behavior.always_run:
                continue
            skill_ids = self.graphify.outgoing_targets(graph, agent_id, EdgeRelation.CAN_USE_SKILL)
            tool_ids = self.graphify.outgoing_targets(graph, agent_id, EdgeRelation.CAN_CALL_TOOL)
            tasks.append(
                RoutedSubTask(
                    task_id=self._task_id(trace_id, agent_id, index),
                    agent_id=agent_id,
                    agent_name=graph.nodes[agent_id]["capability"].name,
                    task=behavior.task,
                    priority=behavior.priority,
                    timeout_seconds=behavior.timeout,
                    parallel_group=behavior.group,
                    required_skills=skill_ids,
                    allowed_tools=tool_ids,
                    mandatory=behavior.mandatory,
                )
            )

        if audit_agent_id in selected_agents or not tasks:
            audit_behavior = AGENT_BEHAVIOR[audit_agent_id]
            audit_index = len(task_specs) + 1
            tasks.append(
                RoutedSubTask(
                    task_id=self._task_id(trace_id, audit_agent_id, audit_index),
                    agent_id=audit_agent_id,
                    agent_name=graph.nodes[audit_agent_id]["capability"].name,
                    task=audit_behavior.task,
                    priority="critical",
                    timeout_seconds=audit_behavior.timeout,
                    parallel_group="audit_finalize",
                    required_skills=self.graphify.outgoing_targets(
                        graph, audit_agent_id, EdgeRelation.CAN_USE_SKILL
                    ),
                    predecessors=[task.task_id for task in tasks],
                    mandatory=True,
                    always_run=True,
                )
            )

        plan_digest = hashlib.sha256(
            f"{trace_id}:{retrieval.intent}:{stats.source_digest}".encode()
        ).hexdigest()[:24]
        retrieved_skill_ids = {item.node_id for item in retrieval.candidate_skills}
        warnings = []
        if not retrieval.within_token_budget:
            warnings.append("Graphify 能力卡片估算超过请求 token_budget")
        return RouterPlan(
            trace_id=trace_id,
            plan_id=f"router_{plan_digest}",
            intent=retrieval.intent,
            intent_score=retrieval.intent_score,
            risk_baseline=RISK_BY_INTENT.get(retrieval.intent, RiskLevel.MEDIUM),
            enable_parallel_agents=request.enable_parallel_agents,
            mandatory_prechecks=sorted(retrieved_skill_ids & {"skill.promptshield_gov"}),
            mandatory_tool_guards=sorted(retrieved_skill_ids & {"skill.mcpguard_gov"}),
            mandatory_context_guards=sorted(
                retrieved_skill_ids & {"skill.sensitivedata_gov", "skill.compliance_gov"}
            ),
            mandatory_postchecks=sorted(retrieved_skill_ids & {"skill.traceaudit_gov"}),
            sub_tasks=tasks,
            graph_version=stats.graph_version,
            graph_source_digest=stats.source_digest,
            estimated_prompt_tokens=retrieval.estimated_prompt_tokens,
            warnings=warnings,
        )
