"""Non-executing security analysis for MCP server manifests and client configs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml
from yaml.events import AliasEvent

from safeagent_gov.input_security import detect_input_risk

MAX_MANIFEST_CHARS = 200_000
MAX_ALIASES = 20
MAX_DEPTH = 32
MAX_NODES = 5_000
VERSION = "1.0.0"

SECRET_KEY = re.compile(r"(?:api[_-]?key|token|secret|password|credential|authorization|cookie)", re.I)
SECRET_REFERENCE = re.compile(r"^(?:\$\{[A-Z][A-Z0-9_]{2,127}\}|\$env:[A-Z][A-Z0-9_]{2,127})$", re.I)
URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.I)
COMMAND_KEYS = {"command", "executable", "binary", "program"}
DESCRIPTION_KEYS = {"description", "instructions", "prompt", "system_prompt", "help"}
PATH_KEYS = {"path", "root", "directory", "cwd", "workspace", "allowed_paths"}
RISK_WEIGHTS = {
    "literal_secret": 70,
    "prompt_injection": 55,
    "unsafe_endpoint": 45,
    "process_execution": 35,
    "broad_file_access": 30,
    "high_risk_capability": 25,
    "network_access": 15,
    "hardening_gap": 10,
    "schema_error": 35,
}
HIGH_RISK_CAPABILITIES = {
    "shell_exec",
    "execute_command",
    "file_delete",
    "file_write",
    "db_write",
    "database_write",
    "send_email",
}


@dataclass
class _WalkState:
    nodes: int = 0


def _safe_load(content: str, format_hint: Literal["auto", "json", "yaml"]) -> tuple[dict[str, Any], str]:
    if len(content) > MAX_MANIFEST_CHARS:
        raise ValueError("MCP manifest 超过 200,000 字符上限")
    selected = format_hint
    if selected == "auto":
        selected = "json" if content.lstrip().startswith(("{", "[")) else "yaml"
    try:
        if selected == "json":
            payload = json.loads(content)
        else:
            aliases = sum(isinstance(event, AliasEvent) for event in yaml.parse(content))
            if aliases > MAX_ALIASES:
                raise ValueError("MCP manifest YAML alias 数量超过安全上限")
            payload = yaml.safe_load(content)
    except (json.JSONDecodeError, yaml.YAMLError, UnicodeError) as exc:
        raise ValueError("MCP manifest 不是有效的 JSON/YAML") from exc
    if not isinstance(payload, dict):
        raise ValueError("MCP manifest 顶层必须是对象")
    return payload, selected


def _path(parent: str, key: str | int) -> str:
    return f"{parent}[{key}]" if isinstance(key, int) else f"{parent}.{key}"


def _walk(value: Any, path: str = "$", depth: int = 0, state: _WalkState | None = None):
    state = state or _WalkState()
    state.nodes += 1
    if state.nodes > MAX_NODES:
        raise ValueError("MCP manifest 节点数超过安全上限")
    if depth > MAX_DEPTH:
        raise ValueError("MCP manifest 嵌套深度超过安全上限")
    yield path, None, value
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = _path(path, key_text)
            yield child_path, key_text, child
            if isinstance(child, (dict, list)):
                yield from _walk(child, child_path, depth + 1, state)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = _path(path, index)
            yield child_path, None, child
            if isinstance(child, (dict, list)):
                yield from _walk(child, child_path, depth + 1, state)


def _is_loopback(hostname: str | None) -> bool:
    return hostname in {"127.0.0.1", "localhost", "::1"}


def _is_private_or_link_local(hostname: str | None) -> bool:
    if not hostname:
        return True
    return (
        hostname == "169.254.169.254"
        or hostname.startswith(("10.", "192.168.", "127."))
        or hostname.startswith("172.")
        or hostname in {"localhost", "::1"}
    )


def _capability_names(payload: dict[str, Any]) -> list[str]:
    names: set[str] = set()
    for path, key, value in _walk(payload):
        if key in {"capability", "capabilities", "tool", "tools", "permissions"}:
            if isinstance(value, str):
                names.add(value.casefold())
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        names.add(item.casefold())
                    elif isinstance(item, dict) and isinstance(item.get("name"), str):
                        names.add(item["name"].casefold())
            elif isinstance(value, dict):
                names.update(str(item).casefold() for item in value)
        if key == "name" and (".tools[" in path or ".capabilities[" in path) and isinstance(value, str):
            names.add(value.casefold())
    return sorted(names)


def scan_mcp_manifest(
    content: str,
    *,
    format_hint: Literal["auto", "json", "yaml"] = "auto",
    source_name: str = "uploaded-manifest",
) -> dict[str, Any]:
    """Parse and inspect an MCP description without starting it or contacting endpoints."""
    payload, parsed_format = _safe_load(content, format_hint)
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(category: str, path: str, detail: str, *, severity: str = "medium") -> None:
        identity = (category, path)
        if identity in seen:
            return
        seen.add(identity)
        evidence.append(
            {
                "category": category,
                "severity": severity,
                "path": path,
                "detail": detail,
            }
        )

    if not any(key in payload for key in {"name", "mcpServers", "servers", "tools", "capabilities"}):
        add("schema_error", "$", "缺少 name、mcpServers、servers、tools 或 capabilities 入口", severity="high")

    for path, key, value in _walk(payload):
        lowered_key = key.casefold() if key else ""
        if key and SECRET_KEY.search(key) and isinstance(value, str) and value and not SECRET_REFERENCE.fullmatch(value):
            add("literal_secret", path, f"{key} 包含内联秘密值；仅允许环境变量引用", severity="critical")
        if lowered_key in COMMAND_KEYS and isinstance(value, str) and value.strip():
            add("process_execution", path, "配置声明了本地进程启动能力", severity="high")
        if lowered_key in PATH_KEYS:
            values = value if isinstance(value, list) else [value]
            if any(isinstance(item, str) and item.strip() in {"/", "~", "*", "C:\\", "C:/"} for item in values):
                add("broad_file_access", path, "文件访问范围覆盖系统根目录、主目录或通配范围", severity="high")
        if lowered_key in DESCRIPTION_KEYS and isinstance(value, str):
            risk = detect_input_risk(value, source="uploaded_doc")
            if risk["action"] != "allow":
                add(
                    "prompt_injection",
                    path,
                    f"描述文本命中 {risk['risk_type']}，不得作为可信指令加载",
                    severity="critical" if risk["action"] in {"block", "isolate"} else "high",
                )
        if isinstance(value, str):
            for url in URL_PATTERN.findall(value):
                parsed = urlsplit(url.rstrip(".,;)]}"))
                if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
                    add("unsafe_endpoint", path, "远程 MCP endpoint 使用明文 HTTP", severity="high")
                elif _is_private_or_link_local(parsed.hostname) and not _is_loopback(parsed.hostname):
                    add("unsafe_endpoint", path, "MCP endpoint 指向私网或链路本地地址", severity="critical")
                else:
                    add("network_access", path, "配置声明了网络 endpoint", severity="medium")

    capabilities = _capability_names(payload)
    for capability in capabilities:
        if capability in HIGH_RISK_CAPABILITIES or any(
            marker in capability for marker in ("shell", "delete", "write", "email", "exec")
        ):
            add("high_risk_capability", "$.capabilities", f"高风险能力需要 MCPGuard 票据与最小权限：{capability}", severity="high")

    security = payload.get("security")
    if not isinstance(security, dict):
        add("hardening_gap", "$.security", "未声明 security 安全边界", severity="medium")
    if payload.get("simulation_only") is not True and any(item in HIGH_RISK_CAPABILITIES for item in capabilities):
        add("hardening_gap", "$.simulation_only", "高风险能力未声明 simulation_only=true", severity="medium")

    categories = sorted({item["category"] for item in evidence})
    risk_score = min(100, sum(RISK_WEIGHTS[category] for category in categories))
    if risk_score >= 85:
        risk_level, recommendation = "critical", "禁止连接或启动；移除秘密值与危险配置后重新检测"
    elif risk_score >= 60:
        risk_level, recommendation = "high", "保持离线，完成安全复核与最小权限收敛后再接入"
    elif risk_score >= 30:
        risk_level, recommendation = "medium", "仅在隔离环境中验证，并强制经过 MCPGuard"
    else:
        risk_level, recommendation = "low", "未发现高危描述，仍需通过 MCPGuard 运行时裁决"
    evidence.sort(key=lambda item: (item["path"], item["category"]))
    for item in evidence:
        item["evidence_id"] = hashlib.sha256(
            json.dumps(item, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:24]
    return {
        "analysis_version": VERSION,
        "source_name": source_name,
        "source_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "parsed_format": parsed_format,
        "server_name": str(payload.get("name") or "multi-server-config")[:160],
        "capabilities": capabilities,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "categories": categories,
        "evidence": evidence,
        "recommendation": recommendation,
        "target_code_executed": False,
        "network_contacted": False,
        "secrets_redacted": True,
    }
