"""Policy-as-code enforcement for MCP tool requests."""

from __future__ import annotations

import ipaddress
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

from mcp.gateway.policy_releases import PolicyReleaseStore, load_policy_version, select_policy
from mcp.gateway.taint import evaluate_taint_flow
from mcp.schemas import PolicyDecision, ToolRequest

from safeagent_gov.errors import PolicyConfigurationError, PolicyNotFoundError


def reload_tool_policy() -> None:
    """Clear the policy cache after a controlled policy deployment."""
    load_policy_version.cache_clear()


def _under(path: str, prefixes: list[str]) -> bool:
    normalized = str(PurePosixPath(path))
    return any(normalized == prefix or normalized.startswith(prefix.rstrip("/") + "/") for prefix in prefixes)


def _host_is_private(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
        return address.is_private or address.is_loopback or address.is_link_local or address.is_reserved
    except ValueError:
        return host in {"localhost", "localhost.localdomain"} or host.endswith(".local")


def _domain_allowed(host: str, whitelist: list[str]) -> bool:
    host = host.casefold().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in whitelist)


def _decision(
    decision: str,
    risk_level: str,
    reason: str,
    policy_hit: str,
    policy_version: str,
) -> dict[str, Any]:
    record = PolicyDecision(
        decision=decision,
        risk_level=risk_level,
        reason=reason,
        policy_hit=policy_hit,
        policy_version=policy_version,
    )
    return record.model_dump(mode="json")


def check_tool_call(
    tool_name: str,
    tool_args: dict[str, Any],
    context: dict[str, Any] | None = None,
    *,
    policy_snapshot: dict[str, Any] | None = None,
    release_store: PolicyReleaseStore | None = None,
) -> dict[str, Any]:
    """Validate and authorize one MCP request against the versioned policy."""
    request = ToolRequest(tool_name=tool_name, tool_args=tool_args, context=context or {})
    try:
        policy = policy_snapshot or select_policy(request.context, release_store)
    except (PolicyConfigurationError, PolicyNotFoundError) as exc:
        return _decision(
            "block",
            "critical",
            f"策略版本不可用，失败关闭: {type(exc).__name__}",
            "gateway.policy_release_unavailable",
            "unavailable",
        )
    version = str(policy.get("version", "unknown"))
    if request.context.policy_version and request.context.policy_version != version:
        return _decision(
            "block",
            "high",
            "请求绑定的策略版本与当前版本不一致",
            "gateway.policy_version_mismatch",
            version,
        )
    config = policy.get("tools", {}).get(request.tool_name)
    if not config:
        return _decision("block", "high", "未注册工具，默认拒绝", "tools.default_deny", version)

    role = request.context.user.role if request.context.user else (request.context.user_role or "staff")
    blocked = policy.get("role_overrides", {}).get(role, {}).get("blocked_tools", [])
    if request.tool_name in blocked:
        return _decision("block", "high", f"角色 {role} 无权调用该工具", f"role_overrides.{role}.blocked_tools", version)

    if request.context.agent:
        agent_role = request.context.agent.role
        blocked = policy.get("agent_role_overrides", {}).get(agent_role, {}).get("blocked_tools", [])
        if request.tool_name in blocked:
            return _decision(
                "block",
                "high",
                f"Agent 角色 {agent_role} 无权调用该工具",
                f"agent_role_overrides.{agent_role}.blocked_tools",
                version,
            )
        if request.context.user and request.context.user.tenant_id != request.context.agent.tenant_id:
            return _decision(
                "block",
                "critical",
                "用户与 Agent 租户不一致",
                "gateway.identity.tenant_mismatch",
                version,
            )

    decision = str(config.get("action", "block"))
    risk = str(config.get("risk_level", "high"))
    reason = "工具请求符合当前策略"
    hit = f"tools.{request.tool_name}.action"

    if request.tool_name in {"file_read", "file_write", "file_delete"}:
        path = str(request.tool_args.get("path", ""))
        if not path.startswith("/") or ".." in PurePosixPath(path).parts:
            return _decision("block", "high", "文件路径无效或包含目录穿越", f"tools.{request.tool_name}.path_validation", version)
        if _under(path, config.get("deny_paths", [])):
            return _decision("block", "critical", f"访问敏感路径 {path}", f"tools.{request.tool_name}.deny_paths", version)
        allow_paths = config.get("allow_paths", [])
        if allow_paths and not _under(path, allow_paths):
            return _decision("block", "high", f"路径不在授权目录: {path}", f"tools.{request.tool_name}.allow_paths", version)

    elif request.tool_name == "send_email":
        recipient = str(request.tool_args.get("to", ""))
        if "@" not in recipient or recipient.startswith("@") or recipient.endswith("@"):
            return _decision("block", "high", "收件人地址无效", "tools.send_email.address_validation", version)
        domain = recipient.rsplit("@", 1)[-1].casefold()
        if _domain_allowed(domain, config.get("internal_domain_whitelist", [])):
            decision, risk, reason, hit = (
                "allow_with_log",
                "medium",
                "内部政务域邮件，仅记录后模拟发送",
                "tools.send_email.internal_domain_whitelist",
            )
        else:
            decision, reason, hit = (
                str(config.get("external_domain_action", "require_approval")),
                "外部域收件人需要人工审批",
                "tools.send_email.external_domain_action",
            )

    elif request.tool_name in {"browser_visit", "api_call"}:
        url = str(request.tool_args.get("url", ""))
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if parsed.scheme not in {"http", "https"} or not host:
            return _decision("block", "high", "仅允许有效的 HTTP/HTTPS 地址", f"tools.{request.tool_name}.url_validation", version)
        if config.get("block_private_ip", True) and _host_is_private(host):
            return _decision("block", "critical", "禁止访问内网、环回或本地域名", f"tools.{request.tool_name}.block_private_ip", version)
        if not _domain_allowed(host, config.get("domain_whitelist", [])):
            return _decision("block", "high", f"域名 {host} 不在白名单", f"tools.{request.tool_name}.domain_whitelist", version)
        decision, reason = "allow_with_log", "白名单政务域，仅模拟访问"

    elif request.tool_name == "db_query":
        sql = str(request.tool_args.get("sql", "")).casefold().strip()
        forbidden = config.get("forbidden_patterns", [])
        if not sql.startswith("select ") or any(token in sql for token in forbidden):
            return _decision("block", "critical", "查询包含写入或高危 SQL", "tools.db_query.forbidden_patterns", version)

    taint_override = evaluate_taint_flow(request.tool_name, request.tool_args, request.context)
    if taint_override:
        return _decision(
            taint_override["decision"],
            taint_override["risk_level"],
            taint_override["reason"],
            taint_override["policy_hit"],
            version,
        )

    return _decision(decision, risk, reason, hit, version)
