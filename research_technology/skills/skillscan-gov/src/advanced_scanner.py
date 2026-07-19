"""Behavior/permission graph scanner with SBOM and hardened package ingestion."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import yaml
from yaml.events import AliasEvent

from .analysis import analyze_javascript, analyze_python, analyze_text_fallback
from .baseline import TEXT_SUFFIXES, scan_token_baseline
from .dependencies import build_sbom, match_dependency_risks
from .package_io import check_deadline, prepare_package
from .policy_loader import load_scan_policy

ANALYSIS_VERSION = "2.0.0"
MANIFEST_NAMES = ("manifest.yaml", "manifest.yml", "skill_manifest.yaml", "skill_manifest.yml")
SOURCE_SUFFIXES = {".py", ".js", ".ts", ".mjs", ".cjs", ".jsx", ".tsx", ".sh", ".bash", ".ps1"}


def _safe_yaml(path: Path, max_aliases: int = 20) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8", errors="strict")
    aliases = sum(isinstance(event, AliasEvent) for event in yaml.parse(content))
    if aliases > max_aliases:
        raise ValueError("YAML alias 数量超过安全上限")
    payload = yaml.safe_load(content) or {}
    if not isinstance(payload, dict):
        raise ValueError("manifest 顶层必须是对象")
    return payload


def _read_manifest(root: Path) -> tuple[dict[str, Any], str | None, list[dict[str, str]]]:
    base = root if root.is_dir() else root.parent
    errors: list[dict[str, str]] = []
    for name in MANIFEST_NAMES:
        path = base / name
        if not path.is_file():
            continue
        try:
            return _safe_yaml(path), name, errors
        except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
            errors.append({"file": name, "error_type": type(exc).__name__})
            return {}, name, errors
    return {}, None, errors


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if root.is_dir() else path.name


def _cross_file_flow(analyses: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sensitive_functions: set[str] = set()
    definitions: dict[str, str] = {}
    for analysis in analyses:
        module = Path(analysis.get("relative_path", "")).stem
        for definition in analysis["definitions"]:
            definitions[definition["name"]] = definition["node_id"]
            definitions[f"{module}.{definition['name']}"] = definition["node_id"]
            if definition.get("sensitive_return"):
                sensitive_functions.update({definition["name"], f"{module}.{definition['name']}"})

    evidence: list[dict[str, Any]] = []
    graph_edges: list[dict[str, Any]] = []

    def callee_candidates(name: str) -> set[str]:
        values = {name, name.rsplit(".", 1)[-1]}
        if "." in name:
            module, symbol = name.rsplit(".", 1)
            values.add(f"{Path(module).stem}.{symbol}")
        return values

    for analysis in analyses:
        for call in analysis["calls"]:
            target = next((definitions[value] for value in callee_candidates(call["callee"]) if value in definitions), None)
            if target:
                graph_edges.append({"from": call["call_id"], "to": target, "type": "resolves_to"})
        newly_tainted: set[str] = set()
        chains: dict[str, str] = {}
        for assignment in analysis["assignments"]:
            source = next(
                (
                    call
                    for call in assignment["source_calls"]
                    if callee_candidates(call) & sensitive_functions
                ),
                None,
            )
            if assignment["sensitive"] or source:
                newly_tainted.add(assignment["target"])
                chains[assignment["target"]] = source or "sensitive_source"
        for sink in analysis["sinks"]:
            variables = newly_tainted.intersection(sink["argument_names"])
            if not variables or sink["tainted"]:
                continue
            variable = sorted(variables)[0]
            chain = f"{chains[variable]} -> {variable} -> {sink['api']}"
            evidence.append(
                {
                    "category": "sensitive_data_flow",
                    "file": sink["file"],
                    "line": sink["line"],
                    "column": 1,
                    "symbol": sink["scope"],
                    "api": sink["api"],
                    "detail": "跨函数/跨文件敏感数据流",
                    "call_chain": chain,
                    "confidence": 0.96,
                    "parser": "behavior_graph",
                }
            )
            graph_edges.append(
                {
                    "from": f"{sink['file']}:data:{variable}",
                    "to": f"{sink['file']}:call:{sink['line']}:{sink['api']}",
                    "type": "cross_file_flows_to",
                    "call_chain": chain,
                }
            )
    return evidence, graph_edges


def _permission_analysis(manifest: dict[str, Any], evidence: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    declared = manifest.get("declared_permissions") or manifest.get("permissions") or {}
    if not isinstance(declared, dict):
        declared = {}
    categories = {item["category"] for item in evidence}
    actual = {
        "shell_exec": bool(categories & {"command_execution"}),
        "network_access": bool(categories & {"network_exfiltration"}),
        "file_read": bool(categories & {"sensitive_file_access", "sensitive_data_flow"}),
        "persistence": "persistence" in categories,
        "dynamic_loading": bool(categories & {"dynamic_loading", "obfuscation"}),
    }
    mismatches = []
    overdeclared = []
    mismatch_evidence = []
    for permission, used in actual.items():
        declared_value = declared.get(permission)
        if used and declared_value is not True:
            status = "explicitly_denied" if declared_value is False else "undeclared"
            mismatch = {
                "permission": permission,
                "status": status,
                "declared": declared_value,
                "actual": True,
                "recommendation": f"若业务必需，显式声明 {permission}=true；否则移除对应行为",
            }
            mismatches.append(mismatch)
            mismatch_evidence.append(
                {
                    "category": "permission_mismatch",
                    "file": "manifest",
                    "line": 1,
                    "column": 1,
                    "symbol": permission,
                    "api": permission,
                    "detail": f"权限 {permission} {status}，但行为图确认实际使用",
                    "confidence": 0.99,
                    "parser": "permission_graph",
                }
            )
        elif not used and declared_value is True:
            overdeclared.append(
                {
                    "permission": permission,
                    "recommendation": f"移除未使用的 {permission} 权限以满足最小权限",
                }
            )
    return {"declared": declared, "actual": actual, "mismatches": mismatches, "overdeclared": overdeclared}, mismatch_evidence


def _risk_summary(categories: set[str], policy: dict[str, Any]) -> tuple[int, str, str]:
    score = min(100, sum(int(policy.get("risk_score", {}).get(category, 0)) for category in categories))
    if score >= 95:
        return score, "critical", "立即隔离，禁止加载或上线"
    if score >= 70:
        return score, "high", "禁止上线，进入人工复核"
    if score >= 35:
        return score, "medium", "限制权限后复核代码、调用链与依赖"
    return score, "low", "未发现高危行为，可在最小权限沙箱中验证"


def scan_skill_package(package_path: str) -> dict[str, Any]:
    """Statically scan a file, directory or ZIP without importing target code."""
    started = time.monotonic()
    policy = load_scan_policy()
    limits = policy.get("limits", {})
    prepared = prepare_package(package_path, limits)
    try:
        timeout = float(limits.get("scan_timeout_seconds", 10))
        max_single = int(limits.get("max_single_file_kb", 1024)) * 1024
        max_tokens = int(limits.get("max_source_tokens", 100_000))
        max_depth = int(limits.get("max_syntax_depth", 200))
        manifest, manifest_file, manifest_errors = _read_manifest(prepared.root)
        analyses: list[dict[str, Any]] = []
        parser_errors: list[dict[str, Any]] = list(manifest_errors)
        scanned_files = 0
        scanned_bytes = 0
        for path in prepared.files:
            check_deadline(started, timeout)
            suffix = path.suffix.casefold()
            if suffix not in TEXT_SUFFIXES | SOURCE_SUFFIXES or path.stat().st_size > max_single:
                continue
            relative = _relative(prepared.root, path)
            try:
                content = path.read_text(encoding="utf-8", errors="strict")
            except (OSError, UnicodeError) as exc:
                parser_errors.append({"file": relative, "error_type": type(exc).__name__})
                continue
            scanned_files += 1
            scanned_bytes += len(content.encode("utf-8"))
            try:
                if suffix == ".py":
                    analysis = analyze_python(content, relative, max_tokens=max_tokens, max_depth=max_depth)
                elif suffix in {".js", ".ts", ".mjs", ".cjs", ".jsx", ".tsx"}:
                    analysis = analyze_javascript(content, relative, max_tokens=max_tokens, max_depth=max_depth)
                elif suffix in {".sh", ".bash", ".ps1"}:
                    analysis = analyze_text_fallback(content, relative)
                else:
                    continue
                analysis["relative_path"] = relative
                analyses.append(analysis)
            except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
                parser_errors.append({"file": relative, "error_type": type(exc).__name__})

        evidence = [item for analysis in analyses for item in analysis["evidence"]]
        graph_nodes = [item for analysis in analyses for item in analysis["graph_nodes"]]
        graph_nodes.extend(
            {
                "id": f"{analysis['relative_path']}:module",
                "type": "module",
                "file": analysis["relative_path"],
            }
            for analysis in analyses
        )
        graph_edges = [item for analysis in analyses for item in analysis["graph_edges"]]
        cross_evidence, cross_edges = _cross_file_flow(analyses)
        evidence.extend(cross_evidence)
        graph_edges.extend(cross_edges)

        sbom = build_sbom(prepared.root, prepared.files)
        dependency_evidence, snapshot_version = match_dependency_risks(sbom)
        evidence.extend(dependency_evidence)
        parser_errors.extend(sbom["parse_errors"])
        if parser_errors:
            evidence.extend(
                {
                    "category": "parser_failure",
                    "file": error["file"],
                    "line": 1,
                    "column": 1,
                    "symbol": "parser",
                    "api": error["error_type"],
                    "detail": "文件无法安全解析，需要人工复核",
                    "confidence": 0.7,
                    "parser": "scanner_guard",
                }
                for error in parser_errors
            )

        permission_analysis, mismatch_evidence = _permission_analysis(manifest, evidence)
        evidence.extend(mismatch_evidence)
        categories = {item["category"] for item in evidence}
        score, level, recommendation = _risk_summary(categories, policy)
        evidence.sort(key=lambda item: (item["file"], int(item.get("line", 1)), item["category"], item["api"]))
        for item in evidence:
            item["evidence_id"] = hashlib.sha256(
                json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()[:24]
            graph_nodes.append(
                {
                    "id": item["evidence_id"],
                    "type": "behavior_evidence",
                    "category": item["category"],
                    "file": item["file"],
                    "line": item["line"],
                }
            )
        permission_for_category = {
            "command_execution": "shell_exec",
            "network_exfiltration": "network_access",
            "sensitive_file_access": "file_read",
            "sensitive_data_flow": "file_read",
            "persistence": "persistence",
            "dynamic_loading": "dynamic_loading",
            "obfuscation": "dynamic_loading",
        }
        for permission, used in permission_analysis["actual"].items():
            permission_id = f"permission:{permission}"
            graph_nodes.append(
                {
                    "id": permission_id,
                    "type": "permission",
                    "name": permission,
                    "declared": permission_analysis["declared"].get(permission),
                    "actual": used,
                }
            )
        for item in evidence:
            permission = permission_for_category.get(item["category"])
            if permission:
                graph_edges.append({"from": item["evidence_id"], "to": f"permission:{permission}", "type": "requires"})
        graph_nodes.append({"id": "package:root", "type": "package", "name": manifest.get("name") or prepared.source.stem})
        for component in sbom["components"]:
            graph_nodes.append(
                {
                    "id": component["purl"],
                    "type": "dependency",
                    "name": component["name"],
                    "version": component["version"],
                    "ecosystem": component["ecosystem"],
                }
            )
            graph_edges.append({"from": "package:root", "to": component["purl"], "type": "depends_on"})
        baseline = scan_token_baseline(prepared.root)
        check_deadline(started, timeout)
        findings = [
            f"{item['category']}：{item['file']}:{item['line']} {item['detail']}"
            for item in evidence[:12]
        ]
        return {
            "skill_name": manifest.get("name") or manifest.get("skill_name") or prepared.source.stem,
            "analysis_version": ANALYSIS_VERSION,
            "policy_version": str(policy.get("version", "unknown")),
            "dependency_snapshot_version": snapshot_version,
            "risk_score": score,
            "risk_level": level,
            "findings": findings,
            "categories": sorted(categories),
            "recommendation": recommendation,
            "scanned_files": scanned_files,
            "scanned_bytes": scanned_bytes,
            "manifest": manifest,
            "manifest_file": manifest_file,
            "permission_analysis": permission_analysis,
            "evidence": evidence,
            "behavior_graph": {"nodes": graph_nodes, "edges": graph_edges},
            "sbom": sbom,
            "parser_errors": parser_errors,
            "archive_stats": prepared.archive_stats,
            "baseline": baseline,
            "target_code_executed": False,
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
        }
    finally:
        prepared.cleanup()
