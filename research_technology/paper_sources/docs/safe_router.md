# SafeRouter-Gov 结构化路由与有界执行

SafeRouter-Gov 使用 Graphify-Gov 的候选 Skill、Agent、MCP 和策略生成严格 `RouterPlan`。独立
`/api/router/plan` 用于计划检查；`/api/agent/run` 已按 `输入检查 → Graphify/Router → Model Gateway 不可信 Planner →
分析子智能体 fan-out/fan-in → MCP 工具 → TraceAudit` 执行真实主流程。

## 规划契约

每个计划包含：

- 签名身份关联的 `trace_id` 与稳定 `plan_id`；
- Graphify 意图、图谱版本和来源摘要；
- 强制前置 PromptShield、工具阶段 MCPGuard、后置 TraceAudit；
- 子任务 Agent、优先级、超时、并行组、所需 Skill、允许工具和前置依赖；
- `AuditAgent` 的 fan-in 任务，依赖全部分析子任务并设置 `always_run=true`。

Graphify 候选超过 `max_sub_agents` 时，Router 按 `critical → high → medium → low` 保留分析任务，并为
AuditAgent 预留位置，避免按名称截断后丢失 ToolRisk 等关键安全节点。

## 执行器安全语义

`SafeRouterExecutor` 使用 NetworkX 校验 DAG，并按拓扑 generation 通过有界 `asyncio` fan-out/fan-in：

- `max_concurrency` 限制同时运行的分析子智能体；关闭并行时退化为串行；
- 每个子任务使用独立超时；强制任务超时、异常或缺少 handler 时失败关闭；
- 前置任务阻断时普通后继不再运行，但 `always_run` 审计汇总仍执行；
- 每个结果必须通过调用方提供的审计回调；审计失败将最终决策提升为 `block/critical`；
- 聚合优先级固定为 `block > require_approval > mask_and_allow > allow_with_log > allow`。

执行器只面向分析型子智能体，不直接调用 MCP 工具。Orchestrator 将 PromptShield、分析阶段 MCPGuard、
每次实际工具调用前 MCPGuard 和后置 TraceAudit 交给统一 Skill Executor；工具动作仍须使用能力票据和
`guarded_tool_call`，路由结果本身不授予执行权。

## API

```http
POST /api/router/plan
Authorization: Bearer <token>
```

```json
{
  "task": "请读取内部人员名单并发送给 external@example.com",
  "scenario": "government_office",
  "enable_parallel_agents": true,
  "max_sub_agents": 8,
  "token_budget": 1200
}
```

客户端 `user_role` 会被签名身份覆盖。计划端点只审计计划；Agent 端点返回 `router_plan`、
`router_execution`、`sub_agent_results`、`skill_executions`、`mandatory_skill_coverage` 和
`toolguard_coverage`。

## 验证

```bash
./scripts/uv_run.sh python -m pytest -q tests/test_safe_router.py
./scripts/uv_run.sh python -m pytest -q tests/test_agent_orchestration.py
./scripts/uv_run.sh python research_technology/benchmarks/runners/eval_router.py
./scripts/uv_run.sh python -m mypy safeagent_gov/router backend/api/router_api.py
```

测试覆盖 Graphify 候选映射、风险优先级、并行 generation、Audit fan-in、强制超时、审计失败关闭、
Agent 主流程、每工具二次门禁和路由故障失败关闭。5 条本地机制集的子智能体召回、意图准确率、Audit
fan-in、强制 Skill/ToolGuard 和 trace 完整率均为 1.0，危险执行为 0；不代表开放世界泛化。
