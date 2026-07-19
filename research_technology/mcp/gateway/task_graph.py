"""Persistent Agent task-graph conformance and anomaly detection."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.gateway.storage import gateway_connection
from mcp.schemas import GatewayContext

from safeagent_gov.errors import TaskGraphError


def tool_args_fingerprint(tool_args: dict[str, Any]) -> str:
    payload = json.dumps(tool_args, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TaskGraphGuard:
    """Detect step reordering, replacement, splitting, loops and plan replay."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        with gateway_connection(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_step_usage (
                    trace_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    tool_name TEXT NOT NULL,
                    args_hash TEXT NOT NULL,
                    uses INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(trace_id, task_id, plan_id, step_index)
                )
                """
            )

    def validate(
        self,
        context: GatewayContext,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        consume: bool = False,
    ) -> None:
        graph = context.task_graph
        if graph is None:
            return
        if not context.trace_id or not context.task_id or context.task_step < 1:
            raise TaskGraphError("任务图请求缺少 trace_id、task_id 或有效步骤")
        matching = [step for step in graph.steps if step.step_index == context.task_step]
        if len(matching) != 1:
            raise TaskGraphError("任务图步骤编号不存在或重复")
        step = matching[0]
        if step.tool_name != tool_name:
            raise TaskGraphError("实际工具与声明计划不一致，疑似工具替换")
        args_hash = tool_args_fingerprint(tool_args)
        if step.args_hash != args_hash:
            raise TaskGraphError("工具参数与声明计划不一致，疑似步骤拆分或参数升级")
        try:
            with gateway_connection(self.path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                for predecessor in step.predecessors:
                    row = connection.execute(
                        """
                        SELECT uses FROM task_step_usage
                        WHERE trace_id = ? AND task_id = ? AND plan_id = ? AND step_index = ?
                        """,
                        (context.trace_id, context.task_id, graph.plan_id, predecessor),
                    ).fetchone()
                    if not row or int(row["uses"]) < 1:
                        connection.execute("ROLLBACK")
                        raise TaskGraphError("前置步骤尚未完成，疑似步骤重排")
                row = connection.execute(
                    """
                    SELECT uses, tool_name, args_hash FROM task_step_usage
                    WHERE trace_id = ? AND task_id = ? AND plan_id = ? AND step_index = ?
                    """,
                    (context.trace_id, context.task_id, graph.plan_id, step.step_index),
                ).fetchone()
                uses = int(row["uses"]) if row else 0
                if row and (row["tool_name"] != tool_name or row["args_hash"] != args_hash):
                    connection.execute("ROLLBACK")
                    raise TaskGraphError("已登记步骤的工具或参数发生 TOCTOU 变化")
                if uses >= step.max_calls:
                    connection.execute("ROLLBACK")
                    raise TaskGraphError("步骤超过最大调用次数，疑似循环或重放")
                if consume:
                    now = datetime.now(timezone.utc).isoformat()
                    if row:
                        connection.execute(
                            """
                            UPDATE task_step_usage SET uses = ?, updated_at = ?
                            WHERE trace_id = ? AND task_id = ? AND plan_id = ? AND step_index = ?
                            """,
                            (uses + 1, now, context.trace_id, context.task_id, graph.plan_id, step.step_index),
                        )
                    else:
                        connection.execute(
                            """
                            INSERT INTO task_step_usage(
                                trace_id, task_id, plan_id, step_index, tool_name, args_hash, uses, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                context.trace_id,
                                context.task_id,
                                graph.plan_id,
                                step.step_index,
                                tool_name,
                                args_hash,
                                1,
                                now,
                            ),
                        )
                connection.execute("COMMIT")
        except sqlite3.Error as exc:
            raise TaskGraphError("任务图状态不可用，已失败关闭") from exc


DEFAULT_TASK_GRAPH_GUARD = TaskGraphGuard()
