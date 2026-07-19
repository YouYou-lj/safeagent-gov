"""Shared deterministic planning baseline used by offline providers and tests."""

from __future__ import annotations

import re
from typing import Any


def infer_deterministic_plan_payload(task: str) -> dict[str, Any]:
    """Infer a small proposal only; MCPGuard remains the sole execution authority."""
    lowered = task.casefold()
    calls: list[dict[str, Any]] = []
    paths = re.findall(r"/data/[\w./\-]+", task)
    if paths or any(token in task for token in ("读取", "人员名单", "文件")):
        path = paths[0].rstrip("。,.，") if paths else "/data/secret/person.xlsx"
        calls.append({"tool_name": "file_read", "tool_args": {"path": path}})
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", task)
    if email_match or any(token in task for token in ("发送邮件", "发送给", "邮件")):
        calls.append(
            {
                "tool_name": "send_email",
                "tool_args": {
                    "to": email_match.group(0) if email_match else "office@gov.cn",
                    "subject": "智能体任务结果",
                    "content": "拟发送的任务摘要（演示数据）",
                },
            }
        )
    url_match = re.search(r"https?://[^\s，。]+", task)
    if url_match:
        calls.append({"tool_name": "browser_visit", "tool_args": {"url": url_match.group(0)}})
    if any(token in lowered for token in ("shell", "执行命令", "rm -rf", "powershell")):
        calls.append({"tool_name": "shell_exec", "tool_args": {"command": task[:300]}})
    steps = [
        {
            "step_index": index,
            **call,
            "predecessors": [index - 1] if index > 1 else [],
        }
        for index, call in enumerate(calls, 1)
    ]
    summary = "基于已知信息生成可审计答复" if not calls else "提出受 MCPGuard 约束的工具计划"
    return {"summary": summary, "steps": steps}
