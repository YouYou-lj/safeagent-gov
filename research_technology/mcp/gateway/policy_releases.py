"""Atomic policy version, deterministic canary and rollback management."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from mcp.gateway.storage import gateway_connection, gateway_state_path
from mcp.schemas import GatewayContext

from safeagent_gov.errors import PolicyConfigurationError, PolicyNotFoundError
from safeagent_gov.paths import research_component_dir

POLICY_DIR = research_component_dir("mcp") / "policies" / "versions"
DEFAULT_STABLE_VERSION = "2.0.0"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
REQUIRED_TOOLS = {
    "file_read",
    "file_write",
    "file_delete",
    "send_email",
    "browser_visit",
    "api_call",
    "shell_exec",
    "db_query",
    "db_write",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@lru_cache(maxsize=16)
def load_policy_version(version: str) -> dict[str, Any]:
    if not SEMVER.fullmatch(version):
        raise PolicyConfigurationError("策略版本必须是 SemVer")
    path = POLICY_DIR / f"{version}.yaml"
    if not path.is_file():
        raise PolicyNotFoundError(f"未找到工具策略版本: {version}")
    policy = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict) or str(policy.get("version")) != version:
        raise PolicyConfigurationError(f"策略文件版本声明不一致: {version}")
    tools = policy.get("tools")
    if not isinstance(tools, dict) or set(tools) != REQUIRED_TOOLS:
        raise PolicyConfigurationError(f"策略 {version} 的工具集合不完整或包含未知工具")
    return policy


def policy_digest(version: str) -> str:
    path = POLICY_DIR / f"{version}.yaml"
    load_policy_version(version)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PolicyReleaseStore:
    """SQLite-backed release state with atomic history and rollback."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._schema_lock = threading.RLock()
        self._initialized_paths: set[Path] = set()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        actual_path = (self.path or gateway_state_path()).resolve()
        with self._schema_lock:
            if actual_path in self._initialized_paths:
                return
            self._initialize_path(actual_path)
            self._initialized_paths.add(actual_path)

    def _initialize_path(self, actual_path: Path) -> None:
        load_policy_version(DEFAULT_STABLE_VERSION)
        with gateway_connection(actual_path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS policy_release_state (
                    component TEXT PRIMARY KEY,
                    stable_version TEXT NOT NULL,
                    canary_version TEXT,
                    rollout_percent INTEGER NOT NULL DEFAULT 0,
                    previous_stable_version TEXT,
                    generation INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    updated_by TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS policy_release_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    component TEXT NOT NULL,
                    action TEXT NOT NULL,
                    before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO policy_release_state(
                    component, stable_version, canary_version, rollout_percent,
                    previous_stable_version, generation, updated_at, updated_by
                ) VALUES ('mcp_tool_policy', ?, NULL, 0, NULL, 1, ?, 'bootstrap')
                """,
                (DEFAULT_STABLE_VERSION, _now()),
            )

    @staticmethod
    def _record(row: Any) -> dict[str, Any]:
        return {
            "component": row["component"],
            "stable_version": row["stable_version"],
            "stable_sha256": policy_digest(row["stable_version"]),
            "canary_version": row["canary_version"],
            "canary_sha256": policy_digest(row["canary_version"]) if row["canary_version"] else None,
            "rollout_percent": row["rollout_percent"],
            "previous_stable_version": row["previous_stable_version"],
            "generation": row["generation"],
            "updated_at": row["updated_at"],
            "updated_by": row["updated_by"],
        }

    def status(self) -> dict[str, Any]:
        self._ensure_schema()
        with gateway_connection(self.path) as connection:
            row = connection.execute(
                "SELECT * FROM policy_release_state WHERE component = 'mcp_tool_policy'"
            ).fetchone()
        if not row:
            raise PolicyConfigurationError("工具策略发布状态不存在")
        return self._record(row)

    def _mutate(self, action: str, actor: str, mutate: Any) -> dict[str, Any]:
        self._ensure_schema()
        if not actor or len(actor) > 160:
            raise PolicyConfigurationError("策略变更 actor 无效")
        with gateway_connection(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM policy_release_state WHERE component = 'mcp_tool_policy'"
            ).fetchone()
            if not row:
                connection.rollback()
                raise PolicyConfigurationError("工具策略发布状态不存在")
            before = self._record(row)
            values = mutate(before)
            connection.execute(
                """
                UPDATE policy_release_state
                SET stable_version=?, canary_version=?, rollout_percent=?,
                    previous_stable_version=?, generation=?, updated_at=?, updated_by=?
                WHERE component='mcp_tool_policy'
                """,
                (
                    values["stable_version"],
                    values.get("canary_version"),
                    values.get("rollout_percent", 0),
                    values.get("previous_stable_version"),
                    int(before["generation"]) + 1,
                    _now(),
                    actor,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM policy_release_state WHERE component = 'mcp_tool_policy'"
            ).fetchone()
            after = self._record(updated)
            connection.execute(
                """
                INSERT INTO policy_release_history(component, action, before_json, after_json, actor, created_at)
                VALUES ('mcp_tool_policy', ?, ?, ?, ?, ?)
                """,
                (
                    action,
                    json.dumps(before, sort_keys=True, separators=(",", ":")),
                    json.dumps(after, sort_keys=True, separators=(",", ":")),
                    actor,
                    _now(),
                ),
            )
            connection.commit()
        load_policy_version.cache_clear()
        return after

    def configure_canary(self, version: str, rollout_percent: int, *, actor: str) -> dict[str, Any]:
        load_policy_version(version)
        if not 1 <= rollout_percent <= 100:
            raise PolicyConfigurationError("灰度比例必须在 1—100 之间")

        def mutate(before: dict[str, Any]) -> dict[str, Any]:
            if version == before["stable_version"]:
                raise PolicyConfigurationError("灰度版本不能等于稳定版本")
            return {
                "stable_version": before["stable_version"],
                "canary_version": version,
                "rollout_percent": rollout_percent,
                "previous_stable_version": before["previous_stable_version"],
            }

        return self._mutate("configure_canary", actor, mutate)

    def promote(self, *, actor: str) -> dict[str, Any]:
        def mutate(before: dict[str, Any]) -> dict[str, Any]:
            if not before["canary_version"]:
                raise PolicyConfigurationError("没有可提升的灰度版本")
            return {
                "stable_version": before["canary_version"],
                "canary_version": None,
                "rollout_percent": 0,
                "previous_stable_version": before["stable_version"],
            }

        return self._mutate("promote", actor, mutate)

    def rollback(self, *, actor: str) -> dict[str, Any]:
        def mutate(before: dict[str, Any]) -> dict[str, Any]:
            target = before["previous_stable_version"]
            if not target:
                raise PolicyConfigurationError("没有可回滚的稳定版本")
            load_policy_version(target)
            return {
                "stable_version": target,
                "canary_version": None,
                "rollout_percent": 0,
                "previous_stable_version": before["stable_version"],
            }

        return self._mutate("rollback", actor, mutate)

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        self._ensure_schema()
        with gateway_connection(self.path) as connection:
            rows = connection.execute(
                """
                SELECT action, before_json, after_json, actor, created_at
                FROM policy_release_history WHERE component='mcp_tool_policy'
                ORDER BY id DESC LIMIT ?
                """,
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [
            {
                "action": row["action"],
                "before": json.loads(row["before_json"]),
                "after": json.loads(row["after_json"]),
                "actor": row["actor"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


def select_policy(context: GatewayContext, store: PolicyReleaseStore | None = None) -> dict[str, Any]:
    release = (store or DEFAULT_POLICY_RELEASE_STORE).status()
    allowed_versions = {release["stable_version"], release["canary_version"]} - {None}
    if context.policy_version:
        if context.policy_version not in allowed_versions:
            raise PolicyConfigurationError("请求绑定的策略版本不是当前稳定或灰度版本")
        return load_policy_version(context.policy_version)
    selected = release["stable_version"]
    if release["canary_version"] and release["rollout_percent"]:
        principal = context.agent or context.user
        bucket_key = "\x1f".join(
            [
                principal.tenant_id if principal else "default",
                principal.principal_id if principal else "anonymous",
                context.task_id or context.trace_id or "no-task",
            ]
        )
        bucket = int(hashlib.sha256(bucket_key.encode("utf-8")).hexdigest()[:8], 16) % 100
        if bucket < int(release["rollout_percent"]):
            selected = release["canary_version"]
    return load_policy_version(selected)


DEFAULT_POLICY_RELEASE_STORE = PolicyReleaseStore()
