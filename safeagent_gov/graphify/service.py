"""Graphify-Gov build, retrieval, health, path, and evaluation service."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path
from time import perf_counter
from typing import Any

import networkx as nx
from pydantic import ValidationError

from safeagent_gov.audit import get_audit_trace
from safeagent_gov.errors import GraphifyConfigurationError, GraphifyNotBuiltError
from safeagent_gov.paths import resource_root
from safeagent_gov.supply_chain import scan_skill_package

from .contracts import (
    CandidateCapability,
    EdgeRelation,
    GraphBuildResult,
    GraphEvaluationCase,
    GraphEvaluationResult,
    GraphHealth,
    GraphSearchRequest,
    GraphSearchResult,
    GraphStats,
    NodeType,
    TraceLearningResult,
)
from .scanner import RepositoryScanner
from .store import GraphStore
from .vector_index import cosine_similarity


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 1.0


def _recall(expected: Iterable[str], actual: Iterable[str]) -> float:
    expected_set = set(expected)
    if not expected_set:
        return 1.0
    return len(expected_set & set(actual)) / len(expected_set)


class GraphifyService:
    """Coordinate deterministic repository graph construction and Top-K retrieval."""

    def __init__(self, repository_root: Path, database_path: Path, registry_path: Path | None = None):
        self.repository_root = repository_root.resolve()
        self.scanner = RepositoryScanner(self.repository_root, registry_path=registry_path)
        self.store = GraphStore(database_path)

    @classmethod
    def from_environment(cls) -> GraphifyService:
        repository_root = resource_root()
        database_path = Path(
            os.getenv("SAFEAGENT_GRAPHIFY_DB_PATH", str(repository_root / "backend" / "data" / "graphify-v2.db"))
        )
        return cls(repository_root, database_path)

    def _registration_scans(self, snapshot) -> dict[str, dict[str, Any]]:
        previous = self.store.node_hashes()
        scans: dict[str, dict[str, Any]] = {}
        for node in snapshot.nodes:
            if node.node_type not in {NodeType.SKILL, NodeType.MCP_TOOL}:
                continue
            if previous.get(node.node_id) == node.content_hash or not node.path:
                continue
            result = scan_skill_package(str(self.repository_root / node.path))
            scans[node.node_id] = {
                "risk_level": result["risk_level"],
                "risk_score": result["risk_score"],
            }
        return scans

    def build(self, reviewer_id: str | None = None) -> GraphBuildResult:
        snapshot = self.scanner.scan()
        return self.store.replace(
            snapshot,
            reviewer_id=reviewer_id,
            registration_scans=self._registration_scans(snapshot),
        )

    def update(self, reviewer_id: str | None = None) -> GraphBuildResult:
        return self.build(reviewer_id=reviewer_id)

    def bootstrap_if_empty(self) -> GraphBuildResult | None:
        """Create the first signed snapshot without mutating an existing graph."""
        try:
            self.store.metadata()
        except GraphifyNotBuiltError:
            return self.build()
        return None

    @staticmethod
    def outgoing_targets(graph: nx.MultiDiGraph, source_id: str, relation: EdgeRelation) -> list[str]:
        targets = {
            target
            for _, target, _, data in graph.out_edges(source_id, keys=True, data=True)
            if data.get("relation") == relation.value
        }
        return sorted(targets)

    @staticmethod
    def incoming_sources(graph: nx.MultiDiGraph, target_id: str, relation: EdgeRelation) -> list[str]:
        sources = {
            source
            for source, _, _, data in graph.in_edges(target_id, keys=True, data=True)
            if data.get("relation") == relation.value
        }
        return sorted(sources)

    def _select_intent(
        self, graph: nx.MultiDiGraph, request: GraphSearchRequest
    ) -> tuple[str, float, dict[str, float]]:
        query = request.query.casefold()
        scenario = request.scenario.casefold()
        ranked: list[tuple[float, str, dict[str, float]]] = []
        fallback = "intent.general_task"
        for node_id, data in graph.nodes(data=True):
            node = data["capability"]
            if node.node_type != NodeType.TASK_INTENT:
                continue
            keywords = [str(item).casefold() for item in node.metadata.get("keywords", [])]
            semantic_examples = [str(item) for item in node.metadata.get("semantic_examples", [])]
            scenarios = [str(item).casefold() for item in node.metadata.get("scenarios", [])]
            keyword_hits = sum(1 for keyword in keywords if keyword and keyword in query)
            keyword_score = keyword_hits / max(1, min(3, len(keywords)))
            semantic_text = " ".join([node.name, node.summary, node.token_card, *keywords, *semantic_examples])
            vector_score = cosine_similarity(request.query, semantic_text)
            semantic_signal = vector_score if vector_score >= 0.18 else 0.0
            scenario_bonus = 0.2 if (keyword_hits or semantic_signal) and scenario in scenarios else 0.0
            score = min(1.0, max(keyword_score, semantic_signal * 0.9) + scenario_bonus)
            if node_id == fallback:
                score = max(score, 0.05)
            ranked.append(
                (
                    score,
                    node_id,
                    {
                        "rule_score": round(keyword_score, 6),
                        "vector_score": round(vector_score, 6),
                        "scenario_bonus": round(scenario_bonus, 6),
                    },
                )
            )
        if not ranked:
            raise GraphifyConfigurationError("能力图谱没有 TaskIntent 节点")
        score, intent_id, signals = max(ranked, key=lambda item: (item[0], item[1] != fallback, item[1]))
        if score <= 0.05 and graph.has_node(fallback):
            fallback_signals = next(item[2] for item in ranked if item[1] == fallback)
            return fallback, 0.05, {**fallback_signals, "combined_score": 0.05}
        return intent_id, score, {**signals, "combined_score": round(score, 6)}

    @staticmethod
    def _path(graph: nx.MultiDiGraph, intent_id: str, node_id: str) -> list[str]:
        if intent_id == node_id:
            return [node_id]
        try:
            return list(nx.shortest_path(graph, intent_id, node_id))
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return [node_id]

    @staticmethod
    def _candidate(
        graph: nx.MultiDiGraph,
        intent_id: str,
        node_id: str,
        score: float,
        reason: str,
    ) -> CandidateCapability:
        node = graph.nodes[node_id]["capability"]
        return CandidateCapability(
            node_id=node_id,
            name=node.name,
            score=score,
            reason=reason,
            mandatory=node.mandatory,
            token_card=node.token_card,
            path=GraphifyService._path(graph, intent_id, node_id),
        )

    @staticmethod
    def _deduplicate(candidates: Iterable[CandidateCapability], top_k: int) -> list[CandidateCapability]:
        best: dict[str, CandidateCapability] = {}
        for candidate in candidates:
            previous = best.get(candidate.node_id)
            if previous is None or candidate.score > previous.score:
                best[candidate.node_id] = candidate
        ranked = sorted(best.values(), key=lambda item: (-int(item.mandatory), -item.score, item.node_id))
        mandatory = [item for item in ranked if item.mandatory]
        optional = [item for item in ranked if not item.mandatory]
        return mandatory + optional[: max(0, top_k - len(mandatory))]

    def search(self, request: GraphSearchRequest) -> GraphSearchResult:
        graph = self.store.load_graph()
        metadata = self.store.metadata()
        intent_id, intent_score, retrieval_signals = self._select_intent(graph, request)

        skill_candidates = [
            self._candidate(graph, intent_id, node_id, 0.96, "任务意图显式 requires_skill")
            for node_id in self.outgoing_targets(graph, intent_id, EdgeRelation.REQUIRES_SKILL)
        ]
        for node_id, data in graph.nodes(data=True):
            node = data["capability"]
            if node.node_type == NodeType.SKILL and node.mandatory:
                skill_candidates.append(self._candidate(graph, intent_id, node_id, 1.0, "系统强制安全 Skill"))

        agent_ids = self.outgoing_targets(graph, intent_id, EdgeRelation.ROUTES_TO_AGENT)
        agent_candidates = [
            self._candidate(graph, intent_id, node_id, 0.92, "任务意图显式 routes_to_agent") for node_id in agent_ids
        ]

        tool_ids: set[str] = set()
        for agent_id in agent_ids:
            tool_ids.update(self.outgoing_targets(graph, agent_id, EdgeRelation.CAN_CALL_TOOL))
            for skill_id in self.outgoing_targets(graph, agent_id, EdgeRelation.CAN_USE_SKILL):
                skill_candidates.append(self._candidate(graph, intent_id, skill_id, 0.82, "候选子智能体可调用"))
        tool_candidates = [
            self._candidate(graph, intent_id, node_id, 0.88, "候选子智能体声明 can_call_tool")
            for node_id in sorted(tool_ids)
        ]

        policy_ids: set[str] = set()
        for tool_id in tool_ids:
            policy_ids.update(self.outgoing_targets(graph, tool_id, EdgeRelation.GOVERNED_BY))
        policy_candidates = [
            self._candidate(graph, intent_id, node_id, 0.9, "候选 MCP 工具受该策略治理")
            for node_id in sorted(policy_ids)
        ]

        skills = self._deduplicate(skill_candidates, request.top_k)
        agents = self._deduplicate(agent_candidates, request.top_k)
        tools = self._deduplicate(tool_candidates, request.top_k)
        policies = self._deduplicate(policy_candidates, request.top_k)
        selected = [*skills, *agents, *tools, *policies]
        card_text = "\n".join(item.token_card for item in selected)
        estimated_tokens = max(1, (len(card_text) + 3) // 4)
        full_context_tokens = max(estimated_tokens, int(metadata.get("full_context_tokens", "0")))
        saved_tokens = max(0, full_context_tokens - estimated_tokens)
        reduction = saved_tokens / full_context_tokens if full_context_tokens else 0.0

        intent_node = graph.nodes[intent_id]["capability"]
        configured_path = [
            str(node_id) for node_id in intent_node.metadata.get("recommended_path", []) if graph.has_node(str(node_id))
        ]
        learned_pattern = self.store.best_trace_pattern(intent_id)
        learned_path = (
            [node_id for node_id in learned_pattern.path if graph.has_node(node_id)]
            if learned_pattern
            else []
        )
        if learned_pattern and len(learned_path) == len(learned_pattern.path):
            configured_path = learned_path
            retrieval_signals["trace_pattern_score"] = round(learned_pattern.success_rate, 6)
            retrieval_signals["trace_pattern_samples"] = float(
                learned_pattern.success_count + learned_pattern.failure_count
            )
        else:
            retrieval_signals["trace_pattern_score"] = 0.0
            retrieval_signals["trace_pattern_samples"] = 0.0
        return GraphSearchResult(
            intent=intent_id,
            intent_score=intent_score,
            retrieval_signals=retrieval_signals,
            candidate_skills=skills,
            candidate_mcp_tools=tools,
            candidate_agents=agents,
            related_policies=policies,
            recommended_path=configured_path,
            token_budget=request.token_budget,
            estimated_prompt_tokens=estimated_tokens,
            within_token_budget=estimated_tokens <= request.token_budget,
            full_context_tokens=full_context_tokens,
            saved_tokens_estimate=saved_tokens,
            token_reduction_rate=reduction,
        )

    @staticmethod
    def _capability_id(prefix: str, raw: str) -> str:
        normalized = re.sub(r"[^a-z0-9_]+", "_", raw.casefold().replace("-", "_")).strip("_")
        return f"{prefix}.{normalized}"

    def learn_trace(self, trace_id: str) -> TraceLearningResult:
        trace = get_audit_trace(trace_id, role="replayer")
        if not trace["integrity"]["valid"]:
            raise GraphifyConfigurationError("TraceAudit 完整性校验失败，拒绝学习路径")
        events = trace["events"]
        router_events = [event for event in events if event["stage"] == "router_plan"]
        final_events = [event for event in events if event["stage"] == "final_output"]
        if not router_events or not final_events:
            raise GraphifyConfigurationError("trace 缺少 router_plan 或 final_output，不能学习")
        intent_id = str(router_events[-1]["event"].get("intent", ""))
        if not intent_id.startswith("intent."):
            raise GraphifyConfigurationError("trace 的 Router intent 无效")
        path: list[str] = []
        for event in events:
            payload = event["event"]
            if event["stage"] == "skill_execution_completed" and payload.get("skill_name"):
                path.append(self._capability_id("skill", str(payload["skill_name"])))
            elif (
                event["stage"] == "sub_agent_result"
                and payload.get("agent_id")
                and payload.get("status") == "completed"
            ):
                path.append(str(payload["agent_id"]))
            elif event["stage"] == "tool_result" and payload.get("tool_name"):
                path.append(self._capability_id("mcp", str(payload["tool_name"])))
            elif event["stage"] == "model_response_received" and payload.get("provider_id"):
                path.append(self._capability_id("model", str(payload["provider_id"])))
        path = list(dict.fromkeys(path))
        graph = self.store.load_graph()
        path = [node_id for node_id in path if graph.has_node(node_id)]
        if not path:
            raise GraphifyConfigurationError("trace 没有可验证的能力执行路径")
        final_status = str(final_events[-1]["event"].get("status", "unknown"))
        success = final_status == "completed"
        pattern = self.store.record_trace_pattern(intent_id, path, success=success, trace_id=trace_id)
        accepted = pattern.success_count >= 2 and pattern.success_rate >= 0.8
        return TraceLearningResult(
            accepted=accepted,
            reason=(
                "成功路径达到推荐阈值"
                if accepted
                else "路径已记录，但成功样本或成功率尚未达到推荐阈值"
            ),
            pattern=pattern,
        )

    def recommend_path(self, request: GraphSearchRequest) -> dict[str, Any]:
        result = self.search(request)
        return {
            "intent": result.intent,
            "recommended_path": result.recommended_path,
            "candidate_count": (
                len(result.candidate_skills) + len(result.candidate_mcp_tools) + len(result.candidate_agents)
            ),
        }

    def stats(self) -> GraphStats:
        return self.store.stats()

    def health(self) -> GraphHealth:
        graph = self.store.load_graph()
        stored_digest = self.store.metadata()["source_digest"]
        current_digest = self.scanner.scan().source_digest
        monitored_types = {NodeType.TASK_INTENT, NodeType.SUB_AGENT, NodeType.SKILL, NodeType.MCP_TOOL}
        orphan_nodes = sorted(
            node_id
            for node_id, data in graph.nodes(data=True)
            if data["capability"].node_type in monitored_types and graph.degree(node_id) == 0
        )
        missing_schema_nodes = sorted(
            node_id
            for node_id, data in graph.nodes(data=True)
            if data["capability"].node_type in {NodeType.SKILL, NodeType.MCP_TOOL}
            and (not data["capability"].input_schema or not data["capability"].output_schema)
        )
        tool_ids = [
            node_id
            for node_id, data in graph.nodes(data=True)
            if data["capability"].node_type == NodeType.MCP_TOOL
        ]
        unguarded = sorted(
            tool_id for tool_id in tool_ids if not self.incoming_sources(graph, tool_id, EdgeRelation.GUARDS)
        )
        ungoverned = sorted(
            tool_id for tool_id in tool_ids if not self.outgoing_targets(graph, tool_id, EdgeRelation.GOVERNED_BY)
        )
        invalid_signatures, unapproved_nodes = self.store.verify_governance()
        source_stale = stored_digest != current_digest
        return GraphHealth(
            healthy=not (
                source_stale
                or orphan_nodes
                or missing_schema_nodes
                or unguarded
                or ungoverned
                or invalid_signatures
                or unapproved_nodes
            ),
            source_stale=source_stale,
            orphan_nodes=orphan_nodes,
            missing_schema_nodes=missing_schema_nodes,
            unguarded_tools=unguarded,
            ungoverned_tools=ungoverned,
            invalid_signature_nodes=invalid_signatures,
            unapproved_nodes=unapproved_nodes,
        )

    def evaluate(self, cases: list[dict[str, Any]]) -> GraphEvaluationResult:
        if not cases:
            raise GraphifyConfigurationError("Graphify 评测集不能为空")
        try:
            validated_cases = [GraphEvaluationCase.model_validate(case).model_dump(mode="python") for case in cases]
        except ValidationError as exc:
            raise GraphifyConfigurationError(f"Graphify 评测数据不符合 Schema: {exc}") from exc
        skill_scores: list[float] = []
        tool_scores: list[float] = []
        policy_scores: list[float] = []
        route_scores: list[float] = []
        mandatory_scores: list[float] = []
        toolguard_scores: list[float] = []
        reductions: list[float] = []
        latencies: list[float] = []
        failures: list[dict[str, Any]] = []
        mandatory_ids = {node.node_id for node in self.store.list_nodes() if node.node_type == NodeType.SKILL and node.mandatory}

        for case in validated_cases:
            started = perf_counter()
            result = self.search(
                GraphSearchRequest(
                    query=str(case["query"]),
                    scenario=str(case.get("scenario", "government_office")),
                    top_k=int(case.get("top_k", 8)),
                )
            )
            latencies.append((perf_counter() - started) * 1000)
            actual_skills = {item.node_id for item in result.candidate_skills}
            actual_tools = {item.node_id for item in result.candidate_mcp_tools}
            actual_policies = {item.node_id for item in result.related_policies}
            skill_score = _recall(case.get("expected_skills", []), actual_skills)
            tool_score = _recall(case.get("expected_tools", []), actual_tools)
            policy_score = _recall(case.get("expected_policies", []), actual_policies)
            route_score = float(result.intent == case.get("expected_intent"))
            mandatory_score = _recall(mandatory_ids, actual_skills)
            toolguard_score = float(not actual_tools or "skill.mcpguard_gov" in actual_skills)
            skill_scores.append(skill_score)
            tool_scores.append(tool_score)
            policy_scores.append(policy_score)
            route_scores.append(route_score)
            mandatory_scores.append(mandatory_score)
            toolguard_scores.append(toolguard_score)
            reductions.append(result.token_reduction_rate)
            if min(skill_score, tool_score, policy_score, route_score, mandatory_score, toolguard_score) < 1.0:
                failures.append(
                    {
                        "case_id": case.get("case_id"),
                        "intent": result.intent,
                        "skill_recall": skill_score,
                        "tool_recall": tool_score,
                        "policy_recall": policy_score,
                        "route_accuracy": route_score,
                    }
                )

        metrics = {
            "skill_recall_at_k": _average(skill_scores),
            "mcp_recall_at_k": _average(tool_scores),
            "policy_recall_at_k": _average(policy_scores),
            "route_accuracy": _average(route_scores),
            "mandatory_skill_coverage": _average(mandatory_scores),
            "toolguard_coverage": _average(toolguard_scores),
            "token_reduction_rate": _average(reductions),
            "average_retrieval_latency_ms": _average(latencies),
        }
        passed = (
            metrics["skill_recall_at_k"] >= 0.95
            and metrics["mcp_recall_at_k"] >= 0.95
            and metrics["policy_recall_at_k"] >= 0.95
            and metrics["route_accuracy"] >= 0.90
            and metrics["mandatory_skill_coverage"] == 1.0
            and metrics["toolguard_coverage"] == 1.0
            and metrics["token_reduction_rate"] >= 0.70
            and metrics["average_retrieval_latency_ms"] <= 300.0
        )
        return GraphEvaluationResult(case_count=len(validated_cases), passed=passed, failures=failures, **metrics)
