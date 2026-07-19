"""Stable MCP public API backed by ``research_technology/mcp``."""

from pathlib import Path

__path__.append(str(Path(__file__).resolve().parents[1] / "research_technology" / "mcp"))

from .gateway import (  # noqa: E402
    check_tool_call,
    guarded_tool_call,
    issue_tool_capability,
    resume_approved_tool_call,
)

__all__ = ["check_tool_call", "guarded_tool_call", "issue_tool_capability", "resume_approved_tool_call"]
