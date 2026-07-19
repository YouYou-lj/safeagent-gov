# MCPGuard-Gov package

The Skill contract and benchmark navigation live here. The single gateway and
server implementation lives in top-level `mcp/`, so MCP clients can use it
without the desktop shell or FastAPI application.

- Contract: `SKILL.md`
- Wrapper: `src/guard.py`
- Tool policies: `../../mcp/policies/versions/`
- Tests: `tests/test_mcpguard_skill.py`
- Full tests: `../../mcp/tests/`
- Holdout runner: `../../benchmarks/runners/eval_mcpguard.py`
- Versioned result: `../../benchmarks/results/mcpguard_holdout_v1.json`
