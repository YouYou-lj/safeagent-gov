"""Transactional SQLite persistence and NetworkX projection for Graphify-Gov."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import networkx as nx

from safeagent_gov.errors import GraphifyConfigurationError, GraphifyNodeNotFoundError, GraphifyNotBuiltError

from .contracts import (
    CapabilityEdge,
    CapabilityNode,
    EdgeRelation,
    GraphBuildResult,
    GraphStats,
    NodeGovernanceRecord,
    NodeType,
    TracePatternRecord,
)
from .scanner import ScanSnapshot
from .signing import (
    sign_node,
    sign_trace_pattern,
    signing_key_id,
    verify_node,
    verify_trace_pattern,
)


class GraphStore:
    """Store one active capability snapshot with atomic replacement semantics."""

    def __init__(self, database_path: Path):
        self.database_path = database_path.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS capability_nodes (
                    node_id TEXT PRIMARY KEY,
                    node_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    token_card TEXT NOT NULL,
                    input_schema_json TEXT NOT NULL,
                    output_schema_json TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    mandatory INTEGER NOT NULL CHECK (mandatory IN (0, 1)),
                    path TEXT,
                    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                    version TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS capability_edges (
                    edge_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES capability_nodes(node_id) ON DELETE CASCADE,
                    relation TEXT NOT NULL,
                    target_id TEXT NOT NULL REFERENCES capability_nodes(node_id) ON DELETE CASCADE,
                    weight REAL NOT NULL,
                    confidence REAL NOT NULL,
                    source_type TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_capability_edges_source
                    ON capability_edges(source_id, relation);
                CREATE INDEX IF NOT EXISTS idx_capability_edges_target
                    ON capability_edges(target_id, relation);

                CREATE TABLE IF NOT EXISTS capability_graph_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS capability_node_governance (
                    node_id TEXT PRIMARY KEY REFERENCES capability_nodes(node_id) ON DELETE CASCADE,
                    content_hash TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    approval_status TEXT NOT NULL CHECK (approval_status IN ('approved', 'rejected')),
                    approved_by TEXT NOT NULL,
                    approved_at TEXT NOT NULL,
                    scan_risk_level TEXT NOT NULL,
                    scan_risk_score INTEGER NOT NULL CHECK (scan_risk_score BETWEEN 0 AND 100)
                );

                CREATE TABLE IF NOT EXISTS trace_patterns (
                    pattern_id TEXT PRIMARY KEY,
                    intent_id TEXT NOT NULL,
                    path_json TEXT NOT NULL,
                    success_count INTEGER NOT NULL CHECK (success_count >= 0),
                    failure_count INTEGER NOT NULL CHECK (failure_count >= 0),
                    last_trace_id TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(intent_id, path_json)
                );
                CREATE INDEX IF NOT EXISTS idx_trace_patterns_intent
                    ON trace_patterns(intent_id, success_count, failure_count);

                CREATE TABLE IF NOT EXISTS trace_pattern_observations (
                    trace_id TEXT PRIMARY KEY,
                    pattern_id TEXT NOT NULL REFERENCES trace_patterns(pattern_id),
                    succeeded INTEGER NOT NULL CHECK (succeeded IN (0, 1)),
                    recorded_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _node_from_row(row: sqlite3.Row) -> CapabilityNode:
        return CapabilityNode(
            node_id=row["node_id"],
            node_type=NodeType(row["node_type"]),
            name=row["name"],
            summary=row["summary"],
            token_card=row["token_card"],
            input_schema=json.loads(row["input_schema_json"]),
            output_schema=json.loads(row["output_schema_json"]),
            risk_level=row["risk_level"],
            mandatory=bool(row["mandatory"]),
            path=row["path"],
            enabled=bool(row["enabled"]),
            version=row["version"],
            content_hash=row["content_hash"],
            metadata=json.loads(row["metadata_json"]),
        )

    @staticmethod
    def _edge_from_row(row: sqlite3.Row) -> CapabilityEdge:
        return CapabilityEdge(
            edge_id=row["edge_id"],
            source_id=row["source_id"],
            relation=EdgeRelation(row["relation"]),
            target_id=row["target_id"],
            weight=float(row["weight"]),
            confidence=float(row["confidence"]),
            source_type=row["source_type"],
        )

    def node_hashes(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT node_id, content_hash FROM capability_nodes").fetchall()
        return {str(row["node_id"]): str(row["content_hash"]) for row in rows}

    def replace(
        self,
        snapshot: ScanSnapshot,
        *,
        reviewer_id: str | None = None,
        registration_scans: dict[str, dict[str, Any]] | None = None,
    ) -> GraphBuildResult:
        scans = registration_scans or {}
        with self._connect() as connection:
            previous_rows = connection.execute("SELECT node_id, content_hash FROM capability_nodes").fetchall()
            previous = {row["node_id"]: row["content_hash"] for row in previous_rows}
            previous_edges = {
                row["edge_id"] for row in connection.execute("SELECT edge_id FROM capability_edges").fetchall()
            }
            previous_governance = {
                row["node_id"]: row
                for row in connection.execute("SELECT * FROM capability_node_governance").fetchall()
            }
            previous_digest_row = connection.execute(
                "SELECT value FROM capability_graph_meta WHERE key = 'source_digest'"
            ).fetchone()
            current = {node.node_id: node.content_hash for node in snapshot.nodes}
            current_edges = {edge.edge_id for edge in snapshot.edges}
            added = sorted(current.keys() - previous.keys())
            removed = sorted(previous.keys() - current.keys())
            updated = sorted(node_id for node_id in current.keys() & previous.keys() if current[node_id] != previous[node_id])
            unchanged = (
                bool(previous)
                and previous_digest_row is not None
                and previous_digest_row["value"] == snapshot.source_digest
                and previous == current
                and previous_edges == current_edges
            )

            protected_types = {NodeType.SKILL, NodeType.MCP_TOOL}
            changed_protected = sorted(
                node.node_id
                for node in snapshot.nodes
                if node.node_type in protected_types and previous.get(node.node_id) != node.content_hash
            )
            if previous and changed_protected and not reviewer_id:
                raise GraphifyConfigurationError(
                    f"高风险能力节点变更需要安全复核员批准: {changed_protected}"
                )

            now = datetime.now(timezone.utc).isoformat()
            governance_rows: list[tuple[object, ...]] = []
            approved_nodes: list[str] = []
            for node in snapshot.nodes:
                existing = previous_governance.get(node.node_id)
                same = existing is not None and existing["content_hash"] == node.content_hash
                scan = scans.get(node.node_id, {})
                if same:
                    assert existing is not None
                    approved_by = str(existing["approved_by"])
                    approved_at = str(existing["approved_at"])
                    scan_level = str(existing["scan_risk_level"])
                    scan_score = int(existing["scan_risk_score"])
                else:
                    if node.node_type in protected_types:
                        approved_by = reviewer_id or "repository-bootstrap"
                        approved_nodes.append(node.node_id)
                    else:
                        approved_by = "graph-policy-auto"
                    approved_at = now
                    scan_level = str(scan.get("risk_level", "not_applicable"))
                    scan_score = int(scan.get("risk_score", 0))
                governance_rows.append(
                    (
                        node.node_id,
                        node.content_hash,
                        sign_node(node.node_id, node.content_hash, node.version),
                        signing_key_id(),
                        "approved",
                        approved_by,
                        approved_at,
                        scan_level,
                        scan_score,
                    )
                )

            if not unchanged:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DELETE FROM capability_edges")
                connection.execute("DELETE FROM capability_nodes")
                connection.executemany(
                    """
                    INSERT INTO capability_nodes (
                        node_id, node_type, name, summary, token_card,
                        input_schema_json, output_schema_json, risk_level,
                        mandatory, path, enabled, version, content_hash, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            node.node_id,
                            node.node_type.value,
                            node.name,
                            node.summary,
                            node.token_card,
                            json.dumps(node.input_schema, ensure_ascii=False, separators=(",", ":")),
                            json.dumps(node.output_schema, ensure_ascii=False, separators=(",", ":")),
                            node.risk_level,
                            int(node.mandatory),
                            node.path,
                            int(node.enabled),
                            node.version,
                            node.content_hash,
                            json.dumps(node.metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                        )
                        for node in snapshot.nodes
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO capability_node_governance(
                        node_id, content_hash, signature, key_id, approval_status,
                        approved_by, approved_at, scan_risk_level, scan_risk_score
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    governance_rows,
                )
                connection.executemany(
                    """
                    INSERT INTO capability_edges (
                        edge_id, source_id, relation, target_id, weight, confidence, source_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            edge.edge_id,
                            edge.source_id,
                            edge.relation.value,
                            edge.target_id,
                            edge.weight,
                            edge.confidence,
                            edge.source_type,
                        )
                        for edge in snapshot.edges
                    ],
                )
                meta = {
                    "graph_version": snapshot.graph_version,
                    "source_digest": snapshot.source_digest,
                    "full_context_tokens": str(snapshot.full_context_tokens),
                }
                connection.executemany(
                    """
                    INSERT INTO capability_graph_meta(key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    sorted(meta.items()),
                )
                connection.commit()

        return GraphBuildResult(
            graph_version=snapshot.graph_version,
            source_digest=snapshot.source_digest,
            node_count=len(snapshot.nodes),
            edge_count=len(snapshot.edges),
            added_nodes=added,
            updated_nodes=updated,
            removed_nodes=removed,
            signed_node_count=len(snapshot.nodes),
            approved_nodes=approved_nodes,
            unchanged=unchanged,
        )

    def list_governance(self) -> list[NodeGovernanceRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM capability_node_governance ORDER BY node_id"
            ).fetchall()
        return [NodeGovernanceRecord.model_validate(dict(row)) for row in rows]

    def verify_governance(self) -> tuple[list[str], list[str]]:
        nodes = {node.node_id: node for node in self.list_nodes()}
        governance = {record.node_id: record for record in self.list_governance()}
        invalid = sorted(
            node_id
            for node_id, node in nodes.items()
            if node_id not in governance
            or governance[node_id].content_hash != node.content_hash
            or not verify_node(node.node_id, node.content_hash, node.version, governance[node_id].signature)
        )
        unapproved = sorted(
            node_id for node_id, record in governance.items() if record.approval_status != "approved"
        )
        return invalid, unapproved

    @staticmethod
    def _pattern_from_row(row: sqlite3.Row) -> TracePatternRecord:
        successes = int(row["success_count"])
        failures = int(row["failure_count"])
        total = successes + failures
        return TracePatternRecord(
            pattern_id=row["pattern_id"],
            intent_id=row["intent_id"],
            path=json.loads(row["path_json"]),
            success_count=successes,
            failure_count=failures,
            success_rate=successes / total if total else 0.0,
            last_trace_id=row["last_trace_id"],
            signature=row["signature"],
            key_id=row["key_id"],
            updated_at=row["updated_at"],
        )

    def record_trace_pattern(
        self,
        intent_id: str,
        path: list[str],
        *,
        success: bool,
        trace_id: str,
    ) -> TracePatternRecord:
        path_json = json.dumps(path, ensure_ascii=False, separators=(",", ":"))
        pattern_id = "trace." + hashlib.sha256(f"{intent_id}:{path_json}".encode()).hexdigest()[:24]
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                "SELECT 1 FROM trace_pattern_observations WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()
            if duplicate is not None:
                raise GraphifyConfigurationError(f"trace 已用于路径学习，拒绝重复计数: {trace_id}")
            existing_nodes = {
                str(row["node_id"])
                for row in connection.execute(
                    f"SELECT node_id FROM capability_nodes WHERE node_id IN ({','.join('?' for _ in path)})",
                    path,
                ).fetchall()
            }
            if intent_id not in {
                str(row["node_id"])
                for row in connection.execute(
                    "SELECT node_id FROM capability_nodes WHERE node_id = ? AND node_type = ?",
                    (intent_id, NodeType.TASK_INTENT.value),
                ).fetchall()
            }:
                raise GraphifyConfigurationError(f"未知任务意图，拒绝学习: {intent_id}")
            if len(existing_nodes) != len(set(path)):
                missing = sorted(set(path) - existing_nodes)
                raise GraphifyConfigurationError(f"路径包含未注册能力节点，拒绝学习: {missing}")
            row = connection.execute(
                "SELECT * FROM trace_patterns WHERE intent_id = ? AND path_json = ?",
                (intent_id, path_json),
            ).fetchone()
            successes = (int(row["success_count"]) if row else 0) + int(success)
            failures = (int(row["failure_count"]) if row else 0) + int(not success)
            signature = sign_trace_pattern(intent_id, path_json, successes, failures, trace_id)
            connection.execute(
                """
                INSERT INTO trace_patterns(
                    pattern_id, intent_id, path_json, success_count, failure_count,
                    last_trace_id, signature, key_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(intent_id, path_json) DO UPDATE SET
                    success_count = excluded.success_count,
                    failure_count = excluded.failure_count,
                    last_trace_id = excluded.last_trace_id,
                    signature = excluded.signature,
                    key_id = excluded.key_id,
                    updated_at = excluded.updated_at
                """,
                (
                    pattern_id,
                    intent_id,
                    path_json,
                    successes,
                    failures,
                    trace_id,
                    signature,
                    signing_key_id(),
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO trace_pattern_observations(trace_id, pattern_id, succeeded, recorded_at)
                VALUES (?, ?, ?, ?)
                """,
                (trace_id, pattern_id, int(success), now),
            )
            stored = connection.execute(
                "SELECT * FROM trace_patterns WHERE intent_id = ? AND path_json = ?",
                (intent_id, path_json),
            ).fetchone()
            connection.commit()
        assert stored is not None
        return self._pattern_from_row(stored)

    def list_trace_patterns(self, intent_id: str | None = None) -> list[TracePatternRecord]:
        with self._connect() as connection:
            if intent_id:
                rows = connection.execute(
                    "SELECT * FROM trace_patterns WHERE intent_id = ? ORDER BY pattern_id",
                    (intent_id,),
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM trace_patterns ORDER BY pattern_id").fetchall()
        records = [self._pattern_from_row(row) for row in rows]
        for row, record in zip(rows, records, strict=True):
            if not verify_trace_pattern(
                record.intent_id,
                row["path_json"],
                record.success_count,
                record.failure_count,
                record.last_trace_id,
                record.signature,
            ):
                raise GraphifyConfigurationError(f"TracePattern 签名无效: {record.pattern_id}")
        return records

    def best_trace_pattern(
        self,
        intent_id: str,
        *,
        minimum_successes: int = 2,
        minimum_success_rate: float = 0.8,
    ) -> TracePatternRecord | None:
        eligible = [
            record
            for record in self.list_trace_patterns(intent_id)
            if record.success_count >= minimum_successes and record.success_rate >= minimum_success_rate
        ]
        return max(eligible, key=lambda item: (item.success_rate, item.success_count, item.pattern_id), default=None)

    def metadata(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT key, value FROM capability_graph_meta").fetchall()
        metadata = {row["key"]: row["value"] for row in rows}
        if "source_digest" not in metadata:
            raise GraphifyNotBuiltError("Graphify 能力图谱尚未构建")
        return metadata

    def list_nodes(self) -> list[CapabilityNode]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM capability_nodes ORDER BY node_id").fetchall()
        return [self._node_from_row(row) for row in rows]

    def list_edges(self) -> list[CapabilityEdge]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM capability_edges ORDER BY edge_id").fetchall()
        return [self._edge_from_row(row) for row in rows]

    def get_node(self, node_id: str) -> CapabilityNode:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM capability_nodes WHERE node_id = ?", (node_id,)).fetchone()
        if row is None:
            raise GraphifyNodeNotFoundError(node_id)
        return self._node_from_row(row)

    def load_graph(self) -> nx.MultiDiGraph:
        nodes = self.list_nodes()
        if not nodes:
            raise GraphifyNotBuiltError("Graphify 能力图谱尚未构建")
        graph = nx.MultiDiGraph()
        for node in nodes:
            graph.add_node(node.node_id, capability=node)
        for edge in self.list_edges():
            graph.add_edge(
                edge.source_id,
                edge.target_id,
                key=edge.edge_id,
                relation=edge.relation.value,
                weight=edge.weight,
                confidence=edge.confidence,
                source_type=edge.source_type,
            )
        for pattern in self.list_trace_patterns():
            content_hash = hashlib.sha256(
                json.dumps(pattern.path, ensure_ascii=False, separators=(",", ":")).encode()
            ).hexdigest()
            node = CapabilityNode(
                node_id=pattern.pattern_id,
                node_type=NodeType.TRACE_PATTERN,
                name=f"TracePattern {pattern.intent_id}",
                summary="仅从完整性校验通过的历史审计链学习的执行路径",
                token_card=f"历史路径成功率 {pattern.success_rate:.3f}，样本 {pattern.success_count + pattern.failure_count}。",
                risk_level="learned_governance_path",
                version="1.0.0",
                content_hash=content_hash,
                metadata=pattern.model_dump(mode="json"),
            )
            graph.add_node(pattern.pattern_id, capability=node)
            for index, target_id in enumerate(pattern.path):
                if not graph.has_node(target_id):
                    continue
                edge_id = hashlib.sha256(
                    f"{pattern.pattern_id}:suggests_path:{index}:{target_id}".encode()
                ).hexdigest()
                graph.add_edge(
                    pattern.pattern_id,
                    target_id,
                    key=edge_id,
                    relation=EdgeRelation.SUGGESTS_PATH.value,
                    weight=pattern.success_rate,
                    confidence=min(1.0, (pattern.success_count + pattern.failure_count) / 10),
                    source_type="verified_trace",
                )
        return graph

    def stats(self) -> GraphStats:
        metadata = self.metadata()
        nodes = self.list_nodes()
        edges = self.list_edges()
        patterns = self.list_trace_patterns()
        node_ids = {node.node_id for node in nodes}
        learned_edge_count = sum(
            1 for pattern in patterns for target_id in pattern.path if target_id in node_ids
        )
        node_types = Counter(node.node_type.value for node in nodes)
        relation_types = Counter(edge.relation.value for edge in edges)
        if patterns:
            node_types[NodeType.TRACE_PATTERN.value] += len(patterns)
            relation_types[EdgeRelation.SUGGESTS_PATH.value] += learned_edge_count
        return GraphStats(
            graph_version=metadata.get("graph_version", "unknown"),
            source_digest=metadata["source_digest"],
            node_count=len(nodes) + len(patterns),
            edge_count=len(edges) + learned_edge_count,
            node_types=dict(sorted(node_types.items())),
            relation_types=dict(sorted(relation_types.items())),
            full_context_tokens=int(metadata.get("full_context_tokens", "0")),
        )
