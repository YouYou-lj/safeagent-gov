"""Single registry for MCP simulator implementations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.servers.api.server import api_call
from mcp.servers.browser.server import browser_visit
from mcp.servers.database.server import db_query, db_write
from mcp.servers.email.server import send_email
from mcp.servers.file.server import file_delete, file_read, file_write
from mcp.servers.shell.server import shell_exec

ToolHandler = Callable[..., dict[str, Any]]

TOOL_HANDLERS: dict[str, ToolHandler] = {
    "file_read": file_read,
    "file_write": file_write,
    "file_delete": file_delete,
    "send_email": send_email,
    "browser_visit": browser_visit,
    "api_call": api_call,
    "shell_exec": shell_exec,
    "db_query": db_query,
    "db_write": db_write,
}


def get_tool_handler(tool_name: str) -> ToolHandler | None:
    return TOOL_HANDLERS.get(tool_name)


def list_registered_tools() -> list[str]:
    return sorted(TOOL_HANDLERS)
