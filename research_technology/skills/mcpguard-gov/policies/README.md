# Policy location

The immutable tool-policy versions are in `mcp/policies/versions/`; they are not
duplicated inside the Skill package. Capability, approval, taint and task-graph
state machines are implemented in `mcp/gateway/` and consume the selected release.
