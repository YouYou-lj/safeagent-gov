"""Source-aware evidence graph and cross-fragment risk aggregation."""

from __future__ import annotations

import hashlib
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from itertools import pairwise
from typing import Any

from safeagent_gov.contracts import ContentChunk, RiskEvidence, SourceEnvelope, SourceType, TextSourceInput

from .cascade import CascadeMode, ReviewHook, cascade_detect
from .detector import RISK_PRIORITY
from .normalization import chunk_source
from .policy_loader import load_classifier_model, load_prompt_policy
from .sources import adapt_text_source, adapt_user_input

ANALYSIS_VERSION = "0.2.0"
EXTERNAL_SOURCE_TYPES = {
    SourceType.WEB_PAGE,
    SourceType.UPLOADED_PDF,
    SourceType.UPLOADED_DOC,
    SourceType.RAG_RESULT,
    SourceType.HISTORY_MEMORY,
}


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8", errors="replace")).hexdigest()
    return digest[:24]


def _result_candidates(result: dict[str, Any]) -> list[dict[str, Any]]:
    if result.get("risk_type") == "none":
        return []
    return list(result.get("all_risks") or [result])


def _action_for(candidate: dict[str, Any], source_type: SourceType) -> str:
    action = str(candidate.get("action", "require_approval"))
    if source_type in EXTERNAL_SOURCE_TYPES and candidate.get("risk_level") in {"high", "critical"}:
        return "isolate"
    return action


def _make_evidence(
    candidate: dict[str, Any],
    source: SourceEnvelope,
    *,
    layer: str,
    chunk_ids: list[str],
    related_source_ids: list[str] | None = None,
) -> RiskEvidence:
    raw_score = float(candidate.get("risk_score", 0.0))
    adjusted_score = min(0.99, raw_score + (1.0 - source.trust_score) * 0.08 + (0.06 if layer == "cross_fragment" else 0.0))
    hits = sorted(set(str(hit) for hit in candidate.get("rule_hits", [])))
    evidence_id = f"evidence:{_stable_id(source.source_id, candidate['risk_type'], layer, '|'.join(hits), '|'.join(chunk_ids))}"
    return RiskEvidence(
        evidence_id=evidence_id,
        source_id=source.source_id,
        source_type=source.source_type.value,
        risk_type=str(candidate["risk_type"]),
        risk_level=str(candidate.get("risk_level", "medium")),
        score=round(adjusted_score, 3),
        excerpt=str(candidate.get("evidence", ""))[:240],
        rule_hits=hits,
        metadata={
            "layer": layer,
            "action": _action_for(candidate, source.source_type),
            "chunk_ids": chunk_ids,
            "related_source_ids": related_source_ids or [source.source_id],
            "origin": source.origin,
            "trust_score": source.trust_score,
            "normalization_flags": source.normalization_flags,
        },
    )


def _merge_overlapping_chunks(left: ContentChunk, right: ContentChunk) -> str:
    overlap = max(0, left.end_char - right.start_char)
    return left.text + right.text[min(overlap, len(right.text)) :]


def _safe_result(source: SourceEnvelope) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "source": source.source_type.value,
        "risk_type": "none",
        "risk_level": "safe",
        "risk_score": 0.02 if source.normalized_content else 0.0,
        "evidence": "",
        "rule_hits": [],
        "action": "allow",
    }


def _serialize_evidence(evidence: RiskEvidence) -> dict[str, Any]:
    record = evidence.model_dump(mode="json")
    record["risk_score"] = record.pop("score")
    record["evidence"] = record.pop("excerpt")
    record["action"] = record["metadata"]["action"]
    record["layer"] = record["metadata"]["layer"]
    return record


