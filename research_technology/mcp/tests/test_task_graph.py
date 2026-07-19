import pytest
from mcp.gateway import check_tool_call
from mcp.gateway.task_graph import TaskGraphGuard, tool_args_fingerprint
from mcp.schemas import GatewayContext

from safeagent_gov.errors import TaskGraphError


def _context(step=1):
    first = {"path": "/data/public/a.txt"}
    second = {"url": "https://www.gov.cn/"}
    return GatewayContext.model_validate(
        {
            "trace_id": "TRACE-GRAPH-1",
            "task_id": "TASK-GRAPH-1",
            "task_step": step,
            "task_graph": {
                "plan_id": "PLAN-GRAPH-1",
                "steps": [
                    {
                        "step_index": 1,
                        "tool_name": "file_read",
                        "args_hash": tool_args_fingerprint(first),
                        "predecessors": [],
                        "max_calls": 1,
                    },
                    {
                        "step_index": 2,
                        "tool_name": "browser_visit",
                        "args_hash": tool_args_fingerprint(second),
                        "predecessors": [1],
                        "max_calls": 1,
                    },
                ],
            },
        }
    )


def test_task_graph_detects_tool_replacement_and_split_parameter_call(tmp_path):
    guard = TaskGraphGuard(tmp_path / "graph.db")
    with pytest.raises(TaskGraphError, match="工具替换"):
        guard.validate(_context(), "browser_visit", {"url": "https://www.gov.cn/"})
    with pytest.raises(TaskGraphError, match="步骤拆分"):
        guard.validate(_context(), "file_read", {"path": "/data/public/part-a.txt"})


def test_task_graph_detects_reorder_then_allows_declared_sequence(tmp_path):
    guard = TaskGraphGuard(tmp_path / "order.db")
    with pytest.raises(TaskGraphError, match="步骤重排"):
        guard.validate(_context(step=2), "browser_visit", {"url": "https://www.gov.cn/"}, consume=True)
    guard.validate(_context(step=1), "file_read", {"path": "/data/public/a.txt"}, consume=True)
    guard.validate(_context(step=2), "browser_visit", {"url": "https://www.gov.cn/"}, consume=True)


def test_task_graph_detects_loop_or_plan_replay(tmp_path):
    guard = TaskGraphGuard(tmp_path / "loop.db")
    context = _context(step=1)
    args = {"path": "/data/public/a.txt"}
    guard.validate(context, "file_read", args, consume=True)
    with pytest.raises(TaskGraphError, match="循环或重放"):
        guard.validate(context, "file_read", args, consume=True)


def test_untrusted_agent_cannot_escalate_role_to_tool_execution():
    result = check_tool_call(
        "file_read",
        {"path": "/data/public/a.txt"},
        {
            "user": {
                "principal_id": "USER-1",
                "principal_type": "user",
                "role": "staff",
                "tenant_id": "TENANT-1",
            },
            "agent": {
                "principal_id": "AGENT-UNTRUSTED",
                "principal_type": "agent",
                "role": "untrusted",
                "tenant_id": "TENANT-1",
            },
        },
    )
    assert result["decision"] == "block"
    assert result["policy_hit"] == "agent_role_overrides.untrusted.blocked_tools"
