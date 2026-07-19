"""Authenticated Graphify-Gov build, retrieval, and governance endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import enforce_tenant, require_roles
from safeagent_gov.audit import create_trace, get_trace_identity, log_event
from safeagent_gov.auth import AuthClaims
from safeagent_gov.errors import (
    GraphifyConfigurationError,
    GraphifyNodeNotFoundError,
    GraphifyNotBuiltError,
)
from safeagent_gov.graphify import GraphifyService, GraphSearchRequest
from safeagent_gov.graphify.contracts import (
    CapabilityNode,
    GraphBuildResult,
    GraphEvaluationResult,
    GraphHealth,
    GraphSearchResult,
    GraphStats,
    TraceLearningResult,
)
from safeagent_gov.paths import resource_root

router = APIRouter(prefix="/api/graphify", tags=["Graphify-Gov"])
REPOSITORY_ROOT = resource_root()
EVALUATION_CASES_PATH = (
    REPOSITORY_ROOT
    / "research_technology"
    / "benchmarks"
    / "datasets"
    / "graphify_cases_v1"
    / "cases.json"
)
DEFAULT_GRAPHIFY_SERVICE = GraphifyService.from_environment()


def get_graphify_service() -> GraphifyService:
    return DEFAULT_GRAPHIFY_SERVICE


def _audit_change(principal: AuthClaims, action: str, result: dict) -> str:
    trace_id = create_trace(
        f"Graphify 能力图谱操作：{action}",
        "graphify_control_plane",
        tenant_id=principal.tenant_id,
        user_id=principal.sub,
        agent_id="graphify-api",
        retention_class="compliance",
        retention_days=365,
    )
    log_event(trace_id, "graphify_change", {"action": action, "result": result}, actor_id=principal.sub)
    log_event(trace_id, "final_output", {"status": "graphify_change_recorded", "output": action})
    return trace_id


@router.post("/build", response_model=GraphBuildResult)
def build_graph(
    principal: AuthClaims = Depends(require_roles("admin", "security_reviewer")),
    service: GraphifyService = Depends(get_graphify_service),
):
    try:
        result = service.build(reviewer_id=principal.sub)
        _audit_change(principal, "build", result.model_dump(mode="json"))
        return result
    except GraphifyConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/update", response_model=GraphBuildResult)
def update_graph(
    principal: AuthClaims = Depends(require_roles("admin", "security_reviewer")),
    service: GraphifyService = Depends(get_graphify_service),
):
    try:
        result = service.update(reviewer_id=principal.sub)
        _audit_change(principal, "update", result.model_dump(mode="json"))
        return result
    except GraphifyConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/search", response_model=GraphSearchResult)
def search_graph(
    request: GraphSearchRequest,
    principal: AuthClaims = Depends(require_roles("admin", "manager", "staff", "operator", "visitor", "auditor")),
    service: GraphifyService = Depends(get_graphify_service),
):
    try:
        return service.search(request.model_copy(update={"user_role": principal.role}))
    except GraphifyNotBuiltError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/node/{node_id}", response_model=CapabilityNode)
def get_node(
    node_id: str,
    _: AuthClaims = Depends(require_roles("admin", "manager", "staff", "operator", "visitor", "auditor")),
    service: GraphifyService = Depends(get_graphify_service),
):
    try:
        return service.store.get_node(node_id)
    except GraphifyNodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Graphify capability node not found") from exc


@router.post("/path/recommend")
def recommend_path(
    request: GraphSearchRequest,
    principal: AuthClaims = Depends(require_roles("admin", "manager", "staff", "operator", "visitor", "auditor")),
    service: GraphifyService = Depends(get_graphify_service),
):
    try:
        return service.recommend_path(request.model_copy(update={"user_role": principal.role}))
    except GraphifyNotBuiltError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/stats", response_model=GraphStats)
def graph_stats(
    _: AuthClaims = Depends(require_roles("admin", "manager", "operator", "auditor", "security_reviewer")),
    service: GraphifyService = Depends(get_graphify_service),
):
    try:
        return service.stats()
    except GraphifyNotBuiltError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/health", response_model=GraphHealth)
def graph_health(
    _: AuthClaims = Depends(require_roles("admin", "manager", "operator", "auditor", "security_reviewer")),
    service: GraphifyService = Depends(get_graphify_service),
):
    try:
        return service.health()
    except GraphifyNotBuiltError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GraphifyConfigurationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/eval", response_model=GraphEvaluationResult)
def evaluate_graph(
    _: AuthClaims = Depends(require_roles("admin", "security_reviewer", "auditor")),
    service: GraphifyService = Depends(get_graphify_service),
):
    if not EVALUATION_CASES_PATH.is_file():
        raise HTTPException(status_code=503, detail="本地 Graphify 评测数据未安装")
    try:
        cases = json.loads(EVALUATION_CASES_PATH.read_text(encoding="utf-8"))
        if not isinstance(cases, list):
            raise GraphifyConfigurationError("Graphify 评测文件根节点必须是数组")
        return service.evaluate(cases)
    except (OSError, UnicodeError, json.JSONDecodeError, GraphifyConfigurationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/learn/{trace_id}", response_model=TraceLearningResult)
def learn_trace_pattern(
    trace_id: str,
    principal: AuthClaims = Depends(require_roles("admin", "security_reviewer")),
    service: GraphifyService = Depends(get_graphify_service),
):
    try:
        enforce_tenant(get_trace_identity(trace_id)["tenant_id"], principal)
        result = service.learn_trace(trace_id)
        _audit_change(principal, "learn_trace_pattern", result.model_dump(mode="json"))
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="trace not found") from exc
    except GraphifyConfigurationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
