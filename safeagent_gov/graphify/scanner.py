"""Fail-closed repository scanner for Graphify-Gov capability metadata."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from safeagent_gov.errors import GraphifyConfigurationError, ModelGatewayConfigurationError
from safeagent_gov.model_gateway import ModelRegistry
from safeagent_gov.paths import research_component_dir

from .contracts import CapabilityEdge, CapabilityNode, EdgeRelation, NodeType


class IntentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    keywords: list[str] = Field(default_factory=list)
    semantic_examples: list[str] = Field(default_factory=list)
    scenarios: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    recommended_path: list[str] = Field(default_factory=list)


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    provider: str
    protocol: str
    network_access: bool


class DataSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    summary: str


class TestCaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    validates: list[str] = Field(min_length=1)


class RegistryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    active_policy_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    mandatory_skills: list[str]
    intents: dict[str, IntentConfig]
    agents: dict[str, AgentConfig]
    models: dict[str, ModelConfig]
    data_sources: dict[str, DataSourceConfig]
    test_cases: dict[str, TestCaseConfig]
    tool_risks: dict[str, str]


@dataclass(frozen=True)
class ScanSnapshot:
    graph_version: str
    source_digest: str
    full_context_tokens: int
    nodes: tuple[CapabilityNode, ...]
    edges: tuple[CapabilityEdge, ...]


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _identifier(prefix: str, raw: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", raw.casefold().replace("-", "_")).strip("_")
    if not normalized:
        raise GraphifyConfigurationError(f"无法为能力生成稳定标识: {raw!r}")
    return f"{prefix}.{normalized}"


def _risk_level(tool_name: str) -> str:
    if tool_name in {"file_delete", "shell_exec", "db_write"}:
        return "critical"
    if tool_name in {"send_email", "api_call"}:
        return "high"
    return "medium"


class RepositoryScanner:
    """Read only fixed manifest/config locations without importing target code."""

    def __init__(self, repository_root: Path, registry_path: Path | None = None):
        self.repository_root = repository_root.resolve()
        self.registry_path = (registry_path or self.repository_root / "configs" / "graphify_registry.yaml").resolve()

    def _safe_read(self, path: Path) -> str:
        resolved = path.resolve()
        if path.is_symlink() or (resolved != self.repository_root and self.repository_root not in resolved.parents):
            raise GraphifyConfigurationError(f"Graphify 输入越出仓库或使用符号链接: {path}")
        try:
            return resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise GraphifyConfigurationError(f"无法读取 Graphify 输入: {path}") from exc

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        try:
            loaded = yaml.safe_load(self._safe_read(path))
        except yaml.YAMLError as exc:
            raise GraphifyConfigurationError(f"无效 YAML: {path}") from exc
        if not isinstance(loaded, dict):
            raise GraphifyConfigurationError(f"YAML 根节点必须是对象: {path}")
        return loaded

    def _load_registry(self) -> RegistryConfig:
        try:
            return RegistryConfig.model_validate(self._load_yaml(self.registry_path))
        except ValidationError as exc:
            raise GraphifyConfigurationError(f"Graphify 注册表不符合 Schema: {exc}") from exc

    def _function_parameters(self, server_path: Path, capability: str) -> list[str]:
        try:
            tree = ast.parse(self._safe_read(server_path), filename=str(server_path))
        except SyntaxError as exc:
            raise GraphifyConfigurationError(f"MCP Server 无法解析: {server_path}") from exc
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == capability:
                args = [item.arg for item in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)]
                return [item for item in args if item not in {"self", "cls", "_"}]
        raise GraphifyConfigurationError(f"manifest capability 没有对应函数: {capability} ({server_path})")

    @staticmethod
    def _edge(source_id: str, relation: EdgeRelation, target_id: str, source_type: str = "registry") -> CapabilityEdge:
        payload = {"source_id": source_id, "relation": relation.value, "target_id": target_id, "source_type": source_type}
        return CapabilityEdge(
            edge_id=_canonical_hash(payload),
            source_id=source_id,
            relation=relation,
            target_id=target_id,
            source_type=source_type,
        )

    def scan(self) -> ScanSnapshot:
        registry = self._load_registry()
        skills_root = research_component_dir("skills", repository_root=self.repository_root)
        mcp_root = research_component_dir("mcp", repository_root=self.repository_root)
        source_texts: dict[str, str] = {str(self.registry_path.relative_to(self.repository_root)): self._safe_read(self.registry_path)}
        model_gateway_path = self.repository_root / "configs" / "model_gateway.yaml"
        model_gateway_text = self._safe_read(model_gateway_path)
        source_texts[str(model_gateway_path.relative_to(self.repository_root))] = model_gateway_text
        try:
            model_registry = ModelRegistry(model_gateway_path)
            model_registry.load()
            model_gateway = model_registry.config()
        except ModelGatewayConfigurationError as exc:
            raise GraphifyConfigurationError("Model Gateway 注册表无效，拒绝构建能力图谱") from exc
        nodes: dict[str, CapabilityNode] = {}
        edges: dict[str, CapabilityEdge] = {}

        for manifest_path in sorted(skills_root.glob("*/manifest.yaml")):
            manifest = self._load_yaml(manifest_path)
            name = str(manifest.get("name", "")).strip()
            if not name:
                raise GraphifyConfigurationError(f"Skill manifest 缺少 name: {manifest_path}")
            inputs = manifest.get("inputs", [])
            outputs = manifest.get("outputs", [])
            if not isinstance(inputs, list) or not isinstance(outputs, list):
                raise GraphifyConfigurationError(f"Skill inputs/outputs 必须为数组: {manifest_path}")
            node_id = _identifier("skill", name)
            manifest_text = self._safe_read(manifest_path)
            relative_manifest = str(manifest_path.relative_to(self.repository_root))
            source_texts[relative_manifest] = manifest_text
            skill_doc = manifest_path.parent / "SKILL.md"
            if skill_doc.exists():
                source_texts[str(skill_doc.relative_to(self.repository_root))] = self._safe_read(skill_doc)
            mandatory = name in registry.mandatory_skills
            nodes[node_id] = CapabilityNode(
                node_id=node_id,
                node_type=NodeType.SKILL,
                name=name,
                summary=f"{name} 安全能力",
                token_card=f"{name}：输入 {', '.join(map(str, inputs)) or '无'}；输出 {', '.join(map(str, outputs)) or '无'}。",
                input_schema=[str(item) for item in inputs],
                output_schema=[str(item) for item in outputs],
                risk_level="security_mandatory" if mandatory else "security_routed",
                mandatory=mandatory,
                path=str(manifest_path.parent.relative_to(self.repository_root)),
                version=str(manifest.get("version", "1.0.0")),
                content_hash=hashlib.sha256(manifest_text.encode("utf-8")).hexdigest(),
                metadata={"entrypoint": manifest.get("entrypoint"), "permissions": manifest.get("permissions", {})},
            )

        tool_nodes: dict[str, CapabilityNode] = {}
        for manifest_path in sorted((mcp_root / "servers").glob("*/manifest.yaml")):
            manifest = self._load_yaml(manifest_path)
            capabilities = manifest.get("capabilities", [])
            if not isinstance(capabilities, list) or not capabilities:
                raise GraphifyConfigurationError(f"MCP manifest 缺少 capabilities: {manifest_path}")
            manifest_text = self._safe_read(manifest_path)
            source_texts[str(manifest_path.relative_to(self.repository_root))] = manifest_text
            server_path = manifest_path.parent / "server.py"
            source_texts[str(server_path.relative_to(self.repository_root))] = self._safe_read(server_path)
            for capability_value in capabilities:
                capability = str(capability_value)
                node_id = _identifier("mcp", capability)
                parameters = self._function_parameters(server_path, capability)
                node = CapabilityNode(
                    node_id=node_id,
                    node_type=NodeType.MCP_TOOL,
                    name=capability,
                    summary=f"{manifest.get('name', manifest_path.parent.name)} MCP Server 提供的受控工具",
                    token_card=f"{capability}({', '.join(parameters)})；风险等级 {_risk_level(capability)}；必须经 MCPGuard。",
                    input_schema=parameters,
                    output_schema=["status", "result"],
                    risk_level=_risk_level(capability),
                    path=str(manifest_path.parent.relative_to(self.repository_root)),
                    version=str(manifest.get("version", "1.0.0")),
                    content_hash=_canonical_hash({"manifest": manifest, "parameters": parameters}),
                    metadata={"simulation_only": bool(manifest.get("simulation_only", False))},
                )
                if node_id in tool_nodes:
                    raise GraphifyConfigurationError(f"重复 MCP capability: {capability}")
                tool_nodes[node_id] = node
                nodes[node_id] = node

        policy_paths = sorted((mcp_root / "policies" / "versions").glob("*.yaml"))
        if not policy_paths:
            raise GraphifyConfigurationError("Graphify 未找到版本化 MCP 策略")
        for policy_path in policy_paths:
            policy = self._load_yaml(policy_path)
            policy_text = self._safe_read(policy_path)
            source_texts[str(policy_path.relative_to(self.repository_root))] = policy_text
            version = str(policy.get("version") or policy_path.stem)
            policy_id = _identifier("policy", f"tool_policy_{version}")
            nodes[policy_id] = CapabilityNode(
                node_id=policy_id,
                node_type=NodeType.POLICY,
                name=f"MCP Tool Policy {version}",
                summary="版本化 MCP 工具授权、审批与失败关闭策略",
                token_card=f"工具策略 {version}：所有 MCP 工具执行前必须加载并裁决。",
                path=str(policy_path.relative_to(self.repository_root)),
                version=version,
                content_hash=hashlib.sha256(policy_text.encode("utf-8")).hexdigest(),
            )
        stable_policy_id = _identifier("policy", f"tool_policy_{registry.active_policy_version}")
        if stable_policy_id not in nodes:
            raise GraphifyConfigurationError(
                f"Graphify active_policy_version 不存在: {registry.active_policy_version}"
            )

        for intent_key, intent in registry.intents.items():
            node_id = _identifier("intent", intent_key)
            nodes[node_id] = CapabilityNode(
                node_id=node_id,
                node_type=NodeType.TASK_INTENT,
                name=intent.name,
                summary=f"{intent.name}任务意图",
                token_card=f"意图 {intent.name}；关键词：{', '.join(intent.keywords)}。",
                version=registry.version,
                content_hash=_canonical_hash(intent.model_dump(mode="json")),
                metadata={
                    "keywords": intent.keywords,
                    "semantic_examples": intent.semantic_examples,
                    "scenarios": intent.scenarios,
                    "recommended_path": intent.recommended_path,
                },
            )

        for agent_key, agent in registry.agents.items():
            node_id = _identifier("agent", agent_key)
            nodes[node_id] = CapabilityNode(
                node_id=node_id,
                node_type=NodeType.SUB_AGENT,
                name=agent.name,
                summary=f"{agent.name} 专业子智能体",
                token_card=f"{agent.name}：可调用 {', '.join(agent.skills + agent.tools) or '无外部能力'}。",
                version=registry.version,
                content_hash=_canonical_hash(agent.model_dump(mode="json")),
            )

        for model_key, model in registry.models.items():
            node_id = _identifier("model", model_key)
            nodes[node_id] = CapabilityNode(
                node_id=node_id,
                node_type=NodeType.MODEL_PROVIDER,
                name=model.name,
                summary=f"{model.provider} / {model.protocol}",
                token_card=f"{model.name}，协议 {model.protocol}，网络访问 {model.network_access}。",
                version=registry.version,
                content_hash=_canonical_hash(model.model_dump(mode="json")),
                metadata=model.model_dump(mode="json"),
            )

        for source_key, source in registry.data_sources.items():
            node_id = _identifier("source", source_key)
            nodes[node_id] = CapabilityNode(
                node_id=node_id,
                node_type=NodeType.DATA_SOURCE,
                name=source.name,
                summary=source.summary,
                token_card=f"输入来源：{source.name}；{source.summary}",
                risk_level="untrusted_input",
                version=registry.version,
                content_hash=_canonical_hash(source.model_dump(mode="json")),
            )

        for case_key, case in registry.test_cases.items():
            node_id = _identifier("case", case_key)
            nodes[node_id] = CapabilityNode(
                node_id=node_id,
                node_type=NodeType.TEST_CASE,
                name=case.name,
                summary=f"验证 {', '.join(case.validates)}",
                token_card=f"测试案例 {case.name}：验证已注册能力与治理路径。",
                risk_level="verification",
                version=registry.version,
                content_hash=_canonical_hash(case.model_dump(mode="json")),
                metadata={"validates": case.validates},
            )

        # Model Gateway is the authoritative multi-provider registry. Graphify
        # records only secret-free routing metadata and never exposes endpoints
        # or credential environment-variable names through capability APIs.
        for provider_key, provider in model_gateway.providers.items():
            node_id = _identifier("model", provider_key)
            public_metadata = {
                "model": provider.model,
                "protocol": provider.protocol.value,
                "network_access": provider.network_access,
                "private_deployment": provider.private_deployment,
                "enabled": provider.enabled,
                "capabilities": sorted(item.value for item in provider.capabilities),
                "task_types": sorted(provider.task_types),
            }
            nodes[node_id] = CapabilityNode(
                node_id=node_id,
                node_type=NodeType.MODEL_PROVIDER,
                name=provider.display_name,
                summary=f"Model Gateway / {provider.protocol.value}",
                token_card=(
                    f"{provider.display_name}；协议 {provider.protocol.value}；"
                    f"私有部署 {provider.private_deployment}；启用 {provider.enabled}。"
                ),
                risk_level="private_model" if provider.private_deployment else "external_model",
                path=str(model_gateway_path.relative_to(self.repository_root)),
                enabled=provider.enabled,
                version=model_gateway.version,
                content_hash=_canonical_hash(public_metadata),
                metadata=public_metadata,
            )

        role_id = "role.security_reviewer"
        nodes[role_id] = CapabilityNode(
            node_id=role_id,
            node_type=NodeType.PERMISSION_ROLE,
            name="security_reviewer",
            summary="高风险能力图谱节点与工具动作的审批角色",
            token_card="安全复核员：处理高风险能力注册与执行审批。",
            version=registry.version,
            content_hash=_canonical_hash({"role": "security_reviewer", "version": registry.version}),
        )

        for risk_name in sorted(set(registry.tool_risks.values())):
            node_id = _identifier("risk", risk_name)
            nodes[node_id] = CapabilityNode(
                node_id=node_id,
                node_type=NodeType.RISK_TYPE,
                name=risk_name,
                summary=f"{risk_name} 风险",
                token_card=f"风险类型：{risk_name}。",
                version=registry.version,
                content_hash=_canonical_hash({"risk": risk_name, "version": registry.version}),
            )
            edge = self._edge(node_id, EdgeRelation.REQUIRES_APPROVAL, role_id)
            edges[edge.edge_id] = edge

        skill_ids = {node_id for node_id, node in nodes.items() if node.node_type == NodeType.SKILL}
        tool_ids = set(tool_nodes)
        agent_ids = {node_id for node_id, node in nodes.items() if node.node_type == NodeType.SUB_AGENT}
        model_ids = {node_id for node_id, node in nodes.items() if node.node_type == NodeType.MODEL_PROVIDER}
        source_ids = {node_id for node_id, node in nodes.items() if node.node_type == NodeType.DATA_SOURCE}

        for mandatory_name in registry.mandatory_skills:
            if _identifier("skill", mandatory_name) not in skill_ids:
                raise GraphifyConfigurationError(f"mandatory_skills 引用不存在的 Skill: {mandatory_name}")

        for intent_key, intent in registry.intents.items():
            intent_id = _identifier("intent", intent_key)
            for skill_name in intent.required_skills:
                target = _identifier("skill", skill_name)
                if target not in skill_ids:
                    raise GraphifyConfigurationError(f"意图 {intent_key} 引用不存在的 Skill: {skill_name}")
                edge = self._edge(intent_id, EdgeRelation.REQUIRES_SKILL, target)
                edges[edge.edge_id] = edge
            for agent_name in intent.agents:
                target = _identifier("agent", agent_name)
                if target not in agent_ids:
                    raise GraphifyConfigurationError(f"意图 {intent_key} 引用不存在的 Agent: {agent_name}")
                edge = self._edge(intent_id, EdgeRelation.ROUTES_TO_AGENT, target)
                edges[edge.edge_id] = edge
            for model_name in intent.models:
                target = _identifier("model", model_name)
                if target not in model_ids:
                    raise GraphifyConfigurationError(f"意图 {intent_key} 引用不存在的 Model: {model_name}")
                edge = self._edge(intent_id, EdgeRelation.SUITABLE_FOR, target)
                edges[edge.edge_id] = edge
            for source_name in intent.data_sources:
                target = _identifier("source", source_name)
                if target not in source_ids:
                    raise GraphifyConfigurationError(f"意图 {intent_key} 引用不存在的数据来源: {source_name}")
                edge = self._edge(intent_id, EdgeRelation.ACCEPTS_SOURCE, target)
                edges[edge.edge_id] = edge

        for agent_key, agent in registry.agents.items():
            agent_id = _identifier("agent", agent_key)
            for skill_name in agent.skills:
                target = _identifier("skill", skill_name)
                if target not in skill_ids:
                    raise GraphifyConfigurationError(f"Agent {agent_key} 引用不存在的 Skill: {skill_name}")
                edge = self._edge(agent_id, EdgeRelation.CAN_USE_SKILL, target)
                edges[edge.edge_id] = edge
            for tool_name in agent.tools:
                target = _identifier("mcp", tool_name)
                if target not in tool_ids:
                    raise GraphifyConfigurationError(f"Agent {agent_key} 引用不存在的 MCP Tool: {tool_name}")
                edge = self._edge(agent_id, EdgeRelation.CAN_CALL_TOOL, target)
                edges[edge.edge_id] = edge

        guard_id = _identifier("skill", "mcpguard-gov")
        if guard_id not in skill_ids:
            raise GraphifyConfigurationError("缺少保护 MCP 工具的 mcpguard-gov")
        for tool_id in sorted(tool_ids):
            guard_edge = self._edge(guard_id, EdgeRelation.GUARDS, tool_id, source_type="manifest")
            policy_edge = self._edge(tool_id, EdgeRelation.GOVERNED_BY, stable_policy_id, source_type="policy")
            edges[guard_edge.edge_id] = guard_edge
            edges[policy_edge.edge_id] = policy_edge
            tool_risk_name = registry.tool_risks.get(nodes[tool_id].name)
            if tool_risk_name:
                risk_edge = self._edge(tool_id, EdgeRelation.PRODUCES_RISK, _identifier("risk", tool_risk_name))
                edges[risk_edge.edge_id] = risk_edge

        for case_key, case in registry.test_cases.items():
            case_id = _identifier("case", case_key)
            for target in case.validates:
                if target not in nodes:
                    raise GraphifyConfigurationError(f"测试案例 {case_key} 引用不存在的能力节点: {target}")
                edge = self._edge(case_id, EdgeRelation.VALIDATES, target, source_type="test_registry")
                edges[edge.edge_id] = edge

        for edge in edges.values():
            if edge.source_id not in nodes or edge.target_id not in nodes:
                raise GraphifyConfigurationError(f"能力边引用不存在节点: {edge.source_id} -> {edge.target_id}")

        source_digest = _canonical_hash(
            {relative: hashlib.sha256(text.encode("utf-8")).hexdigest() for relative, text in sorted(source_texts.items())}
        )
        full_context_tokens = max(1, sum(len(text) for text in source_texts.values()) // 4)
        return ScanSnapshot(
            graph_version=registry.version,
            source_digest=source_digest,
            full_context_tokens=full_context_tokens,
            nodes=tuple(sorted(nodes.values(), key=lambda node: node.node_id)),
            edges=tuple(sorted(edges.values(), key=lambda edge: edge.edge_id)),
        )
