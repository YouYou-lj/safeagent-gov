# MCPGuard-Gov

## Purpose

Authorize Agent tool requests using typed identity/task context, RBAC/ABAC,
signed capability tickets, data-label propagation, transactional approval and
safe simulated MCP servers. High-risk requests are blocked or paused for review.

## Public API

```python
from mcp.gateway import (
    check_tool_call,
    guarded_tool_call,
    issue_tool_capability,
    resume_approved_tool_call,
)
```

`check_tool_call` performs a policy-only decision. Execution through
`guarded_tool_call` requires a task-bound capability ticket unless the request
is paused for approval. Approved work resumes through
`resume_approved_tool_call` and can be consumed only once.

## Safety boundary

Shell, delete, external API, database write, browser, and email operations never
perform a real dangerous action in the prototype.
