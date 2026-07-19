"""Strict public contracts for the Graphify-Gov capability graph."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NodeType(str, Enum):
    TASK_INTENT = "TaskIntent"
    SUB_AGENT = "SubAgent"
    SKILL = "Skill"
    MCP_TOOL = "MCPTool"
    POLICY = "Policy"
    RISK_TYPE = "RiskType"
    MODEL_PROVIDER = "ModelProvider"
    TEST_CASE = "TestCase"
    TRACE_PATTERN = "TracePattern"
    PERMISSION_ROLE = "PermissionRole"
    DATA_SOURCE = "DataSource"


class EdgeRelation(str, Enum):
    REQUIRES_SKILL = "requires_skill"
    ROUTES_TO_AGENT = "routes_to_agent"
    CAN_USE_SKILL = "can_use_skill"
    CAN_CALL_TOOL = "can_call_tool"
    GUARDS = "guards"
    GOVERNED_BY = "governed_by"
    PRODUCES_RISK = "produces_risk"
    REQUIRES_APPROVAL = "requires_approval"
    SUITABLE_FOR = "suitable_for"
    VALIDATES = "validates"
    SUGGESTS_PATH = "suggests_path"
    ACCEPTS_SOURCE = "accepts_source"


class CapabilityNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$", max_length=200)
    node_type: NodeType
    name: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=2000)
    token_card: str = Field(default="", max_length=2000)
    input_schema: list[str] = Field(default_factory=list, max_length=100)
    output_schema: list[str] = Field(default_factory=list, max_length=100)
    risk_level: str = Field(default="unknown", max_length=80)
    mandatory: bool = False
    path: str | None = Field(default=None, max_length=1000)
    enabled: bool = True
    version: str = Field(default="1.0.0", max_length=80)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_id: str
    relation: EdgeRelation
    target_id: str
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_type: str = Field(default="registry", max_length=80)


class GraphBuildResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_version: str
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    added_nodes: list[str] = Field(default_factory=list)
    updated_nodes: list[str] = Field(default_factory=list)
    removed_nodes: list[str] = Field(default_factory=list)
    signed_node_count: int = Field(default=0, ge=0)
    approved_nodes: list[str] = Field(default_factory=list)
    unchanged: bool = False


class NodeGovernanceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")
    key_id: str = Field(min_length=1, max_length=80)
    approval_status: str = Field(pattern=r"^(approved|rejected)$")
    approved_by: str = Field(min_length=1, max_length=160)
    approved_at: str
    scan_risk_level: str = Field(default="unknown", max_length=80)
    scan_risk_score: int = Field(default=0, ge=0, le=100)


class TracePatternRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_id: str = Field(pattern=r"^trace\.[0-9a-f]{24}$")
    intent_id: str = Field(pattern=r"^intent\.[a-z0-9_]+$")
    path: list[str] = Field(min_length=1, max_length=100)
    success_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    success_rate: float = Field(ge=0.0, le=1.0)
    last_trace_id: str = Field(min_length=1, max_length=160)
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")
    key_id: str = Field(min_length=1, max_length=80)
    updated_at: str


class TraceLearningResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    reason: str
    pattern: TracePatternRecord


class CandidateCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    name: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str
    mandatory: bool = False
    token_card: str = ""
    path: list[str] = Field(default_factory=list)


class GraphSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=50_000)
    scenario: str = Field(default="government_office", max_length=160)
    user_role: str = Field(default="staff", max_length=80)
    token_budget: int = Field(default=1200, ge=200, le=20_000)
    top_k: int = Field(default=8, ge=1, le=50)


class GraphSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str
    intent_score: float = Field(ge=0.0, le=1.0)
    retrieval_signals: dict[str, float] = Field(default_factory=dict)
    candidate_skills: list[CandidateCapability]
    candidate_mcp_tools: list[CandidateCapability]
    candidate_agents: list[CandidateCapability]
    related_policies: list[CandidateCapability]
    recommended_path: list[str]
    token_budget: int = Field(ge=200)
    estimated_prompt_tokens: int = Field(ge=0)
    within_token_budget: bool
    full_context_tokens: int = Field(ge=0)
    saved_tokens_estimate: int = Field(ge=0)
    token_reduction_rate: float = Field(ge=0.0, le=1.0)


class GraphHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    healthy: bool
    source_stale: bool
    orphan_nodes: list[str] = Field(default_factory=list)
    missing_schema_nodes: list[str] = Field(default_factory=list)
    unguarded_tools: list[str] = Field(default_factory=list)
    ungoverned_tools: list[str] = Field(default_factory=list)
    invalid_signature_nodes: list[str] = Field(default_factory=list)
    unapproved_nodes: list[str] = Field(default_factory=list)


class GraphStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_version: str
    source_digest: str
    node_count: int
    edge_count: int
    node_types: dict[str, int]
    relation_types: dict[str, int]
    full_context_tokens: int


class GraphEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_count: int
    skill_recall_at_k: float = Field(ge=0.0, le=1.0)
    mcp_recall_at_k: float = Field(ge=0.0, le=1.0)
    policy_recall_at_k: float = Field(ge=0.0, le=1.0)
    route_accuracy: float = Field(ge=0.0, le=1.0)
    mandatory_skill_coverage: float = Field(ge=0.0, le=1.0)
    toolguard_coverage: float = Field(ge=0.0, le=1.0)
    token_reduction_rate: float = Field(ge=0.0, le=1.0)
    average_retrieval_latency_ms: float = Field(ge=0.0)
    passed: bool
    failures: list[dict[str, Any]] = Field(default_factory=list)


class GraphEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=160)
    query: str = Field(min_length=1, max_length=50_000)
    scenario: str = Field(default="government_office", max_length=160)
    top_k: int = Field(default=8, ge=1, le=50)
    expected_intent: str
    expected_skills: list[str] = Field(default_factory=list)
    expected_tools: list[str] = Field(default_factory=list)
    expected_policies: list[str] = Field(default_factory=list)
