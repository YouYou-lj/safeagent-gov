"""Runnable LangGraph agent with a dependency-free sequential fallback."""

from __future__ import annotations

from typing import Any, TypedDict

from .nodes import execute_tools, finish, inspect_input, plan_task, start_trace
from .orchestrator import execute_route, route_task


class AgentState(TypedDict, total=False):
    task: str
    scenario: str
    user_role: str
    tenant_id: str
    user_id: str
    agent_id: str
    planner_mode: str | None
    document_text: str
    document_source: str
    skill_package_path: str | None
    trace_id: str
    input_risk: dict[str, Any]
    document_risk: dict[str, Any] | None
    input_analysis: dict[str, Any]
    blocked: bool
    routing_failed: bool
    routing_error: str
    router_plan: dict[str, Any]
    router_execution: dict[str, Any]
    skill_executions: list[dict[str, Any]]
    expected_skills: list[str]
    completed_skills: list[str]
    mandatory_skill_coverage: float
    toolguard_coverage: float
    plan: list[str]
    planner_info: dict[str, Any]
    planning_failed: bool
    planning_error: str
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    data_labels: list[str]
    final_output: str
    status: str


def _build_graph():
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        return None
    graph = StateGraph(AgentState)
    graph.add_node("trace", start_trace)
    graph.add_node("inspect", inspect_input)
    graph.add_node("route", route_task)
    graph.add_node("plan", plan_task)
    graph.add_node("analyze", execute_route)
    graph.add_node("tools", execute_tools)
    graph.add_node("finish", finish)
    graph.set_entry_point("trace")
    graph.add_edge("trace", "inspect")
    graph.add_conditional_edges(
        "inspect",
        lambda state: "finish" if state.get("blocked") else "route",
        {"finish": "finish", "route": "route"},
    )
    graph.add_conditional_edges(
        "route",
        lambda state: "finish" if state.get("routing_failed") else "plan",
        {"finish": "finish", "plan": "plan"},
    )
    graph.add_edge("plan", "analyze")
    graph.add_edge("analyze", "tools")
    graph.add_edge("tools", "finish")
    graph.add_edge("finish", END)
    return graph.compile()


GRAPH = _build_graph()


def run_agent(
    task: str,
    scenario: str = "政务知识问答",
    user_role: str = "staff",
    document_text: str = "",
    document_source: str = "uploaded_doc",
    skill_package_path: str | None = None,
    planner_mode: str | None = None,
    tenant_id: str = "demo-government",
    user_id: str | None = None,
    agent_id: str = "safeagent-demo",
) -> dict[str, Any]:
    """Run one deterministic, fully audited agent task."""
    state: AgentState = {
        "task": task,
        "scenario": scenario,
        "user_role": user_role,
        "tenant_id": tenant_id,
        "user_id": user_id or f"demo-user:{user_role}",
        "agent_id": agent_id,
        "document_text": document_text,
        "document_source": document_source,
        "skill_package_path": skill_package_path,
        "planner_mode": planner_mode,
    }
    if GRAPH:
        return GRAPH.invoke(state)
    current: dict[str, Any] = start_trace(dict(state))
    current = inspect_input(current)
    if not current.get("blocked"):
        current = route_task(current)
        if not current.get("routing_failed"):
            current = plan_task(current)
            current = execute_route(current)
            current = execute_tools(current)
    return finish(current)
