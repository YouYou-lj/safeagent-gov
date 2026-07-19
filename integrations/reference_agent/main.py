"""Standalone planning-only Agent service with no tool execution authority."""

from __future__ import annotations

import hmac
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = "1.0.0"
AGENT_NAME = "safeagent-reference-tool-agent"
AGENT_VERSION = "1.0.0"


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal["1.0.0"]
    request_id: str = Field(pattern=r"^PLANREQ-[A-F0-9]{16}$")
    task: str = Field(min_length=1, max_length=50_000)
    context: dict[str, Any]
    tool_schemas: dict[str, dict[str, Any]] = Field(max_length=32)


def _configured_token() -> str:
    token = os.getenv("SAFEAGENT_REFERENCE_AGENT_TOKEN", "")
    if len(token) < 16 or len(token) > 8192:
        raise RuntimeError("SAFEAGENT_REFERENCE_AGENT_TOKEN must contain 16-8192 characters")
    return token


def _tool_plan(task: str, available_tools: set[str]) -> dict[str, Any]:
    """Propose tool calls only; never import or invoke MCP handlers."""
    lowered = task.casefold()
    calls: list[dict[str, Any]] = []
    paths = re.findall(r"/data/[\w./\-]+", task)
    if "file_read" in available_tools and (paths or any(token in task for token in ("读取", "人员名单", "文件"))):
        path = paths[0].rstrip("。,.，") if paths else "/data/secret/person.xlsx"
        calls.append({"tool_name": "file_read", "tool_args": {"path": path}})
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", task)
    if "send_email" in available_tools and (
        email_match or any(token in task for token in ("发送邮件", "发送给", "邮件"))
    ):
        calls.append(
            {
                "tool_name": "send_email",
                "tool_args": {
                    "to": email_match.group(0) if email_match else "office@gov.cn",
                    "subject": "外部 Agent 任务结果",
                    "content": "拟发送的任务摘要（参考 Agent 规划）",
                },
            }
        )
    url_match = re.search(r"https?://[^\s，。]+", task)
    if "browser_visit" in available_tools and url_match:
        calls.append({"tool_name": "browser_visit", "tool_args": {"url": url_match.group(0)}})
    if "shell_exec" in available_tools and any(
        token in lowered for token in ("shell", "执行命令", "rm -rf", "powershell")
    ):
        calls.append({"tool_name": "shell_exec", "tool_args": {"command": task[:300]}})
    steps = [
        {
            "step_index": index,
            **call,
            "predecessors": [index - 1] if index > 1 else [],
        }
        for index, call in enumerate(calls, start=1)
    ]
    return {"summary": "外部工具型 Agent 提供的无执行权限计划", "steps": steps}


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _configured_token()
    yield


app = FastAPI(title="SafeAgent Reference Tool Agent", version=AGENT_VERSION, lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": AGENT_NAME, "version": AGENT_VERSION}


@app.post("/v1/agent/plan")
def plan(payload: PlanRequest, request: Request) -> dict[str, Any]:
    expected = f"Bearer {_configured_token()}"
    supplied = request.headers.get("Authorization", "")
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid agent bearer token")
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": payload.request_id,
        "agent": {"name": AGENT_NAME, "version": AGENT_VERSION, "execution_authority": False},
        "plan": _tool_plan(payload.task, set(payload.tool_schemas)),
    }
