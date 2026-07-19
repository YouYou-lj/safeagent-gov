# Stage 8 兼容层清理记录

2026-07-18 技术冻结前完成唯一实现边界收敛：

- 删除 `backend/core/{prompt_shield,skill_scan,audit_logger,mcp_guard}.py`。其公开替代入口分别为 `safeagent_gov.input_security`、`safeagent_gov.supply_chain`、`safeagent_gov.audit` 和 `mcp.gateway`。
- 删除 `agent_demo/mcp_servers/` 与 `agent_demo/langgraph_agent/tools.py` 转发层；LangGraph 节点直接依赖公开的 `mcp.adapters.langgraph`。
- 删除未被运行时使用的 `backend/core/policy_loader.py`。
- 删除无语义差异的 `mcp/policies/tool_policy.yaml` 快照；稳定策略唯一来源改为 `mcp/policies/versions/2.0.0.yaml`，灰度策略为 `2.1.0.yaml`。
- 删除 API 为仓库根目录外启动保留的 `core.*` / `schemas.*` 回退导入；标准启动入口固定为 `uvicorn backend.main:app`。

清理前后均运行全仓测试、全量 lint、Mypy、85% 覆盖率门禁和 AgentSecEval。迁移不删除数据集、版本化策略、评测结果或创新证据。