def analyze_sources(
    sources: Iterable[SourceEnvelope],
    *,
    max_chunk_chars: int = 2_000,
    overlap_chars: int = 200,
    mode: CascadeMode = "full",
    reviewer: ReviewHook | None = None,
) -> dict[str, Any]:
    """Analyze multiple sources jointly and return a backward-compatible decision plus evidence graph."""
    started = time.perf_counter()
    source_list = list(sources)
    if not source_list:
        raise ValueError("at least one source is required")
    source_by_id = {source.source_id: source for source in source_list}
    if len(source_by_id) != len(source_list):
        raise ValueError("source_id values must be unique")

    chunks_by_source: dict[str, list[ContentChunk]] = {
        source.source_id: chunk_source(source, max_chars=max_chunk_chars, overlap_chars=overlap_chars)
        for source in source_list
    }
    evidence_by_id: dict[str, RiskEvidence] = {}
    detected_signatures: dict[str, set[tuple[str, tuple[str, ...]]]] = defaultdict(set)

    for source in source_list:
        for chunk in chunks_by_source[source.source_id]:
            result = cascade_detect(
                chunk.text,
                source.source_type.value,
                mode=mode,
                normalization_flags=source.normalization_flags,
                reviewer=reviewer,
            )
            for candidate in _result_candidates(result):
                signature = (str(candidate["risk_type"]), tuple(sorted(set(candidate.get("rule_hits", [])))))
                detected_signatures[source.source_id].add(signature)
                evidence = _make_evidence(
                    candidate,
                    source,
                    layer=str(candidate.get("_layer", "rule")),
                    chunk_ids=[chunk.chunk_id],
                )
                evidence_by_id[evidence.evidence_id] = evidence

    # Detect attacks split across adjacent chunks without double-counting a rule
    # that either chunk already triggered independently.
    for source in source_list:
        chunks = chunks_by_source[source.source_id]
        for left, right in pairwise(chunks):
            combined = _merge_overlapping_chunks(left, right)
            result = cascade_detect(
                combined,
                source.source_type.value,
                mode=mode,
                normalization_flags=source.normalization_flags,
                reviewer=reviewer,
            )
            for candidate in _result_candidates(result):
                signature = (str(candidate["risk_type"]), tuple(sorted(set(candidate.get("rule_hits", [])))))
                if signature in detected_signatures[source.source_id]:
                    continue
                evidence = _make_evidence(
                    candidate,
                    source,
                    layer="cross_fragment",
                    chunk_ids=[left.chunk_id, right.chunk_id],
                )
                evidence_by_id[evidence.evidence_id] = evidence

    # Correlate adjacent sources only when they share a session. This limits
    # accidental joins between unrelated documents while catching split attacks.
    for left, right in pairwise(source_list):
        if not left.session_id or left.session_id != right.session_id:
            continue
        combined = f"{left.normalized_content[-800:]} {right.normalized_content[:800]}"
        result = cascade_detect(
            combined,
            right.source_type.value,
            mode=mode,
            normalization_flags=sorted(set(left.normalization_flags + right.normalization_flags)),
            reviewer=reviewer,
        )
        for candidate in _result_candidates(result):
            signature = (str(candidate["risk_type"]), tuple(sorted(set(candidate.get("rule_hits", [])))))
            if signature in detected_signatures[left.source_id] or signature in detected_signatures[right.source_id]:
                continue
            left_chunk_ids = [chunk.chunk_id for chunk in chunks_by_source[left.source_id][-1:]]
            right_chunk_ids = [chunk.chunk_id for chunk in chunks_by_source[right.source_id][:1]]
            evidence = _make_evidence(
                candidate,
                right,
                layer="cross_fragment",
                chunk_ids=left_chunk_ids + right_chunk_ids,
                related_source_ids=[left.source_id, right.source_id],
            )
            evidence_by_id[evidence.evidence_id] = evidence

    evidence_list = list(evidence_by_id.values())
    serialized = [_serialize_evidence(item) for item in evidence_list]
    serialized.sort(key=lambda item: (RISK_PRIORITY[item["risk_level"]], item["risk_score"]), reverse=True)

    source_decisions: dict[str, dict[str, Any]] = {}
    for source in source_list:
        records = [item for item in serialized if item["source_id"] == source.source_id]
        if not records:
            source_decisions[source.source_id] = _safe_result(source)
            continue
        top = records[0]
        source_decisions[source.source_id] = {
            "source_id": source.source_id,
            "source": source.source_type.value,
            "risk_type": top["risk_type"],
            "risk_level": top["risk_level"],
            "risk_score": top["risk_score"],
            "evidence": top["evidence"],
            "rule_hits": top["rule_hits"],
            "action": top["action"],
            "all_risks": records,
        }

    graph_nodes: list[dict[str, Any]] = []
    graph_edges: list[dict[str, str]] = []
    for source in source_list:
        graph_nodes.append(
            {
                "id": source.source_id,
                "node_type": "source",
                "source_type": source.source_type.value,
                "origin": source.origin,
                "trust_score": source.trust_score,
                "content_hash": source.content_hash,
                "normalized_hash": source.normalized_hash,
                "normalization_flags": source.normalization_flags,
            }
        )
        if source.parent_source_id:
            graph_edges.append({"from": source.parent_source_id, "to": source.source_id, "edge_type": "derived_from"})
        for chunk in chunks_by_source[source.source_id]:
            graph_nodes.append(
                {
                    "id": chunk.chunk_id,
                    "node_type": "chunk",
                    "source_id": source.source_id,
                    "index": chunk.index,
                    "start_char": chunk.start_char,
                    "end_char": chunk.end_char,
                    "content_hash": chunk.content_hash,
                }
            )
            graph_edges.append({"from": source.source_id, "to": chunk.chunk_id, "edge_type": "contains"})
    for left, right in pairwise(source_list):
        if left.session_id and left.session_id == right.session_id:
            graph_edges.append({"from": left.source_id, "to": right.source_id, "edge_type": "same_session_next"})
    for evidence in evidence_list:
        record = evidence.model_dump(mode="json")
        graph_nodes.append(
            {
                "id": evidence.evidence_id,
                "node_type": "risk_evidence",
                "risk_type": evidence.risk_type,
                "risk_level": record["risk_level"],
                "score": evidence.score,
                "layer": evidence.metadata["layer"],
            }
        )
        for chunk_id in evidence.metadata["chunk_ids"]:
            graph_edges.append({"from": chunk_id, "to": evidence.evidence_id, "edge_type": "supports"})
        for related_source_id in evidence.metadata["related_source_ids"]:
            if related_source_id != evidence.source_id:
                graph_edges.append({"from": related_source_id, "to": evidence.evidence_id, "edge_type": "correlates"})

    if serialized:
        top = serialized[0]
        independent_sources = len({item["source_id"] for item in serialized})
        cross_found = any(item["layer"] == "cross_fragment" for item in serialized)
        aggregate_boost = min(0.10, max(0, independent_sources - 1) * 0.03) + (0.04 if cross_found else 0.0)
        aggregate_score = round(min(0.99, float(top["risk_score"]) + aggregate_boost), 3)
        result: dict[str, Any] = {
            "source": source_list[0].source_type.value if len(source_list) == 1 else "multi_source",
            "risk_type": top["risk_type"],
            "risk_level": top["risk_level"],
            "risk_score": aggregate_score,
            "evidence": top["evidence"],
            "rule_hits": top["rule_hits"],
            "action": top["action"],
            "all_risks": serialized,
        }
    else:
        result = {
            "source": source_list[0].source_type.value if len(source_list) == 1 else "multi_source",
            "risk_type": "none",
            "risk_level": "safe",
            "risk_score": 0.02 if any(source.normalized_content for source in source_list) else 0.0,
            "evidence": "",
            "rule_hits": [],
            "action": "allow",
            "all_risks": [],
        }

    policy_version = str(load_prompt_policy().get("version", "unknown"))
    classifier_model_version = str(load_classifier_model().get("version", "unknown"))
    result.update(
        {
            "analysis_version": ANALYSIS_VERSION,
            "cascade_mode": mode,
            "policy_version": policy_version,
            "classifier_model_version": classifier_model_version,
            "source_decisions": source_decisions,
            "provenance": {
                "source_count": len(source_list),
                "chunk_count": sum(len(chunks) for chunks in chunks_by_source.values()),
                "source_ids": [source.source_id for source in source_list],
                "source_hashes": {source.source_id: source.content_hash for source in source_list},
            },
            "layer_evidence": dict(Counter(item["layer"] for item in serialized)),
            "evidence_graph": {"nodes": graph_nodes, "edges": graph_edges},
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    )
    return result


def analyze_text_input(
    text: str,
    source: SourceType | str = SourceType.USER_INPUT,
    *,
    origin: str | None = None,
    session_id: str | None = None,
    trust_score: float | None = None,
    metadata: dict[str, Any] | None = None,
    mode: CascadeMode = "full",
    reviewer: ReviewHook | None = None,
) -> dict[str, Any]:
    """Convenience entrypoint for existing text-only API callers."""
    source_type = SourceType(source)
    if source_type == SourceType.USER_INPUT:
        envelope = adapt_user_input(text, user_id=origin or "anonymous", session_id=session_id, metadata=metadata)
    else:
        envelope = adapt_text_source(
            text,
            source_type,
            origin=origin or f"inline:{source_type.value}",
            session_id=session_id,
            trust_score=trust_score,
            metadata=metadata,
        )
    return analyze_sources([envelope], mode=mode, reviewer=reviewer)


def analyze_input_bundle(
    text: str,
    source: SourceType | str = SourceType.USER_INPUT,
    *,
    origin: str | None = None,
    session_id: str | None = None,
    trust_score: float | None = None,
    metadata: dict[str, Any] | None = None,
    mode: CascadeMode = "full",
    reviewer: ReviewHook | None = None,
    additional_sources: list[TextSourceInput | dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Analyze a bounded serialized text bundle while preserving cross-source evidence."""
    if additional_sources and len(additional_sources) > 16:
        raise ValueError("PromptShield additional_sources 最多允许 16 项")
    source_type = SourceType(source)
    if source_type == SourceType.USER_INPUT:
        primary = adapt_user_input(text, user_id=origin or "anonymous", session_id=session_id, metadata=metadata)
    else:
        primary = adapt_text_source(
            text,
            source_type,
            origin=origin or f"inline:{source_type.value}",
            session_id=session_id,
            trust_score=trust_score,
            metadata=metadata,
        )
    envelopes = [primary]
    for index, raw in enumerate(additional_sources or [], 1):
        item = raw if isinstance(raw, TextSourceInput) else TextSourceInput.model_validate(raw)
        if item.source == SourceType.USER_INPUT:
            envelope = adapt_user_input(
                item.text,
                user_id=item.origin or f"bundle-user:{index}",
                session_id=session_id,
                metadata=item.metadata,
            )
        else:
            envelope = adapt_text_source(
                item.text,
                item.source,
                origin=item.origin or f"bundle:{item.source.value}:{index}",
                session_id=session_id,
                trust_score=item.trust_score,
                metadata=item.metadata,
            )
        envelopes.append(envelope)
    return analyze_sources(envelopes, mode=mode, reviewer=reviewer)
